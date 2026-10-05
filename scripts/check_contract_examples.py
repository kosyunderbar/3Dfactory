"""S00-02 공통 예제 확인. 운영 입력 검증기/서비스 통합 테스트가 아니다."""
from copy import deepcopy
from datetime import datetime
from pathlib import Path
import json
import re
import uuid

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / 'contracts/v1/examples'
ENVELOPE = 'schemaVersion eventId runId sourceId sourceSeq eventType occurredAt payload'.split()
TRANSPORT = ('transportId vehicleId routeId cargoType status bodyId partsKitId source destination '
             'reservationId slotId assignedAt startedAt completedAt cancelledAt cancelReason').split()
FIELDS = {
    'RUN_STARTED': 'seed config', 'RUN_STATE_CHANGED': 'previousState state reason',
    'FACTORY_SNAPSHOT': 'runState capturedAt simElapsedMs equipment buffers bodies vehicles activeTransports',
    'BODY_REGISTERED': 'bodyId tagId modelCode specCode createdAt initialLocation',
    'SLOT_RESERVED': 'reservationId transportId bufferId slotId bodyId vehicleId',
    'SLOT_RELEASED': 'bufferId slotId bodyId reservationId transportId reason',
    'BODY_ENTERED_CELL': 'bodyId cellId bufferId slotId operationId',
    'TELEMETRY_UPDATED': 'entityType entityId measurements position',
    'EQUIPMENT_STATE_CHANGED': 'cellId equipmentId previousState state bodyId reason',
    'OPERATION_COMPLETED': 'operationId cellId equipmentId unitId durationMs',
    'INSPECTION_COMPLETED': 'inspectionId equipmentId unitId result defectCode',
    'SCENARIO_CHANGED': 'scenarioId action targetId parameters',
    'RUN_FINISHED': 'reason uniqueEventCount',
    **{kind: ' '.join(TRANSPORT) for kind in
       ['TRANSPORT_ASSIGNED', 'TRANSPORT_STARTED', 'TRANSPORT_COMPLETED', 'TRANSPORT_CANCELLED']},
}


def check(condition, message):
    if not condition:
        raise ValueError(message)


def exact_fields(value, fields):
    check(isinstance(value, dict) and set(value) == set(fields), f'field mismatch: {fields}')


def parse(text):
    def pairs(items):
        result = {}
        for key, value in items:
            check(key not in result, f'duplicate JSON key: {key}')
            result[key] = value
        return result

    return json.loads(text, object_pairs_hook=pairs,
                      parse_constant=lambda value: check(False, f'non-finite JSON number: {value}'))


def timestamp(value):
    check(isinstance(value, str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z', value), 'UTC millisecond timestamp')
    return datetime.fromisoformat(value.replace('Z', '+00:00'))


def configuration(value):
    exact_fields(value, 'tickMs snapshotIntervalMs speed maxBodies failProbability locations equipment buffers vehicles routes'.split())
    check(value['speed'] == 1 and value['tickMs'] > 0 and value['snapshotIntervalMs'] % value['tickMs'] == 0, 'P0 timing config')
    check(1 <= value['maxBodies'] <= 100 and 0 <= value['failProbability'] <= 1, 'config bounds')
    locations = {(item['locationType'], item['locationId']): item for item in value['locations']}
    check(len(locations) == len(value['locations']), 'unique configured locations')
    for cell in value['equipment']:
        check(cell['cellId'] == cell['equipmentId'] and cell['bufferId'] == f"BAY-{cell['cellId']}", 'cell config')
    for bay in value['buffers']:
        check(2 <= bay['capacity'] <= 4 and bay['slotIds'] == [f"{bay['bufferId']}-S{i}" for i in range(1, bay['capacity'] + 1)], 'configured slots')
    for route in value['routes']:
        for endpoint, point in [(route['source'], route['points'][0]), (route['destination'], route['points'][-1])]:
            key = (endpoint['locationType'], endpoint['locationId'])
            check(key in locations and point == {k: locations[key][k] for k in ['x', 'y']}, 'route endpoints')


def identifier_fields(value, key=''):
    if isinstance(value, dict):
        for name, child in value.items():
            identifier_fields(child, name)
    elif isinstance(value, list):
        for child in value:
            identifier_fields(child, {'slotIds': 'slotId', 'completedCellIds': 'cellId'}.get(key, key))
    elif value is not None:
        patterns = {'bodyId': r'body-[0-9]{5,10}', 'unitId': r'body-[0-9]{5,10}', 'tagId': r'tag-[0-9]{5,10}',
                    'transportId': r'transport-[0-9]{5,10}', 'reservationId': r'reserve-[0-9]{5,10}',
                    'operationId': r'operation-[0-9]{5,10}', 'inspectionId': r'inspection-[0-9]{5,10}',
                    'partsKitId': r'kit-[0-9]{5,10}', 'vehicleId': r'(AGV|AMR)-[0-9]{3,6}',
                    'cellId': r'(ASM-01|ASM-02|QC-01)', 'equipmentId': r'(ASM-01|ASM-02|QC-01)',
                    'bufferId': r'BAY-(ASM-01|ASM-02|QC-01)', 'slotId': r'BAY-(ASM-01|ASM-02|QC-01)-S[1-4]',
                    'routeId': r'ROUTE-[A-Z0-9-]{1,48}', 'scenarioId': r'scenario-[a-z0-9-]{1,40}'}
        if key in patterns:
            check(isinstance(value, str) and re.fullmatch(patterns[key], value), f'ID format: {key}')
        if key.endswith('At'):
            timestamp(value)


def transport(value):
    exact_fields(value, TRANSPORT)
    cargo, destination = value['cargoType'], value['destination']['locationType']
    check(cargo in ('BODY', 'PARTS'), 'cargo type')
    check(bool(value['bodyId']) == (cargo == 'BODY') and bool(value['partsKitId']) == (cargo == 'PARTS'), 'cargo identity')
    reservation_required = cargo == 'BODY' and destination == 'BUFFER'
    check(bool(value['reservationId']) == reservation_required and bool(value['slotId']) == reservation_required, 'reservation applicability')
    check(value['vehicleId'].startswith('AGV-' if cargo == 'BODY' else 'AMR-'), 'vehicle kind')
    check(destination in (('BUFFER', 'RESULT') if cargo == 'BODY' else ('PARTS_DOCK',)), 'cargo destination')
    state = value['status']
    check(state in ('ASSIGNED', 'IN_TRANSIT', 'COMPLETED', 'CANCELLED'), 'transport state')
    assigned = timestamp(value['assignedAt'])
    for field in ['startedAt', 'completedAt', 'cancelledAt']:
        needed = {'startedAt': state in ('IN_TRANSIT', 'COMPLETED'),
                  'completedAt': state == 'COMPLETED', 'cancelledAt': state == 'CANCELLED'}[field]
        check((value[field] is not None) == needed, f'transport timestamp: {field}')
        if needed:
            check(timestamp(value[field]) >= assigned, 'transport chronology')
    if state == 'COMPLETED':
        check(timestamp(value['completedAt']) >= timestamp(value['startedAt']), 'completion before pickup')
    check(value['cancelReason'] == ('SCENARIO_CANCEL' if state == 'CANCELLED' else None), 'cancel reason')


def snapshot(value):
    body_fields = ('bodyId tagId modelCode specCode status locationType locationId locationSlotId currentCellId '
                   'completedCellIds nextCellId transportId reservationId inspectionResult inspectedAt lastObservedAt').split()
    cells = {item['cellId']: item for item in value['equipment']}
    bodies = {item['bodyId']: item for item in value['bodies']}
    vehicles = {item['vehicleId']: item for item in value['vehicles']}
    active = {item['transportId']: item for item in value['activeTransports']}
    check(set(cells) == {'ASM-01', 'ASM-02', 'QC-01'}, 'all P0 cells present')
    check(len(cells) == len(value['equipment']) and len(bodies) == len(value['bodies']) and len(vehicles) == len(value['vehicles']), 'unique model IDs')
    check(len({b['tagId'] for b in bodies.values()}) == len(bodies), 'one body per tag')
    check(len(active) == len(value['activeTransports']), 'unique transport IDs')
    owners = {bid: [] for bid in bodies}
    for cell in cells.values():
        exact_fields(cell, 'cellId equipmentId state resumeState bodyId operationId remainingWorkMs blockedReason destinationCellId'.split())
        check(cell['cellId'] == cell['equipmentId'], 'representative equipment')
        if cell['bodyId'] is not None:
            check(cell['bodyId'] in bodies, 'cell body reference')
            owners[cell['bodyId']].append(('CELL', cell['cellId'], None))
    reserved = []
    for bay in value['buffers']:
        exact_fields(bay, 'bufferId cellId capacity waitingCount reservedInboundCount availableSlots slots'.split())
        slots = bay['slots']
        check(type(bay['capacity']) is int and 2 <= bay['capacity'] <= 4 and len(slots) == bay['capacity'], 'capacity/slots')
        check([s['slotId'] for s in slots] == [f"{bay['bufferId']}-S{i}" for i in range(1, bay['capacity'] + 1)], 'slot identity')
        waiting = sum(s['status'] == 'OCCUPIED' for s in slots)
        inbound = sum(s['status'] == 'RESERVED' for s in slots)
        check((waiting, inbound, bay['capacity'] - waiting - inbound) ==
              (bay['waitingCount'], bay['reservedInboundCount'], bay['availableSlots']), 'W/R/A match slots')
        for slot in slots:
            exact_fields(slot, 'slotId status bodyId vehicleId transportId reservationId'.split())
            check(slot['status'] in ('FREE', 'RESERVED', 'OCCUPIED'), 'slot state')
            if slot['status'] == 'FREE':
                check(all(slot[key] is None for key in ['bodyId', 'vehicleId', 'transportId', 'reservationId']), 'free slot owner')
            elif slot['status'] == 'OCCUPIED':
                check(slot['bodyId'] in bodies and slot['vehicleId'] is None, 'occupied owner')
                owners[slot['bodyId']].append(('BUFFER', bay['bufferId'], slot['slotId']))
            else:
                check(slot['transportId'] in active, 'reserved transport reference')
                trip = active[slot['transportId']]
                check(trip['destination'] == {'locationType': 'BUFFER', 'locationId': bay['bufferId']}, 'reserved destination')
                check(all(slot[key] == trip[key] and slot[key] is not None for key in ['bodyId', 'vehicleId', 'reservationId', 'slotId']), 'reservation owner match')
                reserved.append(slot['transportId'])
    for vehicle in vehicles.values():
        exact_fields(vehicle, 'vehicleId kind state position bodyId partsKitId transportId'.split())
        if vehicle['bodyId'] is not None:
            check(vehicle['bodyId'] in bodies, 'vehicle body reference')
            owners[vehicle['bodyId']].append(('VEHICLE', vehicle['vehicleId'], None))
        if vehicle['transportId'] is not None:
            check(vehicle['transportId'] in active and active[vehicle['transportId']]['vehicleId'] == vehicle['vehicleId'], 'vehicle transport')
    for bid, body in bodies.items():
        exact_fields(body, body_fields)
        timestamp(body['lastObservedAt'])
        check(body['lastObservedAt'] == value['capturedAt'], 'body observation time')
        if body['locationType'] in ('INPUT', 'RESULT'):
            owners[bid].append((body['locationType'], body['locationId'], None))
        check(owners[bid] == [(body['locationType'], body['locationId'], body['locationSlotId'])], 'body single physical location')
        check(body['currentCellId'] == (body['locationId'] if body['locationType'] == 'CELL' else None), 'current cell')
        if body['transportId'] is not None:
            check(body['transportId'] in active and active[body['transportId']]['bodyId'] == bid, 'body transport')
            check(body['reservationId'] == active[body['transportId']]['reservationId'], 'body reservation')
    check(len({t['vehicleId'] for t in active.values()}) == len(active), 'one trip per vehicle')
    body_trips = [t['bodyId'] for t in active.values() if t['cargoType'] == 'BODY']
    check(len(set(body_trips)) == len(body_trips), 'one trip per body')
    expected_reserved = []
    for tid, trip in active.items():
        transport(trip)
        check(trip['status'] in ('ASSIGNED', 'IN_TRANSIT'), 'only active trips')
        check(trip['vehicleId'] in vehicles and vehicles[trip['vehicleId']]['transportId'] == tid, 'trip vehicle reverse reference')
        if trip['cargoType'] == 'BODY':
            body = bodies[trip['bodyId']]
            check(body['transportId'] == tid, 'trip body reverse reference')
            if trip['destination']['locationType'] == 'BUFFER':
                expected_reserved.append(tid)
            vehicle = vehicles[trip['vehicleId']]
            if trip['status'] == 'ASSIGNED':
                check((body['locationType'], body['locationId']) ==
                      (trip['source']['locationType'], trip['source']['locationId']) and vehicle['bodyId'] is None, 'before pickup body stays at source')
            else:
                check(body['locationType'] == 'VEHICLE' and body['locationId'] == vehicle['vehicleId'] and vehicle['bodyId'] == body['bodyId'], 'loaded body')
    check(sorted(reserved) == sorted(expected_reserved), 'reserved slots/active trips bijection')


def event(value):
    exact_fields(value, ENVELOPE)
    check(type(value['schemaVersion']) is int and value['schemaVersion'] == 1, 'schema version')
    check(type(value['sourceSeq']) is int and 1 <= value['sourceSeq'] <= 9007199254740991, 'safe sequence')
    check(re.fullmatch(r'run-[0-9]{8}-[a-z0-9]{3,32}', value['runId']), 'run ID')
    datetime.strptime(value['runId'][4:12], '%Y%m%d')
    check(re.fullmatch(r'simulator-[0-9]{2,4}', value['sourceId']), 'source ID')
    event_id = uuid.UUID(value['eventId'])
    check(event_id.version == 4 and str(event_id) == value['eventId'], 'canonical UUID v4')
    timestamp(value['occurredAt'])
    identifier_fields(value)
    kind, payload = value['eventType'], value['payload']
    check(kind in FIELDS, 'event kind')
    exact_fields(payload, FIELDS[kind].split())
    if kind == 'RUN_STARTED':
        check(value['sourceSeq'] == 1 and type(payload['seed']) is int and 0 <= payload['seed'] <= 2147483647, 'run start')
        configuration(payload['config'])
    elif kind.startswith('TRANSPORT_'):
        transport(payload)
        state, field = {'TRANSPORT_ASSIGNED': ('ASSIGNED', 'assignedAt'), 'TRANSPORT_STARTED': ('IN_TRANSIT', 'startedAt'),
                        'TRANSPORT_COMPLETED': ('COMPLETED', 'completedAt'), 'TRANSPORT_CANCELLED': ('CANCELLED', 'cancelledAt')}[kind]
        check(payload['status'] == state and payload[field] == value['occurredAt'], 'transport event transition')
    elif kind == 'FACTORY_SNAPSHOT':
        check(payload['capturedAt'] == value['occurredAt'], 'snapshot occurrence')
        snapshot(payload)
    elif kind == 'BODY_REGISTERED':
        check(payload['createdAt'] == value['occurredAt'], 'body registration time')
    elif kind == 'INSPECTION_COMPLETED':
        check(payload['equipmentId'] == 'QC-01' and payload['result'] in ('PASS', 'FAIL'), 'inspection identity/result')
        check(payload['defectCode'] == ('SIM_DEFECT_01' if payload['result'] == 'FAIL' else None), 'inspection defect')
    elif kind == 'RUN_FINISHED':
        check(payload['uniqueEventCount'] == value['sourceSeq'], 'unique generated count includes final event')


def main():
    catalog = parse((EXAMPLES / 'event-catalog.json').read_text())
    lines = (EXAMPLES / 'buffer-lifecycle.ndjson').read_text().splitlines()
    flow = [parse(line) for line in lines]
    check(len(catalog) == len(FIELDS) and {e['eventType'] for e in catalog} == set(FIELDS), 'one example per event kind')
    all_events = catalog + flow
    sizes = []
    for value in all_events:
        event(value)
        sizes.append(len(json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8')) + 1)
    check(len({e['eventId'] for e in all_events}) == len(all_events), 'example UUID collisions')
    check([e['sourceSeq'] for e in flow] == list(range(28, 38)), 'fixture excerpt sequence')
    check(max(sizes) <= 64 * 1024, 'example frame size')
    snaps = [e['payload'] for e in flow if e['eventType'] == 'FACTORY_SNAPSHOT']
    counts = [(s['buffers'][1]['waitingCount'], s['buffers'][1]['reservedInboundCount'], s['buffers'][1]['availableSlots']) for s in snaps]
    check(counts == [(2, 1, 0), (3, 0, 0), (2, 0, 1)], 'reservation/arrival/cell entry capacity')
    check([s['bodies'][2]['locationType'] for s in snaps] == ['CELL', 'BUFFER', 'BUFFER'], 'body 42 location through handover')
    completed = next(e['payload'] for e in flow if e['eventType'] == 'TRANSPORT_COMPLETED')
    config = next(e['payload']['config'] for e in catalog if e['eventType'] == 'RUN_STARTED')
    route = next(r for r in config['routes'] if r['routeId'] == completed['routeId'])
    check((timestamp(completed['completedAt']) - timestamp(completed['startedAt'])).total_seconds() * 1000
          == route['travelDurationMs'], 'fixture travel time matches configured route')
    invalid = []
    missing = deepcopy(catalog[0]); del missing['runId']; invalid.append(missing)
    broken = deepcopy(next(e for e in flow if e['eventType'] == 'FACTORY_SNAPSHOT'))
    broken['payload']['buffers'][1]['slots'][2]['transportId'] = 'transport-00999'; invalid.append(broken)
    double_location = deepcopy(flow[-1]); double_location['payload']['buffers'][1]['slots'][1]['bodyId'] = 'body-00040'; invalid.append(double_location)
    parts = deepcopy(next(e for e in catalog if e['eventType'] == 'TRANSPORT_STARTED'))
    parts['payload'].update(reservationId='reserve-00080', slotId='BAY-ASM-01-S1'); invalid.append(parts)
    for value in invalid:
        try:
            event(value)
        except ValueError:
            continue
        raise ValueError('representative invalid example unexpectedly accepted')
    print(f'PASS: {len(catalog)} event kinds, {len(flow)} NDJSON frames, {len(snaps)} coherent snapshots, '
          f'{len(invalid)} representative errors rejected; W/R/A={counts}; max frame={max(sizes)} bytes (LF included).')


if __name__ == '__main__':
    main()
