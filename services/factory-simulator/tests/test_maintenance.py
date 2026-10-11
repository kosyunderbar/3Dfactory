from datetime import datetime, timezone
import unittest

from factory_simulator.maintenance import ManualMaintenance
from factory_simulator.model import FactoryModel, Location, LocationType, CellState
from factory_simulator.run_configuration import RunConfiguration
from factory_simulator.traffic import traffic_configuration
from factory_simulator.connected_demo import NormalDriver
from factory_simulator.parts_supply import supply_configuration


class MaintenanceTests(unittest.TestCase):
    def fixture(self):
        model = FactoryModel(RunConfiguration.from_path(), allow_initial_fixtures=True,
                             clock=lambda: datetime(2026, 10, 11, tzinfo=timezone.utc))
        for cell in ('ASM-01', 'ASM-02'):
            model.register_fixture_body(Location(LocationType.CELL, cell), completed_cell_ids=() if cell=='ASM-01' else ('ASM-01',))
            model.start_work(cell)
        maintenance = ManualMaintenance(model, lambda fn, *args: fn(*args))
        return model, maintenance

    def command(self, maintenance, action, request_id, **overrides):
        command = dict(runId=maintenance.model.run_id, faultId='fault-00001', action=action, requestId=request_id)
        command.update(overrides)
        maintenance.command(command)

    def test_waits_for_both_manual_steps_preserves_work_and_allows_other_cell(self):
        model, maintenance = self.fixture()
        model.advance(1000); maintenance.step()
        self.assertEqual(model.cell('ASM-01').state, CellState.DOWN)
        frozen = model.operations[0].elapsed_ms
        for _ in range(50):
            model.advance(100); maintenance.step()
        self.assertEqual(model.operations[0].elapsed_ms, frozen)
        self.assertIsNotNone(model.operations[1].completed_at)
        self.assertEqual(maintenance.fault['stage'], 'DETECTED')
        self.command(maintenance, 'repair', 'early')
        self.assertFalse(maintenance.last_command['ok'])
        self.command(maintenance, 'inspect', 'wrong', runId='run-stale')
        self.assertFalse(maintenance.last_command['ok'])
        self.command(maintenance, 'inspect', 'inspect')
        self.assertTrue(maintenance.last_command['ok'])
        self.command(maintenance, 'inspect', 'inspect')
        self.assertEqual(len(maintenance.fault['history']), 2)
        model.advance(5000); maintenance.step()
        self.assertEqual(maintenance.fault['stage'], 'INSPECTING')
        self.assertEqual(model.operations[0].elapsed_ms, frozen)
        self.command(maintenance, 'repair', 'repair')
        model.advance(1900); maintenance.step()
        self.assertEqual(model.cell('ASM-01').state, CellState.DOWN)
        model.advance(100); maintenance.step()
        self.assertEqual(model.cell('ASM-01').state, CellState.RUNNING)
        self.assertEqual(model.operations[0].elapsed_ms, frozen)
        self.assertEqual(maintenance.fault['stage'], 'RESOLVED')
        model.advance(3000); maintenance.step()
        self.assertEqual(model.operations[0].elapsed_ms, 4000)
        self.assertEqual(len(maintenance.fault['history']), 4)
        self.command(maintenance, 'repair', 'duplicate')
        self.assertFalse(maintenance.last_command['ok'])

    def test_five_body_supply_run_drains_after_manual_repair(self):
        model = FactoryModel(supply_configuration(traffic_configuration(RunConfiguration.from_path())), quality_results=('PASS',))
        change = lambda fn, *args: fn(*args)
        driver = NormalDriver(model, 5)
        maintenance = ManualMaintenance(model, change)
        driver.initialize(change)
        detected_at = None
        for _ in range(9000):
            model.tick(); maintenance.step(); driver.enter_waiting(change)
            fault = maintenance.fault
            if fault and fault['stage'] == 'DETECTED':
                if detected_at is None: detected_at = model.sim_elapsed_ms
                if model.sim_elapsed_ms - detected_at >= 5000:
                    self.command(maintenance, 'inspect', 'inspect')
            elif fault and fault['stage'] == 'INSPECTING':
                self.command(maintenance, 'repair', 'repair')
            if driver.drained(): break
        else: self.fail('Traffic simulation failed to drain after repair')
        self.assertEqual(maintenance.fault['stage'], 'RESOLVED')
        self.assertEqual(len(model.operations), 15)
        self.assertTrue(all(body.location.location_type == LocationType.RESULT for body in model.bodies))
        self.assertTrue(all(body.inspection_result.value == 'PASS' for body in model.bodies))
