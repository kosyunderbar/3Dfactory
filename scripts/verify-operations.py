"""One S04 model -> internal HTTP -> operations DB/REST scenario in the existing Compose stack.
The explicit test caller exercises the S04 receiver; it is not the S05 outbox worker.
Only a fresh probe UUID, verified absent in all owned tables before any write, is deleted. No service restart or volume reset is performed.
"""
from datetime import datetime, timezone
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


def main():
    evidence=ROOT/'.build-cache/operations-verification'/uuid.uuid4().hex
    evidence.mkdir(parents=True)
    frames=demo_scenarios(RunConfiguration.from_path())['events']
    # Explicit probe namespace; the script does not read the fixed native-test fixture.
    original_run=frames[0]['runId']
    date=frames[0]['occurredAt'][:10].replace('-','')
    run=f'run-{date}-{uuid.uuid4().hex}'
    frames=json.loads(json.dumps(frames).replace(original_run,run))
    base=os.environ.get('OPERATIONS_BASE_URL','http://127.0.0.1:8082').rstrip('/')
    def http(path,body=None):
        raw=None if body is None else json.dumps(body,ensure_ascii=False,separators=(',',':')).encode()
        req=urllib.request.Request(base+path,data=raw,headers={'Content-Type':'application/json; charset=utf-8'})
        with urllib.request.urlopen(req,timeout=5) as response:
            assert response.status==200
            assert response.headers.get('Cache-Control')=='no-store'
            return json.load(response)
    def sql(query):
        return subprocess.check_output([str(ROOT/'scripts/dev-stack.sh'),'compose','exec','-T','postgres',
            'psql','--no-psqlrc','--username=postgres','--dbname=operations_db','--tuples-only','--no-align',
            '-v','ON_ERROR_STOP=1','-c',query],cwd=ROOT,text=True).strip()
    owned_tables=['factory_snapshot','inspection_result','operation_history','transport_history','alarm','event_projection','processed_event','body','factory_buffer','equipment','vehicle','simulation_run']
    # Refuse before entering cleanup scope if ANY existing row has the probe UUID.
    # All writes/cleanup below use this generated UUID, never a caller-supplied runId.
    preexisting=' + '.join(f"(SELECT count(*) FROM {table} WHERE run_id='{run}')" for table in owned_tables)
    if int(sql('SELECT '+preexisting))!=0:
        raise RuntimeError('Probe UUID already exists; no writes or cleanup performed')
    originals=[];alarm_id=None
    try:
        for frame in frames:
            raw=json.dumps(frame,ensure_ascii=False,separators=(',',':'))
            delivery={'protocolVersion':1,'rawEvent':raw,'eventSha256':hashlib.sha256(raw.encode()).hexdigest(),
                      'receivedAt':datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00','Z')}
            result=http('/internal/v1/events/apply',delivery)
            assert result['status']=='APPLIED',result
            originals.append((frame,raw,delivery))
            if frame['eventType']=='FACTORY_SNAPSHOT' and alarm_id is None and any(e['state']=='DOWN' for e in frame['payload']['equipment']):
                active=http(f'/api/v1/runs/{run}/alarms?conditionActive=true')['items']
                alarm_id=next(a['alarmId'] for a in active if a['type']=='EQUIPMENT_DOWN')
                ack=http(f'/api/v1/alarms/{alarm_id}/acknowledge',{'operatorId':'s04_probe'})
                assert ack['alarm']['conditionActive'] and ack['alarm']['acknowledgedBy']=='s04_probe'
        assert alarm_id is not None
        duplicate=http('/internal/v1/events/apply',originals[0][2])
        assert duplicate['status']=='DUPLICATE_APPLIED'
        rows=json.loads(sql(f"SELECT json_agg(json_build_object('seq',source_seq,'raw',raw_json_text,'hash',payload_hash) ORDER BY source_seq) FROM processed_event WHERE run_id='{run}'"))
        assert len(rows)==len(frames)
        for (frame,raw,delivery),row in zip(originals,rows):
            assert row['seq']==frame['sourceSeq'] and row['raw']==raw and row['hash']==delivery['eventSha256']
        time.sleep(0.55)  # Wait one publication interval after the last model event.
        view=http(f'/api/v1/runs/{run}/snapshot')
        tag=http(f'/api/v1/runs/{run}/tags/tag-00001/body')
        quality=http(f'/api/v1/runs/{run}/quality')
        assert view['dataStatus']=='UNKNOWN' and view['delivery']['diagnosticState']=='UNAVAILABLE'
        assert view['observedAfterEpoch'] and view['runState']=='FINISHED'
        assert tag['data']['locationId']=='HOLD' and tag['data']['inspectionResult']=='FAIL'
        assert quality['quality']==dict(inspectedCount=1,passCount=0,failCount=1,failRate=1.0)
        alarm=http(f'/api/v1/runs/{run}/alarms')['items']
        resolved=next(a for a in alarm if a['alarmId']==alarm_id)
        assert not resolved['conditionActive'] and resolved['resolvedAt'] and resolved['acknowledgedBy']=='s04_probe'
        page=http(f'/api/v1/runs/{run}/events?limit=200')
        assert len(page['items'])==len(frames) and page['nextCursor'] is None
        for name,value in [('snapshot',view),('tag-body',tag),('quality',quality),('alarms',alarm)]:
            (evidence/(name+'.json')).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
        (evidence/'originals.ndjson').write_text(''.join(raw+'\n' for _,raw,_ in originals))
        stats=json.loads(sql(f"SELECT json_build_object('processed',(SELECT count(*) FROM processed_event WHERE run_id='{run}'),'operations',(SELECT count(*) FROM operation_history WHERE run_id='{run}'),'inspections',(SELECT count(*) FROM inspection_result WHERE run_id='{run}'),'transports',(SELECT count(*) FROM transport_history WHERE run_id='{run}'))"))
        result={'suite':'S04 model/internal HTTP/PostgreSQL/REST','runId':run,'events':len(frames),
                'storage':stats,'finalLocation':'HOLD','dataStatus':view['dataStatus'],'alarmAcknowledgedAndRecovered':True,
                'duplicateStatus':duplicate['status'],'automaticOutboxDelivery':False,'guiLive':False,'preexistingRows':0,'ownRunCleaned':False}
        (evidence/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
        print(f"PASS: {len(frames)} events applied through internal HTTP; exact DB bytes/hash; tag HOLD; unique FAIL; alarm ack/recovery; diagnostics truthfully UNKNOWN.")
        print('Evidence:',evidence.relative_to(ROOT))
    finally:
        statements=[f"DELETE FROM {table} WHERE run_id='{run}'" for table in owned_tables]
        sql('BEGIN; '+'; '.join(statements)+'; COMMIT;')
        result_file=evidence/'result.json'
        if result_file.exists():
            result=json.loads(result_file.read_text());result['ownRunCleaned']=True
            result_file.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')


if __name__=='__main__':
    main()
