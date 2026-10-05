"""Offline work fixture: cell handoffs here are NOT simulated AGV transport."""
from .model import FactoryModel, Location, LocationType
from .run_configuration import CELLS, RunConfiguration


def demo_work(configuration: RunConfiguration) -> dict:
    model = FactoryModel(configuration, allow_initial_fixtures=True, quality_results=('PASS',))
    body = model.register_fixture_body(Location(LocationType.CELL, CELLS[0]))
    for cell_id in CELLS:
        if model.body(body.body_id).location.location_id != cell_id:
            # Test arrangement only; dispatch/reservation/pickup is implemented later.
            model._transfer_ownership(body.body_id, model.body(body.body_id).location,
                                      Location(LocationType.CELL, cell_id))
        operation = model.start_work(cell_id)
        tick_ms = configuration.factory['tickMs']
        model.advance(((operation.required_ms + tick_ms - 1) // tick_ms) * tick_ms)
    result = model.inspect()
    result.update(demoFixture=True, transportImplemented=False,
                  qualityMode='FIXED_PASS', handoffs='TEST_FIXTURE_ONLY')
    return result
