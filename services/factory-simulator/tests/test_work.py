from datetime import datetime, timedelta, timezone
import json
import unittest

from factory_simulator.model import (BodyStatus, CellState, FactoryModel, InspectionResult,
                                     Location, LocationType, ModelError)
from factory_simulator.run_configuration import CELLS, DEFAULT_CONFIG, RunConfiguration

NOW = datetime(2026, 10, 5, tzinfo=timezone.utc)
AGV = Location(LocationType.VEHICLE, 'AGV-001')


class CellWorkTests(unittest.TestCase):
    def model(self, **kwargs):
        return FactoryModel(RunConfiguration.from_path(), clock=lambda: NOW,
                            allow_initial_fixtures=True, **kwargs)

    def test_process_order_pause_completion_and_body_retained(self):
        instant = [NOW]
        model = FactoryModel(RunConfiguration.from_path(), clock=lambda: instant[0],
                             allow_initial_fixtures=True, quality_results=('PASS',))
        body = model.register_fixture_body(Location(LocationType.CELL, 'ASM-01'))
        for cell_id, duration in zip(CELLS, (4000, 6000, 3000)):
            operation = model.start_work(cell_id)
            self.assertEqual(model.body(body.body_id).status, BodyStatus.PROCESSING)
            self.assertEqual(model.body(body.body_id).inspection_result, InspectionResult.NOT_INSPECTED)
            model.advance(duration - 100)
            self.assertEqual(model.inspect()['equipment'][CELLS.index(cell_id)]['remainingWorkMs'], 100)
            model.pause()
            before = model.inspect()
            instant[0] += timedelta(minutes=1)
            self.assertEqual(model.advance(1000), ())
            self.assertEqual(model.inspect(), before)
            model.resume()
            completed = model.tick()
            self.assertEqual(len(completed), 1)
            self.assertEqual(completed[0].operation_id, operation.operation_id)
            self.assertEqual(completed[0].to_dict()['durationMs'], duration)
            current = model.body(body.body_id)
            self.assertEqual(current.location, Location(LocationType.CELL, cell_id))
            self.assertEqual(model.cell(cell_id).state, CellState.BLOCKED)
            self.assertEqual(model.cell(cell_id).blocked_reason, 'WAITING_PICKUP')
            self.assertEqual(current.completed_cell_ids, CELLS[:CELLS.index(cell_id) + 1])
            self.assertEqual(model.advance(100), ())  # No duplicate completion.
            with self.assertRaises(ModelError):
                model.start_work(cell_id)
            self.assertEqual(model._transfer_ownership(current.body_id, current.location, current.location), current)
            if cell_id != 'QC-01':
                self.assertEqual(current.status, BodyStatus.WAITING_UNLOAD)
                self.assertEqual((current.inspection_result, current.inspected_at), (InspectionResult.NOT_INSPECTED, None))
                model._transfer_ownership(current.body_id, current.location, AGV)
                self.assertEqual(model.cell(cell_id).state, CellState.IDLE)
                self.assertEqual(model.body(current.body_id).status, BodyStatus.IN_TRANSIT)
                next_cell = current.next_cell_id
                bay = Location(LocationType.BUFFER, 'BAY-' + next_cell, 'BAY-' + next_cell + '-S1')
                model._transfer_ownership(current.body_id, AGV, bay)
                self.assertEqual(model.body(current.body_id).status, BodyStatus.WAITING)
                model._transfer_ownership(current.body_id, bay, Location(LocationType.CELL, next_cell))
        current = model.body(body.body_id)
        self.assertEqual((current.status, current.inspection_result, current.next_cell_id),
                         (BodyStatus.COMPLETED, InspectionResult.PASS, None))
        self.assertEqual(len(model.inspections), 1)
        self.assertEqual(sum(op.to_dict()['durationMs'] for op in model.operations), 13000)
        model._transfer_ownership(current.body_id, current.location, AGV)
        self.assertEqual(model.body(current.body_id).status, BodyStatus.COMPLETED)
        self.assertEqual(model.body(current.body_id).inspected_at, current.inspected_at)

    def test_fixed_and_seeded_quality_and_unique_inspections(self):
        def outcomes(model, count):
            results = []
            for _ in range(count):
                body = model.register_fixture_body(Location(LocationType.CELL, 'QC-01'), completed_cell_ids=CELLS[:2])
                self.assertEqual((body.inspection_result, body.inspected_at), (InspectionResult.NOT_INSPECTED, None))
                model.start_work('QC-01')
                model.advance(3000)
                inspection = model.inspections[-1]
                results.append(inspection.result)
                self.assertEqual(inspection.to_dict()['defectCode'], 'SIM_DEFECT_01' if inspection.result == 'FAIL' else None)
                self.assertEqual(model.advance(100), ())
                model._transfer_ownership(body.body_id, body.location,
                    Location(LocationType.RESULT, 'HOLD' if inspection.result == 'FAIL' else 'GOOD'))
            self.assertEqual(len({i.inspection_id for i in model.inspections}), count)
            self.assertEqual(len({i.body_id for i in model.inspections}), count)
            return results
        self.assertEqual(outcomes(self.model(quality_results=('PASS', 'FAIL')), 3), ['PASS', 'FAIL', 'PASS'])
        self.assertEqual(outcomes(self.model(), 3), outcomes(self.model(), 3))
        for probability, expected in ((0, 'PASS'), (1, 'FAIL')):
            data = json.loads(DEFAULT_CONFIG.read_text())
            data['config']['failProbability'] = probability
            model = FactoryModel(RunConfiguration.from_dict(data), allow_initial_fixtures=True)
            self.assertEqual(outcomes(model, 1), [expected])

    def test_invalid_work_commands_preserve_state_and_ids(self):
        model = self.model()
        for history in ((), ('ASM-02', 'ASM-01')):
            with self.assertRaises(ModelError):
                model.register_fixture_body(Location(LocationType.CELL, 'QC-01'), completed_cell_ids=history)
        body = model.register_body()
        self.assertEqual(body.body_id, 'body-00001')
        asm2 = Location(LocationType.CELL, 'ASM-02')
        model._transfer_ownership(body.body_id, body.location, asm2)
        before = model.inspect()
        for cell_id in ('ASM-02', 'ASM-01', 'UNKNOWN'):
            with self.assertRaises(ModelError):
                model.start_work(cell_id)
        self.assertEqual(model.inspect(), before)
        asm1 = Location(LocationType.CELL, 'ASM-01')
        model._transfer_ownership(body.body_id, asm2, asm1)
        model.pause()
        with self.assertRaises(ModelError):
            model.start_work('ASM-01')
        model.resume()
        self.assertEqual(model.start_work('ASM-01').operation_id, 'operation-00001')
        before = model.inspect()
        with self.assertRaises(ModelError):
            model.start_work('ASM-01')
        with self.assertRaises(ModelError):
            model._transfer_ownership(body.body_id, asm1, AGV)
        for delta in (True, 0, -100, 150):
            with self.subTest(delta=delta), self.assertRaises(ModelError):
                model.advance(delta)
        self.assertEqual(model.inspect(), before)
