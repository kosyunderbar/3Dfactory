import unittest
from math import hypot
from factory_simulator.model import FactoryModel
from factory_simulator.run_configuration import RunConfiguration
from factory_simulator.traffic import traffic_configuration, validate_positions, segment_distance, intersects, expanded
from factory_simulator.connected_demo import NormalDriver
from factory_simulator.p0_demo import P0Driver


class DirectDeliveryTests(unittest.TestCase):
    def model(self, slow=False):
        raw = RunConfiguration.from_path().to_dict()
        if slow:
            for e in raw['config']['equipment']: e['workDurationMs'] = 30000
        return FactoryModel(traffic_configuration(RunConfiguration.from_dict(raw),version=2),quality_results=('PASS',))

    def advance(self, model, driver, stages=None):
        before = {v.vehicle_id:v for v in model.vehicles}
        bodies = {b.body_id:b for b in model.bodies}
        trips = {t.transport_id:t for t in model.active_transports}
        change = lambda f,*a:f(*a)
        if isinstance(driver,P0Driver):
            stage = driver.step(change)
            while stage:
                stages.append(stage); stage = driver.after(stage,change)
        else:
            model.tick(); driver.enter_waiting(change)
        policy = model.configuration.factory['traffic']
        validate_positions(policy,model._vehicles)
        for v in model.vehicles:
            old = before[v.vehicle_id]
            self.assertLessEqual(hypot(v.x-old.x,v.y-old.y),3.750001)
            for o in policy['obstacles']:
                self.assertFalse(intersects((old.x,old.y),(v.x,v.y),expanded(o,policy['vehicleRadius'])))
        for i,a in enumerate(model.vehicles):
            for b in model.vehicles[i+1:]:
                aa,bb = before[a.vehicle_id],before[b.vehicle_id]
                self.assertGreaterEqual(segment_distance((aa.x-bb.x,aa.y-bb.y),(a.x-b.x,a.y-b.y),(0,0)),63-1e-7)
        destinations = [t.destination.location_id for t in model.active_transports if t.destination.location_type=='CELL']
        self.assertEqual(len(destinations),len(set(destinations)))
        for b in model.bodies:
            old = bodies[b.body_id]
            if b.location.location_type=='CELL' and old.location.location_type!='CELL':
                self.assertEqual(old.location.location_type,'VEHICLE','no instantaneous Bay -> CELL transfer')
                trip = trips[old.transport_id]
                vehicle = model._vehicles[trip.vehicle_id]
                self.assertEqual(trip.destination.location_id,b.location.location_id)
                self.assertEqual((vehicle.x,vehicle.y),model._point(b.location))
            if old.location.location_type=='BUFFER' and b.location!=old.location:
                self.assertEqual(b.location.location_type,'VEHICLE')
                vehicle = model._vehicles[b.location.location_id]
                self.assertEqual((vehicle.x,vehicle.y),model._point(old.location))

    def test_empty_cells_receive_directly_at_same_dock_used_for_pickup(self):
        m=self.model();d=NormalDriver(m,1);d.initialize(lambda f,*a:f(*a))
        for _ in range(2500):
            self.advance(m,d)
            if d.drained():break
        self.assertTrue(d.drained())
        trips=[t for t in m.transports if t.cargo_type=='BODY']
        self.assertEqual([(t.source.location_id,t.destination.location_id) for t in trips],
                         [('BODY-IN','ASM-01'),('ASM-01','ASM-02'),('ASM-02','QC-01'),('QC-01','GOOD')])
        self.assertFalse(any(e.to_dict()['eventType'] in ('SLOT_RESERVED','SLOT_RELEASED') for e in m.events))

    def test_busy_cells_use_bays_and_waiting_bodies_are_physically_collected(self):
        for driver_type in (NormalDriver,P0Driver):
            m=self.model(slow=driver_type==NormalDriver);d=NormalDriver(m,3) if driver_type==NormalDriver else P0Driver(m)
            d.initialize(lambda f,*a:f(*a));stages=[]
            for _ in range(7000):
                self.advance(m,d,stages)
                if d.drained():break
            self.assertTrue(d.drained(),driver_type)
            self.assertTrue(any(t.source.location_type=='BUFFER' and t.destination.location_type=='CELL' for t in m.transports))
            releases=[e.to_dict() for e in m.events if e.to_dict()['eventType']=='SLOT_RELEASED']
            self.assertTrue(any(e['payload']['reason']=='BODY_PICKED_UP' for e in releases))
            if driver_type==P0Driver:
                self.assertEqual(stages,['FULL_RESERVED','FULL_IN_TRANSIT','FULL_ARRIVED','CELL_DOWN','SLOT_RELEASED'])

    def test_failed_inbound_cell_retains_cargo_until_recovery(self):
        m=self.model();d=NormalDriver(m,1);d.initialize(lambda f,*a:f(*a))
        for _ in range(1000):
            m.tick()
            if m._vehicles['AGV-001'].state=='MOVING':break
        m.fail_cell('ASM-01')
        for _ in range(200):m.tick()
        self.assertEqual(m.body('body-00001').location.location_type,'VEHICLE')
        self.assertEqual(m._vehicles['AGV-001'].state,'UNLOADING')
        self.assertEqual(m.cell('ASM-01').state,'DOWN')
        m.pause();snapshot=m.snapshot();m.tick();self.assertEqual(m.snapshot()['simElapsedMs'],snapshot['simElapsedMs']);m.resume()
        m.recover_cell('ASM-01')
        for _ in range(2500):
            self.advance(m,d)
            if d.drained():break
        self.assertTrue(d.drained())

    def test_cell_freed_during_pickup_is_rechecked_before_loading(self):
        m=self.model();d=NormalDriver(m,3);d.initialize(lambda f,*a:f(*a))
        for _ in range(3000):
            self.advance(m,d)
            if d.drained():break
        self.assertTrue(d.drained())
        promoted=[t for t in m.transports if t.cancel_reason=='DIRECT_DELIVERY_AVAILABLE']
        self.assertTrue(promoted)
        for old in promoted:
            self.assertIsNone(old.started_at)
            replacement=next(t for t in m.transports if t.transport_id>old.transport_id and t.body_id==old.body_id
                             and t.source==old.source and t.destination.location_type=='CELL')
            self.assertEqual(replacement.status,'COMPLETED')
        self.assertFalse(any(t.body_id=='body-00002' and t.destination.location_id=='BAY-ASM-01' and t.status=='COMPLETED' for t in m.transports))

    def test_cancelling_direct_pickup_releases_cell_without_bay_slot_event(self):
        m=self.model();b=m.register_body();decision=m.assign_transport(b.body_id);m.start_transport(decision.transport_id)
        self.assertFalse(m._cell_accepts_delivery('ASM-01'))
        m.cancel_transport(decision.transport_id)
        self.assertTrue(m._cell_accepts_delivery('ASM-01'))
        self.assertFalse(any(e.to_dict()['eventType']=='SLOT_RELEASED' for e in m.events))
