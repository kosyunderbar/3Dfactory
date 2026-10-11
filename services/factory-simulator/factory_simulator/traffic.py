"""Conservative planar traffic: solid footprints, swept clearance and path reservations.

A circular envelope contains every vehicle (including its load) at every yaw.
Reservations cover the remaining path; disjoint paths may proceed together.
This is kinematic traffic control, not a rigid-body impact simulation.
"""
from heapq import heappop, heappush
from math import hypot, ceil
from .motion import Motion, route_speed

MOVING = {'TO_PICKUP', 'MOVING', 'RETURNING'}
EPS = 0.01


def rect(x, y, w, h, name):
    return dict(id=name, minX=x-w/2, maxX=x+w/2, minY=y-h/2, maxY=y+h/2)


def traffic_configuration(configuration, *, version=4):
    from .run_configuration import RunConfiguration
    data = configuration.to_dict()
    if 'traffic' in data['config']:
        return configuration
    c = data['config']; obstacles = []
    scale = 1.25 if version >= 2 else 1
    # Move the Bay AND its docking point back. Keep the parts service area
    # behind the Bays so it does not occupy the newly opened body-vehicle aisle.
    for loc in c['locations']:
        if loc['locationType'] == 'BUFFER': loc['y'] += 240 if version>=3 else 80
        elif loc['locationType'] in ('STORE', 'PARTS_DOCK'): loc['y'] += 260 if version>=3 else 100
    locations = {loc['locationId']: loc for loc in c['locations']}
    for route in c['routes']:
        speed = route_speed(route)
        for endpoint, index in (('source', 0), ('destination', -1)):
            loc = locations[route[endpoint]['locationId']]
            route['points'][index] = {'x':loc['x'], 'y':loc['y']}
        length = sum(hypot(b['x']-a['x'], b['y']-a['y']) for a,b in zip(route['points'],route['points'][1:]))
        tick = c['tickMs']
        route['travelDurationMs'] = max(tick, ceil(length/speed/tick)*tick)
    for loc in c['locations']:
        x, y, kind, name = loc['x'], loc['y'], loc['locationType'], loc['locationId']
        if kind == 'CELL': obstacles.append(rect(x, y-(80 if version>=2 else 65), 48*scale, 60*scale, name))
        elif kind == 'BUFFER': obstacles.append(rect(x, y+(90 if version>=2 else 70), 37*scale, 68*scale, name))
        elif kind == 'INPUT': obstacles.append(rect(x-70*scale, y, 56*scale, 52*scale, name))
        elif kind == 'RESULT': obstacles.append(rect(x+70*scale, y, 56*scale, 52*scale, name))
        elif kind == 'STORE': obstacles.append(rect(x-70*scale, y, 48*scale, 42*scale, name))
        elif kind == 'PARTS_DOCK': obstacles.append(rect(x, y+60*scale, 48*scale, 42*scale, name))
    # Each vehicle has a distinct parking position, separate from material docks.
    parking = {'AGV': iter(((0,220),(65,340))), 'AMR': iter(((0,500),))}
    if version >= 2:
        parking = {'AGV': iter(((0,220),(0,370))), 'AMR': iter(((0,540),))}
    for v in c['vehicles']:
        x, y = next(parking[v['kind']])
        v['initialPosition'] = {'x':x, 'y':y}
    if version >= 3:
        for v in c['vehicles']:
            v['initialPosition']['x'] = -90
            v['initialPosition']['y'] = {'AGV-001':260,'AGV-002':420,'AMR-001':760}[v['vehicleId']]
    c['traffic'] = dict(policyVersion=version, vehicleRadius=24*scale, clearance=3,
                        bounds=dict(minX=-160,maxX=880,minY=-100,maxY=600) if version>=2 else dict(minX=-140,maxX=840,minY=-70,maxY=560), obstacles=obstacles)
    if version >= 2:
        # Direct cell delivery and physical retrieval from each waiting Bay.
        for source, cell in [('BODY-IN','ASM-01'),('ASM-01','ASM-02'),('ASM-02','QC-01'),
                             ('BAY-ASM-01','ASM-01'),('BAY-ASM-02','ASM-02'),('BAY-QC-01','QC-01')]:
            a,b = locations[source],locations[cell]
            points = [{'x':p['x'],'y':p['y']} for p in (a,b)]
            duration = max(c['tickMs'],ceil(hypot(b['x']-a['x'],b['y']-a['y'])/.0375/c['tickMs'])*c['tickMs'])
            c['routes'].append(dict(routeId='ROUTE-DIRECT-'+source+'-'+cell,cargoType='BODY',
                source=dict(locationType=a['locationType'],locationId=source),destination=dict(locationType='CELL',locationId=cell),
                points=points,travelDurationMs=duration))
    if version >= 3:
        from .lane_traffic import lane_layout
        c['traffic']['bounds']['maxY']=820
        lane_layout(c)
    return RunConfiguration.from_dict(data)


def expanded(r, margin):
    return (r['minX']-margin, r['minY']-margin, r['maxX']+margin, r['maxY']+margin)


def intersects(a, b, r):
    """Closed segment against a closed AABB (including tangency)."""
    low, high = 0., 1.
    for i in range(2):
        delta=b[i]-a[i]
        if abs(delta)<1e-12:
            if a[i]<r[i] or a[i]>r[i+2]: return False
        else:
            u,v=(r[i]-a[i])/delta,(r[i+2]-a[i])/delta
            low=max(low,min(u,v)); high=min(high,max(u,v))
            if low>high: return False
    return True


def segment_distance(a,b,p):
    dx,dy=b[0]-a[0],b[1]-a[1]
    t=max(0,min(1,((p[0]-a[0])*dx+(p[1]-a[1])*dy)/(dx*dx+dy*dy))) if dx or dy else 0
    return hypot(a[0]+t*dx-p[0],a[1]+t*dy-p[1])


def blockers(policy, vehicles, vehicle_id, reservations):
    radius=policy['vehicleRadius']; gap=policy['clearance']
    boxes=[expanded(r,radius+gap) for r in policy['obstacles']]
    for v in vehicles.values():
        if v.vehicle_id != vehicle_id:
            d=2*radius+gap
            boxes.append((v.x-d,v.y-d,v.x+d,v.y+d))
    for other,path in reservations.items():
        if other==vehicle_id: continue
        d=2*radius+gap
        for a,b in zip(path,path[1:]): boxes.append((min(a[0],b[0])-d,min(a[1],b[1])-d,max(a[0],b[0])+d,max(a[1],b[1])+d))
    return boxes


def plan_path(origin, goal, policy, boxes):
    """Visibility graph around expanded solids; exact start/end, no grid snapping."""
    bounds=policy['bounds']; margin=policy['vehicleRadius']+policy['clearance']
    def inside(p): return bounds['minX']+margin <= p[0] <= bounds['maxX']-margin and bounds['minY']+margin <= p[1] <= bounds['maxY']-margin
    def clear(a,b): return inside(a) and inside(b) and not any(intersects(a,b,r) for r in boxes)
    if not clear(origin,origin) or not clear(goal,goal): return None
    if clear(origin,goal): return (origin,goal)
    nodes=[origin,goal]
    for l,t,r,b in boxes:
        for p in ((l-EPS,t-EPS),(l-EPS,b+EPS),(r+EPS,t-EPS),(r+EPS,b+EPS)):
            if clear(p,p): nodes.append(p)
    distances={0:0.}; previous={}; queue=[(hypot(goal[0]-origin[0],goal[1]-origin[1]),0.,0)]
    while queue:
        _,cost,i=heappop(queue)
        if cost != distances.get(i): continue
        if i==1:
            indexes=[1]
            while indexes[-1]!=0: indexes.append(previous[indexes[-1]])
            return tuple(nodes[n] for n in reversed(indexes))
        for j,p in enumerate(nodes):
            if j==i: continue
            added=hypot(p[0]-nodes[i][0],p[1]-nodes[i][1]); candidate=cost+added
            if candidate < distances.get(j,float('inf')) and clear(nodes[i],p):
                distances[j]=candidate;previous[j]=i
                heappush(queue,(candidate+hypot(goal[0]-p[0],goal[1]-p[1]),candidate,j))
    return None


def reserve_motion(model, vehicle_id, motion):
    from . import lane_traffic
    if lane_traffic.enabled(model): return lane_traffic.prepare(model, vehicle_id, motion)
    policy=model.configuration.factory.get('traffic')
    if not policy or motion.phase.value not in MOVING: return motion
    if vehicle_id in model._traffic_reserved: return motion
    vehicle=model._vehicles[vehicle_id]
    origin=(vehicle.x,vehicle.y); goal=motion.points[-1]
    # Keep the start-of-tick reservation until every vehicle has advanced. The
    # shorter remaining path is only available to others on the following tick.
    boxes=blockers(policy,model._vehicles,vehicle_id,model._traffic_tick_paths)
    path=plan_path(origin,goal,policy,boxes)
    if path is None:
        model._traffic_waiting.add(vehicle_id)
        return None
    model._traffic_waiting.discard(vehicle_id)
    model._traffic_reserved[vehicle_id]=path
    model._traffic_tick_paths[vehicle_id]=path
    # Keep configured cruise speed; detours take longer, never accelerate to catch up.
    trip=model._transports.get(vehicle.transport_id)
    speed=route_speed(model._route(trip)) if trip else 0.0375
    speed=min(speed,0.0375)  # Model units/ms; finite kinematic speed.
    length=sum(hypot(b[0]-a[0],b[1]-a[1]) for a,b in zip(path,path[1:]))
    tick=model.configuration.factory['tickMs']
    duration=max(tick,ceil(length/speed/tick)*tick)
    if trip and motion.phase.value=='MOVING': duration+=model._transport_delays.get(trip.transport_id,0)
    return Motion(motion.phase,path,duration)


def remaining_path(motion):
    """Release passed segments without changing the motion's timing or shape."""
    lengths = [hypot(b[0]-a[0], b[1]-a[1]) for a,b in zip(motion.points,motion.points[1:])]
    distance = sum(lengths) * motion.elapsed_ms / motion.required_ms
    for index, length in enumerate(lengths):
        if distance < length:
            return (motion.position(), *motion.points[index+1:])
        distance -= length
    return (motion.points[-1], motion.points[-1])


def yield_if_deadlocked(model):
    """Two blocked moving intents can exchange docks via a free pull-over point."""
    from . import lane_traffic
    if lane_traffic.enabled(model): return lane_traffic.yield_deadlock(model)
    if not model.configuration.factory.get('traffic') or model._traffic_reserved or model._traffic_yield: return
    waiting=[v for v in sorted(model._traffic_waiting,reverse=True) if v in model._motions and model._motions[v].phase.value in MOVING]
    if len(waiting)<2:return
    policy=model.configuration.factory['traffic']
    for vehicle_id in waiting:
        v=model._vehicles[vehicle_id]; motion=model._motions[vehicle_id]; goal=motion.points[-1]
        if not any(other!=vehicle_id and hypot(model._vehicles[other].x-goal[0],model._vehicles[other].y-goal[1])<2*policy['vehicleRadius']+policy['clearance'] for other in waiting): continue
        boxes=blockers(policy,model._vehicles,vehicle_id,{})
        goals=[m.points[-1] for m in model._motions.values()]
        candidates=[(v.x+dx,v.y+dy) for dx,dy in ((0,100),(0,-100),(100,0),(-100,0),(100,100),(-100,100),(100,-100),(-100,-100))]
        for p in candidates:
            if any(hypot(p[0]-g[0],p[1]-g[1])<60 for g in goals):continue
            path=plan_path((v.x,v.y),p,policy,boxes)
            if path:
                model._traffic_yield[vehicle_id]=motion
                model._motions[vehicle_id]=Motion(motion.phase,path,model.configuration.factory['tickMs'])
                return


def validate_positions(policy, vehicles):
    for v in vehicles.values():
        p=(v.x,v.y); margin=policy['vehicleRadius']+policy['clearance']; b=policy['bounds']
        if not (b['minX']+margin<=v.x<=b['maxX']-margin and b['minY']+margin<=v.y<=b['maxY']-margin): raise ValueError('Vehicle outside traffic boundary')
        if any(intersects(p,p,expanded(r,margin)) for r in policy['obstacles']): raise ValueError('Vehicle intersects a solid footprint')
    values=list(vehicles.values())
    for i,a in enumerate(values):
        for b in values[i+1:]:
            if hypot(a.x-b.x,a.y-b.y)<2*policy['vehicleRadius']+policy['clearance']-1e-7: raise ValueError('Vehicle safety envelopes overlap')
