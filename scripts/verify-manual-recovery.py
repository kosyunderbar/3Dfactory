"""Check recorded manual actions against actual model snapshots of a completed run."""
import json
from pathlib import Path
import sys

source = Path(sys.argv[1])
maintenance = json.loads((source / 'maintenance.json').read_text())
events = [json.loads(line) for line in (source / 'originals.ndjson').read_text().splitlines()]
assert events[-1]['eventType'] == 'RUN_FINISHED', 'Run must finish before verification'
fault, = maintenance['faults']
assert maintenance['runId'] == events[0]['runId']
assert [entry['stage'] for entry in fault['history']] == ['DETECTED', 'INSPECTING', 'VERIFYING', 'RESOLVED']
assert [entry['actor'] for entry in fault['history']] == ['SCENARIO', 'USER', 'USER', 'SIMULATOR']
assert fault['resolvedMs'] - fault['history'][2]['simElapsedMs'] == 2000
frames = [event['payload'] for event in events if event['eventType'] == 'FACTORY_SNAPSHOT']
frozen = [frame for frame in frames if fault['occurredMs'] <= frame['simElapsedMs'] < fault['resolvedMs']]
assert frozen
for frame in frozen:
    cell, = [cell for cell in frame['equipment'] if cell['cellId'] == fault['cellId']]
    assert cell['state'] == 'DOWN'
    assert cell['bodyId'] == fault['bodyId']
    assert cell['operationId'] == fault['operationId']
    assert cell['remainingWorkMs'] == fault['requiredWorkMs'] - fault['elapsedWorkMs']
resumed = next(frame for frame in frames if frame['simElapsedMs'] == fault['resolvedMs'])
cell = next(cell for cell in resumed['equipment'] if cell['cellId'] == fault['cellId'])
assert cell['state'] == 'RUNNING'
assert cell['remainingWorkMs'] == fault['requiredWorkMs'] - fault['elapsedWorkMs']
completions = [event for event in events if event['eventType'] == 'OPERATION_COMPLETED' and event['payload']['operationId'] == fault['operationId']]
assert len(completions) == 1
assert all(body['locationType'] == 'RESULT' and body['inspectionResult'] == 'PASS' for body in frames[-1]['bodies'])
assert all(vehicle['state'] == 'IDLE' for vehicle in frames[-1]['vehicles'])
print(json.dumps(dict(runId=maintenance['runId'], eventCount=len(events),
    fault=fault, downSnapshotsChecked=len(frozen), workPreserved=True,
    resumedRemainingWorkMs=cell['remainingWorkMs'], completedExactlyOnce=True,
    finished=True, goodBodies=len(frames[-1]['bodies'])), ensure_ascii=False, indent=2))
