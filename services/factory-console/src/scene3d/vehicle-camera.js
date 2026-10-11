// The model front is local +X; world yaw follows Three.js rotation about +Y.
// Mount ahead of the bumper so the carried body cannot obstruct the lens.
export function vehicleCameraPose(position, yaw, scale = 1) {
  const forward = { x: Math.cos(yaw), z: -Math.sin(yaw) }
  const eye = { x: position.x + forward.x * 1.96 * scale, y: position.y + 1.18 * scale, z: position.z + forward.z * 1.96 * scale }
  return { eye, target: { x: eye.x + forward.x * 20, y: eye.y - .35, z: eye.z + forward.z * 20 } }
}

// Rear-quarter perspective keeps the full load in view, including on narrow screens.
export function vehicleFollowPose(position, yaw, scale = 1) {
  const c = Math.cos(yaw), s = Math.sin(yaw)
  return {
    eye: { x: position.x + (-7 * c + 4.5 * s) * scale, y: position.y + 6 * scale, z: position.z + (7 * s + 4.5 * c) * scale },
    target: { x: position.x, y: position.y + 1.15 * scale, z: position.z },
  }
}

// Shortest-angle easing avoids a full camera revolution at the ±PI boundary.
export function followHeading(current, heading, seconds) {
  const delta = Math.atan2(Math.sin(heading - current), Math.cos(heading - current))
  return Math.abs(delta) < .001 ? current + delta : current + delta * -Math.expm1(-8 * Math.max(0, seconds))
}
