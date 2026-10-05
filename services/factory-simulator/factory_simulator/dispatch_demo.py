"""Offline allocation scenarios; no pickup, arrival or slot release is simulated."""
from .model import FactoryModel, Location, LocationType, ModelError
from .run_configuration import RunConfiguration


def demo_dispatch(configuration: RunConfiguration) -> dict:
    capacities = {item['cellId']: item['capacity'] for item in configuration.factory['buffers']}
    required = max(capacities['ASM-01'], capacities['ASM-02']) + 1
    if configuration.factory['maxBodies'] < required:
        raise ModelError(f'--demo-dispatch requires maxBodies >= {required}')

    def occupy(model, cell, count, history):
        buffer_id = 'BAY-' + cell
        for number in range(1, count + 1):
            model.register_fixture_body(Location(LocationType.BUFFER, buffer_id, f'{buffer_id}-S{number}'),
                                        completed_cell_ids=history)

    held = FactoryModel(configuration, allow_initial_fixtures=True)
    occupy(held, 'ASM-02', capacities['ASM-02'], ('ASM-01',))
    body = held.register_fixture_body(Location(LocationType.CELL, 'ASM-01'))
    operation = held.start_work('ASM-01')
    tick_ms = configuration.factory['tickMs']
    held.advance(((operation.required_ms + tick_ms - 1) // tick_ms) * tick_ms)
    denied = held.assign_transport(body.body_id)
    full = held.inspect()
    # Explicit test rearrangement; the transport lifecycle does not release this slot.
    fixture = held.bodies_at(LocationType.BUFFER, 'BAY-ASM-02')[0]
    held._transfer_ownership(fixture.body_id, fixture.location, Location(LocationType.INPUT, 'BODY-IN'))
    approved = held.assign_transport(body.body_id)

    competition = FactoryModel(configuration, allow_initial_fixtures=True)
    occupy(competition, 'ASM-01', capacities['ASM-01'] - 1, ())
    requests = [competition.register_body(), competition.register_body()]
    decisions = [competition.assign_transport(request.body_id).to_dict() for request in requests]
    return {'demoFixture': True, 'allocationImplemented': True, 'physicalTransportImplemented': False,
            'fixtureRemoval': 'TEST_ARRANGEMENT_ONLY',
            'cellUnload': {'fullDecision': denied.to_dict(), 'fullModel': full,
                           'afterFixtureRemovalDecision': approved.to_dict(), 'allocatedModel': held.inspect()},
            'lastSlotCompetition': {'decisions': decisions, 'model': competition.inspect()}}
