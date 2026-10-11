import { modelScale } from './coordinates.js'
// Interpolate only observed progress on an unchanged authoritative path.
// Moving phase/path changes remain atomic. A stationary handoff does not
// interrupt other vehicles on the same observed fleet interval. No extrapolation.
export function samplePath(path, progress) {
  const lengths = path.slice(1).map((p, i) => Math.hypot(p.x - path[i].x, p.y - path[i].y))
  let distance = lengths.reduce((a, b) => a + b, 0) * Math.max(0, Math.min(1, progress))
  for (let i = 0; i < lengths.length; i++) {
    if (distance <= lengths[i] || i === lengths.length - 1) {
      const a = path[i], b = path[i + 1], t = lengths[i] ? distance / lengths[i] : 0
      return { x: a.x + (b.x - a.x) * t, y: a.y + (b.y - a.y) * t, yaw: -Math.atan2(b.y - a.y, b.x - a.x) }
    }
    distance -= lengths[i]
  }
  return { ...path[0], yaw: 0 }
}
// Policy 3 uses the same stop/rotate/trapezoidal profile as the simulator.
export function sampleMotion(traffic, elapsedMs = traffic.elapsedMs) {
  if (!traffic.segments) return samplePath(traffic.path, elapsedMs / traffic.durationMs)
  if (!traffic.segments.length) return { ...traffic.path[0], yaw: -traffic.heading }
  let elapsed = Math.max(0, Math.min(traffic.durationMs, elapsedMs)), index = 0
  for (; index < traffic.segments.length - 1; index++) {
    const s = traffic.segments[index], duration = s.turnMs + s.travelMs
    if (elapsed < duration) break
    elapsed -= duration
  }
  const s = traffic.segments[index], a = traffic.path[index], b = traffic.path[index + 1]
  const delta = Math.atan2(Math.sin(s.heading - s.initialHeading), Math.cos(s.heading - s.initialHeading))
  // Python chooses -pi for the exactly opposite direction.
  const turn = Math.abs(Math.abs(delta) - Math.PI) < 1e-10 ? -Math.PI : delta
  if (elapsed < s.turnMs) return { ...a, yaw: -(s.initialHeading + turn * elapsed / s.turnMs) }
  const t = Math.max(0, Math.min(s.travelMs, elapsed - s.turnMs)), ramp = s.rampMs, peak = s.peakSpeed
  let distance
  if (t <= ramp) distance = peak * t * t / (2 * ramp)
  else if (t <= s.travelMs - ramp) distance = peak * (t - ramp / 2)
  else distance = peak * (s.travelMs - ramp) - peak * (s.travelMs - t) ** 2 / (2 * ramp)
  const length = Math.hypot(b.x - a.x, b.y - a.y), f = length ? Math.min(1, distance / length) : 1
  return { x: a.x + (b.x - a.x) * f, y: a.y + (b.y - a.y) * f, yaw: -s.heading }
}
function sameMotion(old, v) {
  return old?.traffic && v.traffic && old.state === v.state && old.bodyId === v.bodyId && old.partsKitId === v.partsKitId && old.transportId === v.transportId && old.traffic.durationMs === v.traffic.durationMs && old.traffic.elapsedMs <= v.traffic.elapsedMs && JSON.stringify(old.traffic.path) === JSON.stringify(v.traffic.path) && JSON.stringify(old.traffic.segments) === JSON.stringify(v.traffic.segments) && (v.traffic.segments?.length !== 0 || old.traffic.heading === v.traffic.heading)
}
function stationaryHandoff(old, v) {
  if (!old?.traffic || !v.traffic || !old.position || !v.position) return false
  const a = sampleMotion(old.traffic), b = sampleMotion(v.traffic)
  return Math.hypot(a.x-b.x, a.y-b.y) < 1e-8 && Math.abs(Math.atan2(Math.sin(a.yaw-b.yaw), Math.cos(a.yaw-b.yaw))) < 1e-8
}
export function compatibleFrames(a, b) {
  if (!a || !b || a.runId !== b.runId || a.serverEpoch !== b.serverEpoch || a.sourceId !== b.sourceId || b.simElapsedMs <= a.simElapsedMs || b.simElapsedMs - a.simElapsedMs > 2000) return false
  return a.vehicles.length === b.vehicles.length && b.vehicles.every(v => {
    const old = a.vehicles.find(p => p.vehicleId === v.vehicleId)
    return sameMotion(old, v) || stationaryHandoff(old, v)
  })
}
export function framePositions(current, previous, fraction = 1) {
  return (current?.vehicles ?? []).map(v => {
    const old = previous?.vehicles.find(p => p.vehicleId === v.vehicleId)
    if (sameMotion(old, v)) {
      const t = v.traffic
      const elapsed = old.traffic.elapsedMs + (t.elapsedMs - old.traffic.elapsedMs) * Math.max(0, Math.min(1, fraction))
      return { ...v, position: sampleMotion(t, elapsed) }
    }
    const t = v.traffic
    return { ...v, position: { ...v.position, yaw: t ? sampleMotion(t).yaw : 0 } }
  })
}
export function solidPosition(config, location) {
  const r = config.traffic?.obstacles.find(r => r.id === location.locationId)
  return r ? { x: (r.minX + r.maxX) / 2, y: (r.minY + r.maxY) / 2 } : location
}
// Vehicles own cargo; reservation alone never creates a physical body in a Bay.
export function bodyPlacement(body, config, bodies) {
  if (body.locationType === 'VEHICLE') return { vehicleId: body.locationId }
  const loc = config.locations.find(l => l.locationId === body.locationId)
  if (!loc) return null
  const p = solidPosition(config, loc)
  let offsetY = 0, height = 0.16, count = 1
  if (body.locationType === 'BUFFER') {
    const bay = config.buffers.find(b => b.bufferId === body.locationId)
    const index = bay?.slotIds.indexOf(body.locationSlotId) ?? -1
    if (index < 0) return null
    offsetY = (index - (bay.capacity - 1) / 2) * 1.55 * modelScale(config) / 0.09
  } else if (body.locationType === 'CELL') height = 1.065
  else {
    const colocated = bodies.filter(b => b.locationId === body.locationId && b.locationType === body.locationType)
    // Staging/result storage is aggregated into one visible representative + count.
    // Avoid drawing multiple bodies on top of one another, or outside the solid zone.
    if (colocated[0]?.bodyId !== body.bodyId) return null
    count = colocated.length
  }
  return { x: p.x, y: p.y + offsetY, height: height * modelScale(config), count }
}
