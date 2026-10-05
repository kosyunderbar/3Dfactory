"""S07: registered P0 buffer stages/AMR/fault/quality -> real two DBs/REST/SSE. --browser-stages requires actual CUA proof.
Only a generated UUID checked absent BEFORE TCP sending may be cleaned after full success.
The owned simulator is briefly SIGSTOPped (not the user's services); failed records are preserved.
"""
import argparse
from datetime import datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import threading
import time
import urllib.request
import urllib.parse
import uuid

ROOT=Path(__file__).resolve().parents[1]
SOURCE_TABLES=['delivery_action','event_outbox','raw_event','delivery_stream']
OPS_TABLES=['factory_snapshot','inspection_result','operation_history','transport_history','alarm','event_projection','processed_event','body','factory_buffer','equipment','vehicle','simulation_run']


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--browser-stages',action='store_true');args=parser.parse_args()
    evidence=ROOT/'.build-cache/p0-console-verification'/uuid.uuid4().hex;evidence.mkdir(parents=True)
    ui=os.environ.get('CONSOLE_BASE_URL','http://127.0.0.1:5173').rstrip('/')
    ingestion=os.environ.get('INGESTION_BASE_URL','http://127.0.0.1:8081').rstrip('/')
    def sql(database,query):
        return subprocess.check_output([str(ROOT/'scripts/dev-stack.sh'),'compose','exec','-T','postgres','psql','--no-psqlrc','--username=postgres','--dbname='+database,'--tuples-only','--no-align','-v','ON_ERROR_STOP=1','-c',query],cwd=ROOT,text=True).strip()
    def get(base,path):
        with urllib.request.urlopen(base+path,timeout=5) as response:return json.load(response)
    def wait(check,seconds=30):
        deadline=time.monotonic()+seconds
        while time.monotonic()<deadline:
            try:
                result=check()
                if result:return result
            except (OSError,ValueError):pass
            if process.poll() is not None and process.returncode!=0:raise RuntimeError('Owned simulator failed; inspect simulator.log')
            time.sleep(.1)
        raise RuntimeError('Connected console verification timed out')
    def save(name,value):(evidence/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
    config=json.loads((ROOT/'services/factory-simulator/factory_simulator/config/default-run.json').read_text())
    for item in config['config']['equipment']:item['workDurationMs']=200
    for route in config['config']['routes']:route['travelDurationMs']=1000
    save('run-config.json',config)
    environment=dict(os.environ);environment.update(INGESTION_TCP_HOST=os.environ.get('INGESTION_TCP_HOST','127.0.0.1'),INGESTION_TCP_PORT=os.environ.get('INGESTION_TCP_PORT','9090'),CONNECTED_DEMO_ARTIFACTS=str(evidence/'source'),CONNECTED_DEMO_START_GATE=str(evidence/'start.request'),P0_DEMO_MARKERS=str(evidence))
    log=(evidence/'simulator.log').open('w')
    process=subprocess.Popen([str(ROOT/'scripts/simulator.sh'),'run','--connected-p0-demo','--config',str(evidence/'run-config.json')],cwd=ROOT,env=environment,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
    stopped=False;successful=False;run=None;frames=[];stream_error=[];finished=threading.Event();stream_holder=[];reader=None
    def phase(name,view):save('phase.json',dict(phase=name,runId=run,url=ui+'/?run='+run,view=view));print(name,run,'Evidence:',evidence.relative_to(ROOT),flush=True)
    def collect():
        try:
            response=urllib.request.urlopen(ui+f'/api/v1/runs/{run}/stream',timeout=6);stream_holder.append(response)
            assert response.headers['Content-Type'].startswith('text/event-stream') and response.headers['Cache-Control']=='no-store'
            event=id=data=None
            with (evidence/'sse.ndjson').open('w') as output:
                while not finished.is_set():
                    raw_line=response.readline()
                    if not raw_line:raise RuntimeError('SSE stream ended before verification completed')
                    line=raw_line.decode('utf-8').rstrip('\n')
                    if line.startswith('id: '):id=line[4:]
                    elif line.startswith('event: '):event=line[7:]
                    elif line.startswith('data: '):data=line[6:]
                    elif line=='' and event=='factory-snapshot':
                        view=json.loads(data);assert view['runId']==run and id==f"{view['serverEpoch']}:{view['revision']}"
                        if frames:
                            assert view['serverEpoch']==frames[-1]['serverEpoch'] and view['revision']>frames[-1]['revision']
                            assert frames[-1]['sourceSeq'] is None or view['sourceSeq'] is not None and view['sourceSeq']>=frames[-1]['sourceSeq']
                        frames.append(view);output.write(json.dumps(view,ensure_ascii=False)+'\n');output.flush();event=id=data=None
                    elif line=='' and not data:continue
        except Exception as error:
            if not finished.is_set():stream_error.append(str(error))
        finally:
            for response in stream_holder:response.close()
    try:
        info=wait(lambda:next((json.loads(p.read_text()) for p in (evidence/'source').glob('*/run.json')),None),10);run=info['runId']
        assert re.fullmatch(r'run-\d{8}-[a-f0-9]{32}',run) and info['pid']==process.pid
        for database,tables in [('ingestion_db',SOURCE_TABLES),('operations_db',OPS_TABLES)]:
            existing=' + '.join(f"(SELECT count(*) FROM {table} WHERE run_id='{run}')" for table in tables)
            if int(sql(database,'SELECT '+existing))!=0:raise RuntimeError('Generated probe UUID exists; no TCP write or cleanup permitted')
        (evidence/'start.request').touch()
        def view():return get(ui,f'/api/v1/runs/{run}/snapshot')
        wait(lambda:bool(view().get('sourceSeq')),20)
        reader=threading.Thread(target=collect,daemon=True);reader.start();wait(lambda:len(frames)>0)
        source=Path(info['evidence'])
        def spatial(physical):
            return {k:[{a:b for a,b in item.items() if a!='lastObservedAt'} for item in physical[k]] for k in ('equipment','buffers','bodies','vehicles','activeTransports')}
        stages=['FULL_RESERVED','FULL_IN_TRANSIT','FULL_ARRIVED','CELL_DOWN','SLOT_RELEASED']
        for name in stages:
            captured=wait(lambda:json.loads((source/(name+'.json')).read_text()) if (source/(name+'.json')).exists() else None,60)
            current=wait(lambda:(v if v['sourceSeq'] is not None and v['sourceSeq']>=captured['sourceSeq'] and spatial(v)==spatial(captured['physical']) else None) if (v:=view()) else None,20)
            wait(lambda:any(v['sourceSeq'] is not None and v['sourceSeq']>=captured['sourceSeq'] and spatial(v)==spatial(current) for v in frames),5)
            bay=next(b for b in current['buffers'] if b['cellId']=='ASM-02')
            if name in ('FULL_RESERVED','FULL_IN_TRANSIT'):assert (bay['waitingCount'],bay['reservedInboundCount'],bay['availableSlots'])==(2,1,0)
            if name in ('FULL_ARRIVED','CELL_DOWN'):assert (bay['waitingCount'],bay['reservedInboundCount'],bay['availableSlots'])==(3,0,0)
            if name=='FULL_ARRIVED':assert next(c for c in current['equipment'] if c['cellId']=='ASM-01')['blockedReason']=='BUFFER_FULL'
            if name=='CELL_DOWN':assert any(a['type']=='EQUIPMENT_DOWN' and a['targetId']=='ASM-01' and a['conditionActive'] for a in current['alarms'])
            if name=='SLOT_RELEASED':assert bay['waitingCount']==2 and any(b['currentCellId']=='ASM-02' for b in current['bodies'])
            save(name+'.json',current);phase(name,current)
            if args.browser_stages:wait(lambda:(evidence/('UI.'+name+'.continue')).exists(),600)
            if args.browser_stages and name=='FULL_IN_TRANSIT':
                os.kill(process.pid,signal.SIGSTOP);stopped=True;time.sleep(1);baseline=view()
                offline=wait(lambda:(v if v['dataStatus']=='DISCONNECTED' else None) if (v:=view()) else None,15)
                assert offline['sourceSeq']==baseline['sourceSeq'] and spatial(offline)==spatial(baseline)
                save('source-stopped.json',offline);phase('SOURCE_STOPPED',offline)
                wait(lambda:(evidence/'UI.SOURCE_STOPPED.continue').exists(),600)
                os.kill(process.pid,signal.SIGCONT);stopped=False
            if name=='CELL_DOWN' and args.browser_stages:
                acknowledged=wait(lambda:(v if any(a['type']=='EQUIPMENT_DOWN' and a['targetId']=='ASM-01' and a['conditionActive'] and a['acknowledgedBy']=='s07-operator' for a in v['alarms']) else None) if (v:=view()) else None,10)
                assert spatial(acknowledged)==spatial(current);save('acknowledged.json',acknowledged)
            (evidence/(name+'.continue')).touch()
        wait(lambda:process.poll() is not None,300);assert process.returncode==0
        def delivered():
            status=get(ingestion,f'/internal/v1/runs/{run}/delivery-status')
            if status['streamState']=='BLOCKED' or status['streamState'].startswith('PAUSED_'):raise RuntimeError('Probe stream blocked')
            return status if status['pendingCount']==0 else None
        delivery=wait(delivered,30)
        final=wait(lambda:(v if v['dataStatus']=='FINISHED' else None) if (v:=view()) else None,15)
        wait(lambda:any(v['dataStatus']=='FINISHED' for v in frames),5)
        assert not stream_error,stream_error
        original_path=Path(info['evidence'])/'originals.ndjson';originals=original_path.read_bytes().splitlines();events=[json.loads(x) for x in originals]
        assert events[-1]['eventType']=='RUN_FINISHED' and delivery['nextSourceSeq']==len(events)+1
        source_rows=json.loads(sql('ingestion_db',f"SELECT json_agg(json_build_object('seq',r.source_seq,'raw',r.raw_json_text,'hash',r.payload_hash,'status',o.delivery_status) ORDER BY r.source_seq) FROM raw_event r JOIN event_outbox o USING(run_id,event_id) WHERE run_id='{run}'"))
        ops_rows=json.loads(sql('operations_db',f"SELECT json_agg(json_build_object('seq',source_seq,'raw',raw_json_text,'hash',payload_hash) ORDER BY source_seq) FROM processed_event WHERE run_id='{run}'"))
        assert len(source_rows)==len(ops_rows)==len(events)
        for seq,(raw,left,right) in enumerate(zip(originals,source_rows,ops_rows),1):
            assert left['seq']==right['seq']==seq and left['status']=='DELIVERED' and left['raw'].encode()==right['raw'].encode()==raw
            assert left['hash']==right['hash']==hashlib.sha256(raw).hexdigest()
        tag=get(ui,f'/api/v1/runs/{run}/tags/tag-00001/body')
        assert tag['data']['bodyId']=='body-00001' and tag['data']['locationId']=='HOLD' and tag['data']['inspectionResult']=='FAIL' and len(final['bodies'])==5
        assert final['metrics']['cumulativeQuality']==dict(inspectedCount=5,passCount=4,failCount=1,failRate=.2)
        facts=json.loads(sql('operations_db',f"SELECT json_build_object('operations',(SELECT count(*) FROM operation_history WHERE run_id='{run}'),'inspections',(SELECT count(*) FROM inspection_result WHERE run_id='{run}'))"));assert facts==dict(operations=15,inspections=5)
        start=(datetime.fromisoformat(final['viewAsOfAt'].replace('Z','+00:00'))-timedelta(minutes=5)).isoformat(timespec='milliseconds').replace('+00:00','Z')
        query=urllib.parse.urlencode(dict(**{'from':start,'to':final['viewAsOfAt']}))
        quality=get(ui,f'/api/v1/runs/{run}/quality?'+query);trends=get(ui,f'/api/v1/runs/{run}/trends?'+query+'&bucketMs=60000')
        assert quality['window']==trends['window'] and quality['quality']==dict(inspectedCount=5,passCount=4,failCount=1,failRate=.2)
        assert sum(b['quality']['inspectedCount'] for b in trends['buckets'])==5 and sum(b['quality']['failCount'] for b in trends['buckets'])==1
        page=get(ui,f'/api/v1/runs/{run}/events?limit=2&bodyId=body-00001');assert page['nextCursor'] and all(i['bodyId']=='body-00001' for i in page['items'])
        later=get(ui,f'/api/v1/runs/{run}/events?'+urllib.parse.urlencode(dict(limit=2,bodyId='body-00001',cursor=page['nextCursor'])))
        assert page['viewAsOfAt']==later['viewAsOfAt'] and not ({i['eventId'] for i in page['items']} & {i['eventId'] for i in later['items']})
        layout=get(ui,f'/api/v1/factory/layout?runId={run}');assert layout['config']==config['config']
        assert all(not a['conditionActive'] for a in final['alarms'] if a['type']=='EQUIPMENT_DOWN' and a['targetId']=='ASM-01')
        save('final.json',final);save('tag.json',tag);save('delivery.json',delivery);save('quality.json',quality);save('trends.json',trends);save('history-first.json',page);save('history-next.json',later);save('layout.json',layout);phase('FINISHED',final)
        if args.browser_stages:
            wait(lambda:(evidence/'UI.FINISHED.continue').exists(),600)
            proof=json.loads((evidence/'browser-proof.json').read_text())
            assert proof['runId']==run and proof['mobileVerified'] and proof['keyboardVerified'] and proof['qualityVerified'] and proof['historyVerified'] and proof['alarmVerified']
            assert all((evidence/name).is_file() for name in proof['screenshotFiles'])
        save('result.json',dict(suite='S07 P0 actual TCP/two DBs/proxied SSE',runId=run,preexistingRows=0,events=len(events),sseFrames=len(frames),stages=stages,sourceInterrupted=args.browser_stages,finalStatus=final['dataStatus'],tagLocation=tag['data']['locationId'],inspection='FAIL',facts=facts,quality=quality['quality'],browserVerified=args.browser_stages,ownRunCleaned=False))
        successful=True;print(f'PASS: S07 {len(events)} originals -> both DBs, {len(frames)} SSE bundles, all P0 stages and 5 inspections; browser proof: {args.browser_stages}',flush=True)
    finally:
        finished.set()
        if stopped and process.poll() is None:os.kill(process.pid,signal.SIGCONT)
        if process.poll() is None:
            os.killpg(process.pid,signal.SIGTERM)
            try:process.wait(timeout=5)
            except subprocess.TimeoutExpired:os.killpg(process.pid,signal.SIGKILL);process.wait(timeout=5)
        if reader:reader.join(timeout=2)
        log.close()
        if successful:
            queries=[f"DELETE FROM {table} WHERE run_id='{run}'" for table in OPS_TABLES]
            sql('operations_db',"BEGIN; SELECT pg_advisory_xact_lock(hashtextextended('"+run+"',7304001)); "+'; '.join(queries)+'; COMMIT;')
            sql('ingestion_db','BEGIN; '+'; '.join(f"DELETE FROM {table} WHERE run_id='{run}'" for table in SOURCE_TABLES)+'; COMMIT;')
            result=json.loads((evidence/'result.json').read_text());result['ownRunCleaned']=True;save('result.json',result)
        else:save('failed-probe.json',dict(runId=run,recordsPreserved=True,ownRunCleaned=False))


if __name__=='__main__':main()
