"""Immutable legacy and stop/turn/drive motion profiles; traffic authorizes progress."""
from dataclasses import dataclass
from math import ceil, hypot, nextafter, atan2, pi, sqrt

from .logistics import VehicleState


@dataclass(frozen=True)
class Motion:
    phase: VehicleState
    points: tuple[tuple[float, float], ...]
    required_ms: int
    elapsed_ms: int = 0
    segments: tuple = ()

    def position(self) -> tuple[float, float]:
        if self.segments:
            return self.pose()[:2]
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

    def pose(self):
        i, elapsed = motion_leg(self)
        turn, travel, ramp, initial, heading, peak = self.segments[i]
        a,b = self.points[i:i+2]
        if elapsed < turn:
            return (*a, initial+angle_delta(initial,heading)*elapsed/turn, 0.)
        t = min(travel, max(0, elapsed-turn))
        if t <= ramp:
            distance = peak*t*t/(2*ramp); speed = peak*t/ramp
        elif t <= travel-ramp:
            distance = peak*(t-ramp/2); speed = peak
        else:
            distance = peak*(travel-ramp)-peak*(travel-t)**2/(2*ramp); speed = peak*(travel-t)/ramp
        length = hypot(b[0]-a[0],b[1]-a[1])
        f = min(1, distance/length) if length else 1
        # Exact endpoint coordinates matter for the material hand-off contract.
        x,y = b if t >= travel else (a[0]+(b[0]-a[0])*f,a[1]+(b[1]-a[1])*f)
        return x,y,heading,speed


def empty_motion(phase, origin, destination, speed_per_ms, tick_ms):
    distance = hypot(destination[0] - origin[0], destination[1] - origin[1])
    duration = max(tick_ms, ceil(nextafter(distance / speed_per_ms / tick_ms, float('-inf'))) * tick_ms)
    return Motion(phase, (origin, destination), duration)


def route_speed(route) -> float:
    points = route['points']
    length = sum(hypot(b['x'] - a['x'], b['y'] - a['y']) for a, b in zip(points, points[1:]))
    return length / route['travelDurationMs']


def angle_delta(a, b):
    return (b - a + pi) % (2*pi) - pi


def profiled_motion(phase, path, heading, tick_ms, speed=.0375, *, allow_reverse=False):
    """Stop, rotate, then a bounded trapezoidal speed profile on each lane edge.

    Distances use model units, time milliseconds. Acceleration is 75 units/s²,
    maximum rotation 120 degrees/s. Every boundary is on a simulation tick.
    """
    segments = []
    for index, (a, b) in enumerate(zip(path, path[1:])):
        length = hypot(b[0]-a[0], b[1]-a[1])
        target = atan2(b[1]-a[1], b[0]-a[0]) if length else heading
        leg_speed=speed
        if allow_reverse and phase in (VehicleState.TO_PICKUP, VehicleState.RETURNING) and index==0 and 0<length<=100 and abs(angle_delta(heading,target))>pi/2+1e-8:
            target=angle_delta(0,target+pi)
            leg_speed=min(speed,.01875)
        turn = ceil(abs(angle_delta(heading,target))/(pi/1500)/tick_ms-1e-9)*tick_ms
        ramp = min(leg_speed/.000075, sqrt(length/.000075))
        travel_ms = length/leg_speed + ramp if length >= leg_speed*leg_speed/.000075 else 2*ramp
        travel = max(tick_ms, ceil(travel_ms/tick_ms-1e-9)*tick_ms)
        ramp = min(leg_speed/.000075, travel/2)
        peak = length/(travel-ramp)
        segments.append((turn, travel, ramp, heading, target, peak))
        heading = target
    return Motion(phase, tuple(path), sum(s[0]+s[1] for s in segments), segments=tuple(segments))


def motion_leg(motion):
    elapsed = motion.elapsed_ms
    for i, s in enumerate(motion.segments):
        duration = s[0]+s[1]
        if elapsed < duration:
            return i, elapsed
        elapsed -= duration
    return len(motion.segments)-1, sum(motion.segments[-1][:2])
