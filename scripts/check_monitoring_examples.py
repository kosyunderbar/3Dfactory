"""S00-04 자료 검증. 서비스/DB/브라우저 동작 테스트가 아니다."""
from copy import deepcopy
from datetime import datetime
from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / 'contracts/v1'


def check(condition, message):
    if not condition:
        raise ValueError(message)


def utc(value):
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    check(parsed.isoformat(timespec='milliseconds').replace('+00:00', 'Z') == value, 'UTC millisecond timestamp')
    return parsed


def status(c, p):
    # 계약 예제의 기대 결과를 확인하는 판정표. 런타임에서 재사용하지 않는다.
    if c['operationsBlocked'] or c['streamState'] == 'BLOCKED' or c['streamState'].startswith('PAUSED_'):
        return 'BLOCKED'
    if c['finishedConfirmed']:
        return 'FINISHED'
    if not c['snapshotPresent']:
        return 'WAITING'
    if not c['observedAfterEpoch']:
        return 'RESTORING'
    if c['diagnosticState'] != 'AVAILABLE' or c['clockLeadMs'] > p['clockLeadToleranceMs']:
        return 'UNKNOWN'
    if not c['sourceConnected'] or c['sourceAgeMs'] >= p['disconnectAfterMs']:
        return 'DISCONNECTED'
    if c['sourceAgeMs'] >= p['staleAfterMs']:
        return 'STALE'
    if (c['pendingCount'] > 0 and c['oldestPendingAgeMs'] >= p['deliveryLagBudgetMs']) or c['streamState'] in ['RETRY_WAIT', 'GAP_WAIT']:
        return 'CATCHING_UP'
    return 'PAUSED' if c['runState'] == 'PAUSED' else 'LIVE'


def quality(q):
    check(set(q) == {'inspectedCount', 'passCount', 'failCount', 'failRate'}, 'quality fields')
    check(all(type(q[k]) is int and q[k] >= 0 for k in ['inspectedCount', 'passCount', 'failCount']), 'quality integer counts')
    check(q['inspectedCount'] == q['passCount'] + q['failCount'], 'quality denominator')
    expected = q['failCount'] / q['inspectedCount'] if q['inspectedCount'] else None
    check(q['failRate'] == expected, 'zero denominator must be null')


def snapshot(s, event, p):
    required = set('schemaVersion runId sourceId serverEpoch revision publishedAt viewAsOfAt snapshotCapturedAt sourceSeq runState simElapsedMs observedAfterEpoch dataStatus freshness delivery qualityWindow equipment buffers bodies vehicles activeTransports metrics alarms recentEvents'.split())
    check(set(s) == required and s['schemaVersion'] == 1, 'snapshot complete fields/version')
    check(s['runId'] == event['runId'] and s['sourceId'] == event['sourceId'], 'source/run identity')
    check(s['sourceSeq'] == event['sourceSeq'] and s['snapshotCapturedAt'] == event['payload']['capturedAt'], 'snapshot source correlation')
    for k in ['equipment', 'buffers', 'bodies', 'vehicles', 'activeTransports', 'runState', 'simElapsedMs']:
        check(s[k] == event['payload'][k], 'one physical snapshot: '+k)
    check(utc(s['publishedAt']) >= utc(s['viewAsOfAt']), 'publication after view')
    check(s['qualityWindow']['end'] == s['viewAsOfAt'], 'window as-of time')
    check((utc(s['qualityWindow']['end']) - utc(s['qualityWindow']['start'])).total_seconds()*1000 == p['qualityWindowMs'], 'five-minute quality window')
    f = s['freshness']
    check(set(f) == set('evaluatedAt sourceAgeMs clockLeadMs state staleAfterMs disconnectAfterMs'.split()), 'freshness fields')
    age = (utc(s['viewAsOfAt']) - utc(s['snapshotCapturedAt'])).total_seconds()*1000
    check(f['evaluatedAt'] == s['viewAsOfAt'] and f['sourceAgeMs'] == max(0, age) and f['clockLeadMs'] == max(0, -age), 'source age vs published timestamp')
    check(f['staleAfterMs'] == p['staleAfterMs'] and f['disconnectAfterMs'] == p['disconnectAfterMs'], 'freshness boundaries')
    check(f['state'] == 'FRESH', 'fixture is fresh')
    d = s['delivery']
    check(set(d) == set('runId sourceId sampledAt sourceConnected lastReceivedAt lastAcceptedSeq nextSourceSeq streamState blockedSeq blockedCode pendingCount pendingBytes oldestPendingReceivedAt retryCount rejectedCount diagnosticState'.split()), 'diagnostic fields')
    check(d['runId'] == s['runId'] and d['sourceId'] == s['sourceId'], 'diagnostic run correlation')
    check(d['pendingCount'] == 0 and d['oldestPendingReceivedAt'] is None and d['pendingBytes'] == 0, 'empty outbox')
    check(0 <= (utc(s['viewAsOfAt'])-utc(d['sampledAt'])).total_seconds()*1000 < p['diagnosticMaxAgeMs'], 'diagnostic freshness')
    check(d['nextSourceSeq'] == d['lastAcceptedSeq'] + 1, 'delivered cursor for this fixture')
    check(len(json.dumps(s,ensure_ascii=False,separators=(',', ':')).encode()) <= p['snapshotMaxBytes'], 'snapshot bytes')
    m=s['metrics']
    check(set(m) == set('currentBodyCount runningCellCount blockedCellCount downCellCount cumulativeQuality windowQuality alarmSummary'.split()), 'metrics fields')
    check(m['currentBodyCount'] == len(s['bodies']), 'body count')
    for key, state_name in [('runningCellCount','RUNNING'),('blockedCellCount','BLOCKED'),('downCellCount','DOWN')]:
        check(m[key] == sum(x['state']==state_name for x in s['equipment']), 'cell count '+key)
    quality(m['cumulativeQuality']); quality(m['windowQuality'])
    check(m['alarmSummary']['activeCount'] == sum(a['conditionActive'] for a in s['alarms']), 'fixture alarm count')
    bay=next(x for x in s['buffers'] if x['bufferId']=='BAY-ASM-02')
    check((bay['waitingCount'],bay['reservedInboundCount'],bay['availableSlots']) == (2,1,0), 'Bay full includes reserved pickup')
    b=next(x for x in s['bodies'] if x['bodyId']=='body-00042')
    check(b['locationType']=='CELL' and b['locationId']=='ASM-01', 'before pickup body remains source')


def accept_current(current, incoming, current_generation, incoming_generation):
    # 계약 예제 판정이며 실제 브라우저 로직은 S07에서 구현한다.
    if incoming_generation != current_generation or incoming['runId'] != current['runId'] or incoming['serverEpoch'] != current['serverEpoch']:
        return False
    return incoming['revision'] > current['revision'] and incoming['sourceSeq'] >= current['sourceSeq']


def main():
    p=json.loads((BASE/'monitoring-policy.json').read_text())
    data=json.loads((BASE/'examples/monitoring-examples.json').read_text())
    events=[json.loads(x) for x in (BASE/'examples/buffer-lifecycle.ndjson').read_text().splitlines()]
    event=next(x for x in events if x['eventType']=='FACTORY_SNAPSHOT')
    s=data['snapshot']; snapshot(s,event,p)
    for detail in [data['bodyDetail'],data['tagDetail']]:
        check(len(detail)==16 and detail['data']==s['bodies'][2], 'tag/body identity and detail fields')
        check(all(v==s[k] for k,v in detail.items() if k!='data'), 'detail same published view')
    quality(data['emptyQuality']['quality'])
    waiting=data['waitingSnapshot']
    check(set(waiting)==set(s), 'waiting full fields')
    check(waiting['dataStatus']=='WAITING' and waiting['freshness']['state']=='NO_DATA', 'no observations waiting')
    check(all(waiting[k] is None for k in ['sourceSeq','snapshotCapturedAt','runState','simElapsedMs']), 'no invented source observation')
    check(all(waiting['metrics'][k] is None for k in ['currentBodyCount','runningCellCount','blockedCellCount','downCellCount']), 'unknown is not zero')
    check(all(waiting[k]==[] for k in ['equipment','buffers','bodies','vehicles','activeTransports']), 'no simulated browser data')
    unknown=data['unknownSnapshot']
    check(unknown['dataStatus']=='UNKNOWN' and unknown['delivery']['diagnosticState']=='UNAVAILABLE', 'failed diagnostic cannot promise LIVE')
    check(unknown['buffers']==s['buffers'], 'diagnostic failure cannot free reservations')
    check(set(data['eventPage'])==set('schemaVersion runId viewAsOfAt items nextCursor'.split()), 'history page fields')
    check(data['eventPage']['items'][0]['payload']==events[0]['payload'], 'history preserves fact')
    for c in data['statusCases']:
        check(status(c['input'],p)==c['expected'], 'status boundary: '+c['name'])
    raw=(BASE/'examples/factory-snapshot.sse').read_text()
    check(raw.endswith('\n\n'), 'SSE blank line delimiter')
    fields=dict(line.split(': ',1) for line in raw.strip().splitlines())
    check(fields['event']=='factory-snapshot' and fields['id']==s['serverEpoch']+':'+str(s['revision']), 'named SSE event/identity')
    check(int(fields['retry'])==p['sseReconnectMs'] and json.loads(fields['data'])==s, 'SSE JSON equals REST snapshot')
    negative=[]
    bad=deepcopy(s); del bad['freshness']; negative.append(bad)
    bad=deepcopy(s); bad['sourceSeq']=33; negative.append(bad)
    bad=deepcopy(s); bad['buffers'][1]['availableSlots']=1; negative.append(bad)
    bad=deepcopy(s); bad['metrics']['windowQuality']['failRate']=0; negative.append(bad)
    for bad in negative:
        try: snapshot(bad,event,p)
        except ValueError: pass
        else: raise ValueError('invalid representative snapshot accepted')
    current={'runId':s['runId'],'serverEpoch':s['serverEpoch'],'revision':2,'sourceSeq':33}
    for patch,generation,wanted in [({'revision':1,'sourceSeq':30},1,False),({'revision':2},1,False),({'revision':3},1,True),({'revision':3,'sourceSeq':30},1,False),({'revision':3,'serverEpoch':'old'},1,False),({'revision':3},0,False)]:
        check(accept_current(current,current|patch,1,generation)==wanted,'late REST/epoch/generation guard')
    print(f"PASS: REST/tag/SSE share one snapshot; {len(data['statusCases'])} status boundaries; 4 invalid examples rejected; 6 late-response decisions; empty quality stays null. Contract examples only.")


if __name__ == '__main__':
    main()
