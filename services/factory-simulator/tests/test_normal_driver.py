import unittest
from factory_simulator.connected_demo import NormalDriver
from factory_simulator.model import FactoryModel
from factory_simulator.run_configuration import RunConfiguration


class NormalDriverTests(unittest.TestCase):
    def test_normal_bodies_complete_with_unique_pass_results_and_no_cell_conflicts(self):
        for count in (1, 3):
            with self.subTest(count=count):
                model = FactoryModel(RunConfiguration.from_path(), quality_results=('PASS',))
                driver = NormalDriver(model, count)
                change = lambda method, *args: method(*args)
                driver.initialize(change)
                for _ in range(10000):
                    model.tick()
                    driver.enter_waiting(change)
                    if driver.drained():
                        break
                self.assertTrue(driver.drained())
                bodies = model.snapshot()['bodies']
                self.assertEqual(len(bodies), count)
                for body in bodies:
                    self.assertEqual(body['locationId'], 'GOOD')
                    self.assertEqual(body['inspectionResult'], 'PASS')
                    self.assertEqual(body['completedCellIds'], ['ASM-01', 'ASM-02', 'QC-01'])
                kinds = [event.to_dict()['eventType'] for event in model.events]
                self.assertEqual(kinds.count('BODY_REGISTERED'), count)
                self.assertEqual(kinds.count('OPERATION_COMPLETED'), 3 * count)
                self.assertEqual(kinds.count('INSPECTION_COMPLETED'), count)
                self.assertEqual(kinds.count('TRANSPORT_COMPLETED'), 4 * count)
