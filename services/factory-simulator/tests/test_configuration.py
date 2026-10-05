import unittest
from factory_simulator.configuration import Settings


class ConfigurationTests(unittest.TestCase):
    def test_startup_configuration_and_required_failures(self):
        settings = Settings.from_environment({"INGESTION_TCP_HOST": "ingestion-service", "INGESTION_TCP_PORT": "9090"})
        self.assertEqual((settings.ingestion_host, settings.ingestion_port), ("ingestion-service", 9090))
        for invalid in ({}, {"INGESTION_TCP_HOST": "host"},
                        {"INGESTION_TCP_HOST": "host", "INGESTION_TCP_PORT": "65536"}):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                Settings.from_environment(invalid)
