from datetime import datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path
import unittest

from factory_simulator.logistics import TransportStatus, VehicleState
from factory_simulator.model import BodyStatus, CellState, FactoryModel, Location, LocationType, ModelError
from factory_simulator.run_configuration import CELLS, DEFAULT_CONFIG, RunConfiguration

NOW = datetime(2026, 10, 5, tzinfo=timezone.utc)
ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location('contract_examples', ROOT / 'scripts/check_contract_examples.py')
contract = importlib.util.module_from_spec(spec)
spec.loader.exec_module(contract)


class ScenarioTests(unittest.TestCase):
    def model(self, **kwargs):
        return FactoryModel(RunConfiguration.from_path(), clock=lambda: NOW, **kwargs)

    def verify_events(self, model):
        events = [e.to_dict() for e in model.events]
        self.assertEqual([e['sourceSeq'] for e in events], list(range(1, len(events) + 1)))
        self.assertEqual(len({e['eventId'] for e in events}), len(events))
        for event in events:
            contract.event(event)
        return events

    def test_cancel_repeats_departure_rejection_and_duplicate_arrival(self):
        for phase in ('ASSIGNED', 'TO_PICKUP', 'LOADING'):
            with self.subTest(phase=phase):
                model = self.model()
                body = model.register_body()
                decision = model.assign_transport(body.body_id)
                if phase != 'ASSIGNED':
                    model.start_transport(decision.transport_id)
                if phase == 'LOADING':
                    model.tick()
                cancelled = model.cancel_transport(decision.transport_id)
                self.assertEqual(cancelled.status, TransportStatus.CANCELLED)
                self.assertEqual(model.body(body.body_id).location, body.location)
                self.assertEqual((model.buffer('BAY-ASM-01')['reservedInboundCount'], model.vehicles[0].state), (0, VehicleState.IDLE))
                count = len(model.events)
                self.assertEqual(model.cancel_transport(decision.transport_id), cancelled)
                self.assertEqual(len(model.events), count)
                model.advance(500)
                self.assertEqual(len(model.transports), 1)  # Cancellation holds automatic retry.
                retry = model.assign_transport(body.body_id)
                self.assertNotEqual(retry.transport_id, decision.transport_id)
                self.assertNotEqual(model.transport(retry.transport_id).reservation_id, cancelled.reservation_id)
                count = len(model.events)
                model.cancel_transport(decision.transport_id)
                self.assertEqual(len(model.events), count)
                self.assertEqual(model.body(body.body_id).transport_id, retry.transport_id)
                self.assertEqual(model.buffer('BAY-ASM-01')['reservedInboundCount'], 1)
                model.publish_snapshot()
                self.verify_events(model)
        model = self.model()
        body = model.register_body()
        decision = model.assign_transport(body.body_id)
        before = model.inspect()
        with self.assertRaises(ModelError):
            model.complete_transport(decision.transport_id)
        self.assertEqual(model.inspect(), before)
        model.start_transport(decision.transport_id)
        model.advance(200)
        before = model.inspect()
        count = len(model.events)
        with self.assertRaises(ModelError):
            model.cancel_transport(decision.transport_id)
        self.assertEqual(model.inspect(), before)
        self.assertEqual(len(model.events), count)
        model.advance(4100)
        before = model.inspect()
        count = len(model.events)
        model.complete_transport(decision.transport_id)
        self.assertEqual(model.inspect(), before)
        self.assertEqual(len(model.events), count)
        model.enter_cell(body.body_id)
        before = model.inspect()
        model.complete_transport(decision.transport_id)
        self.assertEqual(model.inspect(), before)
        model.publish_snapshot()
        self.verify_events(model)

    def test_parts_amr_has_no_body_tag_or_bay_reservation(self):
        model = self.model()
        bays = [model.buffer('BAY-' + cell) for cell in CELLS]
        decision = model.assign_parts('ASM-01')
        trip = model.transport(decision.transport_id)
        self.assertEqual((trip.body_id, trip.reservation_id, trip.slot_id, trip.vehicle_id), (None, None, None, 'AMR-001'))
        self.assertEqual(model.assign_parts('ASM-02').reason, 'NO_VEHICLE')
        self.assertEqual(len(model.parts), 1)
        with self.assertRaises(ModelError):
            model.cancel_transport(trip.transport_id)
        model.start_transport(trip.transport_id)
        model.advance(200)
        vehicle = model.inspect()['vehicles'][-1]
        self.assertEqual((vehicle['bodyId'], vehicle['partsKitId']), (None, trip.parts_kit_id))
        model.publish_snapshot()
        model.advance(4100)
        self.assertEqual(model.parts[0].location, Location(LocationType.PARTS_DOCK, 'PARTS-ASM-01'))
        self.assertEqual([model.buffer('BAY-' + cell) for cell in CELLS], bays)
        self.assertEqual(model.bodies, ())
        model.advance(4000)
        self.assertEqual(model.vehicles[-1].state, VehicleState.IDLE)
        self.assertEqual(len(model.transports), 1)
        model.publish_snapshot()
        events = self.verify_events(model)
        self.assertFalse(any(e['eventType'] in ('BODY_REGISTERED', 'SLOT_RESERVED', 'SLOT_RELEASED') for e in events))

    def test_failure_recovery_preserves_work_and_reserved_pickup(self):
        model = self.model(allow_initial_fixtures=True)
        body = model.register_fixture_body(Location(LocationType.CELL, 'ASM-01'))
        op = model.start_work('ASM-01')
        model.advance(1000)
        model.fail_cell('ASM-01')
        failed = model.cell('ASM-01')
        count = len(model.events)
        model.fail_cell('ASM-01')
        self.assertEqual(len(model.events), count)
        model.advance(1000)
        self.assertEqual(model.operations[0].elapsed_ms, 1000)
        self.assertEqual((failed.resume_state, failed.operation_id), (CellState.RUNNING, op.operation_id))
        model.publish_snapshot()
        model.recover_cell('ASM-01')
        model.advance(3000)
        self.assertEqual((model.operations[0].elapsed_ms, model.body(body.body_id).completed_cell_ids), (4000, ('ASM-01',)))
        decision = model.assign_transport(body.body_id)
        model.delay_transport(decision.transport_id, 500)
        model.start_transport(decision.transport_id)
        model.fail_cell('ASM-01')
        model.advance(4500)
        self.assertEqual(model.body(body.body_id).location, body.location)
        self.assertEqual(model.transport(decision.transport_id).status, TransportStatus.ASSIGNED)
        self.assertEqual(model.buffer('BAY-ASM-02')['reservedInboundCount'], 1)
        model.publish_snapshot()
        model.recover_cell('ASM-01')
        model.tick()
        self.assertEqual(model.transport(decision.transport_id).status, TransportStatus.IN_TRANSIT)
        model.fail_cell('ASM-02')
        model.advance(4000)
        self.assertEqual(model.transport(decision.transport_id).status, TransportStatus.IN_TRANSIT)
        model.advance(600)
        self.assertEqual(model.transport(decision.transport_id).status, TransportStatus.COMPLETED)
        before = model.inspect()
        with self.assertRaises(ModelError):
            model.enter_cell(body.body_id)
        self.assertEqual(model.inspect(), before)
        model.recover_cell('ASM-02')
        model.enter_cell(body.body_id)
        model.set_quality_pattern(('FAIL', 'PASS'))
        count = len(model.events)
        model.recover_cell('ASM-02')
        self.assertEqual(len(model.events), count)
        model.publish_snapshot()
        self.verify_events(model)

    def test_100_bodies_capacity_bounds_conservation_and_event_snapshot_agreement(self):
        for capacity in (2, 3, 4):
            with self.subTest(capacity=capacity):
                data = json.loads(DEFAULT_CONFIG.read_text())
                for buffer in data['config']['buffers']:
                    buffer['capacity'] = capacity
                    buffer['slotIds'] = [f"{buffer['bufferId']}-S{i}" for i in range(1, capacity + 1)]
                for equipment in data['config']['equipment']:
                    equipment['workDurationMs'] = 200
                for route in data['config']['routes']:
                    route['travelDurationMs'] = 200
                instant = [NOW]
                model = FactoryModel(RunConfiguration.from_dict(data), clock=lambda: instant[0], quality_results=('PASS', 'FAIL'))
                for _ in range(100):
                    model.register_body()
                model.publish_snapshot()
                model.redispatch()
                for step in range(10000):
                    instant[0] += timedelta(milliseconds=100)
                    model.tick()
                    for cell in reversed(CELLS):
                        waiting = model.bodies_at(LocationType.BUFFER, 'BAY-' + cell)
                        if waiting and model.cell(cell).state == CellState.IDLE:
                            model.enter_cell(waiting[0].body_id)
                    if step % 100 == 0:
                        snapshot = model.publish_snapshot().to_dict()
                        contract.event(snapshot)
                        self.assertEqual(len(snapshot['payload']['bodies']), 100)
                        self.assertTrue(all(0 <= b['waitingCount'] + b['reservedInboundCount'] <= capacity for b in snapshot['payload']['buffers']))
                    if (all(b.location.location_type == LocationType.RESULT for b in model.bodies)
                            and all(v.state == VehicleState.IDLE for v in model.vehicles)):
                        break
                else:
                    self.fail('100-body flow did not drain')
                self.assertEqual((len(model.operations), len(model.inspections), len(model.transports), len(model.cell_entries)), (300, 100, 400, 300))
                self.assertEqual(len({b.tag_id for b in model.bodies}), 100)
                self.assertEqual(sum(b.inspection_result == 'PASS' for b in model.bodies), 50)
                self.assertTrue(all(b.completed_cell_ids == CELLS and b.status == BodyStatus.COMPLETED for b in model.bodies))
                for cell in CELLS:
                    self.assertEqual(model.buffer('BAY-' + cell)['availableSlots'], capacity)
                model.finish_run()
                events = self.verify_events(model)
                self.assertEqual(events[-1]['eventType'], 'RUN_FINISHED')
                self.assertEqual(events[-1]['payload']['uniqueEventCount'], len(events))
                final = events[-2]['payload']
                self.assertEqual(final, model.snapshot(captured_at=final['capturedAt']))
                completed_ops = [e['payload']['operationId'] for e in events if e['eventType'] == 'OPERATION_COMPLETED']
                completed_inspections = [e['payload']['inspectionId'] for e in events if e['eventType'] == 'INSPECTION_COMPLETED']
                completed_trips = [e['payload']['transportId'] for e in events if e['eventType'] == 'TRANSPORT_COMPLETED']
                self.assertEqual((len(set(completed_ops)), len(set(completed_inspections)), len(set(completed_trips))), (300, 100, 400))
                self.assertEqual(len(completed_inspections), 100)
                count = len(model.events)
                model.finish_run()
                self.assertEqual(len(model.events), count)
                with self.assertRaises(ModelError):
                    model.publish_snapshot()
