"""S08 isolated real TCP/HTTP/two-DB failure and 100-body correctness probe.

Use the cached Python 3.12 interpreter. --browser gates require native browser proof;
only SSE is cut by a development-only loopback proxy. No production fault endpoints.
"""
import argparse
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from verification_runtime import ROOT, Runtime, await_condition, free_port
sys.path.insert(0, str(ROOT/'services/factory-simulator'))
from factory_simulator.configuration import Settings
from factory_simulator.logistics import VehicleState
from factory_simulator.model import FactoryModel, LocationType, CellState
from factory_simulator.p0_demo import P0Driver
from factory_simulator.run_configuration import RunConfiguration, CELLS
from factory_simulator.sender import Sender, SourceSession


def spatial(view):
    return {key:[{k:v for k,v in item.items() if k!='lastObservedAt'} for item in view[key]]
            for key in ('equipment','buffers','bodies','vehicles','activeTransports')}


class ObservedSender(Sender):
    def _validate_ack(self, ack, original):
        result=super()._validate_ack(ack, original)
        self.last_ack=dict(ack)
        return result


class Wire:
    def __init__(self, runtime, count=None):
        self.runtime=runtime
        config=RunConfiguration.from_path().to_dict()
        for item in config['config']['equipment']:
            item['workDurationMs']=200
        for item in config['config']['routes']:
            item['travelDurationMs']=200 if count else 1000
        self.model=FactoryModel(RunConfiguration.from_dict(config), quality_results=('FAIL','PASS','PASS','PASS','PASS'))
        self.sender=ObservedSender(Settings('127.0.0.1',int(runtime.env['INGESTION_TCP_PORT'])), error_path=runtime.evidence/'send-errors.ndjson')
        self.session=SourceSession(self.model,self.sender)
        self.originals=[]
        self.file=(runtime.evidence/(self.model.run_id+'.ndjson')).open('wb')
        self.drain()

    @property
    def run(self):return self.model.run_id

    def drain(self):
        while self.sender.pending:
            original=self.sender.pending.head
            confirmed=self.session.send_head()
            assert confirmed is original
            self.originals.append(original)
            self.file.write(original.frame);self.file.flush()

    def change(self, method, *args):
        result=self.session.change(method,*args)
        self.drain()
        return result

    def snapshot(self):
        self.change(self.model.publish_snapshot)
        target=self.originals[-1].source_seq
        await_condition(lambda: self.runtime.get('ingestion',f'/internal/v1/runs/{self.run}/delivery-status')['nextSourceSeq']>target,60)
        view=await_condition(lambda: (v if v['sourceSeq']==target else None) if (v:=self.view()) else None,15)
        assert spatial(view)==spatial(self.model.snapshot())
        return view

    def view(self):return self.runtime.get('operations',f'/api/v1/runs/{self.run}/snapshot')

    def final(self, bodies):
        self.change(self.model.finish_run)
        await_condition(lambda: self.runtime.get('ingestion',f'/internal/v1/runs/{self.run}/delivery-status')['pendingCount']==0,180)
        view=await_condition(lambda:(v if v['dataStatus']=='FINISHED' else None) if (v:=self.view()) else None)
        assert len(view['bodies'])==bodies and not view['activeTransports']
        assert spatial(view)==spatial(self.model.snapshot())
        # Compare every original; no UUID/sequence/payload normalization at either boundary.
        def rows(db,query):return json.loads(self.runtime.sql(db,query))
        left=rows('ingestion_db',f"SELECT json_agg(json_build_object('seq',r.source_seq,'raw',r.raw_json_text,'hash',r.payload_hash,'status',o.delivery_status) ORDER BY source_seq) FROM raw_event r JOIN event_outbox o USING(run_id,event_id) WHERE run_id='{self.run}'")
        right=rows('operations_db',f"SELECT json_agg(json_build_object('seq',source_seq,'raw',raw_json_text,'hash',payload_hash) ORDER BY source_seq) FROM processed_event WHERE run_id='{self.run}'")
        assert len(left)==len(right)==len(self.originals)
        for original,a,b in zip(self.originals,left,right):
            assert a['seq']==b['seq']==original.source_seq and a['status']=='DELIVERED'
            assert a['raw'].encode()==b['raw'].encode()==original.frame[:-1]
            assert a['hash']==b['hash']==hashlib.sha256(original.frame[:-1]).hexdigest()
        facts=rows('operations_db',f"SELECT json_build_object('operations',(SELECT count(*) FROM operation_history WHERE run_id='{self.run}'),'inspections',(SELECT count(*) FROM inspection_result WHERE run_id='{self.run}'),'transports',(SELECT count(*) FROM transport_history WHERE run_id='{self.run}'))")
        assert facts['operations']==bodies*3 and facts['inspections']==bodies
        self.runtime.save(self.run+'-final.json',view)
        return dict(runId=self.run, events=len(self.originals),maxFrameBytes=max(len(o.frame) for o in self.originals),facts=facts,quality=view['metrics']['cumulativeQuality'])

    def close(self):self.sender.close();self.file.close()


class SseCut:
    """Development proxy: REST untouched; cuts/rejects only browser SSE connections."""
    def __init__(self, runtime):
        self.blocked=threading.Event();self.requests=0;self.cuts=0
        cut=self
        class Handler(BaseHTTPRequestHandler):
            protocol_version='HTTP/1.1'
            def log_message(self,*args):pass
            def do_GET(self):
                stream=self.path.split('?')[0].endswith('/stream')
                if stream:
                    cut.requests+=1
                if stream and cut.blocked.is_set():
                    self.send_error(503,'S08 isolated SSE interruption');return
                try:
                    with urllib.request.urlopen(runtime.url('operations')+self.path,timeout=6) as source:
                        self.send_response(source.status)
                        for key in ('Content-Type','Cache-Control'):
                            if source.headers.get(key):self.send_header(key,source.headers[key])
                        self.send_header('Connection','close');self.end_headers();self.close_connection=True
                        if stream:
                            while line:=source.readline():
                                if cut.blocked.is_set():
                                    cut.cuts+=1;return
                                self.wfile.write(line);self.wfile.flush()
                        else:self.wfile.write(source.read())
                except (BrokenPipeError,ConnectionResetError):pass
                except urllib.error.HTTPError as error:
                    self.send_error(error.code)
                except (OSError,ValueError):
                    # A live connection is closed; the browser must reconnect, never receive a fake snapshot.
                    self.close_connection=True
            def do_POST(self):self.send_error(405)
        self.server=ThreadingHTTPServer(('127.0.0.1',free_port()),Handler)
        self.server.daemon_threads=True
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()

    def close(self):self.server.shutdown();self.server.server_close();self.thread.join(timeout=2)


def readiness(runtime,name,status):
    try:
        with urllib.request.urlopen(runtime.url(name)+'/readyz',timeout=5) as response:
            return response.status==status
    except urllib.error.HTTPError as error:return error.code==status


def retry_source(wire,restore,name):
    """Real failure reply/connection failure, then recover only this owned dependency."""
    head=wire.sender.pending.head;seen=[];original_sleep=wire.sender.sleep
    def on_retry(delay):
        assert wire.sender.pending.head is head and head.frame==wire.sender.pending.head.frame
        seen.append(dict(state=wire.sender.state,attempts=wire.sender.attempts,sourceSeq=head.source_seq,sha256=hashlib.sha256(head.frame[:-1]).hexdigest()))
        if len(seen)==1:restore()
        time.sleep(min(delay,.5))
    wire.sender.sleep=on_retry
    try:wire.drain()
    finally:wire.sender.sleep=original_sleep
    assert seen and not wire.sender.pending
    wire.runtime.save(name+'.json',seen)


def browser_probe(runtime,wire,cut):
    port=free_port();env=dict(runtime.env)
    env['OPERATIONS_PROXY_TARGET']='http://127.0.0.1:'+str(cut.server.server_port)
    runtime.spawn('console',[ROOT/'scripts/console.sh','dev','--port',str(port),'--strictPort'],env)
    url=f'http://127.0.0.1:{port}/?run={wire.run}'
    await_condition(lambda:urllib.request.urlopen(url,timeout=2).status==200)
    def gate(phase):
        view=wire.snapshot()
        runtime.save('phase.json',dict(phase=phase,runId=wire.run,url=url,view=view))
        print('BROWSER',phase,url,'Evidence:',runtime.evidence.relative_to(ROOT),flush=True)
        deadline=time.monotonic()+600
        while not (runtime.evidence/('UI.'+phase+'.continue')).exists():
            if time.monotonic()>deadline:raise TimeoutError('Native browser proof missing: '+phase)
            # Keep source TCP and operations observation LIVE while only SSE is cut.
            wire.snapshot();time.sleep(.5)
    gate('SSE_CONNECTED')
    before=wire.view();cut.blocked.set();gate('SSE_INTERRUPTED')
    assert cut.cuts>0 and cut.requests>=2
    after=wire.view();assert after['sourceSeq']>before['sourceSeq'] and after['dataStatus']=='LIVE'
    assert spatial(before)==spatial(after)
    cut.blocked.clear();gate('SSE_RECOVERED')
    proof=json.loads((runtime.evidence/'browser-proof.json').read_text())
    assert proof['runId']==wire.run and all(proof[k] for k in ('connected','lastValuesRetained','screenDisconnected','sourceStillLive','recovered','selectionRetained'))
    assert all((runtime.evidence/p).is_file() for p in proof['screenshots'])
    runtime.save('sse-cut-result.json',dict(requests=cut.requests,cuts=cut.cuts,sourceAdvanced=True,browserVerified=True))


def faults(runtime,wire,browser):
    model=wire.model;driver=P0Driver(model);driver.initialize(wire.change)
    first=next(t for t in model.active_transports if t.cargo_type=='BODY')
    before=model.buffer(first.destination.location_id)
    wire.change(model.cancel_transport,first.transport_id)
    cancelled=wire.snapshot();released=model.buffer(first.destination.location_id)
    assert released['availableSlots']==before['availableSlots']+1
    count=len(wire.originals);wire.change(model.cancel_transport,first.transport_id)
    assert len(wire.originals)==count and model.body(first.body_id).location.location_type==LocationType.INPUT
    retry=wire.change(model.assign_transport,first.body_id)
    assert retry.approved
    wire.change(model.start_transport,retry.transport_id)
    runtime.save('cancel-return.json',dict(before=before,after=released,view=cancelled,repeatedCancellationAddedEvents=0))
    stages=[]
    for _ in range(4000):
        stage=driver.step(wire.change)
        while stage:
            view=wire.snapshot();bay=next(b for b in view['buffers'] if b['cellId']=='ASM-02')
            if stage in ('FULL_RESERVED','FULL_IN_TRANSIT'):assert (bay['waitingCount'],bay['reservedInboundCount'],bay['availableSlots'])==(2,1,0)
            if stage in ('FULL_ARRIVED','CELL_DOWN'):assert (bay['waitingCount'],bay['reservedInboundCount'],bay['availableSlots'])==(3,0,0)
            if stage=='FULL_RESERVED':
                baseline=spatial(view)
                # Commit an original, deliberately discard its real ACK, replay exact pending bytes.
                wire.session.change(model.publish_snapshot);head=wire.sender.pending.head
                wire.sender.close()
                with socket.create_connection(('127.0.0.1',int(runtime.env['INGESTION_TCP_PORT'])),timeout=3) as connection:
                    connection.sendall(head.frame)
                    reply=json.loads(connection.makefile('rb').readline());assert reply['status']=='RECEIVED'
                wire.drain()
                assert wire.sender.last_ack['status']=='DUPLICATE_RECEIVED'
                runtime.save('lost-tcp-ack.json',dict(eventId=head.event_id,sourceSeq=head.source_seq,sha256=hashlib.sha256(head.frame[:-1]).hexdigest(),resentStatus=wire.sender.last_ack['status']))
                # TCP service stop; head survives actual connection refusal.
                runtime.stop('ingestion');wire.sender.close();wire.session.change(model.publish_snapshot)
                retry_source(wire,lambda:runtime.start_service('ingestion'),'tcp-restart')
                assert spatial(wire.snapshot())==baseline
                # Ingestion DB is inaccessible while service remains alive.
                runtime.database_access('ingestion_db',False)
                assert readiness(runtime,'ingestion',503)
                wire.session.change(model.publish_snapshot)
                retry_source(wire,lambda:runtime.database_access('ingestion_db',True),'ingestion-db-outage')
                assert spatial(wire.snapshot())==baseline
                # Operations process stop: successful TCP ACK does not mean business application.
                previous=wire.view();runtime.stop('operations')
                wire.change(model.publish_snapshot)
                pending=runtime.get('ingestion',f'/internal/v1/runs/{wire.run}/delivery-status')
                assert pending['pendingCount']>=1
                runtime.save('operations-stopped.json',pending)
                runtime.start_service('operations')
                await_condition(lambda:runtime.get('ingestion',f'/internal/v1/runs/{wire.run}/delivery-status')['pendingCount']==0,60)
                restored=wire.view();assert restored['serverEpoch']!=previous['serverEpoch'] and spatial(restored)==baseline
                # Restart again without a new original: restored physical values require fresh source observation.
                runtime.stop('operations');runtime.start_service('operations')
                restoring=wire.view();assert restoring['dataStatus']=='RESTORING' and not restoring['observedAfterEpoch']
                assert spatial(restoring)==baseline
                runtime.save('restoring.json',restoring)
                assert wire.snapshot()['observedAfterEpoch']
                # Operations DB outage keeps head unconfirmed in the ingestion outbox.
                runtime.database_access('operations_db',False)
                assert readiness(runtime,'operations',503)
                wire.change(model.publish_snapshot)
                def retained():
                    raw=runtime.sql('ingestion_db',f"SELECT json_agg(json_build_object('seq',r.source_seq,'error',o.last_error,'attempts',o.total_attempt_count,'status',o.delivery_status)) FROM event_outbox o JOIN raw_event r USING(run_id,event_id) WHERE r.run_id='{wire.run}' AND o.delivery_status<>'DELIVERED'")
                    return json.loads(raw) if raw and raw!='null' and 'DB_UNAVAILABLE' in raw else None
                runtime.save('operations-db-outage.json',await_condition(retained,30))
                runtime.database_access('operations_db',True)
                assert spatial(wire.snapshot())==baseline
                # Real PostgreSQL process restart affects both databases; no recreation/migration reset.
                runtime.stop_pg();wire.sender.close();wire.session.change(model.publish_snapshot)
                retry_source(wire,runtime.start_pg,'postgres-restart')
                assert spatial(wire.snapshot())==baseline
                # No reports for >10 s: freshness changes; reservations never time out.
                time.sleep(3.3)
                stale=wire.view();assert stale['dataStatus']=='STALE' and spatial(stale)==baseline
                runtime.save('source-stale.json',stale)
                time.sleep(8.7)
                offline=wire.view();assert offline['dataStatus']=='DISCONNECTED' and spatial(offline)==baseline
                runtime.save('source-disconnected.json',offline)
                fresh=wire.snapshot();assert fresh['dataStatus']=='LIVE' and spatial(fresh)==baseline
                if browser:
                    cut=SseCut(runtime)
                    try:browser_probe(runtime,wire,cut)
                    finally:cut.close()
            if stage=='FULL_IN_TRANSIT':
                wire.change(model.fail_cell,'ASM-02')
                view=wire.snapshot()
                assert next(e for e in view['equipment'] if e['cellId']=='ASM-02')['state']=='DOWN'
            if stage=='FULL_ARRIVED':
                assert next(e for e in view['equipment'] if e['cellId']=='ASM-02')['state']=='DOWN'
                assert next(e for e in view['equipment'] if e['cellId']=='ASM-01')['blockedReason']=='BUFFER_FULL'
            if stage=='CELL_DOWN':
                alarm=next(a for a in view['alarms'] if a['type']=='EQUIPMENT_DOWN' and a['targetId']=='ASM-01' and a['conditionActive'])
                request=urllib.request.Request(runtime.url('operations')+f"/api/v1/alarms/{alarm['alarmId']}/acknowledge",data=b'{"operatorId":"s08-operator"}',headers={'Content-Type':'application/json'},method='POST')
                with urllib.request.urlopen(request,timeout=5) as response:assert response.status==200
                ack=wire.snapshot();assert spatial(ack)==spatial(view)
                assert any(a['alarmId']==alarm['alarmId'] and a['conditionActive'] and a['acknowledgedBy']=='s08-operator' for a in ack['alarms'])
                acknowledged=next(a for a in ack['alarms'] if a['alarmId']==alarm['alarmId'])
                with urllib.request.urlopen(request,timeout=5) as response:assert response.status==200
                repeated=wire.snapshot()
                assert next(a for a in repeated['alarms'] if a['alarmId']==alarm['alarmId'])['acknowledgedAt']==acknowledged['acknowledgedAt']
                wire.change(model.recover_cell,'ASM-02')
            if stage=='SLOT_RELEASED':
                assert (bay['waitingCount'],bay['reservedInboundCount'],bay['availableSlots'])==(2,0,1)
                assert any(a['type']=='EQUIPMENT_DOWN' and a['targetId']=='ASM-01' and not a['conditionActive'] and a['acknowledgedBy']=='s08-operator' for a in view['alarms'])
                assert any(a['type']=='EQUIPMENT_DOWN' and a['targetId']=='ASM-02' and not a['conditionActive'] and a['acknowledgedAt'] is None for a in view['alarms'])
            runtime.save(stage+'.json',view);stages.append(stage)
            print('PASS stage',stage,flush=True)
            stage=driver.after(stage,wire.change)
        if driver.drained():break
    else:raise AssertionError('P0 run failed to drain')
    assert stages==['FULL_RESERVED','FULL_IN_TRANSIT','FULL_ARRIVED','CELL_DOWN','SLOT_RELEASED']
    return wire.final(5)


def flow100(runtime,wire):
    model=wire.model
    for _ in range(100):wire.change(model.register_body)
    wire.snapshot();wire.change(model.redispatch)
    snapshots=0
    for step in range(10000):
        wire.change(model.tick)
        for cell in reversed(CELLS):
            waiting=model.bodies_at(LocationType.BUFFER,'BAY-'+cell)
            if waiting and model.cell(cell).state==CellState.IDLE:wire.change(model.enter_cell,waiting[0].body_id)
        state=model.snapshot()
        # One canonical body location plus exactly matching cell/slot/vehicle ownership at EVERY tick.
        assert len(state['bodies'])==len({b['bodyId'] for b in state['bodies']})==100
        for bay in state['buffers']:
            assert 0<=bay['waitingCount']+bay['reservedInboundCount']<=bay['capacity']
            assert bay['availableSlots']==bay['capacity']-bay['waitingCount']-bay['reservedInboundCount']
        for body in state['bodies']:
            owners=sum(e.get('bodyId')==body['bodyId'] for e in state['equipment'])
            owners+=sum(s.get('bodyId')==body['bodyId'] and s['status']=='OCCUPIED' for b in state['buffers'] for s in b['slots'])
            owners+=sum(v.get('bodyId')==body['bodyId'] for v in state['vehicles'])
            assert owners==(1 if body['locationType'] in ('CELL','BUFFER','VEHICLE') else 0)
        if step%100==0:
            wire.snapshot();snapshots+=1
        if all(b.location.location_type==LocationType.RESULT for b in model.bodies) and all(v.state==VehicleState.IDLE for v in model.vehicles):break
    else:raise AssertionError('100 registered bodies did not finish')
    assert (len(model.operations),len(model.inspections),len(model.transports),len(model.cell_entries))==(300,100,400,300)
    result=wire.final(100)
    assert result['facts']==dict(operations=300,inspections=100,transports=400)
    assert result['quality']==dict(inspectedCount=100,passCount=80,failCount=20,failRate=.2)
    # Same runId,eventId,seq and bytes at all boundaries on duplicate actual TCP originals.
    for kind in ('INSPECTION_COMPLETED','TRANSPORT_COMPLETED'):
        original=next(o for o in wire.originals if json.loads(o.frame)['eventType']==kind)
        for _ in range(10):
            wire.sender.pending.enqueue_originals([original]);wire.sender.send_head()
            assert wire.sender.last_ack['status']=='DUPLICATE_RECEIVED'
    assert int(runtime.sql('operations_db',f"SELECT count(*) FROM inspection_result WHERE run_id='{wire.run}'"))==100
    result.update(ticks=step+1,checkedSnapshots=snapshots,duplicateFactsAdded=0,inspectionDuplicateAttempts=10,transportDuplicateAttempts=10)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    browser_modes=parser.add_mutually_exclusive_group()
    browser_modes.add_argument('--browser',action='store_true')
    browser_modes.add_argument('--browser-evidence',type=Path,help='Reuse already verified native SSE component; records its different run explicitly')
    args=parser.parse_args()
    runtime=Runtime();wires=[];success=False
    print('S08 evidence:',runtime.evidence.relative_to(ROOT),flush=True)
    try:
        browser_reference=None
        if args.browser_evidence:
            path=args.browser_evidence.resolve()
            if not path.is_relative_to(runtime.evidence.parent.resolve()) or path==runtime.evidence.resolve():
                raise ValueError('Reuse only retained S08 native browser evidence')
            proof=json.loads((path/'browser-proof.json').read_text())
            cut=json.loads((path/'sse-cut-result.json').read_text())
            assert all(proof[k] for k in ('connected','lastValuesRetained','screenDisconnected','sourceStillLive','recovered','selectionRetained'))
            assert cut['browserVerified'] and cut['sourceAdvanced'] and cut['cuts']>=1 and cut['requests']>=2
            assert all((path/p).is_file() for p in proof['screenshots'])
            connected=(path/'connected-dom.txt').read_text();interrupted=(path/'interrupted-dom.txt').read_text();recovered=(path/'recovered-dom.txt').read_text()
            assert all(proof['runId'] in dom for dom in (connected,interrupted,recovered))
            assert 'heading "실시간 관측"' in connected and 'heading "화면 연결 확인 필요 · 마지막 확인값"' in interrupted and 'heading "실시간 관측"' in recovered
            assert 'searchbox "태그 또는 차체 검색": tag-00004' in recovered
            assert all(fragment in dom for dom in (connected,interrupted,recovered) for fragment in ('body-00004 / tag-00004','ASM-01 · CELL','transport-00009 / AGV-002','reserve-00008','W2 / R1 / A0'))
            browser_reference=dict(path=str(path.relative_to(ROOT)),runId=proof['runId'],componentOnly=True)
            runtime.save('reused-browser-evidence.json',browser_reference)
        runtime.start_pg();runtime.run([ROOT/'scripts/init-databases.sh'],'initialize')
        # Only two existing edge methods: late snapshots/facts, semantic duplicate IDs, commit-fenced pages.
        runtime.run([ROOT/'scripts/service-maven.sh','operations-service','--offline','--batch-mode','--no-transfer-progress',
                     '-Dtest=OperationsIntegrationTests#completeScenarioIdempotencyFactsLateSnapshotAndRunIsolation+quality100Fail20HalfOpenWindowLateFactAndFencedPagination','verify'],'late-facts-tests')
        for name in ('ingestion','operations'):
            runtime.run([ROOT/'scripts/service-maven.sh',name+'-service','--offline','--batch-mode','--no-transfer-progress','-DskipTests','package'],name+'-package')
        runtime.start_service('operations');runtime.start_service('ingestion')
        first=Wire(runtime);wires.append(first);p0=faults(runtime,first,args.browser)
        second=Wire(runtime,100);wires.append(second);hundred=flow100(runtime,second)
        left=runtime.get('operations',f'/api/v1/runs/{first.run}/tags/tag-00001/body')['data']
        right=runtime.get('operations',f'/api/v1/runs/{second.run}/tags/tag-00001/body')['data']
        assert left['bodyId']==right['bodyId']=='body-00001'
        assert len(first.view()['bodies'])==5 and first.view()['metrics']['cumulativeQuality']['inspectedCount']==5
        assert len(second.view()['bodies'])==100 and second.view()['metrics']['cumulativeQuality']['inspectedCount']==100
        runtime.save('result.json',dict(suite='S08',p0=p0,flow100=hundred,lateFactTests=2,runIsolation=True,
                     browserVerified=bool(args.browser or browser_reference),browserReference=browser_reference,ownedProcessesStopped=False,retainedDatabase=True,performanceBenchmark=False))
        success=True;print('PASS S08:',json.dumps(dict(p0=p0,flow100=hundred,browser=bool(args.browser or browser_reference))),flush=True)
    finally:
        for wire in wires:wire.close()
        if not success:runtime.save('failed-probe.json',dict(recordsPreserved=True))
        runtime.close()


if __name__=='__main__':main()
