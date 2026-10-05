from datetime import datetime, timedelta, timezone
import json
import unittest

from factory_simulator.model import BodyStatus, CellState, FactoryModel, Location, LocationType, ModelError
from factory_simulator.logistics import TransportStatus, VehicleState
from factory_simulator.run_configuration import CELLS, DEFAULT_CONFIG, RunConfiguration

NOW = datetime(2026, 10, 5, tzinfo=timezone.utc)


class DispatchTests(unittest.TestCase):
    def model(self, capacity=3, **kwargs):
        data = json.loads(DEFAULT_CONFIG.read_text())
        for buffer in data['config']['buffers']:
            buffer['capacity'] = capacity
            buffer['slotIds'] = [f"{buffer['bufferId']}-S{i}" for i in range(1, capacity + 1)]
        return FactoryModel(RunConfiguration.from_dict(data), allow_initial_fixtures=True, **kwargs)

    def occupy(self, model, cell_id, count):
        buffer_id = 'BAY-' + cell_id
        for i in range(1, count + 1):
            model.register_fixture_body(Location(LocationType.BUFFER, buffer_id, f'{buffer_id}-S{i}'),
                                        completed_cell_ids=CELLS[:CELLS.index(cell_id)])

    def complete(self, model, cell_id):
        body = model.register_fixture_body(Location(LocationType.CELL, cell_id),
                                          completed_cell_ids=CELLS[:CELLS.index(cell_id)])
        operation = model.start_work(cell_id)
        model.advance(operation.required_ms)
        return model.body(body.body_id)

    def test_last_slot_w_plus_r_capacity_and_idempotent_allocation(self):
        for capacity in (2, 3, 4):
            with self.subTest(capacity=capacity):
                model = self.model(capacity)
                self.occupy(model, 'ASM-01', capacity - 1)
                first, second = model.register_body(), model.register_body()
                approved = model.assign_transport(first.body_id)
                self.assertTrue(approved.approved)
                buffer = model.buffer('BAY-ASM-01')
                self.assertEqual((buffer['waitingCount'], buffer['reservedInboundCount'], buffer['availableSlots']),
                                 (capacity - 1, 1, 0))
                reserved = buffer['slots'][-1]
                self.assertEqual(reserved['status'], 'RESERVED')
                transport = model.transport(approved.transport_id)
                self.assertEqual((reserved['transportId'], reserved['reservationId'], reserved['vehicleId'], reserved['bodyId']),
                                 (transport.transport_id, transport.reservation_id, transport.vehicle_id, first.body_id))
                self.assertEqual(model.body(first.body_id).location, first.location)
                self.assertEqual(model.body(first.body_id).status, BodyStatus.WAITING)
                self.assertEqual((transport.status, transport.started_at), (TransportStatus.ASSIGNED, None))
                self.assertEqual(model.vehicles[0].state, VehicleState.TO_PICKUP)
                self.assertEqual(model.inspect()['vehicles'][0]['bodyId'], None)
                before = model.inspect()
                denied = model.assign_transport(second.body_id)
                self.assertEqual((denied.approved, denied.reason, denied.transport_id), (False, 'BUFFER_FULL', None))
                self.assertEqual(model.inspect(), before)
                self.assertEqual(model.assign_transport(first.body_id), approved)
                self.assertEqual(model.inspect(), before)
                self.assertEqual(len(model.transports), 1)  # Second AGV still free; capacity is the actual limit.
                with self.assertRaises(ModelError):
                    model.register_fixture_body(Location(LocationType.BUFFER, 'BAY-ASM-01', reserved['slotId']))
                with self.assertRaises(ModelError):
                    model._transfer_ownership(second.body_id, second.location, Location(LocationType.VEHICLE, transport.vehicle_id))
                with self.assertRaises(ModelError):
                    model._transfer_ownership(first.body_id, first.location, Location(LocationType.BUFFER, 'BAY-ASM-01', reserved['slotId']))
                buffer['slots'][-1]['status'] = 'FREE'
                self.assertEqual(model.buffer('BAY-ASM-01')['reservedInboundCount'], 1)

    def test_cell_unload_lock_vehicle_shortage_and_result_routes(self):
        model = self.model()
        self.occupy(model, 'ASM-02', 3)
        body = self.complete(model, 'ASM-01')
        self.assertEqual(model.cell('ASM-01').blocked_reason, 'BUFFER_FULL')
        self.assertEqual(model.assign_transport(body.body_id).reason, 'BUFFER_FULL')
        self.assertEqual((model.body(body.body_id).location, model.body(body.body_id).status),
                         (body.location, BodyStatus.WAITING_UNLOAD))
        self.assertEqual(len(model.transports), 0)
        self.assertTrue(all(vehicle.state == VehicleState.IDLE for vehicle in model.vehicles))
        # Fixture removal arranges newly available space; no real arrival/entry is claimed.
        waiting = model.bodies_at(LocationType.BUFFER, 'BAY-ASM-02')[0]
        model._transfer_ownership(waiting.body_id, waiting.location, Location(LocationType.INPUT, 'BODY-IN'))
        decision = model.assign_transport(body.body_id)
        self.assertTrue(decision.approved)
        self.assertEqual(model.body(body.body_id).location, body.location)
        self.assertEqual(model.cell('ASM-01').blocked_reason, 'WAITING_PICKUP')
        self.assertEqual(model.buffer('BAY-ASM-02')['availableSlots'], 0)
        with self.assertRaises(ModelError):
            model._transfer_ownership(body.body_id, body.location, Location(LocationType.VEHICLE, 'AGV-001'))
        # Two input allocations exhaust AGVs without consuming an unrelated destination slot.
        model = self.model()
        for _ in range(2):
            self.assertTrue(model.assign_transport(model.register_body().body_id).approved)
        body = self.complete(model, 'ASM-01')
        before_slots = model.buffer('BAY-ASM-02')
        self.assertEqual(model.cell('ASM-01').blocked_reason, 'NO_VEHICLE')
        self.assertEqual(model.assign_transport(body.body_id).reason, 'NO_VEHICLE')
        self.assertEqual(model.buffer('BAY-ASM-02'), before_slots)
        self.assertEqual(model.vehicles[-1].kind, 'AMR')
        self.assertEqual(model.vehicles[-1].state, VehicleState.IDLE)
        for result, destination in (('PASS', 'GOOD'), ('FAIL', 'HOLD')):
            model = self.model(quality_results=(result,))
            body = self.complete(model, 'QC-01')
            decision = model.assign_transport(body.body_id)
            transport = model.transport(decision.transport_id)
            self.assertEqual((transport.destination.location_id, transport.slot_id, transport.reservation_id),
                             (destination, None, None))
            self.assertEqual(model.body(body.body_id).status, BodyStatus.COMPLETED)
            self.assertEqual(model.body(body.body_id).location, body.location)
            self.assertEqual(sum(model.buffer('BAY-' + cell)['reservedInboundCount'] for cell in CELLS), 0)

    def test_invalid_commands_clock_failure_and_no_time_expiry(self):
        instant = [NOW]
        model = self.model(clock=lambda: instant[0])
        body = model.register_body()
        before = model.inspect()
        instant[0] = datetime(2026, 10, 5)  # Invalid naive clock must not partially allocate.
        with self.assertRaises(ModelError):
            model.assign_transport(body.body_id)
        self.assertEqual(model.inspect(), before)
        instant[0] = NOW
        model.pause()
        paused = model.inspect()
        with self.assertRaises(ModelError):
            model.assign_transport(body.body_id)
        self.assertEqual(model.inspect(), paused)
        model.resume()
        for invalid in ('unknown-body',):
            with self.assertRaises(ModelError):
                model.assign_transport(invalid)
        waiting = model.register_fixture_body(Location(LocationType.CELL, 'ASM-01'))
        before = model.inspect()
        with self.assertRaises(ModelError):
            model.assign_transport(waiting.body_id)
        self.assertEqual(model.inspect(), before)
        model.start_work('ASM-01')
        with self.assertRaises(ModelError):
            model.assign_transport(waiting.body_id)
        decision = model.assign_transport(body.body_id)
        transport = model.transport(decision.transport_id)
        self.assertEqual((transport.transport_id, transport.reservation_id), ('transport-00001', 'reserve-00001'))
        instant[0] += timedelta(days=1)
        model.advance(10000)
        model.pause()
        model.advance(1000)
        self.assertEqual(model.transport(transport.transport_id), transport)
        self.assertEqual(model.buffer('BAY-ASM-01')['reservedInboundCount'], 1)
        self.assertEqual(model.body(body.body_id).location, body.location)
        self.assertEqual(model.vehicles[0].state, VehicleState.TO_PICKUP)
        normal = FactoryModel(RunConfiguration.from_path())
        initial = normal.register_body()
        with self.assertRaises(ModelError):
            normal._transfer_ownership(initial.body_id, initial.location, Location(LocationType.VEHICLE, 'AGV-001'))
