"""Immutable P0 run configuration, separate from TCP connection settings."""
from dataclasses import dataclass
import json
import math
from pathlib import Path
import re
from types import MappingProxyType
from typing import Any, Mapping

CELLS = ('ASM-01', 'ASM-02', 'QC-01')
DEFAULT_CONFIG = Path(__file__).parent / 'config/default-run.json'


def _keys(value: Any, expected: set[str], label: str) -> dict:
    if not isinstance(value, dict) or set(value) != expected:
        raise ValueError(f'{label}: required fields are {sorted(expected)}')
    return value


def _integer(value: Any, minimum: int, maximum: int, label: str) -> None:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f'{label}: integer {minimum}..{maximum} required')


def _number(value: Any, label: str) -> None:
    try:
        finite = type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        finite = False
    if not finite:
        raise ValueError(f'{label}: finite number required')


def _point(value: Any, label: str) -> tuple[int | float, int | float]:
    _keys(value, {'x', 'y'}, label)
    for axis in ('x', 'y'):
        _number(value[axis], f'{label}.{axis}')
    return value['x'], value['y']


def _place(value: Any, label: str) -> tuple[str, str]:
    _keys(value, {'locationType', 'locationId'}, label)
    if type(value['locationType']) is not str or type(value['locationId']) is not str:
        raise ValueError(f'{label}: location type and ID must be strings')
    return value['locationType'], value['locationId']


def _array(value: Any, label: str) -> list:
    if not isinstance(value, list):
        raise ValueError(f'{label}: array required')
    return value


def _unique(items: list, field: str, label: str) -> None:
    values = [item[field] for item in items]
    if any(type(value) is not str for value in values) or len(set(values)) != len(values):
        raise ValueError(f'{label}: duplicate or invalid {field}')


def _validate_factory(config: dict) -> None:
    _keys(config, {'tickMs', 'snapshotIntervalMs', 'speed', 'maxBodies', 'failProbability',
                   'locations', 'equipment', 'buffers', 'vehicles', 'routes'} | ({'traffic'} if 'traffic' in config else set()) | ({'partsSupply'} if 'partsSupply' in config else set()), 'config')
    if 'partsSupply' in config:
        _keys(config['partsSupply'], {'capacity','initialStock'}, 'partsSupply')
        _integer(config['partsSupply']['capacity'], 1, 2, 'capacity')
        _integer(config['partsSupply']['initialStock'], 0, min(config['partsSupply']['capacity'],config['maxBodies']), 'initialStock')
        if config.get('traffic',{}).get('policyVersion') != 4: raise ValueError('partsSupply requires policy 4')
    limit = 9_007_199_254_740_991
    for field in ('tickMs', 'snapshotIntervalMs'):
        _integer(config[field], 1, limit, field)
    if config['snapshotIntervalMs'] % config['tickMs']:
        raise ValueError('snapshotIntervalMs: must be a multiple of tickMs')
    _number(config['speed'], 'speed')
    if config['speed'] != 1:
        raise ValueError('speed: P0 requires 1')
    _integer(config['maxBodies'], 1, 100, 'maxBodies')
    _number(config['failProbability'], 'failProbability')
    if not 0 <= config['failProbability'] <= 1:
        raise ValueError('failProbability: must be 0..1')

    coordinates = {}
    expected_places = {('INPUT', 'BODY-IN'), ('RESULT', 'GOOD'), ('RESULT', 'HOLD'),
                       ('STORE', 'PARTS-STORE'), ('PARTS_DOCK', 'PARTS-ASM-01'),
                       ('PARTS_DOCK', 'PARTS-ASM-02')}
    expected_places.update(('CELL', cell) for cell in CELLS)
    expected_places.update(('BUFFER', 'BAY-' + cell) for cell in CELLS)
    for item in _array(config['locations'], 'locations'):
        _keys(item, {'locationType', 'locationId', 'x', 'y'}, 'location')
        place = _place({key: item[key] for key in ('locationType', 'locationId')}, 'location')
        point = _point({key: item[key] for key in ('x', 'y')}, 'location coordinate')
        if place in coordinates:
            raise ValueError('locations: duplicate location')
        coordinates[place] = point
    if set(coordinates) != expected_places:
        raise ValueError('locations: P0 requires all configured factory locations')

    equipment = _array(config['equipment'], 'equipment')
    for item in equipment:
        _keys(item, {'cellId', 'equipmentId', 'bufferId', 'workDurationMs'}, 'equipment')
        if item['cellId'] not in CELLS or item['equipmentId'] != item['cellId'] or item['bufferId'] != 'BAY-' + item['cellId']:
            raise ValueError('equipment: invalid P0 cell/equipment/buffer reference')
        _integer(item['workDurationMs'], 1, limit, 'workDurationMs')
    _unique(equipment, 'cellId', 'equipment')
    if {item['cellId'] for item in equipment} != set(CELLS):
        raise ValueError('equipment: requires ASM-01, ASM-02 and QC-01')

    buffers = _array(config['buffers'], 'buffers')
    for item in buffers:
        _keys(item, {'bufferId', 'cellId', 'capacity', 'slotIds'}, 'buffer')
        if item['cellId'] not in CELLS or item['bufferId'] != 'BAY-' + item['cellId']:
            raise ValueError('buffer: invalid cell reference')
        _integer(item['capacity'], 2, 4, 'capacity')
        expected = [f"{item['bufferId']}-S{number}" for number in range(1, item['capacity'] + 1)]
        if item['slotIds'] != expected:
            raise ValueError('slotIds: must match capacity in S1..Sn order')
    _unique(buffers, 'cellId', 'buffers')
    if {item['cellId'] for item in buffers} != set(CELLS):
        raise ValueError('buffers: each P0 cell requires one Bay')

    vehicles = _array(config['vehicles'], 'vehicles')
    for item in vehicles:
        _keys(item, {'vehicleId', 'kind', 'home', 'initialPosition'}, 'vehicle')
        kind = item['kind']
        if kind not in ('AGV', 'AMR') or not isinstance(item['vehicleId'], str) or not re.fullmatch(kind + r'-[0-9]{3,6}', item['vehicleId']):
            raise ValueError('vehicle: kind and ID prefix must agree')
        home = _place(item['home'], 'vehicle.home')
        if home not in coordinates:
            raise ValueError('vehicle.home: unknown location')
        _point(item['initialPosition'], 'vehicle.initialPosition')
    _unique(vehicles, 'vehicleId', 'vehicles')
    if sum(item['kind'] == 'AGV' for item in vehicles) != 2 or sum(item['kind'] == 'AMR' for item in vehicles) != 1:
        raise ValueError('vehicles: P0 requires two body AGVs and one parts AMR')

    expected_routes = {('BODY', ('INPUT', 'BODY-IN'), ('BUFFER', 'BAY-ASM-01')),
                       ('BODY', ('CELL', 'ASM-01'), ('BUFFER', 'BAY-ASM-02')),
                       ('BODY', ('CELL', 'ASM-02'), ('BUFFER', 'BAY-QC-01')),
                       ('BODY', ('CELL', 'QC-01'), ('RESULT', 'GOOD')),
                       ('BODY', ('CELL', 'QC-01'), ('RESULT', 'HOLD')),
                       ('PARTS', ('STORE', 'PARTS-STORE'), ('PARTS_DOCK', 'PARTS-ASM-01')),
                       ('PARTS', ('STORE', 'PARTS-STORE'), ('PARTS_DOCK', 'PARTS-ASM-02'))}
    if 'traffic' in config:
        policy = config['traffic']
        _keys(policy, {'policyVersion','vehicleRadius','clearance','bounds','obstacles'} | ({'lanes','holdingPoints'} if policy['policyVersion']>=3 else set()), 'traffic')
        _integer(policy['policyVersion'], 1, 4, 'traffic.policyVersion')
        if policy['policyVersion'] >= 2:
            expected_routes.update({('BODY', ('INPUT','BODY-IN'), ('CELL','ASM-01')),
                                    ('BODY', ('CELL','ASM-01'), ('CELL','ASM-02')),
                                    ('BODY', ('CELL','ASM-02'), ('CELL','QC-01'))})
            expected_routes.update(('BODY', ('BUFFER','BAY-'+cell), ('CELL',cell)) for cell in CELLS)
        for field in ('vehicleRadius','clearance'):
            _number(policy[field], field)
            if policy[field] < ((30 if policy['policyVersion']>=2 else 24) if field == 'vehicleRadius' else 3): raise ValueError('traffic envelope below model size')
        _keys(policy['bounds'], {'minX','minY','maxX','maxY'}, 'traffic.bounds')
        if not 1 <= len(policy['obstacles']) <= 32: raise ValueError('traffic obstacle count')
        for item in [policy['bounds'], *policy['obstacles']]:
            if item is not policy['bounds']: _keys(item, {'id','minX','minY','maxX','maxY'}, 'traffic.obstacle')
            for field in ('minX','minY','maxX','maxY'): _number(item[field], field)
            if item['minX']>=item['maxX'] or item['minY']>=item['maxY']: raise ValueError('traffic rectangle order')
        _unique(policy['obstacles'], 'id', 'traffic.obstacles')
        if policy['policyVersion'] >= 3:
            from .lane_traffic import graph
            from .traffic import intersects, expanded
            if not 1 <= len(policy['lanes']) <= 256: raise ValueError('lane count')
            for edge in policy['lanes']:
                _keys(edge, {'start','end'}, 'lane')
                for p in edge.values():
                    _keys(p, {'x','y'}, 'lane point')
                    for value in p.values(): _number(value, 'coordinate')
                    bounds=policy['bounds']; margin=policy['vehicleRadius']+policy['clearance']
                    if not bounds['minX']+margin<=p['x']<=bounds['maxX']-margin or not bounds['minY']+margin<=p['y']<=bounds['maxY']-margin: raise ValueError('lane outside bounds')
                a,b=((p['x'],p['y']) for p in (edge['start'],edge['end']))
                if a==b or (a[0]!=b[0] and a[1]!=b[1]): raise ValueError('lane must be rectilinear')
                if any(intersects(a,b,expanded(o,policy['vehicleRadius']+policy['clearance'])) for o in policy['obstacles']): raise ValueError('lane intersects obstacle')
            if not 1<=len(policy['holdingPoints'])<=32: raise ValueError('holding point count')
            for p in policy['holdingPoints']:
                _keys(p, {'x','y'}, 'holding point')
                for value in p.values(): _number(value, 'holding coordinate')
            network=graph(policy)
            for p in [*policy['holdingPoints'],*[v['initialPosition'] for v in vehicles],*config['locations']]:
                if (p['x'],p['y']) not in network: raise ValueError('lane graph missing dock or holding point')
            for start in network:
                seen={start}; todo=[start]
                while todo:
                    for nxt in network[todo.pop()]:
                        if nxt not in seen:seen.add(nxt);todo.append(nxt)
                if len(seen)!=len(network): raise ValueError('lane graph is not strongly connected')
        from .traffic import validate_positions
        from .logistics import Vehicle
        validate_positions(policy, {v['vehicleId']: Vehicle(v['vehicleId'],v['kind'],v['initialPosition']['x'],v['initialPosition']['y']) for v in vehicles})
    actual_routes = set()
    routes = _array(config['routes'], 'routes')
    for item in routes:
        _keys(item, {'routeId', 'cargoType', 'source', 'destination', 'points', 'travelDurationMs'}, 'route')
        if not isinstance(item['routeId'], str) or not re.fullmatch(r'ROUTE-[A-Z0-9-]{1,48}', item['routeId']):
            raise ValueError('routeId: invalid format')
        source, destination = _place(item['source'], 'route.source'), _place(item['destination'], 'route.destination')
        if source not in coordinates or destination not in coordinates:
            raise ValueError('route: unknown endpoint')
        signature = (item['cargoType'], source, destination)
        if type(item['cargoType']) is not str or signature not in expected_routes or signature in actual_routes:
            raise ValueError('route: unsupported or duplicate P0 path')
        actual_routes.add(signature)
        points = [_point(point, 'route.point') for point in _array(item['points'], 'route.points')]
        if len(points) < 2 or points[0] != coordinates[source] or points[-1] != coordinates[destination]:
            raise ValueError('route.points: endpoints must match registered coordinates')
        _integer(item['travelDurationMs'], 1, limit, 'travelDurationMs')
    _unique(routes, 'routeId', 'routes')
    if actual_routes != expected_routes:
        raise ValueError('routes: requires the complete fixed P0 paths')


def _freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


def _json_object(pairs: list[tuple[str, Any]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f'Configuration JSON: duplicate key {key}')
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError(f'Configuration JSON: non-finite number {value}')


@dataclass(frozen=True)
class RunConfiguration:
    seed: int
    source_id: str
    factory: Mapping[str, Any]

    def __post_init__(self) -> None:
        _integer(self.seed, 0, 2_147_483_647, 'seed')
        if not isinstance(self.source_id, str) or not re.fullmatch(r'simulator-[0-9]{2,4}', self.source_id):
            raise ValueError('sourceId: expected simulator-NN..NNNN')
        # Copy before freezing: mutations of the input dictionary cannot change this run.
        copied = _thaw(self.factory)
        _validate_factory(copied)
        object.__setattr__(self, 'factory', _freeze(copied))

    @classmethod
    def from_dict(cls, value: dict) -> 'RunConfiguration':
        _keys(value, {'seed', 'sourceId', 'config'}, 'run configuration')
        return cls(value['seed'], value['sourceId'], value['config'])

    @classmethod
    def from_path(cls, path: Path = DEFAULT_CONFIG) -> 'RunConfiguration':
        value = json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=_json_object,
                           parse_constant=_reject_constant)
        return cls.from_dict(value)

    def to_dict(self) -> dict:
        return {'seed': self.seed, 'sourceId': self.source_id, 'config': _thaw(self.factory)}
