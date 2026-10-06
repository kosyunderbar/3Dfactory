from datetime import datetime, timezone
import unittest

from factory_simulator.model import BodyStatus, CellState, FactoryModel, Location, LocationType, ModelError
from factory_simulator.logistics import TransportStatus, VehicleState
from factory_simulator.run_configuration import CELLS, RunConfiguration

NOW = datetime(2026, 10, 5, tzinfo=timezone.utc)


class TransportTests(unittest.TestCase):
    def model(self, **kwargs):
        return FactoryModel(RunConfiguration.from_path(), clock=lambda: NOW, **kwargs)

    def complete_fixture(self, model, cell):
        body = model.register_fixture_body(Location(LocationType.CELL, cell), completed_cell_ids=CELLS[:CELLS.index(cell)])
        operation = model.start_work(cell)
        model.advance(operation.required_ms)
        return model.body(body.body_id)

    def test_reserved_arrival_full_buffer_entry_and_one_redispatch(self):
        model = self.model(allow_initial_fixtures=True)
        waiting = [model.register_fixture_body(Location(LocationType.BUFFER, 'BAY-ASM-02', f'BAY-ASM-02-S{i}'),
                                              completed_cell_ids=('ASM-01',)) for i in (1, 2)]
        body = self.complete_fixture(model, 'ASM-01')
        first = model.assign_transport(body.body_id)
        model.start_transport(first.transport_id)
        self.assertTrue(model.inspect()["factoryRunStarted"])
        self.assertEqual(model.buffer('BAY-ASM-02')['availableSlots'], 0)
        model.advance(4000)  # Empty AGV reaches pickup; body still in completed CELL.
        self.assertEqual(model.vehicles[0].state, VehicleState.LOADING)
        self.assertEqual(model.body(body.body_id).location, body.location)
        model.tick()  # Loading complete: source -> AGV, together with IN_TRANSIT.
        self.assertEqual(model.cell('ASM-01').state, CellState.IDLE)
        self.assertEqual(model.body(body.body_id).location, Location(LocationType.VEHICLE, 'AGV-001'))
        self.assertEqual(model.transport(first.transport_id).status, TransportStatus.IN_TRANSIT)
        second = model.register_fixture_body(Location(LocationType.CELL, 'ASM-01'))
        model.start_work('ASM-01')
        model.advance(1000)
        self.assertEqual(model.vehicles[0].x, 187.5)
        self.assertEqual(model.buffer('BAY-ASM-02')['reservedInboundCount'], 1)
        model.advance(3000)
        self.assertEqual(model.vehicles[0].state, VehicleState.UNLOADING)
        self.assertEqual(model.buffer('BAY-ASM-02')['reservedInboundCount'], 1)
        self.assertEqual(model.cell('ASM-01').blocked_reason, 'BUFFER_FULL')
        model.tick()
        buffer = model.buffer('BAY-ASM-02')
        self.assertEqual((buffer['waitingCount'], buffer['reservedInboundCount'], buffer['availableSlots']), (3, 0, 0))
        arrived = model.body(body.body_id)
        self.assertEqual(arrived.location, Location(LocationType.BUFFER, 'BAY-ASM-02', 'BAY-ASM-02-S3'))
        self.assertEqual((arrived.transport_id, arrived.reservation_id), (None, None))
        self.assertEqual(buffer['slots'][2]['transportId'], first.transport_id)
        self.assertEqual(buffer['slots'][2]['reservationId'], model.transport(first.transport_id).reservation_id)
        self.assertEqual(model.vehicles[0].state, VehicleState.RETURNING)
        self.assertEqual(model.inspect()['vehicles'][0]['bodyId'], None)
        operation = model.enter_cell(waiting[0].body_id)
        entry = model.cell_entries[-1]
        self.assertEqual(entry.available_slots_after_release, 1)
        self.assertEqual(entry.operation_id, operation.operation_id)
        self.assertEqual(model.body(waiting[0].body_id).status, BodyStatus.PROCESSING)
        self.assertEqual(model.body(second.body_id).location, Location(LocationType.CELL, 'ASM-01'))
        self.assertEqual(model.transport(model.body(second.body_id).transport_id).slot_id, entry.slot_id)
        buffer = model.buffer('BAY-ASM-02')
        self.assertEqual((buffer['waitingCount'], buffer['reservedInboundCount'], buffer['availableSlots']), (2, 1, 0))
        self.assertEqual(len(model.transports), 2)
        self.assertEqual(model.vehicles[0].state, VehicleState.TO_PICKUP)
        self.assertEqual(model.vehicles[1].state, VehicleState.IDLE)
        self.assertEqual(model._motions['AGV-001'].points[0], model._point(arrived.location))

    def test_returning_vehicle_can_take_new_work_without_position_jump(self):
        config = RunConfiguration.from_path().to_dict()
        for cell in config['config']['equipment']:
            cell['workDurationMs'] = 200
        model = FactoryModel(RunConfiguration.from_dict(config), clock=lambda: NOW)
        body = model.register_body()
        model.redispatch()
        while model.body(body.body_id).location.location_type != LocationType.BUFFER:
            model.tick()
        self.assertEqual(model.vehicles[0].state, VehicleState.RETURNING)
        model.advance(500)
        model.enter_cell(body.body_id)
        model.tick()
        before = (model.vehicles[0].x, model.vehicles[0].y)
        model.tick()
        transport = model.transport(model.body(body.body_id).transport_id)
        self.assertEqual(transport.vehicle_id, 'AGV-001')
        self.assertEqual(model.vehicles[0].state, VehicleState.TO_PICKUP)
        origin = model._motions['AGV-001'].points[0]
        self.assertNotEqual(origin, (0, 100))
        self.assertLess(origin[0], before[0])
        self.assertEqual((model.vehicles[0].x, model.vehicles[0].y), origin)

    def test_normal_input_to_good_hold_and_empty_return_without_fixture_moves(self):
        for result, destination in (('PASS', 'GOOD'), ('FAIL', 'HOLD')):
            with self.subTest(result=result):
                model = self.model(quality_results=(result,))
                body = model.register_body()
                model.redispatch()
                for _ in range(2500):
                    model.tick()
                    current = model.body(body.body_id)
                    if current.location.location_type == LocationType.BUFFER:
                        model.enter_cell(body.body_id)
                    if current.location.location_type == LocationType.RESULT:
                        break
                else:
                    self.fail('Normal transport flow failed to drain')
                current = model.body(body.body_id)
                self.assertEqual((current.location.location_id, current.status, current.inspection_result),
                                 (destination, BodyStatus.COMPLETED, result))
                self.assertEqual(current.completed_cell_ids, CELLS)
                self.assertEqual(model.body_by_tag(body.tag_id), current)
                self.assertEqual((len(model.operations), len(model.inspections), len(model.transports), len(model.cell_entries)), (3, 1, 4, 3))
                self.assertTrue(all(t.status == TransportStatus.COMPLETED for t in model.transports))
                self.assertEqual(model.active_transports, ())
                self.assertTrue(all(v['bodyId'] is None for v in model.inspect()['vehicles']))
                for _ in range(1000):
                    if all(v.state == VehicleState.IDLE for v in model.vehicles):
                        break
                    model.tick()
                else:
                    self.fail('Empty vehicles did not return home')
                self.assertTrue(all((v.x, v.y) == (0, 100) for v in model.vehicles if v.kind == 'AGV'))
                for cell in CELLS:
                    buffer = model.buffer('BAY-' + cell)
                    self.assertEqual((buffer['waitingCount'], buffer['reservedInboundCount'], buffer['availableSlots']), (0, 0, 3))
                    self.assertEqual(model.cell(cell).state, CellState.IDLE)

    def test_pause_entry_preconditions_and_clock_failure_preserve_ownership(self):
        model = self.model()
        body = model.register_body()
        decision = model.assign_transport(body.body_id)
        model.start_transport(decision.transport_id)
        model.tick()  # LOADING
        model.pause()
        before = model.inspect()
        self.assertEqual(model.advance(1000), ())
        for command in (lambda: model.start_transport(decision.transport_id), lambda: model.enter_cell(body.body_id)):
            with self.assertRaises(ModelError):
                command()
        self.assertEqual(model.inspect(), before)
        model.resume()
        model.tick()  # MOVING
        model.advance(1000)
        motion = model.start_transport(decision.transport_id)
        self.assertEqual(motion.elapsed_ms, 1000)  # Repeated start does not reset movement.
        model.pause()
        before = model.inspect()
        model.advance(1000)
        self.assertEqual(model.inspect(), before)
        model.resume()
        model.advance(3100)  # Arrival completed, now returning.
        model.pause()
        before = model.inspect()
        model.advance(1000)
        self.assertEqual(model.inspect(), before)
        model.resume()
        with self.assertRaises(ModelError):
            model.start_transport(decision.transport_id)
        operation = model.enter_cell(body.body_id)
        before = model.inspect()
        with self.assertRaises(ModelError):
            model.enter_cell(body.body_id)
        self.assertEqual(model.inspect(), before)
        instant = [NOW]
        model = FactoryModel(RunConfiguration.from_path(), allow_initial_fixtures=True, clock=lambda: instant[0])
        held = model.register_fixture_body(Location(LocationType.CELL, 'ASM-01'))
        waiting = model.register_fixture_body(Location(LocationType.BUFFER, 'BAY-ASM-01', 'BAY-ASM-01-S1'))
        before = model.inspect()
        with self.assertRaises(ModelError):
            model.enter_cell(waiting.body_id)
        self.assertEqual(model.inspect(), before)
        model._transfer_ownership(held.body_id, held.location, Location(LocationType.INPUT, 'BODY-IN'))
        instant[0] = datetime(2026, 10, 5)
        before = model.inspect()
        with self.assertRaises(ModelError):
            model.enter_cell(waiting.body_id)
        self.assertEqual(model.inspect(), before)

        # A failed pickup tick must also roll back another cell's work progress.
        instant[0] = NOW
        model = FactoryModel(RunConfiguration.from_path(), allow_initial_fixtures=True, clock=lambda: instant[0])
        input_body = model.register_body()
        decision = model.assign_transport(input_body.body_id)
        model.start_transport(decision.transport_id)
        processing = model.register_fixture_body(Location(LocationType.CELL, 'ASM-02'), completed_cell_ids=('ASM-01',))
        model.start_work('ASM-02')
        model.tick()  # Vehicle now LOADING; independent cell has progressed 100ms.
        instant[0] = datetime(2026, 10, 5)
        before = model.inspect()
        with self.assertRaises(ModelError):
            model.tick()
        self.assertEqual(model.inspect(), before)
