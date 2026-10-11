"""Immutable body/parts transport, vehicle and cell-entry records."""
from __future__ import annotations
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .model import Location


class TransportStatus(StrEnum):
    ASSIGNED = 'ASSIGNED'
    IN_TRANSIT = 'IN_TRANSIT'
    COMPLETED = 'COMPLETED'
    CANCELLED = 'CANCELLED'


class VehicleState(StrEnum):
    IDLE = 'IDLE'
    TO_PICKUP = 'TO_PICKUP'
    LOADING = 'LOADING'
    MOVING = 'MOVING'
    UNLOADING = 'UNLOADING'
    RETURNING = 'RETURNING'


@dataclass(frozen=True)
class Vehicle:
    vehicle_id: str
    kind: str
    x: float
    y: float
    state: VehicleState = VehicleState.IDLE
    transport_id: str | None = None


@dataclass(frozen=True)
class Transport:
    transport_id: str
    vehicle_id: str
    route_id: str
    body_id: str | None
    source: Location
    destination: Location
    reservation_id: str | None
    slot_id: str | None
    assigned_at: str
    status: TransportStatus = TransportStatus.ASSIGNED
    started_at: str | None = None
    completed_at: str | None = None
    cancelled_at: str | None = None
    cancel_reason: str | None = None
    cargo_type: str = 'BODY'
    parts_kit_id: str | None = None

    def to_dict(self) -> dict:
        def endpoint(location):
            return {'locationType': location.location_type.value, 'locationId': location.location_id}
        return {'transportId': self.transport_id, 'vehicleId': self.vehicle_id,
                'routeId': self.route_id, 'cargoType': self.cargo_type, 'status': self.status.value,
                'bodyId': self.body_id, 'partsKitId': self.parts_kit_id,
                'source': endpoint(self.source), 'destination': endpoint(self.destination),
                'reservationId': self.reservation_id, 'slotId': self.slot_id,
                'assignedAt': self.assigned_at, 'startedAt': self.started_at,
                'completedAt': self.completed_at, 'cancelledAt': self.cancelled_at,
                'cancelReason': self.cancel_reason}


@dataclass(frozen=True)
class DispatchDecision:
    approved: bool
    reason: str
    transport_id: str | None = None

    def to_dict(self) -> dict:
        return {'approved': self.approved, 'reason': self.reason, 'transportId': self.transport_id}


@dataclass(frozen=True)
class CellEntry:
    body_id: str
    cell_id: str
    buffer_id: str | None
    slot_id: str | None
    operation_id: str
    transport_id: str | None
    reservation_id: str | None
    entered_at: str
    available_slots_after_release: int

    def to_dict(self) -> dict:
        return {'bodyId': self.body_id, 'cellId': self.cell_id, 'bufferId': self.buffer_id,
                'slotId': self.slot_id, 'operationId': self.operation_id,
                'transportId': self.transport_id, 'reservationId': self.reservation_id,
                'enteredAt': self.entered_at, 'availableSlotsAfterRelease': self.available_slots_after_release}


@dataclass(frozen=True)
class PartsKit:
    parts_kit_id: str
    location: Location
    transport_id: str | None = None
    consumed_by: str | None = None
