import unittest
from dataclasses import replace
from datetime import datetime, timezone
from math import hypot, pi, cos, sin
from factory_simulator.model import FactoryModel
from factory_simulator.logistics import VehicleState
from factory_simulator.run_configuration import RunConfiguration
from factory_simulator.traffic import traffic_configuration, expanded, intersects, segment_distance
from factory_simulator.motion import Motion, profiled_motion, angle_delta
from factory_simulator import lane_traffic
from factory_simulator.connected_demo import NormalDriver
from factory_simulator.p0_demo import P0Driver


class LaneTrafficTests(unittest.TestCase):
    version=3
    def model(self, capacity=3, tick=100):
        raw=RunConfiguration.from_path().to_dict();raw['config']['tickMs']=tick
        for b in raw['config']['buffers']:
            b['capacity']=capacity;b['slotIds']=[b['bufferId']+f'-S{i+1}' for i in range(capacity)]
        return FactoryModel(traffic_configuration(RunConfiguration.from_dict(raw),version=self.version),quality_results=('PASS','FAIL'),clock=lambda:datetime(2026,10,10,tzinfo=timezone.utc))

    def check_step(self,m,step):
        before=dict(m._vehicles); motions=dict(m._motions); headings=dict(m._traffic_heading)
        speeds={v:motion.pose()[3] if motion.segments else 0 for v,motion in motions.items()}
        step()
        dt=m.configuration.factory['tickMs'];policy=m.configuration.factory['traffic']
        for v in m.vehicles:
            old=before[v.vehicle_id];a=(old.x,old.y);b=(v.x,v.y)
            self.assertLessEqual(hypot(v.x-old.x,v.y-old.y),.0375*dt+1e-7)
            self.assertLessEqual(abs(angle_delta(headings.get(v.vehicle_id,0),m._traffic_heading.get(v.vehicle_id,0))),pi/1500*dt+1e-7)
            for o in policy['obstacles']:self.assertFalse(intersects(a,b,expanded(o,33)))
            current=m._motions.get(v.vehicle_id)
            speed=current.pose()[3] if current and current.segments else 0
            self.assertLessEqual(abs(speed-speeds.get(v.vehicle_id,0)),.000075*dt+1e-7)
            if current and current.segments:
                for x,y in zip(current.points,current.points[1:]):
                    if self.version==3:
                        self.assertTrue(x==y or y in m._lane_graph[x], 'every route edge must be an allowed lane')
                    else:
                        nodes=sorted((p for p in m._lane_graph if segment_distance(x,y,p)<1e-8),key=lambda p:hypot(p[0]-x[0],p[1]-x[1]))
                        self.assertTrue(all(b in m._lane_graph[a] for a,b in zip(nodes,nodes[1:])), 'compressed straight leg stays on allowed lanes')
                previous=motions.get(v.vehicle_id)
                if previous and previous.segments and current.points!=previous.points:
                    self.assertLess(speeds[v.vehicle_id],1e-8,'route change only from rest')
        for i,a in enumerate(m.vehicles):
            for b in m.vehicles[i+1:]:
                aa,bb=before[a.vehicle_id],before[b.vehicle_id]
                self.assertGreaterEqual(segment_distance((aa.x-bb.x,aa.y-bb.y),(a.x-b.x,a.y-b.y),(0,0)),63-1e-7)
        self.assertTrue(all(len(p)==2 for p in m._traffic_reserved.values()))

    def test_normal_and_fault_capacity_variants_complete_with_swept_safety(self):
        for count,capacity,tick,parts in ((1,3,100,False),(3,3,100,True),(0,2,100,False),(0,4,500,True)):
            with self.subTest(count=count,capacity=capacity,tick=tick):
                m=self.model(capacity,tick);d=NormalDriver(m,count) if count else P0Driver(m)
                change=lambda f,*a:f(*a);d.initialize(change);stages=[]
                if parts and count:
                    decision=m.assign_parts('ASM-01');m.start_transport(decision.transport_id)
                def step():
                    if count:m.tick();d.enter_waiting(change)
                    else:
                        stage=d.step(change)
                        while stage:stages.append(stage);stage=d.after(stage,change)
                for n in range(16000):
                    self.check_step(m,step)
                    if n==100:
                        m.pause();frozen=m.snapshot();m.tick();self.assertEqual(frozen,m.snapshot());m.resume()
                    if d.drained():break
                self.assertTrue(d.drained(),(count,capacity,tick,m._traffic_waiting,m._traffic_yield))
                if not count:self.assertEqual(stages,['FULL_RESERVED','FULL_IN_TRANSIT','FULL_ARRIVED','CELL_DOWN','SLOT_RELEASED'])
                if parts:self.assertTrue(all(t.status=='COMPLETED' for t in m.transports if t.cargo_type=='PARTS'))
                m.finish_run()

    def test_profile_turns_in_place_and_bounds_acceleration_at_short_and_long_legs(self):
        for tick in (100,500):
            m=profiled_motion(VehicleState.MOVING,((0,0),(2,0),(2,150)),pi,tick)
            previous=(0,0,pi,0)
            for elapsed in range(0,m.required_ms+1,10):
                p=replace(m,elapsed_ms=elapsed).pose()
                self.assertLessEqual(abs(p[3]-previous[3]),.000075*10+1e-8)
                turn=abs(angle_delta(previous[2],p[2]))
                self.assertLessEqual(turn,pi/1500*10+1e-8)
                if turn>1e-8:self.assertEqual(p[:2],previous[:2])
                self.assertLessEqual(p[3],.037500001);previous=p
            self.assertEqual(m.points[-1],replace(m,elapsed_ms=m.required_ms).position())

    def test_no_mid_edge_return_preemption_or_cancellation(self):
        m=self.model();b=m.register_body();decision=m.assign_transport(b.body_id);m.start_transport(decision.transport_id)
        for _ in range(100):
            m.tick()
            if m._motions['AGV-001'].segments and m._motions['AGV-001'].pose()[3]>0:break
        snapshot=m.snapshot()
        with self.assertRaisesRegex(ValueError,'stopped lane node'):m.cancel_transport(decision.transport_id)
        self.assertEqual(snapshot,m.snapshot())
        v=m._vehicles['AGV-001'];m._vehicles[v.vehicle_id]=replace(v,state=VehicleState.RETURNING,transport_id=None)
        self.assertNotIn(v.vehicle_id,[v.vehicle_id for v in m._available_agvs()])

    def test_swapping_parking_places_resolves_on_declared_holding_nodes(self):
        m=self.model();a,b=m.vehicles[:2]
        for v,goal in ((a,b),(b,a)):
            m._vehicles[v.vehicle_id]=replace(v,state=VehicleState.RETURNING)
            m._motions[v.vehicle_id]=Motion(VehicleState.RETURNING,((v.x,v.y),(goal.x,goal.y)),100)
        for _ in range(4000):
            self.check_step(m,m.tick)
            if not m._motions:break
        self.assertFalse(m._motions,'parking swap must not deadlock')
        self.assertEqual((m._vehicles[a.vehicle_id].x,m._vehicles[a.vehicle_id].y),(b.x,b.y))

    def test_invalid_or_disconnected_lanes_are_rejected(self):
        for mutate in (lambda c:c['traffic']['lanes'].clear(),
                       lambda c:c['traffic']['lanes'][0]['end'].update(x=155,y=21),
                       lambda c:c['traffic']['holdingPoints'].append(dict(x=999,y=999))):
            data=self.model().configuration.to_dict();mutate(data['config'])
            with self.assertRaises(ValueError):RunConfiguration.from_dict(data)


class EfficientTrafficTests(LaneTrafficTests):
    version=4

    def test_short_dock_exit_reverses_without_turn_and_straight_lane_has_no_extra_stops(self):
        motion=profiled_motion(VehicleState.RETURNING,((150,100),(150,180)),-pi/2,100,allow_reverse=True)
        self.assertEqual(motion.segments[0][0],0)
        self.assertLessEqual(motion.segments[0][5],.01875)
        self.assertEqual(lane_traffic.compress(((0,180),(150,180),(200,180),(350,180),(350,100))),((0,180),(350,180),(350,100)))

    def check_step(self,m,step):
        before=dict(m._vehicles)
        super().check_step(m,step)
        if m._final_returning:
            self.assertFalse(m.active_transports)
            self.assertTrue(all(b.location.location_type.value=='RESULT' for b in m.bodies))
            for vehicle_id in m._final_returning:
                points=m._motions[vehicle_id].points
                self.assertIn((845,650),points);self.assertIn((0,650),points)
        for v in m.vehicles:
            old=before[v.vehicle_id]
            dx,dy=v.x-old.x,v.y-old.y
            if old.state==VehicleState.MOVING and hypot(dx,dy)>1e-8:
                heading=m._traffic_heading[v.vehicle_id]
                self.assertGreater(dx*cos(heading)+dy*sin(heading),0, 'loaded cargo must travel forwards, including yield/reroute legs')

    def test_loaded_profile_cannot_reverse_even_if_caller_requests_it(self):
        motion=profiled_motion(VehicleState.MOVING,((150,100),(150,180)),-pi/2,100,allow_reverse=True)
        self.assertGreater(motion.segments[0][0],0)
        self.assertAlmostEqual(motion.segments[0][4],pi/2)
        for elapsed in range(0,motion.required_ms+1,10):
            x,y,heading,speed=replace(motion,elapsed_ms=elapsed).pose()
            if speed>0:self.assertGreater(sin(heading),0)
            elif elapsed<motion.segments[0][0]:self.assertEqual((x,y),(150,100))
        m=self.model()
        self.assertFalse(lane_traffic.can_reverse_departure(m,'AGV-001',motion,((150,100),(150,180))))
        empty=replace(motion,phase=VehicleState.RETURNING)
        self.assertTrue(lane_traffic.can_reverse_departure(m,'AGV-001',empty,((150,100),(150,180))))
        self.assertFalse(lane_traffic.can_reverse_departure(m,'AGV-001',empty,((200,180),(200,260))))

    def test_cell_handoff_waits_and_reuses_delivering_vehicle(self):
        m=self.model();d=NormalDriver(m,1);change=lambda f,*a:f(*a);d.initialize(change)
        waited={};checked=set()
        for _ in range(4000):
            m.tick();d.enter_waiting(change)
            for vehicle,cell in m._cell_waiters.items():
                if lane_traffic.waiting_for_work(m,vehicle):
                    v=m._vehicles[vehicle];self.assertEqual((v.x,v.y),m._point(next(t.destination for t in reversed(m.transports) if t.vehicle_id==vehicle)))
                    self.assertNotIn(vehicle,m._motions);waited[cell]=vehicle
            for t in m.transports:
                if t.source.location_id in waited and t.source.location_type.value=='CELL':
                    self.assertEqual(t.vehicle_id,waited[t.source.location_id]);checked.add(t.source.location_id)
            if d.drained():break
        self.assertTrue(d.drained());self.assertEqual(checked,{'ASM-01','ASM-02','QC-01'})
        for config in m.configuration.factory['vehicles']:
            if config['kind']=='AGV':
                v=m._vehicles[config['vehicleId']]
                self.assertEqual((v.x,v.y),(config['initialPosition']['x'],config['initialPosition']['y']))

    def test_failed_quality_and_idle_bay_vehicle_do_not_block_later_pickup(self):
        m=FactoryModel(traffic_configuration(RunConfiguration.from_path()),quality_results=('FAIL','PASS'))
        d=P0Driver(m);change=lambda f,*a:f(*a);d.initialize(change)
        def step():
            stage=d.step(change)
            while stage:stage=d.after(stage,change)
        for _ in range(7000):
            self.check_step(m,step)
            if d.drained():break
        self.assertTrue(d.drained(), 'idle dock occupants must yield to an assigned pickup')
        self.assertEqual(d.stage,5)
