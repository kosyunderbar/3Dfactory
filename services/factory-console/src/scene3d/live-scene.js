import * as THREE from 'three'
import { box, bodyModel, vehicleModel, partsLoad, label, updateLabel, palette, disposeTree } from './models.js'
import { cellFlag, vehicleFlag } from './status.js'
import { toWorld, modelScale } from './coordinates.js'
import { bodyPlacement } from './motion.js'
import { createPlayback } from './playback.js'

export function createLiveScene({ scene, labels, routes, targets, entries, config, showParts, invalidate, equipment, slots, partsDocks = new Map() }) {
  const scale = modelScale(config)
  const vehicles = new Map(), bodies = new Map(), paths = new Map()
  let latest = null, signatures = new Map()
  const playback = createPlayback()
  const group = new THREE.Group(); scene.add(group)
  function selectable(object, entry) { object.userData.entry = entry; targets.push(object); entries.push(entry) }
  function remove(object) { object.removeFromParent(); disposeTree(object) }
  for (const v of config.vehicles) {
    if (!showParts && v.kind === 'AMR') continue
    const model = vehicleModel(false, v.vehicleId), cargo = partsLoad()
    model.scale.setScalar(scale)
    cargo.visible = false; model.add(cargo); model.visible = false; group.add(model)
    const text = label(labels, v.vehicleId, 0, 1.15, 0, { width: 5, color: '#3467c7', detail: '관측 대기', minScreenWidth: 116, maxScreenWidth: 116, compact: true }); text.visible = false
    // A yaw-independent envelope also protects the carried body from labels.
    text.userData.vehicleEnvelope = { radius: 2.2 * scale, halfHeight: 1.15 * scale }
    const ring = new THREE.Mesh(new THREE.RingGeometry(2.10, 2.16, 48), new THREE.MeshBasicMaterial({ color: palette.blue, transparent: true, opacity: 0.4, side: THREE.DoubleSide }))
    ring.rotation.x = -Math.PI / 2; ring.position.y = 0.04; model.add(ring); ring.visible = Boolean(config.traffic)
    selectable(model, { kind: 'vehicle', id: v.vehicleId, title: v.vehicleId })
    vehicles.set(v.vehicleId, { model, cargo, text, ring })
  }
  function setFrame(frame, live) {
    playback.push(frame, live, performance.now())
    invalidate()
  }
  function applyFrame(frame) {
    if (frame === latest) return
    latest = frame
    for (const [id, object] of vehicles) {
      const visible = Boolean(frame?.vehicles.some(v => v.vehicleId === id))
      object.model.visible = visible; object.text.visible = visible
    }
    for (const [id, object] of bodies) {
      const body = frame?.bodies.find(b => b.bodyId === id)
      if (!body) {
        const index = targets.indexOf(object.model); if (index >= 0) targets.splice(index, 1)
        const entry = entries.findIndex(e => e.kind === 'body' && e.id === id); if (entry >= 0) entries.splice(entry, 1)
        remove(object.model); remove(object.text); bodies.delete(id)
      }
    }
    for (const b of frame?.bodies ?? []) if (!bodies.has(b.bodyId)) {
      const model = bodyModel(b.inspectionResult === 'FAIL' ? palette.amber : palette.white)
      group.add(model)
      const text = label(labels, b.bodyId, 0, 0, 0, { width: 4.4 })
      selectable(model, { kind: 'body', id: b.bodyId, title: `${b.bodyId} · ${b.tagId}` })
      bodies.set(b.bodyId, { model, text, count: 1 })
    }
    for (const cell of frame?.equipment ?? []) {
      const station = equipment.get(cell.cellId)
      updateLabel(station?.userData.statusLabel, cell.cellId, cellFlag(cell))
      const lamp = station?.userData.lamp
      if (lamp) lamp.material.color.setHex(({ DOWN: 0xd06455, BLOCKED: palette.amber, RUNNING: palette.blue })[cell.state] ?? palette.steel)
    }
    for (const bay of frame?.buffers ?? []) for (const slot of bay.slots) {
      const pad = slots.get(slot.slotId)
      if (pad) pad.material.color.setHex(({ FREE: 0xeaf0f6, RESERVED: 0xb9cff3, OCCUPIED: 0x93a7b9 })[slot.status])
    }
    for(const stock of frame?.partsSupply ?? []){
      const dock=partsDocks.get(stock.dockId)
      if(!dock)continue
      dock.table.userData.kits.forEach((kit,index)=>{kit.visible=index<stock.available})
      updateLabel(dock.text,stock.dockId,{detail:`${stock.available} / ${stock.capacity} 키트${stock.inbound ? ' · 보급 중' : ''}`,color:stock.available ? '#326c70' : '#96651d',background:stock.available ? '#f4fbfa' : '#fff0d5'})
    }
    for (const v of frame?.vehicles ?? []) {
      if (!vehicles.has(v.vehicleId)) continue
      updateLabel(vehicles.get(v.vehicleId).text, v.vehicleId, vehicleFlag(v, frame.activeTransports ?? [], config, frame.equipment ?? []))
      const signature = JSON.stringify(v.traffic?.path ?? [])
      if (signatures.get(v.vehicleId) !== signature) {
        if (paths.has(v.vehicleId)) remove(paths.get(v.vehicleId))
        const points = (v.traffic?.path ?? []).map(p => { const w = toWorld(p, 0.08); return new THREE.Vector3(w.x, w.y, w.z) })
        const line = new THREE.Group()
        for (let i = 1; i < points.length; i++) {
          const a = points[i-1], b = points[i], length = a.distanceTo(b)
          if (!length) continue
          const strip = box(line, length, 0.02, 0.075, (a.x+b.x)/2, 0.08, (a.z+b.z)/2, v.kind === 'AMR' ? 0x438185 : palette.blue)
          strip.rotation.y = -Math.atan2(b.z-a.z,b.x-a.x); strip.castShadow = false
        }
        routes.add(line); paths.set(v.vehicleId, line); signatures.set(v.vehicleId, signature)
      }
    }
  }
  function draw(now) {
    const sample = playback.sample(now)
    applyFrame(sample.frame)
    for (const v of sample.vehicles) {
      const object = vehicles.get(v.vehicleId); if (!object) continue
      const { model, cargo, text, ring } = object, p = toWorld(v.position)
      model.visible = true; text.visible = true
      if(object.lastPosition){
        const dx=p.x-object.lastPosition.x,dz=p.z-object.lastPosition.z
        const travel=dx*Math.cos(v.position.yaw)-dz*Math.sin(v.position.yaw)
        for(const wheel of model.userData.wheels ?? [])wheel.rotation.z-=travel/(.255*scale)
      }
      object.lastPosition={x:p.x,z:p.z}
      model.position.set(p.x, 0, p.z); model.rotation.y = v.position.yaw
      cargo.visible = Boolean(v.partsKitId)
      text.position.set(p.x, 1.15 * scale, p.z)
      text.userData.labelAnchor.copy(text.position)
      ring.material.color.setHex(v.traffic?.waiting ? palette.amber : palette.blue)
    }
    for (const cell of latest?.equipment ?? []) {
      const work = cell.state === 'RUNNING' ? 1 : 0
      // Use reported simulator time. Stale/archived scenes never keep animating.
      equipment.get(cell.cellId)?.userData.pose?.(work, sample.simElapsedMs / 1000)
    }
    for (const b of latest?.bodies ?? []) {
      const object = bodies.get(b.bodyId), placement = bodyPlacement(b, config, latest.bodies)
      const { model, text } = object
      for (const material of model.userData.paint) material.color.setHex(b.inspectionResult === 'FAIL' ? palette.amber : palette.white)
      model.visible = Boolean(placement); text.visible = Boolean(placement)
      if (!placement) continue
      if (placement.vehicleId) {
        const vehicle = vehicles.get(placement.vehicleId)
        if (!vehicle || !latest.vehicles.some(v => v.vehicleId === placement.vehicleId && v.bodyId === b.bodyId)) { model.visible = false; text.visible = false; continue }
        if (model.parent !== vehicle.model) vehicle.model.add(model); model.scale.setScalar(1); model.position.set(0, 1.065, 0); model.rotation.y = 0
        text.visible = false
      } else {
        if (model.parent !== group) group.add(model); model.scale.setScalar(scale); const p = toWorld(placement, placement.height)
        model.position.set(p.x, p.y, p.z); model.rotation.y = b.locationType === 'CELL' ? -Math.PI / 2 : 0
        text.position.set(p.x, p.y + 2.3, p.z)
        if (object.count !== placement.count) {
          remove(text); object.text = label(labels, placement.count > 1 ? `${b.locationId} · ${placement.count}대` : b.bodyId, p.x, p.y + 2.3, p.z, { width: 4.4 }); object.count = placement.count
        }
      }
    }
    return sample.animating
  }
  return { setFrame, draw, vehicle(id) { const model=vehicles.get(id)?.model; return model?.visible ? model : null }, stop() { playback.stop(); draw(performance.now()) } }
}
