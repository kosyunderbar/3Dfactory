"""S00-03 전달 계약 자료만 확인. 네트워크/DB/재시도 구현의 성공을 입증하지 않는다."""
from copy import deepcopy
from datetime import datetime
from pathlib import Path
import hashlib
import json
import math

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / 'contracts/v1'
IDENTITY = ['runId', 'sourceId', 'eventId', 'sourceSeq', 'eventSha256']
COMMON = ['protocolVersion', 'kind', *IDENTITY, 'status', 'code', 'retryAfterMs']


def check(condition, message):
    if not condition:
        raise ValueError(message)


def size(value):
    return len(json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode('utf-8'))


def response(value, kind, expected):
    fields = COMMON + (['receivedAt', 'committedAt'] if kind == 'INGESTION_ACK' else ['appliedAt', 'recordedAt'])
    check(set(value) == set(fields), 'complete response fields')
    check(type(value['protocolVersion']) is int and value['protocolVersion'] == 1 and value['kind'] == kind, 'version/kind')
    known = all(value[k] is not None for k in IDENTITY[:-1])
    check(known or all(value[k] is None for k in IDENTITY[:-1]), 'known/unknown identity group')
    if known:
        check(all(value[k] == expected[k] for k in IDENTITY), 'response correlation')
    elif kind == 'APPLICATION_RESULT':
        check(value['eventSha256'] is None, 'unparsed delivery has no event hash')
    for key in fields:
        if key.endswith('At') and value[key] is not None:
            parsed = datetime.fromisoformat(value[key].replace('Z', '+00:00'))
            check(parsed.isoformat(timespec='milliseconds').replace('+00:00', 'Z') == value[key], 'UTC millisecond response time')
    success_states = ['RECEIVED', 'DUPLICATE_RECEIVED'] if kind == 'INGESTION_ACK' else ['APPLIED', 'DUPLICATE_APPLIED']
    check(value['status'] in success_states + ['REJECTED', 'RETRY_LATER'], 'response status')
    success = value['status'] in success_states
    check(not success or known, 'success requires full identity')
    if kind == 'INGESTION_ACK':
        check((value['committedAt'] is not None) == success, 'no successful commit promise on failure')
        check(value['receivedAt'] is not None, 'received time')
        if success:
            check(value['committedAt'] >= value['receivedAt'] and value['code'] == 'OK', 'ACK success')
    else:
        check((value['appliedAt'] is not None) == success, 'no business apply promise on failure')
        check(not success or value['recordedAt'] is not None, 'successful result record')
        check(value['status'] != 'RETRY_LATER' or value['recordedAt'] is None, 'retry has no terminal record')
    retry = value['retryAfterMs']
    check((retry is not None) == (value['status'] == 'RETRY_LATER'), 'retry hint applicability')
    if retry is not None:
        check(type(retry) is int and 1 <= retry <= 30000, 'retry hint bounds')


def main():
    policy = json.loads((BASE / 'delivery-policy.json').read_text())
    examples = json.loads((BASE / 'examples/delivery-examples.json').read_text())
    req = examples['request']
    check(req['method'] == 'POST' and req['path'] == '/internal/v1/events/apply', 'internal request route')
    body = req['body']
    check(set(body) == {'protocolVersion', 'rawEvent', 'eventSha256', 'receivedAt'} and body['protocolVersion'] == 1, 'delivery envelope')
    raw = body['rawEvent'].encode('utf-8')
    check(b'\n' not in raw and b'\r' not in raw and len(raw) + 1 <= policy['tcp']['frameMaxBytes'], 'raw frame bytes')
    check(hashlib.sha256(raw).hexdigest() == body['eventSha256'], 'original byte SHA-256')
    event = json.loads(body['rawEvent'])
    expected = {k: event[k] for k in IDENTITY[:-1]}
    expected['eventSha256'] = body['eventSha256']
    check(size(body) <= policy['http']['requestMaxBytes'], 'HTTP request bound')
    acks = examples['tcpAcks']
    for value in acks:
        response(value, 'INGESTION_ACK', expected)
        check(size(value) + 1 <= policy['tcp']['ackMaxBytes'], 'ACK bound')
    for item in examples['applicationResponses']:
        value = item['body']
        response(value, 'APPLICATION_RESULT', expected)
        status, code, http = value['status'], value['code'], item['httpStatus']
        allowed = {'APPLIED': [200], 'DUPLICATE_APPLIED': [200], 'RETRY_LATER': [409, 429, 503], 'REJECTED': [400, 409, 413, 415, 422]}
        check(http in allowed[status], 'HTTP/application meaning')
        if status == 'RETRY_LATER':
            check(item['headers'].get('Retry-After') == str(math.ceil(value['retryAfterMs'] / 1000)), 'seconds vs milliseconds')
        if http == 422:
            check(value['recordedAt'] is not None and code in ['MODEL_INVALID', 'BUSINESS_ID_CONFLICT', 'INVALID_EVENT'], 'durable business rejection')
        check(size(value) <= policy['http']['responseMaxBytes'], 'HTTP result bound')
    first, duplicate = examples['applicationResponses'][:2]
    check(first['body']['appliedAt'] == duplicate['body']['appliedAt'], 'duplicate preserves original application time')
    check(acks[0]['receivedAt'] == acks[1]['receivedAt'], 'duplicate preserves initial received time')
    # 공백만 달라도 동일 원본으로 취급하지 않는 계약의 확인.
    changed = json.dumps(event, ensure_ascii=False, indent=2).encode('utf-8')
    check(json.loads(changed) == event and hashlib.sha256(changed).hexdigest() != body['eventSha256'], 'byte identity, not JSON normalization')
    retry = policy['retry']
    expected_delays = [min(retry['baseDelayMs'] * 2 ** k, retry['maxDelayMs']) for k in range(8)]
    check(expected_delays == examples['backoffWithZeroJitterMs'], 'bounded backoff defaults')
    source = policy['source']
    check(source['sendWindow'] == 1 and source['maxAttempts'] == 10 and policy['outbox']['maxAttempts'] == 20, 'limited automatic attempts')
    for suffix in ['Events', 'Bytes']:
        check(source[f'resumeBelow{suffix}'] < source[f'pauseAt{suffix}'] < source[f'pendingMax{suffix}'], 'pause credit/hysteresis')
    # 한도는 LF 포함이며, HTTP는 JSON 문자열의 이스케이프 여유를 둔다.
    check(policy['tcp']['frameMaxBytes'] == 65536 and policy['http']['requestMaxBytes'] >= 6 * (65536 - 1) + 1024, 'frame/escaped request boundary')
    invalid = deepcopy(acks[0]); invalid['status'] = 'RETRY_LATER'; invalid['retryAfterMs'] = 1000
    try:
        response(invalid, 'INGESTION_ACK', expected)
    except ValueError:
        pass
    else:
        raise ValueError('retry ACK incorrectly promises commit')
    print(f"PASS: raw byte/hash correlation; {len(acks)} TCP ACKs, {len(examples['applicationResponses'])} HTTP results; "
          f"seconds/ms and bounded retries; source/outbox attempts={source['maxAttempts']}/{policy['outbox']['maxAttempts']}; "
          'failure ACK cannot promise commit.')


if __name__ == '__main__':
    main()
