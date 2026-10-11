"""Immutable v1 originals; sequence survives retirement of confirmed local records."""
from dataclasses import dataclass
import json
from uuid import uuid4


@dataclass(frozen=True)
class Event:
    ndjson: str

    def to_dict(self) -> dict:
        return json.loads(self.ndjson)


class EventJournal:
    def __init__(self, run_id, source_id):
        self.run_id, self.source_id = run_id, source_id
        self.records: list[Event] = []
        self.next_sequence = 1

    def append(self, kind, timestamp, payload):
        seq = self.next_sequence
        if seq > 9007199254740991:
            raise ValueError('Event sequence exhausted')
        value = {'schemaVersion': 1, 'eventId': str(uuid4()), 'runId': self.run_id,
                 'sourceId': self.source_id, 'sourceSeq': seq, 'eventType': kind,
                 'occurredAt': timestamp, 'payload': payload}
        raw = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':')) + '\n'
        if len(raw.encode('utf-8')) > 65536:
            raise ValueError('v1 event exceeds 65536-byte frame limit')
        event = Event(raw)
        self.records.append(event)
        self.next_sequence += 1
        return event


def transition_facts(before, after):
    """Facts first; callers can capture their resulting complete snapshot afterwards."""
    for scenario in after['scenarios'][len(before['scenarios']):]:
        yield 'SCENARIO_CHANGED', None, scenario
    for key, body in after['bodies'].items():
        if key not in before['bodies']:
            yield 'BODY_REGISTERED', body.created_at, {'bodyId': key, 'tagId': body.tag_id,
                'modelCode': body.model_code, 'specCode': body.spec_code, 'createdAt': body.created_at,
                'initialLocation': {'locationType': body.location.location_type.value, 'locationId': body.location.location_id}}
    for key, operation in after['operations'].items():
        prior = before['operations'].get(key)
        if operation.completed_at is not None and (prior is None or prior.completed_at is None):
            yield 'OPERATION_COMPLETED', operation.completed_at, {'operationId': key, 'cellId': operation.cell_id,
                'equipmentId': operation.cell_id, 'unitId': operation.body_id, 'durationMs': operation.elapsed_ms}
    for key, inspection in after['inspections'].items():
        if key not in before['inspections']:
            payload = inspection.to_dict()
            del payload['inspectedAt']
            yield 'INSPECTION_COMPLETED', inspection.inspected_at, payload
    for entry in after['entries'][len(before['entries']):]:
        if entry.buffer_id is not None:
            yield 'SLOT_RELEASED', entry.entered_at, {'bufferId': entry.buffer_id, 'slotId': entry.slot_id,
                'bodyId': entry.body_id, 'reservationId': entry.reservation_id, 'transportId': entry.transport_id,
                'reason': 'BODY_ENTERED_CELL'}
        yield 'BODY_ENTERED_CELL', entry.entered_at, {'bodyId': entry.body_id, 'cellId': entry.cell_id,
            'bufferId': entry.buffer_id, 'slotId': entry.slot_id, 'operationId': entry.operation_id}
    for key, body in after['bodies'].items():
        prior = before['bodies'].get(key)
        if prior and prior.location.location_type == 'BUFFER' and body.location.location_type == 'VEHICLE':
            arrival = next((t for t in reversed(list(before['transports'].values())) if t.body_id == key
                            and t.status == 'COMPLETED' and t.destination.location_id == prior.location.location_id
                            and t.slot_id == prior.location.slot_id),None)
            trip = after['transports'][body.transport_id]
            yield 'SLOT_RELEASED', trip.started_at, {'bufferId':prior.location.location_id,'slotId':prior.location.slot_id,
                'bodyId':key,'reservationId':arrival.reservation_id if arrival else None,
                'transportId':arrival.transport_id if arrival else None,'reason':'BODY_PICKED_UP'}
    for key, transport in after['transports'].items():
        prior = before['transports'].get(key)
        if prior is not None and prior.status == transport.status:
            continue
        if prior is None and transport.reservation_id:
            yield 'SLOT_RESERVED', transport.assigned_at, {'reservationId': transport.reservation_id,
                'transportId': key, 'bufferId': transport.destination.location_id, 'slotId': transport.slot_id,
                'bodyId': transport.body_id, 'vehicleId': transport.vehicle_id}
        if transport.status == 'CANCELLED' and transport.reservation_id:
            yield 'SLOT_RELEASED', transport.cancelled_at, {'bufferId': transport.destination.location_id,
                'slotId': transport.slot_id, 'bodyId': transport.body_id, 'reservationId': transport.reservation_id,
                'transportId': key, 'reason': 'CANCEL_BEFORE_DEPARTURE'}
        kind, timestamp = {'ASSIGNED': ('TRANSPORT_ASSIGNED', transport.assigned_at),
                          'IN_TRANSIT': ('TRANSPORT_STARTED', transport.started_at),
                          'COMPLETED': ('TRANSPORT_COMPLETED', transport.completed_at),
                          'CANCELLED': ('TRANSPORT_CANCELLED', transport.cancelled_at)}[transport.status]
        yield kind, timestamp, transport.to_dict()
    for key, cell in after['cells'].items():
        prior = before['cells'][key]
        if prior.state == cell.state:
            continue
        reason = ('FAILURE_INJECTED' if cell.state == 'DOWN' else 'RECOVERED' if prior.state == 'DOWN'
                  else 'WORK_STARTED' if cell.state == 'RUNNING' else 'WORK_COMPLETED' if cell.state == 'BLOCKED'
                  else 'PICKUP_COMPLETED')
        owner = next((body for body in after['bodies'].values()
                      if body.location.location_type == 'CELL' and body.location.location_id == key), None)
        yield 'EQUIPMENT_STATE_CHANGED', None, {'cellId': key, 'equipmentId': key, 'previousState': prior.state.value,
            'state': cell.state.value, 'bodyId': owner.body_id if owner else None, 'reason': reason}
    if before['paused'] != after['paused']:
        yield 'RUN_STATE_CHANGED', None, {'previousState': 'PAUSED' if before['paused'] else 'RUNNING',
            'state': 'PAUSED' if after['paused'] else 'RUNNING', 'reason': 'PAUSE_REQUEST' if after['paused'] else 'RESUME_REQUEST'}
