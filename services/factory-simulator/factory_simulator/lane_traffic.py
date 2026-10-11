"""Lane policies 3/4: stable lane routes, one edge at a time, and stop/turn/drive motion.

A reservation includes the complete swept circular cargo envelope up to a safe
stop. Intersecting envelopes cannot be held simultaneously. A vehicle acquires
its next edge before moving and stops at its end, so waiting never brakes late.
"""
from heapq import heappop, heappush
from math import hypot
from .motion import profiled_motion, motion_leg, route_speed


def enabled(model):
    return model.configuration.factory.get('traffic',{}).get('policyVersion',0) >= 3


def stopped(model, vehicle_id):
    if not enabled(model): return True
    m = model._motions.get(vehicle_id)
    return not m or not m.segments or motion_leg(m)[1] == 0 or m.elapsed_ms == m.required_ms


def lane_layout(config):
    """Policy 4 uses bidirectional main aisles; policy 3 retains one-way circulation."""
    efficient=config['traffic']['policyVersion']>=4
    lanes=[]
    def edge(a,b,both=False):
        lanes.append(dict(start=dict(x=a[0],y=a[1]),end=dict(x=b[0],y=b[1])))
        if both: edge(b,a)
    upper=(0,150,200,350,400,550,600,700)
    lower=(0,100,200,300,400,500,600,700)
    for a,b in zip(upper,upper[1:]):edge((a,180),(b,180),efficient)
    for a,b in zip(lower,lower[1:]):edge((b,260),(a,260),efficient)
    for x in (150,350,550):edge((x,180),(x,100),True)
    for x in (100,300,500):edge((x,260),(x,340),True)
    for x in (200,400,600):edge((x,180),(x,260),True)
    edge((0,260),(0,180),efficient);edge((0,180),(0,100),True)
    edge((700,180),(700,260),efficient);edge((700,180),(700,130),True);edge((700,130),(700,70),True)
    ys=(260,420,510,560,760)
    for a,b in zip(ys,ys[1:]):edge((0,a),(0,b),True)
    for y in (260,420,760):edge((0,y),(-90,y),True)
    for a,b in zip((0,150,200,350,400,600),(150,200,350,400,600,700)):
        edge((a,510),(b,510),True)
    for x in (200,400,600,700):edge((x,260),(x,510),True)
    if efficient:
        lanes=[e for e in lanes if not (e['start']['x']==e['end']['x']==700 and {e['start']['y'],e['end']['y']}=={260,510})]
        edge((700,260),(700,340),True);edge((700,340),(700,510),True)
        edge((700,260),(780,260),True);edge((700,340),(780,340),True)
        edge((780,260),(845,260),True);edge((780,340),(845,340),True)
        edge((845,260),(845,340),True);edge((845,340),(845,650),True)
        edge((845,650),(0,650),True)
        lanes=[e for e in lanes if not (e['start']['x']==e['end']['x']==0 and {e['start']['y'],e['end']['y']}=={560,760})]
        edge((0,560),(0,650),True);edge((0,650),(0,760),True)
    config['traffic']['lanes']=lanes
    config['traffic']['holdingPoints']=[dict(x=-90,y=y) for y in (260,420,760)] + [dict(x=x,y=510) for x in (200,400,600,700)]
    if efficient:config['traffic']['holdingPoints'].extend([dict(x=780,y=260),dict(x=780,y=340)])


def graph(policy):
    result={}
    for e in policy['lanes']:
        a,b=((p['x'],p['y']) for p in (e['start'],e['end']))
        result.setdefault(a,[]).append(b); result.setdefault(b,[])
    return result


def separation(a,b,c,d):
    from .traffic import segment_distance
    # All policy 3 edges are axis aligned. General segment intersection included.
    def cross(p,q,r):return (q[0]-p[0])*(r[1]-p[1])-(q[1]-p[1])*(r[0]-p[0])
    if (max(min(a[0],b[0]),min(c[0],d[0])) <= min(max(a[0],b[0]),max(c[0],d[0]))
        and max(min(a[1],b[1]),min(c[1],d[1])) <= min(max(a[1],b[1]),max(c[1],d[1]))
        and cross(a,b,c)*cross(a,b,d)<=0 and cross(c,d,a)*cross(c,d,b)<=0):return 0.
    return min(segment_distance(a,b,c),segment_distance(a,b,d),segment_distance(c,d,a),segment_distance(c,d,b))


def conflicts(model, vehicle_id, a,b):
    from .traffic import segment_distance
    policy=model.configuration.factory['traffic']; distance=2*policy['vehicleRadius']+policy['clearance']
    for other,v in model._vehicles.items():
        if other==vehicle_id:continue
        if segment_distance(a,b,(v.x,v.y)) < distance-1e-7:return True
        path=model._traffic_tick_paths.get(other)
        if path and separation(a,b,*path) < distance-1e-7:return True
    return False


def plan(model, vehicle_id, origin, goal, *, avoid=False, allow_outer=False):
    """A* over directed lanes; transient occupancy is a cost, not a new obstacle."""
    if origin==goal:return (origin,goal)
    network=model._lane_graph
    if origin not in network or goal not in network:return None
    costs={origin:0.}; previous={}; queue=[(hypot(goal[0]-origin[0],goal[1]-origin[1]),0.,origin)]
    while queue:
        _,cost,a=heappop(queue)
        if cost!=costs.get(a):continue
        if a==goal:
            path=[a]
            while path[-1]!=origin:path.append(previous[path[-1]])
            return compress(tuple(reversed(path))) if efficient(model) else tuple(reversed(path))
        for b in network[a]:
            if model.configuration.factory.get('partsSupply'):
                if model._vehicles[vehicle_id].kind == 'AGV' and min(a[1],b[1]) < 0: continue
                if model._vehicles[vehicle_id].kind == 'AMR' and max(a[1],b[1]) >= 0: continue
            if not allow_outer and model._vehicles[vehicle_id].kind == 'AGV' and origin[1]<510 and goal[1]<510 and max(a[1],b[1])>=510:continue
            blocked=conflicts(model,vehicle_id,a,b)
            if avoid and blocked:continue
            # 3 seconds of estimated congestion, plus one stop/turn allowance.
            score=cost+hypot(b[0]-a[0],b[1]-a[1])+20+(112.5 if blocked else 0)
            if score < costs.get(b,float('inf')):
                costs[b]=score;previous[b]=a
                heappush(queue,(score+hypot(goal[0]-b[0],goal[1]-b[1]),score,b))
    return None


def cruise_speed(model, vehicle_id, phase):
    trip=model._transports.get(model._vehicles[vehicle_id].transport_id)
    if not trip:return .0375
    route=model._route(trip)
    speed=min(.0375,route_speed(route))
    delay=model._transport_delays.get(trip.transport_id,0) if phase.value=='MOVING' else 0
    return speed*route['travelDurationMs']/(route['travelDurationMs']+delay)


def prepare(model, vehicle_id, motion):
    if motion.phase.value not in ('TO_PICKUP','MOVING','RETURNING'):return motion
    v=model._vehicles[vehicle_id]; tick=model.configuration.factory['tickMs']
    if not motion.segments:
        path=plan(model,vehicle_id,(v.x,v.y),motion.points[-1])
        if path is None:
            raise ValueError('Policy 3 movement endpoint is outside the lane graph')
        speed=cruise_speed(model,vehicle_id,motion.phase)
        motion=profiled_motion(motion.phase,path,model._traffic_heading.get(vehicle_id,0.),tick,speed,allow_reverse=can_reverse_departure(model,vehicle_id,motion,path))
        model._motions[vehicle_id]=motion
    i,elapsed=motion_leg(motion)
    edge=motion.points[i:i+2]
    if elapsed==0:
        model._traffic_reserved.pop(vehicle_id,None)
        if conflicts(model,vehicle_id,*edge):
            model._traffic_waiting.add(vehicle_id)
            model._lane_wait_since.setdefault(vehicle_id,model.sim_elapsed_ms)
            if vehicle_id in model._final_returning:return None
            # Route changes happen only at a stopped node after sustained blockage.
            # Preserve the old route unless a completely clear alternative exists.
            if model.sim_elapsed_ms-model._lane_wait_since[vehicle_id]>=3000:
                path=plan(model,vehicle_id,(v.x,v.y),motion.points[-1],avoid=True)
                old_length=sum(hypot(b[0]-a[0],b[1]-a[1]) for a,b in zip(motion.points[i:],motion.points[i+1:]))
                new_length=sum(hypot(b[0]-a[0],b[1]-a[1]) for a,b in zip(path,path[1:])) if path else float('inf')
                wait_cost=(model.sim_elapsed_ms-model._lane_wait_since[vehicle_id])*.0375
                # A two-second route-change penalty prevents marginal detours.
                if path and path!=motion.points[i:] and new_length+75 < old_length+wait_cost:
                    model._motions[vehicle_id]=profiled_motion(motion.phase,path,model._traffic_heading.get(vehicle_id,0.),tick,cruise_speed(model,vehicle_id,motion.phase),allow_reverse=can_reverse_departure(model,vehicle_id,motion,path))
                    model._lane_wait_since[vehicle_id]=model.sim_elapsed_ms
            return None
        model._traffic_reserved[vehicle_id]=edge
        model._traffic_tick_paths[vehicle_id]=edge
        model._traffic_waiting.discard(vehicle_id);model._lane_wait_since.pop(vehicle_id,None)
    return motion


def progressed(model, vehicle_id, motion):
    model._traffic_heading[vehicle_id]=motion.pose()[2]
    if motion.elapsed_ms==motion.required_ms or motion_leg(motion)[1]==0:
        model._traffic_reserved.pop(vehicle_id,None)


def yield_deadlock(model):
    """Resolve a standstill only through designated holding nodes, never free space."""
    if model._traffic_reserved or model._traffic_yield:return
    waiting=[v for v in model._traffic_waiting if v in model._motions and v not in model._final_returning]
    if not waiting or min(model.sim_elapsed_ms-model._lane_wait_since.get(v,model.sim_elapsed_ms) for v in waiting)<3000:return
    # The oldest request gets priority; a younger request moves to a pull-over.
    waiting.sort(key=lambda v:(model._lane_wait_since.get(v,0),v),reverse=True)
    for vehicle_id in waiting:
        v=model._vehicles[vehicle_id]; motion=model._motions[vehicle_id]
        goals=[m.points[-1] for k,m in model._motions.items() if k!=vehicle_id]
        candidates=sorted(model.configuration.factory['traffic']['holdingPoints'],key=lambda p:hypot(v.x-p['x'],v.y-p['y']))
        for p in candidates:
            point=(p['x'],p['y'])
            if v.kind=='AGV' and point[1]>600:continue
            if point==(v.x,v.y) or any(hypot(point[0]-g[0],point[1]-g[1])<63 for g in goals):continue
            path=plan(model,vehicle_id,(v.x,v.y),point,avoid=True)
            if path:
                model._traffic_yield[vehicle_id]=motion
                model._motions[vehicle_id]=profiled_motion(motion.phase,path,model._traffic_heading.get(vehicle_id,0.),model.configuration.factory['tickMs'],cruise_speed(model,vehicle_id,motion.phase),allow_reverse=can_reverse_departure(model,vehicle_id,motion,path))
                model._traffic_waiting.discard(vehicle_id);model._lane_wait_since.pop(vehicle_id,None)
                return


def efficient(model):
    return model.configuration.factory.get('traffic',{}).get('policyVersion',0)>=4


def compress(path):
    """Keep turns and destinations; drive straight through intermediate graph nodes."""
    result=[]
    for p in path:
        while len(result)>=2:
            a,b=result[-2:]
            if ((a[0]==b[0]==p[0] or a[1]==b[1]==p[1])
                and (b[0]-a[0])*(p[0]-b[0])+(b[1]-a[1])*(p[1]-b[1])>0):result.pop()
            else:break
        result.append(p)
    return tuple(result)


def waiting_for_work(model, vehicle_id):
    if not efficient(model):return False
    cell=model._cell_waiters.get(vehicle_id)
    if not cell:return False
    work=model.cell(cell)
    operation=model._operations.get(work.operation_id)
    # Keep the delivering vehicle for a soon-finished operation. Do not reserve it
    # indefinitely for failed/long processes; other ready jobs remain dispatchable.
    return work.state.value=='RUNNING' and operation and operation.required_ms-operation.elapsed_ms<=8000


def clear_idle_docks(model):
    """An idle vehicle yields only when another assigned trip needs its position."""
    if not efficient(model):return
    from dataclasses import replace
    from .logistics import VehicleState
    from .motion import Motion
    goals=[m.points[-1] for m in model._motions.values()]
    for vehicle_id,v in model._vehicles.items():
        if v.state!=VehicleState.IDLE or vehicle_id in model._motions:continue
        if not any(hypot(v.x-g[0],v.y-g[1])<63 for g in goals):continue
        choices=[]
        for p in model.configuration.factory['traffic']['holdingPoints']:
            point=(p['x'],p['y'])
            if v.kind=='AGV' and point[1]>600:continue
            if any(hypot(point[0]-g[0],point[1]-g[1])<63 for g in goals):continue
            path=plan(model,vehicle_id,(v.x,v.y),point,avoid=True)
            if path:choices.append((sum(hypot(b[0]-a[0],b[1]-a[1]) for a,b in zip(path,path[1:])),point))
        if choices:
            _,point=min(choices)
            model._vehicles[vehicle_id]=replace(v,state=VehicleState.RETURNING)
            model._cell_waiters.pop(vehicle_id,None)
            model._motions[vehicle_id]=Motion(VehicleState.RETURNING,((v.x,v.y),point),model.configuration.factory['tickMs'])
            goals.append(point)


def can_reverse_departure(model, vehicle_id, motion, path):
    """Only an empty vehicle leaving a material dock may reverse its first leg."""
    if not efficient(model) or motion.phase.value not in ('TO_PICKUP','RETURNING'):return False
    v=model._vehicles[vehicle_id]
    trip=model._transports.get(v.transport_id)
    if trip and trip.status.value=='IN_TRANSIT':return False
    return any(loc['locationType'] in ('CELL','BUFFER','INPUT','RESULT','PARTS_DOCK')
               and (loc['x'],loc['y'])==path[0]
               for loc in model.configuration.factory['locations'])


def queue_final_return(model):
    """After the entire batch is delivered, return AGVs via the outside aisle in turn."""
    if not efficient(model) or not model.bodies or model.active_transports:return
    if any(b.location.location_type.value!='RESULT' for b in model.bodies):return
    if any(v.state.value!='IDLE' for v in model.vehicles):return
    from dataclasses import replace
    from .logistics import VehicleState
    for config in reversed(model.configuration.factory['vehicles']):
        if config['kind']!='AGV':continue
        vehicle_id=config['vehicleId'];v=model._vehicles[vehicle_id]
        home=(config['initialPosition']['x'],config['initialPosition']['y'])
        if (v.x,v.y)==home:continue
        path=[(v.x,v.y)]
        for goal in ((845,650),(0,650),home):
            leg=plan(model,vehicle_id,path[-1],goal,allow_outer=True)
            if leg is None:raise ValueError('Final return must have a connected outer aisle')
            path.extend(leg[1:])
        path=compress(tuple(p for i,p in enumerate(path) if i==0 or p!=path[i-1]))
        model._vehicles[vehicle_id]=replace(v,state=VehicleState.RETURNING)
        model._motions[vehicle_id]=profiled_motion(VehicleState.RETURNING,path,model._traffic_heading.get(vehicle_id,0.),model.configuration.factory['tickMs'])
        model._final_returning.add(vehicle_id)
        return


def final_return_complete(model):
    if not efficient(model):return True
    return all((model._vehicles[v['vehicleId']].x,model._vehicles[v['vehicleId']].y)==
               (v['initialPosition']['x'],v['initialPosition']['y'])
               for v in model.configuration.factory['vehicles'] if v['kind']=='AGV')
