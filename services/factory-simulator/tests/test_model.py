from dataclasses import FrozenInstanceError
from datetime import datetime, timezone
import json
import unittest

from factory_simulator.model import FactoryModel, Location, LocationType, ModelError
from factory_simulator.run_configuration import DEFAULT_CONFIG, RunConfiguration

NOW = datetime(2026, 10, 5, 0, 0, 0, 123000, tzinfo=timezone.utc)
INPUT = Location(LocationType.INPUT, 'BODY-IN')
CELL = Location(LocationType.CELL, 'ASM-01')


class ModelFoundationTests(unittest.TestCase):
    def test_configuration_accepts_p0_bounds_and_rejects_invalid_structure(self):
        data = json.loads(DEFAULT_CONFIG.read_text())
        for capacity in (2, 4):
            candidate = json.loads(DEFAULT_CONFIG.read_text())
            for buffer in candidate['config']['buffers']:
                buffer['capacity'] = capacity
                buffer['slotIds'] = [f"{buffer['bufferId']}-S{i}" for i in range(1, capacity + 1)]
            RunConfiguration.from_dict(candidate)
        changes = [('capacity', lambda d: d['config']['buffers'][0].update(capacity=1)),
                   ('slots', lambda d: d['config']['buffers'][0].update(slotIds=['BAY-ASM-01-S1'])),
                   ('tick', lambda d: d['config'].update(snapshotIntervalMs=150)),
                   ('boolean', lambda d: d.update(seed=True)),
                   ('route', lambda d: d['config']['routes'][0]['points'][0].update(x=999)),
                   ('unknown', lambda d: d['config']['equipment'][0].update(cellId='ASM-99'))]
        for label, change in changes:
            with self.subTest(label=label), self.assertRaises(ValueError):
                candidate = json.loads(DEFAULT_CONFIG.read_text())
                change(candidate)
                RunConfiguration.from_dict(candidate)
        config = RunConfiguration.from_dict(data)
        data['config']['buffers'][0]['capacity'] = 99
        self.assertEqual(config.factory['buffers'][0]['capacity'], 3)
        with self.assertRaises(TypeError):
            config.factory['buffers'][0]['capacity'] = 4

    def test_registration_identity_mapping_limits_and_run_isolation(self):
        data = json.loads(DEFAULT_CONFIG.read_text())
        data['config']['maxBodies'] = 2
        config = RunConfiguration.from_dict(data)
        model = FactoryModel(config, clock=lambda: NOW)
        body = model.register_body(body_id='body-00001', tag_id='tag-00009')
        self.assertEqual(model.body_by_tag('tag-00009'), body)
        self.assertEqual((body.location, body.created_at), (INPUT, '2026-10-05T00:00:00.123Z'))
        self.assertRegex(model.run_id, r'^run-20261005-[0-9a-f]{12}4[0-9a-f]{3}[89ab][0-9a-f]{15}$')
        for arguments in ({'body_id': 'body-00001'}, {'tag_id': 'tag-00009'}, {'model_code': 'lower-case'}):
            with self.subTest(arguments=arguments), self.assertRaises(ModelError):
                model.register_body(**arguments)
        second = model.register_body()
        self.assertEqual((second.body_id, second.tag_id), ('body-00002', 'tag-00002'))
        with self.assertRaises(ModelError):
            model.register_body()
        other = FactoryModel(config, clock=lambda: NOW)
        self.assertNotEqual(other.run_id, model.run_id)
        self.assertEqual(other.register_body().body_id, 'body-00001')
        self.assertEqual(len(model.bodies), 2)
        with self.assertRaises(FrozenInstanceError):
            body.tag_id = 'tag-00002'
        with self.assertRaises(FrozenInstanceError):
            body.location = CELL

    def test_single_owner_transfer_checks_before_commit_and_fixture_boundaries(self):
        config = RunConfiguration.from_path()
        normal = FactoryModel(config, clock=lambda: NOW)
        with self.assertRaises(ModelError):
            normal.register_fixture_body(CELL)
        model = FactoryModel(config, clock=lambda: NOW, allow_initial_fixtures=True)
        body = model.register_body()
        blocker = model.register_fixture_body(CELL)
        before = model.inspect()
        with self.assertRaises(ModelError):
            model._transfer_ownership(body.body_id, INPUT, CELL)
        with self.assertRaises(ModelError):
            model.register_fixture_body(CELL)
        for location in (Location(LocationType.BUFFER, 'BAY-ASM-01'),
                         Location(LocationType.BUFFER, 'BAY-ASM-01', 'BAY-ASM-01-S4'),
                         Location(LocationType.CELL, 'ASM-99'),
                         Location(LocationType.VEHICLE, 'AMR-001')):
            with self.subTest(location=location), self.assertRaises(ModelError):
                model._transfer_ownership(body.body_id, INPUT, location)
        self.assertEqual(model.inspect(), before)
        agv = Location(LocationType.VEHICLE, 'AGV-001')
        moved = model._transfer_ownership(blocker.body_id, CELL, agv)
        self.assertEqual(model.bodies_at(LocationType.CELL, 'ASM-01'), ())
        self.assertEqual(model.bodies_at(LocationType.VEHICLE, 'AGV-001'), (moved,))
        with self.assertRaises(ModelError):
            model._transfer_ownership(body.body_id, INPUT, agv)
        bay = Location(LocationType.BUFFER, 'BAY-ASM-01', 'BAY-ASM-01-S1')
        model._transfer_ownership(blocker.body_id, agv, bay)
        with self.assertRaises(ModelError):
            model.register_fixture_body(bay)
        with self.assertRaises(ModelError):
            model._transfer_ownership(blocker.body_id, CELL, INPUT)
        self.assertEqual(model.body(blocker.body_id).location, bay)
        self.assertEqual(len(model.bodies_at(LocationType.INPUT, 'BODY-IN')), 1)
        self.assertEqual(model.bodies_at(LocationType.VEHICLE, 'AGV-001'), ())
        # Read descriptions are detached: a caller cannot add a second physical location.
        description = model.inspect()
        description['bodies'][0]['locationId'] = 'ASM-02'
        self.assertEqual(model.body(body.body_id).location, INPUT)
