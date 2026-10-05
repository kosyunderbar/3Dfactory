"""S05 real Python/TCP/outbox/HTTP/operations/REST verification in an existing Compose stack.
Default: one fresh run without service disruption. --with-restarts additionally stops operations,
restarts ingestion with pending reports, then restores operations. No volume reset is performed.
Only a fresh UUID verified absent in both DBs is cleaned, and only after complete successful delivery.
Failed probe records are preserved for diagnosis; stopped operations is restored in finally.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.request
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'services/factory-simulator'))
from factory_simulator.scenario_demo import demo_scenarios
from factory_simulator.run_configuration import RunConfiguration
from factory_simulator.configuration import Settings
from factory_simulator.sender import Sender, Original

INGESTION_TABLES=['delivery_action','event_outbox','raw_event','delivery_stream']
OPERATIONS_TABLES=['factory_snapshot','inspection_result','operation_history','transport_history','alarm','event_projection','processed_event','body','factory_buffer','equipment','vehicle','simulation_run']


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--with-restarts',action='store_true')
    args=parser.parse_args()
    evidence=ROOT/'.build-cache/delivery-verification'/uuid.uuid4().hex
    evidence.mkdir(parents=True)
    def compose(*parts):
        with (evidence/'commands.log').open('a') as log:
            subprocess.run([str(ROOT/'scripts/dev-stack.sh'),'compose',*parts],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,check=True)
    def sql(database,query):
        return subprocess.check_output([str(ROOT/'scripts/dev-stack.sh'),'compose','exec','-T','postgres','psql','--no-psqlrc','--username=postgres','--dbname='+database,'--tuples-only','--no-align','-v','ON_ERROR_STOP=1','-c',query],cwd=ROOT,text=True).strip()
    ingestion=os.environ.get('INGESTION_BASE_URL','http://127.0.0.1:8081').rstrip('/')
    operations=os.environ.get('OPERATIONS_BASE_URL','http://127.0.0.1:8082').rstrip('/')
    def get(base,path):
        with urllib.request.urlopen(base+path,timeout=5) as response:return json.load(response)
    def wait_until(check,seconds=60):
        end=time.monotonic()+seconds
        while time.monotonic()<end:
            try:
                result=check()
                if result:return result
            except (OSError,ValueError):pass
            time.sleep(.15)
        raise RuntimeError('Probe delivery/readiness timeout')
    frames=demo_scenarios(RunConfiguration.from_path())['events']
    original_run=frames[0]['runId']
    run='run-'+frames[0]['occurredAt'][:10].replace('-','')+'-'+uuid.uuid4().hex
    frames=json.loads(json.dumps(frames).replace(original_run,run))
    originals=[Original.from_frame((json.dumps(f,ensure_ascii=False,separators=(',',':'))+'\n').encode()) for f in frames]
    for database,tables in [('ingestion_db',INGESTION_TABLES),('operations_db',OPERATIONS_TABLES)]:
        existing=' + '.join(f"(SELECT count(*) FROM {table} WHERE run_id='{run}')" for table in tables)
        if int(sql(database,'SELECT '+existing))!=0:raise RuntimeError('Probe UUID already exists; no write/cleanup performed')
    sender=Sender(Settings(os.environ.get('INGESTION_TCP_HOST','127.0.0.1'),int(os.environ.get('INGESTION_TCP_PORT','9090'))),error_path=evidence/'send-errors.ndjson')
    successful=False;operations_stopped=False;ack_count=0;before_failure=None;pending_state=None;recovered_state=None;restart_attempts=None
    def send(batch):
        nonlocal ack_count
        sender.pending.enqueue_originals(batch)
        while sender.pending:sender.send_head();ack_count+=1
    def status():return get(ingestion,f'/internal/v1/runs/{run}/delivery-status')
    def delivered_through(seq):
        state=status()
        if state['streamState']=='BLOCKED' or state['streamState'].startswith('PAUSED_'):raise RuntimeError('Probe stream paused: '+json.dumps(state))
        return state if state['nextSourceSeq']>seq else None
    try:
        first_snapshot=next(i for i,f in enumerate(frames) if f['eventType']=='FACTORY_SNAPSHOT')
        send(originals[:first_snapshot+1]);wait_until(lambda:delivered_through(first_snapshot+1),20)
        before_failure=get(operations,f'/api/v1/runs/{run}/snapshot')
        assert before_failure['dataStatus']=='LIVE' and before_failure['delivery']['diagnosticState']=='AVAILABLE',before_failure['dataStatus']
        if args.with_restarts:
            # Do not disrupt another producer's pending work. This is a local development-only scenario.
            other=int(sql('ingestion_db',f"SELECT count(*) FROM event_outbox WHERE run_id<>'{run}' AND delivery_status<>'DELIVERED'"))
            if other:raise RuntimeError('Other pending reports exist; service interruption refused')
            compose('stop','--timeout','5','operations-service');operations_stopped=True
        send(originals[first_snapshot+1:])
        if args.with_restarts:
            pending_state=status();assert pending_state['pendingCount']>0 and pending_state['nextSourceSeq']==first_snapshot+2
            assert int(sql('operations_db',f"SELECT count(*) FROM processed_event WHERE run_id='{run}'"))==first_snapshot+1
            attempts_before=int(sql('ingestion_db',f"SELECT o.attempt_count FROM event_outbox o JOIN raw_event r USING(run_id,event_id) WHERE r.run_id='{run}' AND r.source_seq={first_snapshot+2}"))
            compose('restart','ingestion-service');wait_until(lambda:get(ingestion,'/readyz')['status']=='UP',30)
            recovered_state=status();assert recovered_state['pendingCount']==pending_state['pendingCount'] and recovered_state['nextSourceSeq']==pending_state['nextSourceSeq']
            attempts_after=int(sql('ingestion_db',f"SELECT o.attempt_count FROM event_outbox o JOIN raw_event r USING(run_id,event_id) WHERE r.run_id='{run}' AND r.source_seq={first_snapshot+2}"))
            assert attempts_after>=attempts_before
            restart_attempts=dict(before=attempts_before,after=attempts_after)
            sender.close();sender.pending.enqueue_originals([originals[0]]);sender.send_head()
            assert sender.confirmed==[(1,'DUPLICATE_RECEIVED')]
            compose('up','-d','--wait','--wait-timeout','60','--no-deps','operations-service');operations_stopped=False
        final=status() if delivered_through(len(frames)) else wait_until(lambda:delivered_through(len(frames)),60)
        assert final['pendingCount']==0 and final['nextSourceSeq']==len(frames)+1
        def finished_view():
            view=get(operations,f'/api/v1/runs/{run}/snapshot')
            return view if view['dataStatus']=='FINISHED' else None
        view=wait_until(finished_view,10)
        assert view['freshness']['state']=='ARCHIVED' and view['delivery']['diagnosticState']=='AVAILABLE'
        tag=get(operations,f'/api/v1/runs/{run}/tags/tag-00001/body');assert tag['data']['locationId']=='HOLD' and tag['data']['inspectionResult']=='FAIL'
        quality=get(operations,f'/api/v1/runs/{run}/quality');assert quality['quality']==dict(inspectedCount=1,passCount=0,failCount=1,failRate=1.0)
        source_rows=json.loads(sql('ingestion_db',f"SELECT json_agg(json_build_object('seq',r.source_seq,'raw',r.raw_json_text,'hash',r.payload_hash,'status',o.delivery_status) ORDER BY r.source_seq) FROM raw_event r JOIN event_outbox o USING(run_id,event_id) WHERE run_id='{run}'"))
        operation_rows=json.loads(sql('operations_db',f"SELECT json_agg(json_build_object('seq',source_seq,'raw',raw_json_text,'hash',payload_hash) ORDER BY source_seq) FROM processed_event WHERE run_id='{run}'"))
        assert len(source_rows)==len(operation_rows)==len(frames)
        for original,left,right in zip(originals,source_rows,operation_rows):
            assert left['status']=='DELIVERED' and left['seq']==right['seq']==original.source_seq
            assert left['raw'].encode()==right['raw'].encode()==original.frame[:-1]
            assert left['hash']==right['hash']==original.sha256
        metrics=json.loads(sql('operations_db',f"SELECT json_build_object('processed',(SELECT count(*) FROM processed_event WHERE run_id='{run}'),'operations',(SELECT count(*) FROM operation_history WHERE run_id='{run}'),'transports',(SELECT count(*) FROM transport_history WHERE run_id='{run}'),'inspections',(SELECT count(*) FROM inspection_result WHERE run_id='{run}'))"))
        result=dict(suite='S05 Python/TCP/outbox/HTTP/operations/REST',runId=run,events=len(frames),ackCount=ack_count,withRestarts=args.with_restarts,preexistingRows=0,
                    beforeDataStatus=before_failure['dataStatus'],finalDataStatus=view['dataStatus'],finalDelivery=final,storage=metrics,restartAttempts=restart_attempts,originalHash=hashlib.sha256(b''.join(o.frame for o in originals)).hexdigest(),guiLive=False,ownRunCleaned=False)
        (evidence/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
        for name,data in [('before',before_failure),('pending',pending_state),('recovered',recovered_state),('final',view),('tag',tag),('quality',quality)]:
            if data is not None:(evidence/(name+'.json')).write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
        (evidence/'originals.ndjson').write_bytes(b''.join(o.frame for o in originals))
        successful=True
        print(f"PASS: {len(frames)} Python/TCP ACKs -> automatic outbox/HTTP -> {len(frames)} operations commits; exact originals; LIVE then FINISHED; pending/restart recovery: {args.with_restarts}.")
        print('Evidence:',evidence.relative_to(ROOT))
    finally:
        sender.close()
        if operations_stopped:compose('up','-d','--wait','--wait-timeout','60','--no-deps','operations-service')
        if successful:
            # No pending or in-flight head remains. Serialize with operations' own per-run write lock.
            queries=[f"DELETE FROM {table} WHERE run_id='{run}'" for table in OPERATIONS_TABLES]
            sql('operations_db',"BEGIN; SELECT pg_advisory_xact_lock(hashtextextended('"+run+"',7304001)); "+'; '.join(queries)+'; COMMIT;')
            sql('ingestion_db','BEGIN; '+'; '.join(f"DELETE FROM {table} WHERE run_id='{run}'" for table in INGESTION_TABLES)+'; COMMIT;')
            result=json.loads((evidence/'result.json').read_text());result['ownRunCleaned']=True
            (evidence/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
        else:
            (evidence/'failed-probe.json').write_text(json.dumps(dict(runId=run,recordsPreserved=True,ownRunCleaned=False),indent=2)+'\n')
            print('Probe did not fully succeed; its accepted records are preserved:',run,flush=True)


if __name__=='__main__':main()
