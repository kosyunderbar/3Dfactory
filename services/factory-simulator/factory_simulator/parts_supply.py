"""Rear AMR supply with finite dock inventory and one physical kit per trip."""
from dataclasses import replace
from math import ceil, hypot


def supply_configuration(configuration):
    from .run_configuration import RunConfiguration
    data = configuration.to_dict()
    c = data['config']
    if 'partsSupply' in c:
        return configuration
    if c.get('traffic', {}).get('policyVersion') != 4:
        raise ValueError('Rear parts supply requires traffic policy 4')
    c['partsSupply'] = dict(capacity=2, initialStock=min(2, c['maxBodies']))
    positions = {'PARTS-STORE': (0, -140), 'PARTS-ASM-01': (150, -140), 'PARTS-ASM-02': (350, -140)}
    for loc in c['locations']:
        if loc['locationId'] in positions:
            loc['x'], loc['y'] = positions[loc['locationId']]
    for v in c['vehicles']:
        if v['kind'] == 'AMR': v['initialPosition'] = dict(x=-90, y=-240)
    from .traffic import rect
    policy = c['traffic']
    policy['bounds'].update(minY=-300, maxY=700)
    policy['lanes'] = [e for e in policy['lanes'] if max(e['start']['y'],e['end']['y'])<=650]
    policy['holdingPoints'] = [p for p in policy['holdingPoints'] if p['y']<=650]
    policy['obstacles'] = [o for o in policy['obstacles'] if o['id'] not in positions]
    policy['obstacles'] += [rect(-87.5, -140, 60, 52.5, 'PARTS-STORE')]
    policy['obstacles'] += [rect(x, -80, 60, 52.5, name) for name, (x, _) in positions.items() if name != 'PARTS-STORE']
    # Keep the old body lane graph intact. Rear branches have no AGV destinations.
    def edge(a, b):
        for start, end in ((a, b), (b, a)):
            policy['lanes'].append(dict(start=dict(x=start[0], y=start[1]), end=dict(x=end[0], y=end[1])))
    for a, b in [((-90,-240),(0,-240)),((0,-240),(0,-220)),((0,-220),(0,-140)),
                 ((0,-140),(0,100)),((0,-220),(150,-220)),((150,-220),(350,-220)),
                 ((150,-220),(150,-140)),((350,-220),(350,-140))]: edge(a,b)
    policy['holdingPoints'].append(dict(x=-90,y=-240))
    for route in c['routes']:
        if route['cargoType'] != 'PARTS': continue
        x, y = positions[route['destination']['locationId']]
        route['points'] = [dict(x=0,y=-140),dict(x=0,y=-220),dict(x=x,y=-220),dict(x=x,y=y)]
        length = sum(hypot(b['x']-a['x'], b['y']-a['y']) for a,b in zip(route['points'],route['points'][1:]))
        route['travelDurationMs'] = ceil(length/.0375/c['tickMs'])*c['tickMs']
    return RunConfiguration.from_dict(data)


def enabled(model):
    return 'partsSupply' in model.configuration.factory


def available(model, cell):
    from .model import Location, LocationType
    return [kit for kit in model.parts if not kit.consumed_by and kit.location == Location(LocationType.PARTS_DOCK, 'PARTS-'+cell)]


def has_parts(model, cell):
    return not enabled(model) or cell == 'QC-01' or bool(available(model, cell))


def initialize(model):
    if not enabled(model): return
    from .logistics import PartsKit
    from .model import Location, LocationType
    for cell in ('ASM-01','ASM-02'):
        for _ in range(model.configuration.factory['partsSupply']['initialStock']):
            kit_id = f'kit-{model._next_parts_number:05d}'
            model._parts[kit_id] = PartsKit(kit_id, Location(LocationType.PARTS_DOCK, 'PARTS-'+cell))
            model._next_parts_number += 1


def consume(model, cell, body_id):
    if not enabled(model) or cell == 'QC-01': return
    from .model import ModelError
    kits = available(model, cell)
    if not kits: raise ModelError('Assembly requires a physically available parts kit')
    model._parts[kits[0].parts_kit_id] = replace(kits[0], consumed_by=body_id)


def snapshot(model):
    result = []
    for cell in ('ASM-01','ASM-02'):
        dock = 'PARTS-'+cell
        trips = [t for t in model.transports if t.cargo_type == 'PARTS' and t.destination.location_id == dock]
        used = sum(bool(k.consumed_by) and k.location.location_id == dock for k in model.parts)
        result.append(dict(cellId=cell, dockId=dock, capacity=model.configuration.factory['partsSupply']['capacity'],
            initialStock=model.configuration.factory['partsSupply']['initialStock'], available=len(available(model,cell)),
            inbound=sum(t.status.value in ('ASSIGNED','IN_TRANSIT') for t in trips),
            delivered=sum(t.status.value == 'COMPLETED' for t in trips), consumed=used,
            stockoutMs=model._parts_wait_ms[cell]))
    return result


def replenish(model):
    if not enabled(model): return
    from .logistics import VehicleState
    from .motion import empty_motion
    from . import lane_traffic
    candidates = []
    for stock in snapshot(model):
        cell = stock['cellId']
        # Active operations already consumed their kit. Never replenish beyond
        # the registered batch's remaining demand, even during a long fault.
        consumed = {k.consumed_by for k in model.parts if k.consumed_by and k.location.location_id == stock['dockId']}
        remaining = sum(cell not in b.completed_cell_ids and b.body_id not in consumed for b in model.bodies)
        if stock['available'] + stock['inbound'] < min(stock['capacity'], remaining):
            imminent = any(b.next_cell_id == cell and b.status.value in ('WAITING','WAITING_UNLOAD') for b in model.bodies)
            candidates.append((stock['available'], not imminent, cell))
    for _, _, cell in sorted(candidates):
        decision = model.assign_parts(cell)
        if decision.approved:
            model.start_transport(decision.transport_id)
            return
    # No pending delivery: return the empty AMR to its rear waiting position.
    for v in model.vehicles:
        if v.kind != 'AMR' or v.state != VehicleState.IDLE: continue
        home = next(c['initialPosition'] for c in model.configuration.factory['vehicles'] if c['vehicleId']==v.vehicle_id)
        goal = home['x'], home['y']
        if (v.x,v.y) != goal:
            model._vehicles[v.vehicle_id] = replace(v,state=VehicleState.RETURNING)
            model._motions[v.vehicle_id] = empty_motion(VehicleState.RETURNING,(v.x,v.y),goal,.0375,model.configuration.factory['tickMs'])


def count_wait(model, tick_ms):
    if not enabled(model): return
    for cell in ('ASM-01','ASM-02'):
        if model.cell(cell).state.value != 'IDLE' or has_parts(model,cell): continue
        if any(b.next_cell_id == cell and b.status.value in ('WAITING','WAITING_UNLOAD') and b.transport_id is None for b in model.bodies):
            model._parts_wait_ms[cell] += tick_ms
