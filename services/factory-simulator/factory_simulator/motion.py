"""Tick-driven movement over configured coordinates, without collision planning."""
from dataclasses import dataclass
from math import ceil, hypot, nextafter

from .logistics import VehicleState


@dataclass(frozen=True)
class Motion:
    phase: VehicleState
    points: tuple[tuple[float, float], ...]
    required_ms: int
    elapsed_ms: int = 0

    def position(self) -> tuple[float, float]:
        lengths = [hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(self.points, self.points[1:])]
        total = sum(lengths)
        if total == 0 or self.elapsed_ms >= self.required_ms:
            return self.points[-1]
        distance = total * self.elapsed_ms / self.required_ms
        for a, b, length in zip(self.points, self.points[1:], lengths):
            if length > 0 and distance <= length:
                fraction = distance / length
                return a[0] + (b[0] - a[0]) * fraction, a[1] + (b[1] - a[1]) * fraction
            distance -= length
        return self.points[-1]


def empty_motion(phase, origin, destination, speed_per_ms, tick_ms):
    distance = hypot(destination[0] - origin[0], destination[1] - origin[1])
    duration = max(tick_ms, ceil(nextafter(distance / speed_per_ms / tick_ms, float('-inf'))) * tick_ms)
    return Motion(phase, (origin, destination), duration)


def route_speed(route) -> float:
    points = route['points']
    length = sum(hypot(b['x'] - a['x'], b['y'] - a['y']) for a, b in zip(points, points[1:]))
    return length / route['travelDurationMs']
