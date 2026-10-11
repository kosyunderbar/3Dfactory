"""Offline lane policy production/fault evidence. Run with PYTHONPATH=services/factory-simulator.

No services or databases are changed. --update-fixtures also refreshes Java contract fixtures.
"""
import argparse
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--update-fixtures',action='store_true')
parser.add_argument('--policy',type=int,choices=(3,4),default=3)
parser.add_argument('--label',choices=('forward',),default='')
args=parser.parse_args()
suffix='-'+args.label if args.label else ''
from pathlib import Path
from dataclasses import replace
from math import hypot, degrees
from factory_simulator.motion import angle_delta
import json
from factory_simulator.model import FactoryModel
from factory_simulator.run_configuration import RunConfiguration
from factory_simulator.traffic import traffic_configuration, segment_distance
from factory_simulator.connected_demo import NormalDriver
from factory_simulator.p0_demo import P0Driver
out=Path(f'.build-cache/lane-validation-v{args.policy}{suffix}');out.mkdir(exist_ok=True)
results=[]
for name,count in [('normal',3),('p0',0)]:
 m=FactoryModel(traffic_configuration(RunConfiguration.from_path(),version=args.policy),quality_results=('PASS',) if count else ('FAIL','PASS'))
 d=NormalDriver(m,count) if count else P0Driver(m);change=lambda f,*a:f(*a);d.initialize(change);m.publish_snapshot()
 distance=0.;rotation=0.;minimum=1e9;wait_ticks=0;reroutes=0;pullovers=0;stages=[];poses=[]
 for i in range(16000):
  headings=dict(m._traffic_heading);old=dict(m._vehicles);motions=dict(m._motions);yielding=set(m._traffic_yield)
  if count:m.tick();d.enter_waiting(change)
  else:
   stage=d.step(change)
   while stage:stages.append(stage);stage=d.after(stage,change)
  for v in m.vehicles:
   distance+=hypot(v.x-old[v.vehicle_id].x,v.y-old[v.vehicle_id].y)
   rotation+=abs(degrees(angle_delta(headings.get(v.vehicle_id,0),m._traffic_heading.get(v.vehicle_id,0))))
   prev=motions.get(v.vehicle_id);cur=m._motions.get(v.vehicle_id)
   if prev and prev.segments and cur and cur.segments and prev.points!=cur.points:reroutes+=1
  pullovers+=len(set(m._traffic_yield)-yielding);wait_ticks+=len(m._traffic_waiting)
  for j,a in enumerate(m.vehicles):
   for b in m.vehicles[j+1:]:
    aa,bb=old[a.vehicle_id],old[b.vehicle_id]
    minimum=min(minimum,segment_distance((aa.x-bb.x,aa.y-bb.y),(a.x-b.x,a.y-b.y),(0,0)))
  if i%5==0:m.publish_snapshot()
  if d.drained():break
 assert d.drained(),name
 m.finish_run();(out/(name+'.ndjson')).write_text(''.join(e.ndjson for e in m.events))
 results.append(dict(policy=args.policy,totalDistance=distance,totalRotationDegrees=rotation,scenario=name,simElapsedMs=m.sim_elapsed_ms,ticks=i+1,minSweptDistance=minimum,waitingVehicleTicks=wait_ticks,stoppedReroutes=reroutes,pullovers=pullovers,stages=stages,results=[b.location.location_id for b in m.bodies]))
 # Compact representative contract fixture with first snapshots of each pose/phase.
 if count and args.update_fixtures:
  chosen=[];seen=set()
  for e in m.events:
   raw=e.to_dict()
   if raw['eventType']=='FACTORY_SNAPSHOT':
    key=tuple((v['state'],v['traffic']['waiting'],bool(v['traffic']['segments'])) for v in raw['payload']['vehicles'])
    if key in seen:continue
    seen.add(key)
   chosen.append(e.ndjson)
  for service in ('ingestion-service','operations-service'):
   Path(f'services/{service}/src/test/resources/lane-traffic-v{args.policy}-scenario.ndjson').write_text(''.join(chosen))
print(json.dumps(results,indent=2))
Path(f'docs/development/3d-review/lane-v{args.policy}{suffix}-simulation-verification.json').write_text(json.dumps(results,indent=2)+'\n')
