"""Deterministic offline cancellation/failure/parts scenarios with v1 output."""
from .logistics import VehicleState
from .model import CellState, FactoryModel, LocationType, ModelError
from .run_configuration import CELLS, RunConfiguration


def demo_scenarios(configuration: RunConfiguration) -> dict:
    model = FactoryModel(configuration)
    body = model.register_body()
    cancelled_id = model.assign_transport(body.body_id).transport_id
    model.cancel_transport(cancelled_id)
    count = len(model.events)
    model.cancel_transport(cancelled_id)
    repeated_cancel_added = len(model.events) - count
    model.publish_snapshot()
    retry_id = model.assign_transport(body.body_id).transport_id
    model.delay_transport(retry_id, 300)
    model.set_quality_pattern(('FAIL', 'PASS'))
    model.fail_cell('ASM-01')
    model.start_transport(retry_id)
    parts_id = model.assign_parts('ASM-01').transport_id
    model.start_transport(parts_id)
    for _ in range(5000):
        model.tick()
        if model.body(body.body_id).location.location_type == LocationType.BUFFER:
            break
    else:
        raise ModelError('Scenario demo exceeded 5000 ticks before arrival')
    model.publish_snapshot()  # Arrival is allowed into Bay while target cell is DOWN.
    model.recover_cell('ASM-01')
    model.enter_cell(body.body_id)
    model.tick()
    model.fail_cell('ASM-01')
    operation_id = model.cell('ASM-01').operation_id
    elapsed_before = next(op.elapsed_ms for op in model.operations if op.operation_id == operation_id)
    model.advance(configuration.factory['tickMs'] * 5)
    elapsed_during_failure = next(op.elapsed_ms for op in model.operations if op.operation_id == operation_id)
    model.publish_snapshot()
    model.recover_cell('ASM-01')
    for _ in range(5000):
        model.tick()
        for cell in reversed(CELLS):
            waiting = model.bodies_at(LocationType.BUFFER, 'BAY-' + cell)
            if waiting and model.cell(cell).state == CellState.IDLE:
                model.enter_cell(waiting[0].body_id)
        if (model.body(body.body_id).location.location_type == LocationType.RESULT
                and all(v.state == VehicleState.IDLE for v in model.vehicles)):
            break
    else:
        raise ModelError('Scenario demo exceeded 5000 ticks before drain')
    trip = model.transport(retry_id)
    count = len(model.events)
    model.complete_transport(trip.transport_id)
    repeated_arrival_added = len(model.events) - count
    model.finish_run()
    return {'modelPreview': True, 'networkConnected': False,
            'scenarioSummary': {'cancelledTransportId': cancelled_id, 'retriedTransportId': retry_id,
                                'repeatedCancelAddedEvents': repeated_cancel_added,
                                'repeatedArrivalAddedEvents': repeated_arrival_added,
                                'workBeforeFailureMs': elapsed_before, 'workDuringFailureMs': elapsed_during_failure,
                                'partsTransportId': parts_id},
            'finalSnapshot': model.snapshot(), 'events': [event.to_dict() for event in model.events]}
