"""S09 owned native measurement: 3x300s normal and 3x120s per stress target.

One original remains in flight. Requested rate is never reported as achieved rate.
Only UUIDs created in this fresh cluster may be removed between repetitions.
No dependencies beyond the existing Python simulator and cached Java/Node/PG tools.
"""
import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import plistlib
import socket
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request

from verification_runtime import ROOT, Runtime, await_condition, free_port
sys.path.insert(0,str(ROOT/'services/factory-simulator'))
from factory_simulator.model import FactoryModel, LocationType, CellState
from factory_simulator.run_configuration import RunConfiguration, DEFAULT_CONFIG
from factory_simulator.configuration import Settings
from factory_simulator.sender import Sender, SourceSession

SOURCE_TABLES=['delivery_action','event_outbox','raw_event','delivery_stream']
OPS_TABLES=['factory_snapshot','inspection_result','operation_history','transport_history','alarm','event_projection','processed_event','body','factory_buffer','equipment','vehicle','simulation_run']

def distribution(values):
    values=sorted(values)
    if not values:return dict(count=0,p50=None,p95=None,max=None)
    return dict(count=len(values),p50=values[math.ceil(len(values)*.5)-1],
                p95=values[math.ceil(len(values)*.95)-1],max=values[-1])

class MeasuredSender(Sender):
    def __init__(self,settings,path):
        self.rows=[];self.acks=[];self.wire_attempts=0;self.ack=None
        owner=self
        class Wire:
            def __init__(self,connection):self.connection=connection
            def sendall(self,data):owner.wire_attempts+=1;return self.connection.sendall(data)
            def __getattr__(self,key):return getattr(self.connection,key)
        super().__init__(settings,connector=lambda *a,**kw:Wire(socket.create_connection(*a,**kw)),error_path=path)
    def _validate_ack(self,ack,original):
        result=super()._validate_ack(ack,original);self.acks.append(ack);self.ack=ack;return result
    def send_head(self):
        original=self.pending.head;start=time.perf_counter_ns();wall=time.time()*1000;attempts=self.wire_attempts
        result=super().send_head()
        self.rows.append(dict(self.ack,runId=original.run_id,eventId=original.event_id,sourceSeq=original.source_seq,
            eventType=json.loads(original.frame)['eventType'],frameBytes=len(original.frame),
            sendStartNs=start,sendEndNs=time.perf_counter_ns(),sendWallMs=wall,ackWallMs=time.time()*1000,
            attempts=self.wire_attempts-attempts))
        return result

class Observer:
    def __init__(self,runtime,run,directory):
        self.rt=runtime;self.run=run;self.directory=directory;self.stop=threading.Event();self.frames=[];self.samples=[];self.errors=[]
        self.threads=[threading.Thread(target=self.stream,daemon=True),threading.Thread(target=self.sample,daemon=True)]
        for thread in self.threads:thread.start()
    def stream(self):
        try:
            with urllib.request.urlopen(self.rt.url('operations')+f'/api/v1/runs/{self.run}/stream',timeout=10) as response, (self.directory/'sse.ndjson').open('w') as output:
                event=data=None
                while not self.stop.is_set():
                    line=response.readline().decode().rstrip('\n')
                    if line.startswith('event: '):event=line[7:]
                    elif line.startswith('data: '):data=line[6:]
                    elif not line and event=='factory-snapshot':
                        view=json.loads(data);row=dict(sourceSeq=view['sourceSeq'],revision=view['revision'],serverEpoch=view['serverEpoch'],
                            runId=view['runId'],observerNs=time.perf_counter_ns(),observerWallMs=time.time()*1000,bytes=len(data.encode()),dataStatus=view['dataStatus'])
                        self.frames.append(row);output.write(json.dumps(row)+'\n');output.flush();event=data=None
        except Exception as error:
            if not self.stop.is_set():self.errors.append(str(error))
    def sample(self):
        while not self.stop.is_set():
            try:self.samples.append(dict(at=time.time()*1000,**self.rt.get('ingestion',f'/internal/v1/runs/{self.run}/delivery-status')))
            except OSError as error:self.errors.append(str(error))
            self.stop.wait(1)
    def close(self):
        self.stop.set()
        for thread in self.threads:thread.join(timeout=2)
        (self.directory/'queue-samples.json').write_text(json.dumps(self.samples,indent=2)+'\n')

def phase(rt,name,run,port):
    rt.save('phase.json',dict(phase=name,runId=run,url=f'http://127.0.0.1:{port}/?run={run}',evidence=str(rt.evidence)))
    print(name,run,flush=True)

def trial(rt,name,target,seconds,port,browser):
    directory=rt.evidence/name;directory.mkdir()
    model=FactoryModel(RunConfiguration.from_path(DEFAULT_CONFIG),quality_results=('FAIL','PASS','PASS','PASS','PASS'))
    run=model.run_id
    assert rt.sql('operations_db',f"SELECT count(*) FROM simulation_run WHERE run_id='{run}'")=='0'
    assert rt.sql('ingestion_db',f"SELECT count(*) FROM raw_event WHERE run_id='{run}'")=='0'
    sender=MeasuredSender(Settings('127.0.0.1',int(rt.env['INGESTION_TCP_PORT'])),directory/'send-errors.ndjson')
    session=SourceSession(model,sender);originals=(directory/'originals.ndjson').open('wb');max_pending=0
    def drain():
        nonlocal max_pending
        max_pending=max(max_pending,len(sender.pending))
        while sender.pending:originals.write(sender.pending.head.frame);originals.flush();session.send_head()
    def production():
        session.tick()
        for cell in ('QC-01','ASM-02','ASM-01'):
            waiting=model.bodies_at(LocationType.BUFFER,'BAY-'+cell)
            if waiting and model.cell(cell).state==CellState.IDLE:session.change(model.enter_cell,waiting[0].body_id)
    observer=None
    try:
        session.change(model.register_body);session.change(model.redispatch);session.change(model.publish_snapshot);drain()
        def initial_snapshot():
            sequence=rt.get('operations',f'/api/v1/runs/{run}/snapshot')['sourceSeq']
            return sequence is not None and sequence>=len(sender.rows)
        await_condition(initial_snapshot)
        observer=Observer(rt,run,directory)
        phase(rt,name,run,port)
        if browser and target==25:
            deadline=time.monotonic()+600
            while not (rt.evidence/('UI.'+name+'.continue')).exists():
                if time.monotonic()>deadline:raise TimeoutError('Actual browser normal-trial gate timed out')
                session.change(model.publish_snapshot);drain();time.sleep(.5)
        # Same 5s reporting warmup per case, excluded from active measurements.
        warm=time.monotonic()+5
        while time.monotonic()<warm:session.change(model.publish_snapshot);drain();time.sleep(.04)
        start=time.monotonic();start_wall=time.time()*1000;active_start=len(sender.rows);tick_due=start;report_due=start;body_due=start+40;missed=0;tick_missed=0
        while time.monotonic()-start<seconds:
            now=time.monotonic()
            if now>=tick_due:
                production();tick_missed+=max(0,int((now-tick_due)/.1));tick_due=now+.1
            if now>=body_due:
                session.change(model.register_body);session.change(model.redispatch);body_due+=40
            if now>=report_due:
                missed+=max(0,int((now-report_due)*target));report_due=now+1/target
                session.change(model.publish_snapshot)
            drain()
            time.sleep(max(0,min(.001,report_due-time.monotonic(),tick_due-time.monotonic())))
        duration=time.monotonic()-start;end_wall=time.time()*1000;active=sender.rows[active_start:];drain_start=time.monotonic()
        while not (all(b.location.location_type==LocationType.RESULT for b in model.bodies) and not model.active_transports and all(v.state.value=='IDLE' for v in model.vehicles)):
            if time.monotonic()-drain_start>180:raise TimeoutError('Production drain exceeded 180s')
            production();session.change(model.publish_snapshot);drain();time.sleep(.1)
        session.change(model.finish_run);drain();originals.close()
        status=await_condition(lambda:(s if s['pendingCount']==0 else None) if (s:=rt.get('ingestion',f'/internal/v1/runs/{run}/delivery-status')) else None,60)
        final=await_condition(lambda:(v if v['dataStatus']=='FINISHED' else None) if (v:=rt.get('operations',f'/api/v1/runs/{run}/snapshot')) else None)
        await_condition(lambda:any(f['dataStatus']=='FINISHED' for f in observer.frames),10)
        observer.close();assert not observer.errors,observer.errors
        raw=(directory/'originals.ndjson').read_bytes().splitlines()
        rows=json.loads(rt.sql('ingestion_db',f"SELECT json_agg(json_build_object('seq',r.source_seq,'raw',r.raw_json_text,'hash',r.payload_hash,'status',o.delivery_status) ORDER BY r.source_seq) FROM raw_event r JOIN event_outbox o USING(run_id,event_id) WHERE run_id='{run}'"))
        ops=json.loads(rt.sql('operations_db',f"SELECT json_agg(json_build_object('seq',source_seq,'raw',raw_json_text,'hash',payload_hash) ORDER BY source_seq) FROM processed_event WHERE run_id='{run}'"))
        assert len(raw)==len(rows)==len(ops)==len(sender.rows)
        for seq,(original,left,right) in enumerate(zip(raw,rows,ops),1):
            assert left['seq']==right['seq']==seq and left['status']=='DELIVERED'
            assert left['raw'].encode()==right['raw'].encode()==original and left['hash']==right['hash']==hashlib.sha256(original).hexdigest()
        assert status['nextSourceSeq']==len(raw)+1
        received={r['sourceSeq']:datetime.fromisoformat(r['receivedAt'].replace('Z','+00:00')).timestamp()*1000 for r in sender.rows}
        frames=[f for f in observer.frames if start_wall<=f['observerWallMs']<=end_wall and f['sourceSeq'] in received]
        measured=dict(name=name,runId=run,targetEventsPerSecond=target,requestedSeconds=seconds,actualSeconds=duration,
            activeStartWallMs=start_wall,activeEndWallMs=end_wall,activeUniqueEvents=len(active),actualUniqueRate=len(active)/duration,
            activeSnapshotEvents=sum(r['eventType']=='FACTORY_SNAPSHOT' for r in active),snapshotScheduleMisses=missed,tickScheduleMisses=tick_missed,
            originals=len(raw),ingestionRows=len(rows),operationsRows=len(ops),wireAttempts=sender.wire_attempts,
            ackStatuses={key:sum(a['status']==key for a in sender.acks) for key in ('RECEIVED','DUPLICATE_RECEIVED','RETRY_LATER','REJECTED')},
            unacknowledged=len(sender.pending),deliveryPending=status['pendingCount'],maxSourcePendingEvents=max_pending,
            maxSampledDeliveryPending=max(s['pendingCount'] for s in observer.samples),
            maxSampledDeliveryBytes=max(s['pendingBytes'] for s in observer.samples),
            frameBytes=distribution([len(r)+1 for r in raw]),ackRoundTripMs=distribution([(r['sendEndNs']-r['sendStartNs'])/1e6 for r in active]),
            receiveToObservedSseMs=distribution([f['observerWallMs']-received[f['sourceSeq']] for f in frames]),
            observedActiveSseFrames=len(frames),physicalBodies=len(final['bodies']),physicalVehicles=len(final['vehicles']),
            cumulativeQuality=final['metrics']['cumulativeQuality'],drainSeconds=time.monotonic()-drain_start,
            targetReached=len(active)/duration>=target,nominalRateFraction=len(active)/duration/target,
            targetCriteria='Actual unique rate >= nominal target',byteExactBothDatabases=True,ownRowsCleaned=False)
        rt.save(name+'/send-measurements.json',sender.rows);rt.save(name+'/final.json',final);rt.save(name+'/result.json',measured)
        # Strictly this newly created successful UUID, preserving all source/measurement artifacts.
        rt.sql('operations_db',"BEGIN; SELECT pg_advisory_xact_lock(hashtextextended('"+run+"',7304001)); "+'; '.join(f"DELETE FROM {t} WHERE run_id='{run}'" for t in OPS_TABLES)+'; COMMIT;')
        rt.sql('ingestion_db','BEGIN; '+'; '.join(f"DELETE FROM {t} WHERE run_id='{run}'" for t in SOURCE_TABLES)+'; COMMIT;')
        measured['ownRowsCleaned']=True;rt.save(name+'/result.json',measured)
        print('COMPLETE',name,'rate',round(measured['actualUniqueRate'],2),'ACK p95',round(measured['ackRoundTripMs']['p95'],2),'originals',len(raw),flush=True)
        return measured
    finally:
        originals.close();sender.close()
        if observer:observer.close()

def summarize(rt,results):
    trace={}
    for service in ('ingestion','operations'):
        path=rt.evidence/(service+'-measurement.csv')
        if not path.exists():continue
        with path.open() as file:
            for row in csv.reader(file):
                if len(row)!=9:raise ValueError('Measurement trace truncated/limited')
                phase_name,run,event,seq,status,start,end,wall,pid=row
                trace.setdefault(run,{}).setdefault(phase_name,[]).append(dict(seq=int(seq),ms=(int(end)-int(start))/1e6,status=status,wall=int(wall),pid=int(pid)))
    browser=[]
    path=rt.evidence/'browser.ndjson'
    if path.exists():browser=[json.loads(row) for row in path.read_text().splitlines()]
    for result in results:
        start=result['activeStartWallMs'];end=result['activeEndWallMs'];run=result['runId']
        result['internalPhasesMs']={key:distribution([r['ms'] for r in rows if start<=r['wall']<=end]) for key,rows in trace.get(run,{}).items()}
        expected={r['sourceSeq'] for r in json.loads((rt.evidence/result['name']/'send-measurements.json').read_text())}
        result['internalTraceCounts']={key:dict(rows=len(rows),uniqueSequences=len({r['seq'] for r in rows}),missingSequences=len(expected-{r['seq'] for r in rows})) for key,rows in trace.get(run,{}).items()}
        result['internalTracePids']={key:sorted({r['pid'] for r in rows}) for key,rows in trace.get(run,{}).items()}
        assert set(result['internalTraceCounts'])=={'ingestion-queue','ingestion-transaction','delivery-http','operations-transaction'}
        assert all(count['missingSequences']==0 for count in result['internalTraceCounts'].values())
        received={r['sourceSeq']:datetime.fromisoformat(r['receivedAt'].replace('Z','+00:00')).timestamp()*1000 for r in json.loads((rt.evidence/result['name']/'send-measurements.json').read_text())}
        active_rows=[r for r in json.loads((rt.evidence/result['name']/'send-measurements.json').read_text()) if start<=r['ackWallMs']<=end]
        active_seqs={r['sourceSeq'] for r in active_rows}
        generated={}
        with (rt.evidence/result['name']/'originals.ndjson').open() as originals:
            for line in originals:
                event=json.loads(line)
                if event['sourceSeq'] in active_seqs:generated[event['sourceSeq']]=datetime.fromisoformat(event['occurredAt'].replace('Z','+00:00')).timestamp()*1000
        result['generatedToReceivedMs']=distribution([received[seq]-at for seq,at in generated.items()])
        result['receivedToOperationsCommitMs']=distribution([r['wall']-received[r['seq']] for r in trace[run]['operations-transaction'] if r['seq'] in active_seqs and r['status']=='APPLIED'])
        # Date.now() - (timeOrigin + performance.now()) was captured in the same callback.
        # Correct clock-origin offsets before comparing the browser epoch with server wall time.
        rendered_wall=lambda row:row['renderedAt']+row['clockOffsetMs']
        renders=[r for r in browser if r['kind']=='render' and r['runId']==run and start<=rendered_wall(r)<=end and r['sourceSeq'] in received]
        visible=[r for r in renders if r['visibility']=='visible' and r['focused']]
        # A frame-only sample from a different selected run cannot demonstrate this run's GUI performance.
        offsets=sorted(r['clockOffsetMs'] for r in visible);offset=offsets[len(offsets)//2] if offsets else 0
        frame_rows=[r for r in browser if r['kind']=='frame' and start<=r['at']+r.get('clockOffsetMs',offset)<=end and r['visibility']=='visible' and r['focused']] if visible else []
        result['browser']=dict(totalRenderSamples=len(renders),foregroundRenderSamples=len(visible),
            viewports=list({(r['width'],r['height'],r['dpr']) for r in renders}),
            receiveToFrameMs=distribution([rendered_wall(r)-received[r['sourceSeq']] for r in visible]),
            uncorrectedReceiveToFrameMs=distribution([r['renderedAt']-received[r['sourceSeq']] for r in visible]),
            browserClockOffsetMs=distribution([r['clockOffsetMs'] for r in visible]),
            clockOriginCorrected=True,frameWindowAlignment='Per-frame offset if recorded; otherwise median render offset of this trial',
            vueToFrameMs=distribution([r['vueToFrameMs'] for r in visible]),
            foregroundFrameIntervalMs=distribution([r['intervalMs'] for r in frame_rows]),
            foregroundObservedFps=(1000*len(frame_rows)/sum(r['intervalMs'] for r in frame_rows)) if frame_rows else None,
            longTasks=sum(r['kind']=='longtask' and start<=r['at']<=end for r in browser))
        rt.save(result['name']+'/result.json',result)

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--browser',action='store_true');parser.add_argument('--continue-artifacts',action='store_true')
    parser.add_argument('--rates',type=int,choices=(25,100,300,500),nargs='+',default=[25,100,300,500],help='Repeat only selected input targets, three times each')
    parser.add_argument('--first-repeat',type=int,choices=(1,2,3),default=1,help='Start the first selected target at this repeat; later targets use all three')
    parser.add_argument('--skip-regression',action='store_true',help='Only after selected regressions already passed; build without repeating tests')
    args=parser.parse_args()
    if len(args.rates)!=len(set(args.rates)):parser.error('Duplicate input targets are not allowed')
    rt=Runtime('performance-verification');results=[]
    print('EVIDENCE',rt.evidence,flush=True)
    environment=dict(os=platform.platform(),architecture=platform.machine(),python=sys.version,
        workload='Single SourceSession writer, one original in flight, model snapshots plus actual body transitions',
        clock='Same-host wall clock for cross-process estimates; process-monotonic for internal spans',
        repeatConditions='Fresh UUID, own successful rows removed after byte-exact reconciliation; same 5s warmup',
        observer='Native REST diagnostics 1Hz and SSE; optional actual Chrome GUI',measurementOverhead='Enabled CSV and dev browser collectors; not a production instrumentation guarantee',
        containerResources='Native host benchmark; Compose VM limits do not constrain this run. Other user workloads are not stopped',
        postgres=subprocess.check_output([str(rt.bin/'postgres'),'--version'],text=True).strip(),
        java=subprocess.run([str(rt.java),'-version'],capture_output=True,text=True).stderr.strip())
    if platform.system()=='Darwin':
        hardware=subprocess.run(['sysctl','-n','machdep.cpu.brand_string','hw.memsize','hw.ncpu'],capture_output=True,text=True)
        if hardware.returncode==0:
            cpu,memory,cores=hardware.stdout.strip().splitlines();environment.update(cpu=cpu,memoryBytes=int(memory),logicalCores=int(cores))
        chrome=Path('/Applications/Google Chrome.app/Contents/Info.plist')
        if chrome.exists():environment['chrome']=plistlib.loads(chrome.read_bytes())['CFBundleShortVersionString']
    lock=json.loads((ROOT/'services/factory-console/package-lock.json').read_text())
    for name in ('vue','vite','echarts'):environment[name]=lock['packages']['node_modules/'+name]['version']
    rt.save('environment.json',environment)
    try:
        rt.start_pg();rt.run([ROOT/'scripts/init-databases.sh'],'initial-databases')
        rt.env['FACTORY_INGESTION_TESTS']='true'
        for service,test in [('ingestion','EventStoreTests#realTcpCommitLostAckPipeliningMalformedAndPartialDisconnect'),('operations','OperationsIntegrationTests#completeScenarioIdempotencyFactsLateSnapshotAndRunIsolation')]:
            rt.run([ROOT/'scripts/service-maven.sh',service+'-service','--offline','--batch-mode','--no-transfer-progress','-DskipTests' if args.skip_regression else '-Dtest='+test,'verify'],service+'-selected')
        # Selected integration tests own their fixture UUIDs; retain their results but establish a constant empty trial baseline.
        if not args.skip_regression:
            for database,tables in [('operations_db',OPS_TABLES),('ingestion_db',SOURCE_TABLES)]:rt.sql(database,'TRUNCATE '+','.join(tables)+' CASCADE')
        rt.env['FACTORY_MEASUREMENT_ENABLED']='true';rt.start_service('operations');rt.start_service('ingestion')
        rt.spawn('resource-sampler',[sys.executable,ROOT/'scripts/collect-measurement-resources.py',rt.evidence])
        port=free_port();env=dict(rt.env,OPERATIONS_PROXY_TARGET=rt.url('operations'),VITE_FACTORY_MEASUREMENT='true',FACTORY_BROWSER_MEASUREMENT_FILE=str(rt.evidence/'browser.ndjson'))
        rt.spawn('console',[ROOT/'scripts/console.sh','dev','--host','127.0.0.1','--port',str(port)],env)
        await_condition(lambda:urllib.request.urlopen(f'http://127.0.0.1:{port}/readyz',timeout=2).status==200)
        for index,target in enumerate(args.rates):
            seconds=300 if target==25 else 120
            for repeat in range(args.first_repeat if index==0 else 1,4):results.append(trial(rt,f'normal-{repeat}' if target==25 else f'stress-{target}-{repeat}',target,seconds,port,args.browser))
        if args.continue_artifacts:
            phase(rt,'MEASUREMENTS_COMPLETE','',port)
            await_condition(lambda:(rt.evidence/'artifacts.continue').exists(),3600)
        rt.stop('ingestion');rt.stop('operations');summarize(rt,results)
        rt.save('result.json',dict(suite='S09 measured native pipeline',trials=results,completedTrials=len(results),requestedTrials=3*len(args.rates)-args.first_repeat+1,selectedRates=args.rates,firstRepeat=args.first_repeat,selectedRegressionSkipped=args.skip_regression,
            byteExactBothDatabases=all(r['byteExactBothDatabases'] for r in results),ownedProcessesStopped=False,retainedDatabase=True))
        print('PASS:',len(results),'measured trials; requested and achieved rates recorded separately',flush=True)
    except Exception as error:
        rt.save('failed-probe.json',dict(error=str(error),completedTrials=len(results),recordsPreserved=True));raise
    finally:rt.close()

if __name__=='__main__':main()
