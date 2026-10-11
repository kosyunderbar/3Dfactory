// One uniform projection for locations, routes and future live vehicles.
// Factory coordinates have no declared physical unit; these are display units.
export const WORLD_SCALE = 0.09
export const modelScale = config => config.traffic?.policyVersion >= 2 ? 1.25 : 1
export function toWorld(point, height = 0) {
  return { x: point.x * WORLD_SCALE, y: height, z: point.y * WORLD_SCALE }
}

export function floorBounds(config, showParts = true) {
  if (config.traffic) {
    const b = config.traffic.bounds
    return { minX: b.minX * WORLD_SCALE, maxX: b.maxX * WORLD_SCALE, minZ: b.minY * WORLD_SCALE, maxZ: (config.traffic.policyVersion>=3 && !showParts ? Math.min(b.maxY,config.traffic.policyVersion>=4 ? 700 : 600) : b.maxY) * WORLD_SCALE }
  }
  const routes = config.routes.filter(route => showParts || route.cargoType !== 'PARTS')
  const locations = config.locations.filter(location => showParts || ['INPUT', 'CELL', 'BUFFER', 'RESULT'].includes(location.locationType))
  const points = [...locations, ...routes.flatMap(route => route.points)].map(point => toWorld(point))
  if (!points.length) return { minX: -8, maxX: 8, minZ: -8, maxZ: 8 }
  return {
    minX: Math.min(...points.map(p => p.x)) - 7,
    maxX: Math.max(...points.map(p => p.x)) + 7,
    minZ: Math.min(...points.map(p => p.z)) - 7,
    maxZ: Math.max(...points.map(p => p.z)) + 6,
  }
}
