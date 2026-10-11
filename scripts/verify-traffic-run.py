"""Read-only end-to-end check of a completed connected traffic run. Never removes records."""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
source=Path(sys.argv[1]).resolve()
originals=(source/'originals.ndjson').read_bytes().splitlines()
events=[json.loads(row) for row in originals]
run=events[0]['runId']
assert re.fullmatch(r'run-\d{8}-[a-f0-9]{32}',run)
assert events[-1]['eventType']=='RUN_FINISHED', 'Wait for the run to finish'
def sql(database,query):
    value=subprocess.check_output([str(ROOT/'scripts/dev-stack.sh'),'compose','exec','-T','postgres','psql','--no-psqlrc','--username=postgres','--dbname='+database,'--tuples-only','--no-align','-v','ON_ERROR_STOP=1','-c',query],cwd=ROOT,text=True)
    return json.loads(value)
def get(base,path):
    with urllib.request.urlopen(base+path,timeout=5) as response:return json.load(response)
left=sql('ingestion_db',f"SELECT json_agg(json_build_object('seq',r.source_seq,'raw',r.raw_json_text,'hash',r.payload_hash,'status',o.delivery_status) ORDER BY r.source_seq) FROM raw_event r JOIN event_outbox o USING(run_id,event_id) WHERE run_id='{run}'")
right=sql('operations_db',f"SELECT json_agg(json_build_object('seq',source_seq,'raw',raw_json_text,'hash',payload_hash) ORDER BY source_seq) FROM processed_event WHERE run_id='{run}'")
assert len(left)==len(right)==len(events)
for seq,(raw,a,b) in enumerate(zip(originals,left,right),1):
    assert a['seq']==b['seq']==seq and a['status']=='DELIVERED'
    assert a['raw'].encode()==b['raw'].encode()==raw
    assert a['hash']==b['hash']==hashlib.sha256(raw).hexdigest()
delivery=get('http://127.0.0.1:8081',f'/internal/v1/runs/{run}/delivery-status')
view=get('http://127.0.0.1:8082',f'/api/v1/runs/{run}/snapshot')
assert delivery['pendingCount']==0 and view['dataStatus']=='FINISHED'
assert all(v['state']=='IDLE' for v in view['vehicles']) and not view['activeTransports']
assert all(b['locationType']=='RESULT' for b in view['bodies'])
result=dict(runId=run,events=len(events),allOriginalBytesSequencesHashesMatch=True,
    deliveryPending=delivery['pendingCount'],status=view['dataStatus'],
    policyVersion=events[0]['payload']['config']['traffic']['policyVersion'],
    bodies=[dict(id=b['bodyId'],location=b['locationId'],quality=b['inspectionResult']) for b in view['bodies']])
print(json.dumps(result,indent=2))
(ROOT/f'docs/development/3d-review/lane-v{result["policyVersion"]}{"-forward" if "--forward" in sys.argv[2:] else ""}-connected-verification.json').write_text(json.dumps(result,indent=2)+'\n')
