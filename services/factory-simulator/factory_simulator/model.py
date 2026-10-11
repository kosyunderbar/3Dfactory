"""Registration, ownership and cell work/inspection, with cell work, atomic allocation and tick-driven transport."""
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import StrEnum
from functools import wraps
import re
import random
from threading import get_ident
from typing import Callable
from uuid import uuid4

from .run_configuration import CELLS, RunConfiguration
from .logistics import PartsKit, CellEntry, DispatchDecision, Transport, TransportStatus, Vehicle, VehicleState
from .motion import Motion, empty_motion, route_speed
from .events import EventJournal, transition_facts
from . import lane_traffic
from .traffic import reserve_motion, remaining_path, yield_if_deadlocked, validate_positions


class ModelError(ValueError):
    """Rejected model command; existing model state is unchanged."""


class LocationType(StrEnum):
    INPUT = 'INPUT'
    CELL = 'CELL'
    BUFFER = 'BUFFER'
    VEHICLE = 'VEHICLE'
    RESULT = 'RESULT'
    STORE = 'STORE'
    PARTS_DOCK = 'PARTS_DOCK'


@dataclass(frozen=True)
class Location:
    location_type: LocationType
    location_id: str
    slot_id: str | None = None

    def __post_init__(self) -> None:
        try:
            object.__setattr__(self, 'location_type', LocationType(self.location_type))
        except (ValueError, TypeError):
            raise ModelError('Unknown body location type') from None
        if not isinstance(self.location_id, str) or not self.location_id:
            raise ModelError('Body location ID is required')
        if self.location_type != LocationType.BUFFER and self.slot_id is not None:
            raise ModelError('Only BUFFER locations may have a slot ID')


class BodyStatus(StrEnum):
    WAITING = 'WAITING'
    PROCESSING = 'PROCESSING'
    WAITING_UNLOAD = 'WAITING_UNLOAD'
    IN_TRANSIT = 'IN_TRANSIT'
    COMPLETED = 'COMPLETED'


class InspectionResult(StrEnum):
    NOT_INSPECTED = 'NOT_INSPECTED'
    PASS = 'PASS'
    FAIL = 'FAIL'


class CellState(StrEnum):
    IDLE = 'IDLE'
    RUNNING = 'RUNNING'
    BLOCKED = 'BLOCKED'
    DOWN = 'DOWN'


@dataclass(frozen=True)
class CellWork:
    cell_id: str
    state: CellState = CellState.IDLE
    operation_id: str | None = None
    blocked_reason: str | None = None
    resume_state: CellState | None = None


@dataclass(frozen=True)
class Operation:
    operation_id: str
    cell_id: str
    body_id: str
    required_ms: int
    elapsed_ms: int
    started_at: str
    completed_at: str | None = None

    def to_dict(self) -> dict:
        return {'operationId': self.operation_id, 'cellId': self.cell_id,
                'equipmentId': self.cell_id, 'unitId': self.body_id,
                'status': 'COMPLETED' if self.completed_at is not None else 'RUNNING',
                'requiredWorkMs': self.required_ms, 'elapsedWorkMs': self.elapsed_ms,
                'durationMs': self.elapsed_ms if self.completed_at is not None else None,
                'startedAt': self.started_at, 'completedAt': self.completed_at}


@dataclass(frozen=True)
class Inspection:
    inspection_id: str
    body_id: str
    result: InspectionResult
    inspected_at: str

    def to_dict(self) -> dict:
        return {'inspectionId': self.inspection_id, 'equipmentId': 'QC-01',
                'unitId': self.body_id, 'result': self.result.value,
                'defectCode': 'SIM_DEFECT_01' if self.result == InspectionResult.FAIL else None,
                'inspectedAt': self.inspected_at}


@dataclass(frozen=True)
class Body:
    body_id: str
    tag_id: str
    model_code: str
    spec_code: str
    created_at: str
    location: Location
    status: BodyStatus = BodyStatus.WAITING
    completed_cell_ids: tuple[str, ...] = ()
    inspection_result: InspectionResult = InspectionResult.NOT_INSPECTED
    inspected_at: str | None = None
    transport_id: str | None = None
    reservation_id: str | None = None

    @property
    def next_cell_id(self) -> str | None:
        return CELLS[len(self.completed_cell_ids)] if len(self.completed_cell_ids) < len(CELLS) else None

    def to_dict(self) -> dict:
        return {'bodyId': self.body_id, 'tagId': self.tag_id,
                'modelCode': self.model_code, 'specCode': self.spec_code,
                'createdAt': self.created_at, 'locationType': self.location.location_type.value,
                'locationId': self.location.location_id, 'locationSlotId': self.location.slot_id,
                'status': self.status.value, 'completedCellIds': list(self.completed_cell_ids),
                'currentCellId': self.location.location_id if self.location.location_type == LocationType.CELL else None,
                'nextCellId': self.next_cell_id, 'inspectionResult': self.inspection_result.value,
                'inspectedAt': self.inspected_at, 'transportId': self.transport_id,
                'reservationId': self.reservation_id}


def _utc_time(clock: Callable[[], datetime]) -> datetime:
    instant = clock()
    if not isinstance(instant, datetime) or instant.tzinfo is None or instant.utcoffset() is None:
        raise ModelError('Model clock must provide an aware UTC-convertible datetime')
    return instant.astimezone(timezone.utc)


def _timestamp(instant: datetime) -> str:
    return instant.isoformat(timespec='milliseconds').replace('+00:00', 'Z')


def recorded(method):
    @wraps(method)
    def change(self, *args, **kwargs):
        self._assert_writer()
        if self._finished and method.__name__ != 'finish_run':
            raise ModelError('Finished run cannot accept new changes')
        if self._record_depth:
            return method(self, *args, **kwargs)
        with self._state_change():
            event_mark = len(self._journal.records)
            before = self._facts_state()
            self._record_depth += 1
            try:
                result = method(self, *args, **kwargs)
            finally:
                self._record_depth -= 1
            self._emit_changes(before)
            if self._event_sink is not None:
                self._event_sink(tuple(self._journal.records[event_mark:]))
            return result
    return change


class FactoryModel:
    """One writer, immutable reads, one canonical location per registered body.

    _transfer_ownership arranges explicit fixtures; it is not dispatch
    authorization and cannot move allocated bodies. assign_transport checks allocation conditions. start_transport/enter_cell own runtime handoffs.
    """
    def __init__(self, configuration: RunConfiguration, *,
                 clock: Callable[[], datetime] | None = None,
                 allow_initial_fixtures: bool = False,
                 quality_results: tuple[str, ...] | None = None):
        if not isinstance(configuration, RunConfiguration):
            raise ModelError('A validated RunConfiguration is required')
        if type(allow_initial_fixtures) is not bool:
            raise ModelError('allow_initial_fixtures must be boolean')
        if quality_results is not None:
            if not isinstance(quality_results, tuple) or not quality_results or any(result not in ('PASS', 'FAIL') for result in quality_results):
                raise ModelError('quality_results must be a nonempty tuple of PASS/FAIL')
        self._quality_results = quality_results
        self._random = random.Random(configuration.seed)
        self._configuration = configuration
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        started = _utc_time(self._clock)
        self._run_id = f'run-{started:%Y%m%d}-{uuid4().hex}'
        self._started_at = _timestamp(started)
        self._owner_thread = get_ident()
        self._allow_initial_fixtures = allow_initial_fixtures
        self._bodies: dict[str, Body] = {}
        self._next_body_number = 1
        self._cells = {cell_id: CellWork(cell_id) for cell_id in CELLS}
        self._operations: dict[str, Operation] = {}
        self._inspections: dict[str, Inspection] = {}
        self._next_operation_number = 1
        self._next_inspection_number = 1
        self._vehicles = {item['vehicleId']: Vehicle(item['vehicleId'], item['kind'],
                          item['initialPosition']['x'], item['initialPosition']['y'])
                          for item in configuration.factory['vehicles']}
        self._transports: dict[str, Transport] = {}
        self._next_transport_number = 1
        self._next_reservation_number = 1
        self._cell_entries: list[CellEntry] = []
        self._motions: dict[str, Motion] = {}
        self._traffic_reserved = {}
        self._traffic_tick_paths = {}
        self._traffic_waiting = set()
        self._traffic_yield = {}
        self._traffic_heading = {}
        self._lane_wait_since = {}
        self._cell_waiters = {}
        self._final_returning = set()
        self._lane_graph = lane_traffic.graph(configuration.factory['traffic']) if lane_traffic.enabled(self) else {}
        self._flow_started = False
        self._sim_elapsed_ms = 0
        self._paused = False
        self._has_started_activity = False
        self._finished = False
        self._record_depth = 0
        self._event_sink = None
        self._parts: dict[str, PartsKit] = {}
        self._next_parts_number = 1
        self._parts_wait_ms = {'ASM-01':0, 'ASM-02':0}
        from . import parts_supply
        parts_supply.initialize(self)
        self._dispatch_holds: set[str] = set()
        self._scenarios: list[dict] = []
        self._transport_delays: dict[str, int] = {}
        self._quality_offset = 0
        self._journal = EventJournal(self.run_id, configuration.source_id)
        self._journal.append('RUN_STARTED', self._started_at,
                             {'seed': configuration.seed, 'config': configuration.to_dict()['config']})

    @property
    def run_id(self) -> str:
        return self._run_id

    @property
    def configuration(self) -> RunConfiguration:
        return self._configuration

    @property
    def bodies(self) -> tuple[Body, ...]:
        return tuple(self._bodies.values())

    def body(self, body_id: str) -> Body:
        try:
            return self._bodies[body_id]
        except KeyError:
            raise ModelError(f'Unknown body: {body_id}') from None

    def body_by_tag(self, tag_id: str) -> Body:
        for body in self._bodies.values():
            if body.tag_id == tag_id:
                return body
        raise ModelError(f'Unknown tag: {tag_id}')

    def bodies_at(self, location_type: LocationType, location_id: str) -> tuple[Body, ...]:
        return tuple(body for body in self._bodies.values()
                     if body.location.location_type == location_type and body.location.location_id == location_id)

    @recorded
    def register_body(self, *, model_code: str = 'DEMO-EV-A', spec_code: str = 'STANDARD',
                      body_id: str | None = None, tag_id: str | None = None) -> Body:
        return self._register(Location(LocationType.INPUT, 'BODY-IN'), model_code,
                              spec_code, body_id, tag_id)

    @recorded
    def register_fixture_body(self, location: Location, *, model_code: str = 'DEMO-EV-A',
                              spec_code: str = 'STANDARD', body_id: str | None = None,
                              tag_id: str | None = None,
                              completed_cell_ids: tuple[str, ...] = ()) -> Body:
        self._assert_writer()
        if not isinstance(location, Location):
            raise ModelError('A single Location value is required')
        if not self._allow_initial_fixtures or location.location_type not in (LocationType.CELL, LocationType.BUFFER):
            raise ModelError('Initial CELL/BUFFER placement requires explicit fixture mode')
        cell_id = location.location_id.removeprefix('BAY-')
        if cell_id not in CELLS or completed_cell_ids != CELLS[:CELLS.index(cell_id)]:
            raise ModelError('Fixture history must explicitly match the completed process prefix')
        body = self._register(location, model_code, spec_code, body_id, tag_id)
        seeded = replace(body, completed_cell_ids=completed_cell_ids)
        self._bodies[body.body_id] = seeded
        return seeded

    def _assert_writer(self) -> None:
        if get_ident() != self._owner_thread:
            raise ModelError('All state changes must run on the model owner thread')

    def _validate_location(self, location: Location) -> None:
        if not isinstance(location, Location):
            raise ModelError('A single Location value is required')
        config = self.configuration.factory
        if location.location_type in (LocationType.STORE, LocationType.PARTS_DOCK):
            raise ModelError('Parts locations cannot own bodies')
        if location.location_type == LocationType.VEHICLE:
            if not any(vehicle['vehicleId'] == location.location_id and vehicle['kind'] == 'AGV'
                       for vehicle in config['vehicles']):
                raise ModelError('Only a registered body AGV may own a body')
            return
        if not any(place['locationType'] == location.location_type and place['locationId'] == location.location_id
                   for place in config['locations']):
            raise ModelError('Body location is not registered in this run')
        if location.location_type == LocationType.BUFFER:
            buffer = next(item for item in config['buffers'] if item['bufferId'] == location.location_id)
            if location.slot_id not in buffer['slotIds']:
                raise ModelError('BUFFER location requires one configured slot ID')

    def _check_available(self, location: Location, excluding: str | None = None) -> None:
        self._validate_location(location)
        # INPUT and output areas hold many bodies; a cell, Bay face or AGV holds one.
        if location.location_type in (LocationType.CELL, LocationType.BUFFER, LocationType.VEHICLE):
            if any(body.body_id != excluding and body.location == location for body in self._bodies.values()):
                raise ModelError('Destination is already occupied by another body')
        if location.location_type == LocationType.BUFFER and any(
                transport.destination.location_id == location.location_id and transport.slot_id == location.slot_id
                for transport in self.active_transports):
            raise ModelError('Destination slot is already reserved')
        if location.location_type == LocationType.VEHICLE and self._vehicles[location.location_id].transport_id is not None:
            raise ModelError('Destination vehicle is already allocated')

    def _register(self, location: Location, model_code: str, spec_code: str,
                  body_id: str | None, tag_id: str | None) -> Body:
        self._assert_writer()
        if len(self._bodies) >= self.configuration.factory['maxBodies']:
            raise ModelError('This run has reached maxBodies; completed registrations are retained')
        number = self._next_body_number
        existing_tags = {body.tag_id for body in self._bodies.values()}
        while f'body-{number:05d}' in self._bodies or f'tag-{number:05d}' in existing_tags:
            number += 1
        candidate_body = body_id if body_id is not None else f'body-{number:05d}'
        candidate_tag = tag_id if tag_id is not None else f'tag-{number:05d}'
        for label, value, pattern in [('bodyId', candidate_body, r'body-[0-9]{5,10}'),
                                      ('tagId', candidate_tag, r'tag-[0-9]{5,10}'),
                                      ('modelCode', model_code, r'[A-Z0-9-]{1,32}'),
                                      ('specCode', spec_code, r'[A-Z0-9-]{1,32}')]:
            if not isinstance(value, str) or not re.fullmatch(pattern, value):
                raise ModelError(f'{label}: invalid v1 format')
        if candidate_body in self._bodies or candidate_tag in existing_tags:
            raise ModelError('bodyId and tagId must each be unique within this run')
        self._check_available(location)
        body = Body(candidate_body, candidate_tag, model_code, spec_code,
                    _timestamp(_utc_time(self._clock)), location)
        # Commit only after every check: failed registrations consume no IDs or ownership.
        self._bodies[body.body_id] = body
        self._next_body_number = number + 1
        self._refresh_blocked_cells()
        return body

    def _transfer_ownership(self, body_id: str, expected_source: Location, destination: Location) -> Body:
        self._assert_writer()
        if not self._allow_initial_fixtures:
            raise ModelError("Direct ownership transfer requires explicit fixture mode; use the transport lifecycle")
        body = self.body(body_id)
        if body.transport_id is not None:
            raise ModelError('An allocated body requires the transport lifecycle, not a fixture transfer')
        if body.location != expected_source:
            raise ModelError('Body is no longer at the expected source location')
        self._check_available(destination, excluding=body_id)
        if expected_source == destination:
            return body
        source_cell = self._cells.get(expected_source.location_id) if expected_source.location_type == LocationType.CELL else None
        if source_cell is not None and source_cell.state == CellState.RUNNING:
            raise ModelError('A processing body cannot leave its cell')
        status = body.status
        if status != BodyStatus.COMPLETED:
            status = BodyStatus.IN_TRANSIT if destination.location_type == LocationType.VEHICLE else BodyStatus.WAITING
        moved = replace(body, location=destination, status=status)
        # One replacement removes old ownership and establishes the new one together.
        self._bodies[body_id] = moved
        if source_cell is not None and expected_source != destination:
            self._cells[source_cell.cell_id] = CellWork(source_cell.cell_id)
        self._refresh_blocked_cells()
        return moved

    @property
    def vehicles(self) -> tuple[Vehicle, ...]:
        return tuple(self._vehicles.values())

    @property
    def transports(self) -> tuple[Transport, ...]:
        return tuple(self._transports.values())

    @property
    def active_transports(self) -> tuple[Transport, ...]:
        return tuple(item for item in self.transports
                     if item.status in (TransportStatus.ASSIGNED, TransportStatus.IN_TRANSIT))

    def transport(self, transport_id: str) -> Transport:
        try:
            return self._transports[transport_id]
        except KeyError:
            raise ModelError(f'Unknown transport: {transport_id}') from None

    def buffer(self, buffer_id: str) -> dict:
        """Detached view: counts come from canonical ownership and active transports."""
        config = next((item for item in self.configuration.factory['buffers']
                       if item['bufferId'] == buffer_id), None)
        if config is None:
            raise ModelError(f'Unknown buffer: {buffer_id}')
        slots = []
        for slot_id in config['slotIds']:
            owner = next((body for body in self.bodies if body.location ==
                          Location(LocationType.BUFFER, buffer_id, slot_id)), None)
            reservation = next((item for item in self.active_transports
                                if item.destination.location_type == LocationType.BUFFER
                                and item.destination.location_id == buffer_id and item.slot_id == slot_id), None)
            if owner and reservation:
                raise ModelError('Invalid model: slot cannot be occupied and reserved together')
            arrival = next((item for item in reversed(self.transports)
                            if owner and item.body_id == owner.body_id and item.status == TransportStatus.COMPLETED
                            and item.destination.location_id == buffer_id and item.slot_id == slot_id), None)
            slots.append({'slotId': slot_id, 'status': 'OCCUPIED' if owner else 'RESERVED' if reservation else 'FREE',
                          'bodyId': owner.body_id if owner else reservation.body_id if reservation else None,
                          'vehicleId': reservation.vehicle_id if reservation else None,
                          'transportId': reservation.transport_id if reservation else arrival.transport_id if arrival else None,
                          'reservationId': reservation.reservation_id if reservation else arrival.reservation_id if arrival else None})
        waiting = sum(item['status'] == 'OCCUPIED' for item in slots)
        reserved = sum(item['status'] == 'RESERVED' for item in slots)
        return {'bufferId': buffer_id, 'cellId': config['cellId'], 'capacity': config['capacity'],
                'waitingCount': waiting, 'reservedInboundCount': reserved,
                'availableSlots': config['capacity'] - waiting - reserved, 'slots': slots}

    @property
    def direct_delivery(self) -> bool:
        return self.configuration.factory.get('traffic', {}).get('policyVersion', 1) >= 2

    def _cell_accepts_delivery(self, cell_id: str) -> bool:
        from .parts_supply import has_parts
        return (self.cell(cell_id).state == CellState.IDLE
                and has_parts(self, cell_id)
                and not self.bodies_at(LocationType.CELL, cell_id)
                and not any(t.destination == Location(LocationType.CELL,cell_id) for t in self.active_transports))

    def _dispatch_destination(self, body: Body) -> Location:
        if body.next_cell_id is not None:
            if (self.direct_delivery and self._cell_accepts_delivery(body.next_cell_id)
                    and (body.location.location_type == LocationType.BUFFER
                         or (not self.bodies_at(LocationType.BUFFER,'BAY-'+body.next_cell_id)
                             and not any(t.body_id != body.body_id and t.destination == Location(LocationType.BUFFER,'BAY-'+body.next_cell_id)
                                         for t in self.active_transports)))):
                return Location(LocationType.CELL,body.next_cell_id)
            return Location(LocationType.BUFFER, 'BAY-' + body.next_cell_id)
        return Location(LocationType.RESULT, 'GOOD' if body.inspection_result == InspectionResult.PASS else 'HOLD')

    def _available_agvs(self) -> tuple[Vehicle, ...]:
        return tuple(vehicle for vehicle in self.vehicles
                     if vehicle.kind == 'AGV' and vehicle.state in (VehicleState.IDLE, VehicleState.RETURNING)
                     and vehicle.transport_id is None
                     and lane_traffic.stopped(self, vehicle.vehicle_id)
                     and not lane_traffic.waiting_for_work(self, vehicle.vehicle_id)
                     and not self.bodies_at(LocationType.VEHICLE, vehicle.vehicle_id))

    def _blocked_reason(self, body: Body) -> str:
        if body.transport_id is not None:
            return 'WAITING_PICKUP'
        destination = self._dispatch_destination(body)
        if destination.location_type == LocationType.BUFFER and self.buffer(destination.location_id)['availableSlots'] <= 0:
            return 'BUFFER_FULL'
        if not self._available_agvs():
            return 'NO_VEHICLE'
        return 'WAITING_PICKUP'  # Awaiting an explicit dispatch request; no approval implied.

    def _refresh_blocked_cells(self) -> None:
        for cell_id, cell in self._cells.items():
            if cell.state == CellState.BLOCKED:
                owner = self.bodies_at(LocationType.CELL, cell_id)[0]
                self._cells[cell_id] = replace(cell, blocked_reason=self._blocked_reason(owner))

    @recorded
    def assign_transport(self, body_id: str) -> DispatchDecision:
        """Check slot + vehicle and publish one allocation, leaving cargo at source.

        Calls are serialized by the model owner thread. Resource denial updates
        only the blocking reason; malformed commands consume no IDs/resources.
        """
        self._assert_writer()
        body = self.body(body_id)
        if self._paused:
            raise ModelError('Dispatch is unavailable while paused')
        if body.transport_id is not None:
            transport = self.transport(body.transport_id)
            return DispatchDecision(True, 'WAITING_PICKUP' if transport.status == TransportStatus.ASSIGNED else 'IN_TRANSIT', body.transport_id)
        if body.location.location_type == LocationType.INPUT:
            if body.status != BodyStatus.WAITING or body.completed_cell_ids or body.inspection_result != InspectionResult.NOT_INSPECTED:
                raise ModelError('Input dispatch requires an unprocessed waiting body')
        elif body.location.location_type == LocationType.CELL:
            cell = self.cell(body.location.location_id)
            if (cell.state != CellState.BLOCKED or cell.operation_id is None
                    or self._operations[cell.operation_id].completed_at is None
                    or body.status not in (BodyStatus.WAITING_UNLOAD, BodyStatus.COMPLETED)):
                raise ModelError('Cell dispatch requires completed work and a held body')
        elif self.direct_delivery and body.location.location_type == LocationType.BUFFER:
            if (body.status != BodyStatus.WAITING or body.next_cell_id is None
                    or body.location.location_id != 'BAY-'+body.next_cell_id):
                raise ModelError('Bay pickup requires a body waiting for its next cell')
            if not self._cell_accepts_delivery(body.next_cell_id):
                return DispatchDecision(False,'CELL_BUSY')
        else:
            raise ModelError('Body dispatch source must be INPUT or completed CELL')
        destination = self._dispatch_destination(body)
        slot_id = None
        if destination.location_type == LocationType.BUFFER:
            buffer = self.buffer(destination.location_id)
            if buffer['availableSlots'] <= 0:
                self._refresh_blocked_cells()
                return DispatchDecision(False, 'BUFFER_FULL')
            slot_id = next(item['slotId'] for item in buffer['slots'] if item['status'] == 'FREE')
        vehicles = self._available_agvs()
        if not vehicles:
            self._refresh_blocked_cells()
            return DispatchDecision(False, 'NO_VEHICLE')
        pickup_x, pickup_y = self._point(body.location)
        vehicle = min(vehicles, key=lambda item: (
            (item.x - pickup_x) ** 2 + (item.y - pickup_y) ** 2, item.vehicle_id))
        route = next((item for item in self.configuration.factory['routes']
                      if item['cargoType'] == 'BODY'
                      and item['source']['locationType'] == body.location.location_type
                      and item['source']['locationId'] == body.location.location_id
                      and item['destination']['locationType'] == destination.location_type
                      and item['destination']['locationId'] == destination.location_id), None)
        if route is None:
            raise ModelError('No configured route for this body process')
        reservation_id = f'reserve-{self._next_reservation_number:05d}' if slot_id else None
        transport = Transport(f'transport-{self._next_transport_number:05d}', vehicle.vehicle_id,
                              route['routeId'], body.body_id, body.location, destination,
                              reservation_id, slot_id, _timestamp(_utc_time(self._clock)))
        allocated_body = replace(body, transport_id=transport.transport_id, reservation_id=reservation_id)
        allocated_vehicle = replace(vehicle, state=VehicleState.TO_PICKUP, transport_id=transport.transport_id)
        # No writes before all validation, route selection and clock conversion succeed.
        self._transports[transport.transport_id] = transport
        self._bodies[body_id] = allocated_body
        self._vehicles[vehicle.vehicle_id] = allocated_vehicle
        # Interrupt an empty return only after the new allocation is valid.
        # start_transport then builds the pickup motion from the actual position.
        self._motions.pop(vehicle.vehicle_id, None)
        self._cell_waiters.pop(vehicle.vehicle_id, None)
        self._traffic_reserved.pop(vehicle.vehicle_id, None)
        self._traffic_waiting.discard(vehicle.vehicle_id)
        self._lane_wait_since.pop(vehicle.vehicle_id, None)
        self._traffic_yield.pop(vehicle.vehicle_id, None)
        self._next_transport_number += 1
        self._dispatch_holds.discard(body_id)
        if reservation_id is not None:
            self._next_reservation_number += 1
        self._refresh_blocked_cells()
        return DispatchDecision(True, 'WAITING_PICKUP', transport.transport_id)

    @contextmanager
    def _state_change(self):
        """Rollback one writer transition, including any immediate redispatch."""
        collections = ('_parts', '_parts_wait_ms', '_dispatch_holds', '_scenarios', '_transport_delays', '_bodies', '_cells', '_operations', '_inspections', '_vehicles',
                       '_transports', '_motions', '_cell_entries', '_traffic_reserved', '_traffic_waiting', '_traffic_yield', '_traffic_tick_paths', '_traffic_heading', '_lane_wait_since', '_cell_waiters', '_final_returning')
        values = ('_next_body_number', '_next_operation_number', '_next_inspection_number',
                  '_next_transport_number', '_next_reservation_number', '_sim_elapsed_ms',
                  '_paused', '_flow_started', '_has_started_activity', '_finished', '_quality_results',
                  '_quality_offset', '_next_parts_number')
        checkpoint = {name: getattr(self, name).copy() for name in collections}
        checkpoint.update({name: getattr(self, name) for name in values})
        random_state = self._random.getstate()
        event_mark = len(self._journal.records)
        sequence_mark = self._journal.next_sequence
        try:
            yield
        except Exception:
            for name, value in checkpoint.items():
                setattr(self, name, value)
            self._random.setstate(random_state)
            del self._journal.records[event_mark:]
            self._journal.next_sequence = sequence_mark
            raise

    def _route(self, transport: Transport):
        return next(item for item in self.configuration.factory['routes'] if item['routeId'] == transport.route_id)

    def _point(self, location: Location) -> tuple[float, float]:
        item = next(item for item in self.configuration.factory['locations']
                    if item['locationType'] == location.location_type and item['locationId'] == location.location_id)
        return item['x'], item['y']

    @recorded
    def start_transport(self, transport_id: str) -> Motion:
        """Enable this approved vehicle's pickup movement; cargo stays at source."""
        self._assert_writer()
        transport = self.transport(transport_id)
        if self._paused or transport.status not in (TransportStatus.ASSIGNED, TransportStatus.IN_TRANSIT):
            raise ModelError('Transport start requires an unpaused active allocation')
        vehicle = self._vehicles[transport.vehicle_id]
        if vehicle.vehicle_id in self._motions:
            return self._motions[vehicle.vehicle_id]  # Repeated start never resets elapsed time.
        body = self._cargo(transport)
        if (transport.status != TransportStatus.ASSIGNED or vehicle.state != VehicleState.TO_PICKUP
                or vehicle.transport_id != transport_id or body.transport_id != transport_id
                or body.location != transport.source):
            raise ModelError('Pickup allocation/source mismatch')
        motion = empty_motion(VehicleState.TO_PICKUP, (vehicle.x, vehicle.y), self._point(transport.source),
                              route_speed(self._route(transport)), self.configuration.factory['tickMs'])
        self._motions[vehicle.vehicle_id] = motion
        self._has_started_activity = True
        self._flow_started = True
        return motion

    @recorded
    def redispatch(self) -> tuple[DispatchDecision, ...]:
        self._assert_writer()
        with self._state_change():
            return self._redispatch()

    def _redispatch(self) -> tuple[DispatchDecision, ...]:
        """Drain completed downstream cells before new input, on the same writer."""
        self._assert_writer()
        if self._paused:
            raise ModelError('Redispatch is unavailable while paused')
        self._flow_started = True
        candidates = []
        from .parts_supply import replenish
        replenish(self)
        for cell_id in reversed(CELLS):
            if self.cell(cell_id).state == CellState.BLOCKED:
                candidates.extend(self.bodies_at(LocationType.CELL, cell_id))
        if self.direct_delivery:
            for cell_id in reversed(CELLS):
                if self._cell_accepts_delivery(cell_id):
                    candidates.extend(self.bodies_at(LocationType.BUFFER,'BAY-'+cell_id))
        candidates.extend(body for body in self.bodies_at(LocationType.INPUT, 'BODY-IN')
                          if body.status == BodyStatus.WAITING and not body.completed_cell_ids)
        decisions = []
        full_destinations = set()
        for body in candidates:
            if body.transport_id is not None or body.body_id in self._dispatch_holds:
                continue
            destination = self._dispatch_destination(body)
            if destination in full_destinations:
                continue
            if not self._available_agvs():
                # A completed cell outranks an empty trip fetching new input.
                # Loaded cargo and pickups already loading are never interrupted.
                if not self.configuration.factory.get('traffic') or body.location.location_type == LocationType.INPUT:
                    break
                if (destination.location_type == LocationType.BUFFER
                        and self.buffer(destination.location_id)['availableSlots'] <= 0):
                    continue
                if not self._prioritize_completed_body(body):
                    continue
            decision = self.assign_transport(body.body_id)
            if decision.reason == 'BUFFER_FULL':
                full_destinations.add(destination)
            decisions.append(decision)
            if decision.approved:
                self.start_transport(decision.transport_id)
        self._refresh_blocked_cells()
        return tuple(decisions)

    @recorded
    def _prioritize_completed_body(self, body: Body) -> bool:
        if not self.configuration.factory.get('traffic') or body.location.location_type != LocationType.CELL:
            return False
        candidates = [trip for trip in self._transports.values()
                      if trip.status == TransportStatus.ASSIGNED and trip.cargo_type == 'BODY'
                      and trip.source.location_type == LocationType.INPUT
                      and self._vehicles[trip.vehicle_id].state == VehicleState.TO_PICKUP
                      and trip.vehicle_id not in self._traffic_yield
                      and lane_traffic.stopped(self, trip.vehicle_id)]
        if not candidates:
            return False
        x, y = self._point(body.location)
        trip = min(candidates, key=lambda t: ((self._vehicles[t.vehicle_id].x-x)**2
                                              + (self._vehicles[t.vehicle_id].y-y)**2, t.vehicle_id))
        self._cancel_transport(trip.transport_id, reason='PRIORITY_REDISPATCH', hold=False)
        return True

    @property
    def cell_entries(self) -> tuple[CellEntry, ...]:
        return tuple(self._cell_entries)

    @recorded
    def enter_cell(self, body_id: str) -> Operation | DispatchDecision:
        self._assert_writer()
        with self._state_change():
            return self._enter_cell(body_id)

    def _enter_cell(self, body_id: str) -> Operation | DispatchDecision:
        """Bay ownership -> processing cell + operation + free slot, together."""
        self._assert_writer()
        body = self.body(body_id)
        if self.direct_delivery:
            if body.location.location_type != LocationType.BUFFER:
                raise ModelError('Cell admission requires physical AGV delivery')
            decision = self.assign_transport(body_id)
            if decision.approved and self.transport(decision.transport_id).vehicle_id not in self._motions:
                self.start_transport(decision.transport_id)
            return decision
        if (self._paused or body.location.location_type != LocationType.BUFFER
                or body.status != BodyStatus.WAITING or body.transport_id is not None
                or body.inspection_result != InspectionResult.NOT_INSPECTED
                or body.next_cell_id is None or body.location.location_id != 'BAY-' + body.next_cell_id):
            raise ModelError('Cell entry requires an unpaused waiting body in its next Bay')
        cell_id = body.next_cell_id
        if self.cell(cell_id).state != CellState.IDLE or self.bodies_at(LocationType.CELL, cell_id):
            raise ModelError('Cell entry requires an empty idle cell')
        slot = next(item for item in self.buffer(body.location.location_id)['slots']
                    if item['slotId'] == body.location.slot_id)
        if slot['status'] != 'OCCUPIED' or slot['bodyId'] != body_id:
            raise ModelError('Cell entry requires this body to own its Bay slot')
        operation = self._new_operation(cell_id, body)
        entry = CellEntry(body_id, cell_id, body.location.location_id, body.location.slot_id,
                          operation.operation_id, slot['transportId'], slot['reservationId'], operation.started_at,
                          self.buffer(body.location.location_id)['availableSlots'] + 1)
        processing = replace(body, location=Location(LocationType.CELL, cell_id), status=BodyStatus.PROCESSING)
        self._operations[operation.operation_id] = operation
        self._bodies[body_id] = processing
        self._cells[cell_id] = CellWork(cell_id, CellState.RUNNING, operation.operation_id)
        self._next_operation_number += 1
        self._has_started_activity = True
        self._cell_entries.append(entry)
        self._refresh_blocked_cells()
        self.redispatch()
        return operation

    def _validate_cargo(self, transport: Transport, vehicle: Vehicle, *, at_source: bool) -> Body:
        body = self._cargo(transport)
        expected = transport.source if at_source else Location(LocationType.VEHICLE, vehicle.vehicle_id)
        if (body.transport_id != transport.transport_id or (body.reservation_id if transport.cargo_type == 'BODY' else None) != transport.reservation_id
                or body.location != expected or vehicle.transport_id != transport.transport_id):
            raise ModelError('Transport cargo ownership mismatch')
        if transport.destination.location_type == LocationType.BUFFER:
            slot = next(item for item in self.buffer(transport.destination.location_id)['slots']
                        if item['slotId'] == transport.slot_id)
            if (slot['status'] != 'RESERVED' or slot['transportId'] != transport.transport_id
                    or slot['reservationId'] != transport.reservation_id
                    or slot['vehicleId'] != vehicle.vehicle_id or slot['bodyId'] != body.body_id):
                raise ModelError('Transport requires its own intact destination reservation')
        return body

    def _advance_vehicles(self, tick_ms: int) -> None:
        # Retain completed paths through this whole tick. A later vehicle must not
        # enter space swept earlier in the same simultaneous simulation interval.
        self._traffic_tick_paths = dict(self._traffic_reserved)
        lane_traffic.clear_idle_docks(self)
        motions = tuple(self._motions.items())
        if lane_traffic.enabled(self):
            motions = sorted(motions, key=lambda pair:(pair[0] not in self._traffic_reserved, self._lane_wait_since.get(pair[0], self.sim_elapsed_ms), pair[0]))
        for vehicle_id, motion in motions:
            vehicle = self._vehicles[vehicle_id]
            motion = reserve_motion(self, vehicle_id, motion)
            if motion is None:
                continue
            self._motions[vehicle_id] = motion
            advanced = replace(motion, elapsed_ms=min(motion.required_ms, motion.elapsed_ms + tick_ms))
            x, y = advanced.position()
            if advanced.segments: lane_traffic.progressed(self, vehicle_id, advanced)
            updated_vehicle = replace(vehicle, x=x, y=y)
            if advanced.elapsed_ms < advanced.required_ms:
                self._vehicles[vehicle_id] = updated_vehicle
                self._motions[vehicle_id] = advanced
                if vehicle_id in self._traffic_reserved and not advanced.segments:
                    self._traffic_reserved[vehicle_id] = remaining_path(advanced)
                continue
            self._traffic_reserved.pop(vehicle_id, None)
            self._traffic_waiting.discard(vehicle_id)
            if vehicle_id in self._traffic_yield:
                original = self._traffic_yield.pop(vehicle_id)
                self._vehicles[vehicle_id] = updated_vehicle
                self._motions[vehicle_id] = Motion(original.phase, ((x,y), original.points[-1]), tick_ms)
                continue
            if motion.phase == VehicleState.RETURNING:
                self._final_returning.discard(vehicle_id)
                self._vehicles[vehicle_id] = replace(updated_vehicle, state=VehicleState.IDLE)
                del self._motions[vehicle_id]
                continue
            transport = self.transport(vehicle.transport_id)
            route = self._route(transport)
            if motion.phase == VehicleState.TO_PICKUP:
                self._vehicles[vehicle_id] = replace(updated_vehicle, state=VehicleState.LOADING)
                self._motions[vehicle_id] = Motion(VehicleState.LOADING, ((x, y), (x, y)), tick_ms)
            elif motion.phase == VehicleState.LOADING:
                if transport.source.location_type == LocationType.CELL and self.cell(transport.source.location_id).state == CellState.DOWN:
                    continue
                body = self._validate_cargo(transport, vehicle, at_source=True)
                if (self.direct_delivery and transport.destination.location_type == LocationType.BUFFER
                        and self._dispatch_destination(body).location_type == LocationType.CELL):
                    # Recheck immediately before loading: an initially busy cell
                    # may now be empty. Release the Bay reservation explicitly.
                    self._cancel_transport(transport.transport_id,reason='DIRECT_DELIVERY_AVAILABLE',hold=False)
                    decision = self.assign_transport(body.body_id)
                    self.start_transport(decision.transport_id)
                    continue
                if self.bodies_at(LocationType.VEHICLE, vehicle_id) or (x, y) != self._point(transport.source):
                    raise ModelError('Pickup requires an empty AGV at the source')
                timestamp = _timestamp(_utc_time(self._clock))
                if timestamp < transport.assigned_at:
                    raise ModelError('Pickup clock precedes allocation')
                # Its reservation is valid even at A=0; no second capacity check.
                if transport.cargo_type == 'BODY':
                    self._bodies[body.body_id] = replace(body, location=Location(LocationType.VEHICLE, vehicle_id),
                        status=BodyStatus.COMPLETED if body.status == BodyStatus.COMPLETED else BodyStatus.IN_TRANSIT)
                else:
                    self._parts[body.parts_kit_id] = replace(body, location=Location(LocationType.VEHICLE, vehicle_id))
                self._transports[transport.transport_id] = replace(transport, status=TransportStatus.IN_TRANSIT, started_at=timestamp)
                if transport.source.location_type == LocationType.CELL:
                    self._cells[transport.source.location_id] = CellWork(transport.source.location_id)
                self._vehicles[vehicle_id] = replace(updated_vehicle, state=VehicleState.MOVING)
                points = tuple((point['x'], point['y']) for point in route['points'])
                self._motions[vehicle_id] = Motion(VehicleState.MOVING, points, route['travelDurationMs'] + self._transport_delays.get(transport.transport_id, 0))
            elif motion.phase == VehicleState.MOVING:
                self._vehicles[vehicle_id] = replace(updated_vehicle, state=VehicleState.UNLOADING)
                self._motions[vehicle_id] = Motion(VehicleState.UNLOADING, ((x, y), (x, y)), tick_ms)
            elif motion.phase == VehicleState.UNLOADING:
                if (transport.destination.location_type == LocationType.CELL
                        and self.cell(transport.destination.location_id).state == CellState.DOWN):
                    continue
                self._motions[vehicle_id] = advanced
                self._vehicles[vehicle_id] = updated_vehicle
                self.complete_transport(transport.transport_id)

    @property
    def sim_elapsed_ms(self) -> int:
        return self._sim_elapsed_ms

    @property
    def operations(self) -> tuple[Operation, ...]:
        return tuple(self._operations.values())

    @property
    def inspections(self) -> tuple[Inspection, ...]:
        return tuple(self._inspections.values())

    def cell(self, cell_id: str) -> CellWork:
        try:
            return self._cells[cell_id]
        except KeyError:
            raise ModelError(f'Unknown cell: {cell_id}') from None

    @recorded
    def pause(self) -> None:
        self._assert_writer()
        self._paused = True

    @recorded
    def resume(self) -> None:
        self._assert_writer()
        self._paused = False

    @recorded
    def start_work(self, cell_id: str) -> Operation:
        self._assert_writer()
        cell = self.cell(cell_id)
        owners = self.bodies_at(LocationType.CELL, cell_id)
        if self._paused or cell.state != CellState.IDLE or len(owners) != 1:
            raise ModelError('Work requires an unpaused, idle cell holding exactly one body')
        body = owners[0]
        if body.status != BodyStatus.WAITING or body.next_cell_id != cell_id or body.inspection_result != InspectionResult.NOT_INSPECTED:
            raise ModelError('Body must be waiting for this exact next process and not yet inspected')
        operation = self._new_operation(cell_id, body)
        processing = replace(body, status=BodyStatus.PROCESSING)
        running = CellWork(cell_id, CellState.RUNNING, operation.operation_id)
        self._operations[operation.operation_id] = operation
        self._bodies[body.body_id] = processing
        self._cells[cell_id] = running
        self._next_operation_number += 1
        self._has_started_activity = True
        return operation

    def _new_operation(self, cell_id: str, body: Body) -> Operation:
        duration = next(item['workDurationMs'] for item in self.configuration.factory['equipment'] if item['cellId'] == cell_id)
        timestamp = _timestamp(_utc_time(self._clock))
        from .parts_supply import consume
        consume(self, cell_id, body.body_id)
        return Operation(f'operation-{self._next_operation_number:05d}', cell_id, body.body_id,
                              duration, 0, timestamp)

    def tick(self) -> tuple[Operation, ...]:
        return self.advance(self.configuration.factory['tickMs'])

    def advance(self, delta_ms: int) -> tuple[Operation, ...]:
        self._assert_writer()
        tick_ms = self.configuration.factory['tickMs']
        if type(delta_ms) is not int or delta_ms <= 0 or delta_ms % tick_ms:
            raise ModelError('Advance requires positive integer milliseconds in whole configured ticks')
        if self._finished:
            raise ModelError('Finished run cannot advance')
        if self._paused:
            return ()
        completed = []
        for _ in range(delta_ms // tick_ms):
            completed.extend(self._advance_tick(tick_ms))
        return tuple(completed)

    @recorded
    def _advance_tick(self, tick_ms: int) -> tuple[Operation, ...]:
        # A tick stages its changes before publishing them on the single writer.
        from .parts_supply import count_wait
        count_wait(self, tick_ms)
        operations, bodies, cells, inspections = {}, {}, {}, {}
        completing = [self._operations[cell.operation_id] for cell in self._cells.values()
                      if cell.state == CellState.RUNNING and
                      self._operations[cell.operation_id].elapsed_ms + tick_ms >= self._operations[cell.operation_id].required_ms]
        completed_at = _timestamp(_utc_time(self._clock)) if completing else None
        for cell_id in CELLS:
            cell = self._cells[cell_id]
            if cell.state != CellState.RUNNING:
                continue
            operation = self._operations[cell.operation_id]
            elapsed = min(operation.required_ms, operation.elapsed_ms + tick_ms)
            finished = elapsed == operation.required_ms
            updated = replace(operation, elapsed_ms=elapsed, completed_at=completed_at if finished else None)
            operations[operation.operation_id] = updated
            if not finished:
                continue
            body = self.body(operation.body_id)
            history = body.completed_cell_ids + (cell_id,)
            if cell_id == 'QC-01':
                if self._quality_results is not None:
                    result = InspectionResult(self._quality_results[(self._next_inspection_number - 1 - self._quality_offset) % len(self._quality_results)])
                else:
                    result = InspectionResult.FAIL if self._random.random() < self.configuration.factory['failProbability'] else InspectionResult.PASS
                inspection = Inspection(f'inspection-{self._next_inspection_number:05d}', body.body_id, result, completed_at)
                inspections[inspection.inspection_id] = inspection
                bodies[body.body_id] = replace(body, completed_cell_ids=history, status=BodyStatus.COMPLETED,
                                              inspection_result=result, inspected_at=completed_at)
            else:
                bodies[body.body_id] = replace(body, completed_cell_ids=history, status=BodyStatus.WAITING_UNLOAD)
            # No unload or reservation is implied: the body remains inside its cell.
            cells[cell_id] = CellWork(cell_id, CellState.BLOCKED, operation.operation_id, 'WAITING_PICKUP')
        self._operations.update(operations)
        self._bodies.update(bodies)
        self._cells.update(cells)
        self._inspections.update(inspections)
        self._next_inspection_number += len(inspections)
        lane_traffic.queue_final_return(self)
        self._advance_vehicles(tick_ms)
        if self.configuration.factory.get('traffic'):
            validate_positions(self.configuration.factory['traffic'], self._vehicles)
            yield_if_deadlocked(self)
        self._sim_elapsed_ms += tick_ms
        self._refresh_blocked_cells()
        if self._flow_started:
            self.redispatch()
        return tuple(operation for operation in operations.values() if operation.completed_at is not None)

    def inspect(self) -> dict:
        """Local diagnostic only; not a v1 event or complete FACTORY_SNAPSHOT."""
        return {'modelPreview': True, 'modelState': 'ACTIVE' if self._has_started_activity else 'INITIALIZED',
                'factoryRunStarted': self._has_started_activity,
                'runState': 'FINISHED' if self._finished else 'PAUSED' if self._paused else 'RUNNING', 'simElapsedMs': self.sim_elapsed_ms,
                'runId': self.run_id, 'sourceId': self.configuration.source_id,
                'startedAt': self._started_at, 'seed': self.configuration.seed,
                'config': self.configuration.to_dict()['config'],
                'bodies': [body.to_dict() for body in self.bodies],
                'equipment': [self._inspect_cell(cell_id) for cell_id in CELLS],
                'operations': [operation.to_dict() for operation in self.operations],
                'inspections': [inspection.to_dict() for inspection in self.inspections],
                'buffers': [self.buffer(item['bufferId']) for item in self.configuration.factory['buffers']],
                'vehicles': [self._inspect_vehicle(vehicle) for vehicle in self.vehicles],
                'activeTransports': [transport.to_dict() for transport in self.active_transports],
                'transports': [transport.to_dict() for transport in self.transports],
                'cellEntries': [entry.to_dict() for entry in self.cell_entries],
                'transportFlowStarted': self._flow_started,
                'vehicleMotions': [{'vehicleId': vehicle_id, 'phase': motion.phase.value,
                    'remainingMs': motion.required_ms - motion.elapsed_ms}
                    for vehicle_id, motion in self._motions.items()]}

    def _inspect_cell(self, cell_id: str) -> dict:
        cell = self.cell(cell_id)
        owners = self.bodies_at(LocationType.CELL, cell_id)
        operation = self._operations.get(cell.operation_id)
        return {'cellId': cell_id, 'equipmentId': cell_id, 'state': cell.state.value,
                'bodyId': owners[0].body_id if owners else None, 'operationId': cell.operation_id,
                'remainingWorkMs': operation.required_ms - operation.elapsed_ms if operation else 0,
                'blockedReason': cell.blocked_reason, 'resumeState': cell.resume_state.value if cell.resume_state else None,
                'destinationCellId': owners[0].next_cell_id if owners and (cell.state == CellState.BLOCKED or cell.resume_state == CellState.BLOCKED) else None,
                'fixturePendingStart': bool(owners and cell.state == CellState.IDLE)}

    def _inspect_vehicle(self, vehicle: Vehicle) -> dict:
        owners = self.bodies_at(LocationType.VEHICLE, vehicle.vehicle_id)
        result = {'vehicleId': vehicle.vehicle_id, 'kind': vehicle.kind, 'state': vehicle.state.value,
                'position': {'x': vehicle.x, 'y': vehicle.y},
                'bodyId': owners[0].body_id if owners else None, 'partsKitId': next((kit.parts_kit_id for kit in self._parts.values() if kit.location == Location(LocationType.VEHICLE, vehicle.vehicle_id)), None),
                'transportId': vehicle.transport_id}
        if self.configuration.factory.get('traffic'):
            motion = self._motions.get(vehicle.vehicle_id)
            moving = motion is not None and vehicle.vehicle_id in self._traffic_reserved
            result['traffic'] = {'path': [{'x':x,'y':y} for x,y in (motion.points if moving else ((vehicle.x,vehicle.y),(vehicle.x,vehicle.y)))],
                                 'elapsedMs': motion.elapsed_ms if moving else 0,
                                 'durationMs': motion.required_ms if moving else self.configuration.factory['tickMs'],
                                 'waiting': vehicle.vehicle_id in self._traffic_waiting}
            if lane_traffic.enabled(self):
                active = motion is not None and bool(motion.segments)
                result['traffic'].update(
                    path=[dict(x=x,y=y) for x,y in motion.points] if active else [dict(x=vehicle.x,y=vehicle.y)]*2,
                    elapsedMs=motion.elapsed_ms if active else 0,
                    durationMs=motion.required_ms if active else self.configuration.factory['tickMs'],
                    heading=self._traffic_heading.get(vehicle.vehicle_id,0.),
                    segments=[dict(turnMs=s[0],travelMs=s[1],rampMs=s[2],initialHeading=s[3],heading=s[4],peakSpeed=s[5]) for s in motion.segments] if active else [])
        return result
    def _cargo(self, transport: Transport) -> Body | PartsKit:
        return self.body(transport.body_id) if transport.cargo_type == 'BODY' else self._parts[transport.parts_kit_id]

    @property
    def parts(self) -> tuple[PartsKit, ...]:
        return tuple(self._parts.values())

    @recorded
    def assign_parts(self, cell_id: str) -> DispatchDecision:
        if self._paused or cell_id not in ('ASM-01', 'ASM-02'):
            raise ModelError('Parts assignment requires an unpaused assembly destination')
        if len(self._parts) >= self.configuration.factory['maxBodies'] * 2:
            raise ModelError('Synthetic parts registration limit reached')
        from . import parts_supply
        if parts_supply.enabled(self):
            stock = next(s for s in parts_supply.snapshot(self) if s['cellId']==cell_id)
            if stock['available'] + stock['inbound'] >= stock['capacity']:
                return DispatchDecision(False, 'PARTS_FULL')
        vehicle = next((v for v in self.vehicles if v.kind == 'AMR' and (v.state == VehicleState.IDLE or
                        (parts_supply.enabled(self) and v.state == VehicleState.RETURNING and lane_traffic.stopped(self,v.vehicle_id)))
                        and v.transport_id is None and not any(k.location == Location(LocationType.VEHICLE, v.vehicle_id) for k in self.parts)), None)
        if vehicle is None:
            return DispatchDecision(False, 'NO_VEHICLE')
        route = next(r for r in self.configuration.factory['routes'] if r['cargoType'] == 'PARTS'
                     and r['destination']['locationId'] == 'PARTS-' + cell_id)
        source = Location(LocationType.STORE, 'PARTS-STORE')
        kit_id = f'kit-{self._next_parts_number:05d}'
        transport = Transport(f'transport-{self._next_transport_number:05d}', vehicle.vehicle_id, route['routeId'],
                              None, source, Location(LocationType.PARTS_DOCK, 'PARTS-' + cell_id),
                              None, None, _timestamp(_utc_time(self._clock)), cargo_type='PARTS', parts_kit_id=kit_id)
        self._parts[kit_id] = PartsKit(kit_id, source, transport.transport_id)
        self._transports[transport.transport_id] = transport
        self._vehicles[vehicle.vehicle_id] = replace(vehicle, state=VehicleState.TO_PICKUP, transport_id=transport.transport_id)
        self._motions.pop(vehicle.vehicle_id, None)
        self._traffic_reserved.pop(vehicle.vehicle_id, None)
        self._traffic_waiting.discard(vehicle.vehicle_id)
        self._lane_wait_since.pop(vehicle.vehicle_id, None)
        self._next_parts_number += 1
        self._next_transport_number += 1
        return DispatchDecision(True, 'WAITING_PICKUP', transport.transport_id)

    def _scenario(self, action, target, parameters):
        self._scenarios.append({'scenarioId': f'scenario-model-{len(self._scenarios) + 1:05d}',
                               'action': action, 'targetId': target, 'parameters': parameters})

    @recorded
    def cancel_transport(self, transport_id: str) -> Transport:
        return self._cancel_transport(transport_id, reason='SCENARIO_CANCEL', hold=True)

    def _cancel_transport(self, transport_id: str, *, reason: str, hold: bool) -> Transport:
        transport = self.transport(transport_id)
        if transport.status == TransportStatus.CANCELLED:
            return transport
        if self._paused or transport.cargo_type != 'BODY' or transport.status != TransportStatus.ASSIGNED:
            raise ModelError('v1 cancellation requires an unpaused BODY transport before departure')
        vehicle = self._vehicles[transport.vehicle_id]
        if vehicle.state not in (VehicleState.TO_PICKUP, VehicleState.LOADING):
            raise ModelError('Cancellation is only available before loading completes')
        if not lane_traffic.stopped(self, vehicle.vehicle_id):
            raise ModelError('Cancellation requires a stopped lane node')
        body = self._validate_cargo(transport, vehicle, at_source=True)
        timestamp = _timestamp(_utc_time(self._clock))
        if timestamp < transport.assigned_at:
            raise ModelError('Cancellation clock precedes assignment')
        cancelled = replace(transport, status=TransportStatus.CANCELLED, cancelled_at=timestamp, cancel_reason=reason)
        self._transports[transport_id] = cancelled
        self._bodies[body.body_id] = replace(body, transport_id=None, reservation_id=None)
        self._vehicles[vehicle.vehicle_id] = replace(vehicle, state=VehicleState.IDLE, transport_id=None)
        self._motions.pop(vehicle.vehicle_id, None)
        self._cell_waiters.pop(vehicle.vehicle_id, None)
        self._traffic_reserved.pop(vehicle.vehicle_id, None)
        self._traffic_waiting.discard(vehicle.vehicle_id)
        self._lane_wait_since.pop(vehicle.vehicle_id, None)
        self._traffic_yield.pop(vehicle.vehicle_id, None)
        if self.configuration.factory.get('traffic'):
            config = next(v for v in self.configuration.factory['vehicles'] if v['vehicleId'] == vehicle.vehicle_id)
            home = (config['initialPosition']['x'], config['initialPosition']['y'])
            self._vehicles[vehicle.vehicle_id] = replace(vehicle, state=VehicleState.RETURNING, transport_id=None)
            self._motions[vehicle.vehicle_id] = empty_motion(VehicleState.RETURNING, (vehicle.x,vehicle.y), home,
                                                            0.0375, self.configuration.factory['tickMs'])
        if hold:
            self._dispatch_holds.add(body.body_id)
            self._scenario('CANCEL_BEFORE_DEPARTURE', transport_id, {})
        self._refresh_blocked_cells()
        return cancelled

    @recorded
    def complete_transport(self, transport_id: str) -> Transport:
        transport = self.transport(transport_id)
        if transport.status == TransportStatus.COMPLETED:
            return transport
        vehicle = self._vehicles[transport.vehicle_id]
        motion = self._motions.get(vehicle.vehicle_id)
        if (self._paused or transport.status != TransportStatus.IN_TRANSIT
                or vehicle.state != VehicleState.UNLOADING or motion is None
                or motion.elapsed_ms != motion.required_ms
                or (vehicle.x, vehicle.y) != self._point(transport.destination)):
            raise ModelError('Arrival requires completed unloading at the assigned destination')
        cargo = self._validate_cargo(transport, vehicle, at_source=False)
        timestamp = _timestamp(_utc_time(self._clock))
        if timestamp < transport.started_at:
            raise ModelError('Arrival clock precedes departure')
        completed = replace(transport, status=TransportStatus.COMPLETED, completed_at=timestamp)
        destination = replace(transport.destination, slot_id=transport.slot_id)
        if destination.location_type == LocationType.CELL:
            if self.cell(destination.location_id).state != CellState.IDLE or self.bodies_at(LocationType.CELL,destination.location_id):
                raise ModelError('Direct arrival requires an empty operational cell')
        self._transports[transport_id] = completed
        if transport.cargo_type == 'BODY':
            status = BodyStatus.COMPLETED if cargo.status == BodyStatus.COMPLETED else BodyStatus.WAITING
            self._bodies[cargo.body_id] = replace(cargo, location=destination, status=status, transport_id=None, reservation_id=None)
            if destination.location_type == LocationType.CELL:
                body = self._bodies[cargo.body_id]
                operation = self._new_operation(destination.location_id,body)
                self._operations[operation.operation_id] = operation
                self._bodies[body.body_id] = replace(body,status=BodyStatus.PROCESSING)
                self._cells[destination.location_id] = CellWork(destination.location_id,CellState.RUNNING,operation.operation_id)
                self._next_operation_number += 1
                self._cell_entries.append(CellEntry(body.body_id,destination.location_id,None,None,operation.operation_id,
                    completed.transport_id,None,operation.started_at,0))
        else:
            self._parts[cargo.parts_kit_id] = replace(cargo, location=destination, transport_id=None)
        if lane_traffic.efficient(self):
            self._vehicles[vehicle.vehicle_id] = replace(vehicle, state=VehicleState.IDLE, transport_id=None)
            self._motions.pop(vehicle.vehicle_id,None)
            if destination.location_type == LocationType.CELL:
                self._cell_waiters[vehicle.vehicle_id] = destination.location_id
            elif destination.location_type == LocationType.RESULT:
                # Only clear the shared outbound dock; no lap back to distant home.
                self._vehicles[vehicle.vehicle_id] = replace(vehicle,state=VehicleState.RETURNING,transport_id=None)
                self._motions[vehicle.vehicle_id] = empty_motion(VehicleState.RETURNING,(vehicle.x,vehicle.y),(780,260 if vehicle.vehicle_id=='AGV-001' else 340),.0375,self.configuration.factory['tickMs'])
            return completed
        self._vehicles[vehicle.vehicle_id] = replace(vehicle, state=VehicleState.RETURNING, transport_id=None)
        config = next(v for v in self.configuration.factory['vehicles'] if v['vehicleId'] == vehicle.vehicle_id)
        home = ((config['initialPosition']['x'], config['initialPosition']['y'])
                if self.configuration.factory.get('traffic') else
                self._point(Location(config['home']['locationType'], config['home']['locationId'])))
        self._motions[vehicle.vehicle_id] = empty_motion(VehicleState.RETURNING, (vehicle.x, vehicle.y), home,
                                  route_speed(self._route(transport)), self.configuration.factory['tickMs'])
        return completed

    @recorded
    def fail_cell(self, cell_id: str) -> CellWork:
        cell = self.cell(cell_id)
        if cell.state == CellState.DOWN:
            return cell
        if self._paused:
            raise ModelError('Cell failure injection requires an unpaused model')
        failed = replace(cell, state=CellState.DOWN, resume_state=cell.state)
        self._cells[cell_id] = failed
        self._scenario('CELL_DOWN', cell_id, {})
        return failed

    @recorded
    def recover_cell(self, cell_id: str) -> CellWork:
        cell = self.cell(cell_id)
        if cell.state != CellState.DOWN:
            return cell
        if self._paused:
            raise ModelError('Cell recovery requires an unpaused model')
        self._cells[cell_id] = replace(cell, state=cell.resume_state, resume_state=None)
        self._scenario('CELL_RECOVER', cell_id, {})
        self._refresh_blocked_cells()
        if self._flow_started:
            self.redispatch()
        return self.cell(cell_id)

    @recorded
    def delay_transport(self, transport_id: str, additional_ms: int) -> None:
        transport = self.transport(transport_id)
        if (self._paused or transport.status != TransportStatus.ASSIGNED
                or type(additional_ms) is not int or additional_ms < 0):
            raise ModelError('Delay requires an unpaused assigned transport and nonnegative integer milliseconds')
        self._transport_delays[transport_id] = self._transport_delays.get(transport_id, 0) + additional_ms
        self._scenario('TRANSPORT_DELAY', transport_id, {'additionalDelayMs': additional_ms})

    @recorded
    def set_quality_pattern(self, results: tuple[str, ...]) -> None:
        if self._paused or not isinstance(results, tuple) or not results or any(r not in ('PASS', 'FAIL') for r in results):
            raise ModelError('Quality pattern requires an unpaused model and nonempty PASS/FAIL tuple')
        self._quality_results = results
        self._quality_offset = self._next_inspection_number - 1
        self._scenario('QUALITY_PATTERN', self.run_id, {'results': list(results)})

    def _facts_state(self):
        return {'bodies': self._bodies.copy(), 'cells': self._cells.copy(), 'operations': self._operations.copy(),
                'inspections': self._inspections.copy(), 'transports': self._transports.copy(),
                'entries': tuple(self._cell_entries), 'scenarios': tuple(self._scenarios),
                'paused': self._paused, 'finished': self._finished}

    def _emit_changes(self, before):
        changes = list(transition_facts(before, self._facts_state()))
        instant = _timestamp(_utc_time(self._clock)) if any(timestamp is None for _, timestamp, _ in changes) else None
        for kind, timestamp, payload in changes:
            self._journal.append(kind, timestamp or instant, payload)
        if not before['finished'] and self._finished:
            instant = _timestamp(_utc_time(self._clock))
            self._journal.append('RUN_STATE_CHANGED', instant, {'previousState': 'RUNNING', 'state': 'FINISHED', 'reason': 'DRAINED'})
            self._journal.append('FACTORY_SNAPSHOT', instant, self.snapshot(captured_at=instant))
            self._journal.append('RUN_FINISHED', instant, {'reason': 'DRAINED', 'uniqueEventCount': self._journal.next_sequence})

    def set_event_sink(self, sink):
        """Install one atomic admission callback on the model's single writer."""
        self._assert_writer()
        if self._event_sink is not None:
            raise ModelError('A source session is already attached')
        self._event_sink = sink

    def discard_confirmed_events(self, source_seq):
        """Release acknowledged originals without reusing their immutable sequence numbers."""
        self._assert_writer()
        self._journal.records[:] = [e for e in self._journal.records if e.to_dict()['sourceSeq'] > source_seq]

    @property
    def events(self):
        return tuple(self._journal.records)

    def snapshot(self, *, captured_at: str | None = None) -> dict:
        self._assert_writer()
        captured = captured_at or _timestamp(_utc_time(self._clock))
        if not isinstance(captured, str) or not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{3}Z', captured):
            raise ModelError('Snapshot requires a UTC millisecond timestamp')
        try:
            datetime.fromisoformat(captured.replace('Z', '+00:00'))
        except ValueError:
            raise ModelError('Snapshot requires a valid UTC timestamp') from None
        equipment = []
        for cell_id in CELLS:
            cell = self._inspect_cell(cell_id)
            pending = cell.pop('fixturePendingStart')
            if pending or (cell['state'] == 'DOWN' and cell['resumeState'] == 'IDLE' and cell['bodyId'] is not None):
                raise ModelError('Fixture must start cell work before a complete v1 snapshot')
            equipment.append(cell)
        bodies = []
        for body in self.bodies:
            data = body.to_dict()
            del data['createdAt']
            data['lastObservedAt'] = captured
            bodies.append(data)
        return {'runState': 'FINISHED' if self._finished else 'PAUSED' if self._paused else 'RUNNING',
                'capturedAt': captured, 'simElapsedMs': self.sim_elapsed_ms, 'equipment': equipment,
                'buffers': [self.buffer(b['bufferId']) for b in self.configuration.factory['buffers']],
                'bodies': bodies, 'vehicles': [self._inspect_vehicle(v) for v in self.vehicles],
                'activeTransports': [t.to_dict() for t in self.active_transports],
                **self._parts_snapshot()}

    def _parts_snapshot(self):
        from . import parts_supply
        return {'partsSupply': parts_supply.snapshot(self)} if parts_supply.enabled(self) else {}

    @recorded
    def publish_snapshot(self):
        self._assert_writer()
        if self._finished:
            raise ModelError('RUN_FINISHED must remain the last new event')
        payload = self.snapshot()
        return self._journal.append('FACTORY_SNAPSHOT', payload['capturedAt'], payload)

    @recorded
    def finish_run(self) -> None:
        if self._finished:
            return
        if (self._paused or not self.bodies or any(b.location.location_type != LocationType.RESULT for b in self.bodies)
                or self.active_transports or self._motions or any(v.state != VehicleState.IDLE for v in self.vehicles)
                or any(c.state != CellState.IDLE for c in self._cells.values())
                or not lane_traffic.final_return_complete(self)):
            raise ModelError('Run can finish only after bodies, cells and empty vehicles have drained')
        self._finished = True
        self._flow_started = False

