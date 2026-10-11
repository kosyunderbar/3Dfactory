"""The actual launcher flags must select the promised body count and recovery mode."""
import unittest
from unittest.mock import patch
from factory_simulator.__main__ import main


class ScenarioSelectionTests(unittest.TestCase):
    def test_console_scenario_flags_choose_one_three_normal_and_five_manual(self):
        for flag, count, manual in [('--connected-demo', 1, False),
                                    ('--connected-three-demo', 3, False),
                                    ('--connected-maintenance-demo', 5, True)]:
            with self.subTest(flag=flag), \
                 patch('sys.argv', ['factory_simulator', flag, '--traffic']), \
                 patch.dict('os.environ', {'INGESTION_TCP_HOST': '127.0.0.1', 'INGESTION_TCP_PORT': '9090'}), \
                 patch('factory_simulator.__main__.signal.signal'), \
                 patch('factory_simulator.__main__.run_connected', return_value=0) as run:
                self.assertEqual(main(), 0)
                self.assertEqual(run.call_args.kwargs['body_count'], count)
                self.assertEqual(run.call_args.kwargs['manual_maintenance'], manual)
