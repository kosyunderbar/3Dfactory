import { compatibleFrames, framePositions } from './motion.js'

const sameSource = (a, b) => a && b && a.runId === b.runId && a.sourceId === b.sourceId && a.serverEpoch === b.serverEpoch

// One delayed clock for the whole factory. Receipt jitter must not restart an
// animation or move it backwards. Only interpolate between received snapshots.
export function createPlayback({ delayMs = 600 } = {}) {
  let queue = [], enabled = false
  function push(frame, live, now) {
    const last = queue.at(-1)
    if (!live || !enabled || !sameSource(last?.frame, frame) || frame.simElapsedMs - last.frame.simElapsedMs > 2000) {
      queue = frame ? [{ frame, at: now }] : []; enabled = live
      return
    }
    if (frame.simElapsedMs < last.frame.simElapsedMs) return
    if (frame.simElapsedMs === last.frame.simElapsedMs) {
      // SSE also republishes metrics/health with no new physical observation.
      if (frame.sourceSeq !== last.frame.sourceSeq) last.frame = frame
      return
    }
    queue.push({ frame, at: Math.max(now, last.at + .001) })
    // Bounded even when the tab was hidden or rendering was suspended.
    if (queue.length > 16) queue.splice(0, queue.length - 16)
  }
  function sample(now) {
    if (!queue.length) return { frame: null, vehicles: [], simElapsedMs: 0, animating: false }
    const target = enabled ? now - delayMs : Infinity
    while (queue.length > 1 && queue[1].at <= target) queue.shift()
    const a = queue[0], b = queue[1]
    const fraction = b ? Math.max(0, Math.min(1, (target - a.at) / (b.at - a.at))) : 0
    const compatible = b && compatibleFrames(a.frame, b.frame)
    const poses = compatible ? framePositions(b.frame, a.frame, fraction) : framePositions(a.frame, null)
    // Cargo, lamps, stock and route labels change together on the same clock.
    const vehicles = a.frame.vehicles.map(v => ({ ...v, position: poses.find(p => p.vehicleId === v.vehicleId).position }))
    return { frame: a.frame, vehicles, simElapsedMs: a.frame.simElapsedMs + (b ? (b.frame.simElapsedMs - a.frame.simElapsedMs) * fraction : 0), animating: enabled && target < queue.at(-1).at }
  }
  function stop() { if (queue.length) queue = [queue.at(-1)]; enabled = false }
  return { push, sample, stop }
}
