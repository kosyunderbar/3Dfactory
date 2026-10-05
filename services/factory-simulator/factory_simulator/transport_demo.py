"""Offline runtime transport and buffer lifecycle; only initial placement uses fixtures."""
from .logistics import TransportStatus, VehicleState
from .model import FactoryModel, Location, LocationType, ModelError
from .run_configuration import CELLS, RunConfiguration


def demo_transport(configuration: RunConfiguration) -> dict:
    capacity = next(item['capacity'] for item in configuration.factory['buffers'] if item['cellId'] == 'ASM-02')
    if configuration.factory['maxBodies'] < capacity + 1:
        raise ModelError(f'--demo-transport requires maxBodies >= {capacity + 1}')

    def until(model, predicate):
        for _ in range(5000):
            if predicate():
                return
            model.tick()
        raise ModelError('Transport demo exceeded 5000 ticks; use shorter configured durations')

    normal = FactoryModel(configuration, quality_results=('PASS',))
    body = normal.register_body()
    normal.redispatch()
    for _ in range(5000):
        normal.tick()
        current = normal.body(body.body_id)
        if current.location.location_type == LocationType.BUFFER:
            normal.enter_cell(body.body_id)
        if (current.location.location_type == LocationType.RESULT
                and all(vehicle.state == VehicleState.IDLE for vehicle in normal.vehicles)):
            break
    else:
        raise ModelError('Transport demo exceeded 5000 ticks; use shorter configured durations')

    boundary = FactoryModel(configuration, allow_initial_fixtures=True)
    waiting = [boundary.register_fixture_body(Location(LocationType.BUFFER, 'BAY-ASM-02', f'BAY-ASM-02-S{i}'),
                                             completed_cell_ids=('ASM-01',)) for i in range(1, capacity)]
    first = boundary.register_fixture_body(Location(LocationType.CELL, 'ASM-01'))
    operation = boundary.start_work('ASM-01')
    tick_ms = configuration.factory['tickMs']
    boundary.advance(((operation.required_ms + tick_ms - 1) // tick_ms) * tick_ms)
    decision = boundary.assign_transport(first.body_id)
    allocated = boundary.inspect()
    boundary.start_transport(decision.transport_id)
    until(boundary, lambda: boundary.transport(decision.transport_id).status == TransportStatus.IN_TRANSIT)
    second = boundary.register_fixture_body(Location(LocationType.CELL, 'ASM-01'))
    boundary.start_work('ASM-01')
    until(boundary, lambda: boundary.transport(decision.transport_id).status == TransportStatus.COMPLETED)
    # A custom short travel duration may arrive before the second assembly completes.
    until(boundary, lambda: boundary.body(second.body_id).completed_cell_ids == ('ASM-01',))
    arrived = boundary.inspect()
    boundary.enter_cell(waiting[0].body_id)
    after_entry = boundary.inspect()
    return {'modelPreview': True, 'physicalTransportImplemented': True,
            'initialFixturesOnly': True, 'networkConnected': False,
            'normalRun': normal.inspect(),
            'bufferLifecycle': {'allocated': allocated, 'arrived': arrived,
                                'entry': boundary.cell_entries[-1].to_dict(), 'redispatched': after_entry}}
