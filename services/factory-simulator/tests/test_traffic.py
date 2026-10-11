import unittest
from dataclasses import replace
from math import hypot
from factory_simulator.run_configuration import RunConfiguration
from factory_simulator.model import FactoryModel
from factory_simulator.p0_demo import P0Driver
from factory_simulator.traffic import traffic_configuration, expanded, intersects, plan_path, validate_positions, segment_distance


class TrafficTests(unittest.TestCase):
    def setUp(self):
        self.configuration = traffic_configuration(RunConfiguration.from_path(), version=1)

    def test_completed_cell_preempts_empty_input_pickup_and_all_bodies_finish(self):
        from factory_simulator.connected_demo import NormalDriver
        model = FactoryModel(self.configuration, quality_results=('PASS',))
        driver = NormalDriver(model, 3)
        change = lambda f,*a:f(*a)
        driver.initialize(change)
        completed_at = picked_at = None
        cancellations = set()
        for _ in range(3000):
            before = {v.vehicle_id: v for v in model.vehicles}
            model.tick(); driver.enter_waiting(change)
            body = model.body('body-00001')
            if completed_at is None and 'ASM-01' in body.completed_cell_ids:
                completed_at = model.sim_elapsed_ms
                trip = model.transport(body.transport_id)
                self.assertEqual((trip.vehicle_id, trip.source.location_id), ('AGV-001', 'ASM-01'))
                self.assertEqual(model.body('body-00003').location.location_id, 'BODY-IN')
                self.assertNotIn('body-00003', model._dispatch_holds)
            if completed_at is not None and picked_at is None and body.location.location_type == 'VEHICLE':
                picked_at = model.sim_elapsed_ms
            for trip in model._transports.values():
                if trip.cancel_reason == 'PRIORITY_REDISPATCH' and trip.transport_id not in cancellations:
                    cancellations.add(trip.transport_id)
                    self.assertEqual(before[trip.vehicle_id].state.value, 'TO_PICKUP')
                    self.assertIsNone(trip.started_at)
                    self.assertEqual(trip.source.location_type, 'INPUT')
            vehicles = model.vehicles
            for i,a in enumerate(vehicles):
                for b in vehicles[i+1:]:
                    aa,bb = before[a.vehicle_id],before[b.vehicle_id]
                    self.assertGreaterEqual(segment_distance((aa.x-bb.x,aa.y-bb.y),(a.x-b.x,a.y-b.y),(0,0)),51-1e-7)
            if driver.drained(): break
        self.assertIsNotNone(picked_at)
        self.assertLessEqual(picked_at-completed_at, 3000, 'completed ASM-01 must not wait behind new input')
        self.assertTrue(cancellations)
        self.assertTrue(driver.drained(), 'deferred input must still finish')
        self.assertTrue(all(b.location.location_id == 'GOOD' for b in model.bodies))
        events = [e.to_dict() for e in model.events]
        for tid in cancellations:
            released = next(e for e in events if e['eventType']=='SLOT_RELEASED' and e['payload']['transportId']==tid)
            cancelled = next(e for e in events if e['eventType']=='TRANSPORT_CANCELLED' and e['payload']['transportId']==tid)
            self.assertLess(released['sourceSeq'], cancelled['sourceSeq'])
        self.assertFalse(any(e['eventType']=='SCENARIO_CHANGED' for e in events))

    def test_reservation_releases_passed_corners_but_preserves_current_tick(self):
        from factory_simulator.motion import Motion
        from factory_simulator.logistics import VehicleState
        from factory_simulator.traffic import remaining_path
        motion = Motion(VehicleState.RETURNING, ((0,0),(100,0),(100,100)),2000,1500)
        self.assertEqual(remaining_path(motion), ((100,50),(100,100)))
        model = FactoryModel(self.configuration)
        body = model.register_body()
        trip = model.assign_transport(body.body_id)
        model.start_transport(trip.transport_id)
        model.tick()
        vehicle = model._vehicles['AGV-001']
        self.assertEqual(model._traffic_tick_paths['AGV-001'][0], (0,220))
        self.assertEqual(model._traffic_reserved['AGV-001'][0], (vehicle.x,vehicle.y))
        self.assertNotEqual(model._traffic_reserved['AGV-001'][0], (0,220))

    def test_p0_drains_with_swept_clearance_pause_and_all_observation_stages(self):
        model = FactoryModel(self.configuration, quality_results=('FAIL', 'PASS'))
        driver = P0Driver(model)
        change = lambda f, *args: f(*args)
        driver.initialize(change)
        policy = self.configuration.factory['traffic']
        seen = []
        detours = 0
        waits = 0
        for tick in range(6000):
            before = {v.vehicle_id: v for v in model.vehicles}
            stage = driver.step(change)
            while stage:
                seen.append(stage)
                stage = driver.after(stage, change)
            validate_positions(policy, model._vehicles)
            # Swept movement, not only endpoint checks: chassis cannot tunnel.
            for vehicle in model.vehicles:
                old = before[vehicle.vehicle_id]
                self.assertLessEqual(hypot(vehicle.x-old.x, vehicle.y-old.y), 3.750001)
                for obstacle in policy['obstacles']:
                    self.assertFalse(intersects((old.x, old.y), (vehicle.x, vehicle.y), expanded(obstacle, policy['vehicleRadius'])))
            vehicles = model.vehicles
            for i, a in enumerate(vehicles):
                for b in vehicles[i+1:]:
                    aa, bb = before[a.vehicle_id], before[b.vehicle_id]
                    self.assertGreaterEqual(segment_distance((aa.x-bb.x, aa.y-bb.y), (a.x-b.x, a.y-b.y), (0,0)), 48)
            for path in model._traffic_reserved.values():
                detours += len(path) > 2
                for a, b in zip(path, path[1:]):
                    self.assertFalse(any(intersects(a,b,expanded(r,27)) for r in policy['obstacles']))
            waits += len(model._traffic_waiting)
            if tick == 200:
                model.pause()
                frozen = [(v.x,v.y) for v in model.vehicles]
                for _ in range(20): model.tick()
                self.assertEqual(frozen, [(v.x,v.y) for v in model.vehicles])
                model.resume()
            if driver.drained(): break
        self.assertTrue(driver.drained(), 'traffic must not deadlock')
        self.assertEqual(seen, ['FULL_RESERVED','FULL_IN_TRANSIT','FULL_ARRIVED','CELL_DOWN','SLOT_RELEASED'])
        self.assertGreater(detours, 0)
        self.assertGreater(waits, 0)
        for v in model.vehicles:
            home = next(c['initialPosition'] for c in self.configuration.factory['vehicles'] if c['vehicleId']==v.vehicle_id)
            self.assertEqual((v.x,v.y), (home['x'],home['y']))

    def test_obstacle_detour_no_path_and_invalid_start(self):
        policy = dict(vehicleRadius=24,clearance=3,bounds=dict(minX=-100,minY=-100,maxX=300,maxY=300))
        obstacle = (50, -20, 100, 120)
        path = plan_path((0,0),(150,0),policy,[obstacle])
        self.assertGreater(len(path), 2)
        self.assertTrue(all(not intersects(a,b,obstacle) for a,b in zip(path,path[1:])))
        self.assertIsNone(plan_path((0,0),(75,0),policy,[obstacle]))
        self.assertIsNone(plan_path((0,0),(150,0),policy,[(50,-100,100,300)]))
        raw = self.configuration.to_dict()
        raw['config']['vehicles'][1]['initialPosition'] = raw['config']['vehicles'][0]['initialPosition']
        with self.assertRaises(ValueError): RunConfiguration.from_dict(raw)
        raw = self.configuration.to_dict();raw['config']['traffic']['vehicleRadius']=1
        with self.assertRaises(ValueError): RunConfiguration.from_dict(raw)

    def test_empty_vehicle_swap_yields_and_cannot_cross(self):
        from factory_simulator.motion import Motion
        from factory_simulator.logistics import VehicleState
        model = FactoryModel(self.configuration)
        a,b = model.vehicles[:2]
        for v, goal in ((a,b),(b,a)):
            model._vehicles[v.vehicle_id] = replace(v,state=VehicleState.RETURNING)
            model._motions[v.vehicle_id] = Motion(VehicleState.RETURNING, ((v.x,v.y),(goal.x,goal.y)),100)
        yielded = False
        for _ in range(1200):
            model.tick()
            yielded |= bool(model._traffic_yield)
            validate_positions(self.configuration.factory['traffic'],model._vehicles)
            if not model._motions: break
        self.assertTrue(yielded)
        self.assertFalse(model._motions, 'swapping goals must resolve with a pull-over')
        self.assertEqual((model._vehicles[a.vehicle_id].x,model._vehicles[a.vehicle_id].y),(b.x,b.y))

    def test_capacity_variants_and_coarse_ticks_do_not_deadlock(self):
        for capacity, tick_ms in ((2,100),(4,500)):
            raw = RunConfiguration.from_path().to_dict()
            raw['config']['tickMs'] = tick_ms
            for bay in raw['config']['buffers']:
                bay['capacity'] = capacity
                bay['slotIds'] = [f"{bay['bufferId']}-S{i+1}" for i in range(capacity)]
            model = FactoryModel(traffic_configuration(RunConfiguration.from_dict(raw),version=2),quality_results=('PASS',))
            driver = P0Driver(model);change = lambda f,*args:f(*args);driver.initialize(change)
            for _ in range(6000):
                stage = driver.step(change)
                while stage: stage = driver.after(stage,change)
                if driver.drained(): break
            self.assertTrue(driver.drained(), (capacity,tick_ms))

    def test_cancel_at_pickup_clears_the_dock_for_the_other_vehicle(self):
        from factory_simulator.connected_demo import NormalDriver
        model = FactoryModel(self.configuration,quality_results=('PASS',))
        model.register_body();model.register_body();model.redispatch()
        for _ in range(200):
            model.tick()
            vehicle = next((v for v in model.vehicles if v.state.value=='LOADING'),None)
            if vehicle: break
        self.assertIsNotNone(vehicle)
        held = model.transport(vehicle.transport_id).body_id
        model.cancel_transport(vehicle.transport_id)
        self.assertEqual(model._vehicles[vehicle.vehicle_id].state.value,'RETURNING')
        other = next(b.body_id for b in model.bodies if b.body_id != held)
        driver = NormalDriver(model);change = lambda f,*a:f(*a)
        for _ in range(3000):
            model.tick();driver.enter_waiting(change)
            if model.body(other).location.location_type.value=='RESULT' and all(v.state.value=='IDLE' for v in model.vehicles):break
        self.assertEqual(model.body(other).location.location_id,'GOOD')
        self.assertTrue(all(v.state.value=='IDLE' for v in model.vehicles))

    def test_wide_aisle_has_room_for_passing_and_keeps_docks_in_sync(self):
        policy = self.configuration.factory['traffic']
        cells = [r for r in policy['obstacles'] if r['id'] in ('ASM-01','ASM-02','QC-01')]
        bays = [r for r in policy['obstacles'] if r['id'].startswith('BAY-')]
        front, back = max(r['maxY'] for r in cells), min(r['minY'] for r in bays)
        radius, gap = policy['vehicleRadius'], policy['clearance']
        self.assertGreater(back-front, 2*(radius+gap) + 2*radius+gap)
        boxes = [expanded(r,radius+gap) for r in policy['obstacles']]
        y = (front+back)/2
        self.assertEqual(plan_path((0,y),(700,y),policy,boxes),((0,y),(700,y)))
        locations = {l['locationId']:l for l in self.configuration.factory['locations']}
        for route in self.configuration.factory['routes']:
            for endpoint,index in (('source',0),('destination',-1)):
                loc=locations[route[endpoint]['locationId']]
                self.assertEqual((route['points'][index]['x'],route['points'][index]['y']),(loc['x'],loc['y']))
        # Never move an already-published layout a second time.
        self.assertIs(traffic_configuration(self.configuration),self.configuration)
