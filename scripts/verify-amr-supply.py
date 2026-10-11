"""Verify actual recorded inventory, AMR delivery and batch completion."""
import json
from pathlib import Path
import sys
import re
import urllib.request

source = Path(sys.argv[1])
events = [json.loads(line) for line in (source/'originals.ndjson').read_text().splitlines()]
assert events[-1]['eventType']=='RUN_FINISHED', 'Wait for the entire run to complete'
config=events[0]['payload']['config']
frames=[e['payload'] for e in events if e['eventType']=='FACTORY_SNAPSHOT']
assert config['partsSupply']==dict(capacity=2,initialStock=2)
loaded=0
for frame in frames:
    assert len(frame['partsSupply'])==2
    for stock in frame['partsSupply']:
        assert stock['available']+stock['inbound']<=stock['capacity']
        assert stock['available']+stock['consumed']==stock['initialStock']+stock['delivered']
        assert stock['stockoutMs']==0, 'Unexpected normal-scenario parts starvation'
        assert stock['inbound']==sum(t['cargoType']=='PARTS' and t['destination']['locationId']==stock['dockId'] for t in frame['activeTransports'])
    for v in frame['vehicles']:
        if v['kind']=='AMR':
            assert v['position']['y']<0, 'AMR left its rear aisle'
            if v['partsKitId']:
                loaded+=1
                assert v['bodyId'] is None
        else: assert v['position']['y']>=0, 'AGV entered the parts aisle'
assert loaded>0
deliveries=[e['payload'] for e in events if e['eventType']=='TRANSPORT_COMPLETED' and e['payload']['cargoType']=='PARTS']
assert {t['destination']['locationId'] for t in deliveries}=={'PARTS-ASM-01','PARTS-ASM-02'}
assert len({t['partsKitId'] for t in deliveries})==len(deliveries)
last=frames[-1]
assert all(b['locationId']=='GOOD' and b['inspectionResult']=='PASS' for b in last['bodies'])
assert all(s['consumed']==len(last['bodies']) for s in last['partsSupply'])
assert all(s['available']==s['inbound']==0 for s in last['partsSupply'])
assert all(v['state']=='IDLE' and v['position']==next(c['initialPosition'] for c in config['vehicles'] if c['vehicleId']==v['vehicleId']) for v in last['vehicles'])
connected = False
if '--connected' in sys.argv:
    run = events[0]['runId']
    assert re.fullmatch(r'run-[0-9]{8}-[a-f0-9]{32}',run)
    def get(url):
        with urllib.request.urlopen(url,timeout=5) as response:return json.load(response)
    view = get(f'http://127.0.0.1:8082/api/v1/runs/{run}/snapshot')
    delivery = get(f'http://127.0.0.1:8081/internal/v1/runs/{run}/delivery-status')
    assert view['dataStatus']=='FINISHED' and delivery['pendingCount']==0
    assert view['partsSupply']==last['partsSupply']
    assert view['sourceSeq']==next(e['sourceSeq'] for e in reversed(events) if e['eventType']=='FACTORY_SNAPSHOT')
    assert all(b['locationId']=='GOOD' for b in view['bodies'])
    assert all(v['state']=='IDLE' for v in view['vehicles'])
    connected = True
print(json.dumps(dict(runId=events[0]['runId'],events=len(events),snapshots=len(frames),
    loadedAmrSnapshots=loaded,partsDeliveries=len(deliveries),finalStock=last['partsSupply'],
    allGood=True,allVehiclesHome=True,partsWaitMs=0,operationsSnapshotMatches=connected),ensure_ascii=False,indent=2))
