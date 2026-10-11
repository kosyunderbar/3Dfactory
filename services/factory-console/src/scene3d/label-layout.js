import * as THREE from 'three'

// Keep status cards readable when zoomed out without stacking text on text.
// Leader lines retain their connection to the actual equipment/vehicle anchor.
export function layoutStatusLabels(labels, camera, width, height) {
  const units = (camera.right-camera.left)/(camera.zoom*width)
  const right = new THREE.Vector3().setFromMatrixColumn(camera.matrixWorld,0)
  const up = new THREE.Vector3().setFromMatrixColumn(camera.matrixWorld,1)
  const occupied = []
  const overlaps = (a,b) => a.left < b.right+5 && a.right+5 > b.left && a.top < b.bottom+5 && a.bottom+5 > b.top
  const vehicleRects = new Map()
  for (const sprite of labels.children) {
    const envelope = sprite.userData.vehicleEnvelope
    if (!envelope || !sprite.visible) continue
    const anchor = sprite.userData.labelAnchor
    const rect = { left: Infinity, right: -Infinity, top: Infinity, bottom: -Infinity }
    for (const dx of [-envelope.radius,envelope.radius]) for (const dy of [-envelope.halfHeight,envelope.halfHeight]) for (const dz of [-envelope.radius,envelope.radius]) {
      const p = anchor.clone().add(new THREE.Vector3(dx,dy,dz)).project(camera)
      const x = (p.x+1)*width/2, y = (1-p.y)*height/2
      rect.left = Math.min(rect.left,x); rect.right = Math.max(rect.right,x)
      rect.top = Math.min(rect.top,y); rect.bottom = Math.max(rect.bottom,y)
    }
    vehicleRects.set(sprite,rect); occupied.push(rect)
  }
  for (const sprite of [...labels.children]) {
    const size = sprite.userData.labelSize
    if (!size?.minScreenWidth) continue
    const anchor = sprite.userData.labelAnchor
    sprite.position.copy(anchor)
    sprite.material.visible = true
    const worldWidth = Math.min(Math.max(size.width,size.minScreenWidth*units),(size.maxScreenWidth ?? Infinity)*units)
    sprite.scale.set(worldWidth,worldWidth*size.aspect,1)
    const projected = anchor.clone().project(camera)
    const originalX = (projected.x+1)*width/2, originalY = (1-projected.y)*height/2
    const w = worldWidth/units, h = w*size.aspect
    let leader = sprite.userData.leader
    if (!leader) {
      leader = new THREE.Line(new THREE.BufferGeometry().setFromPoints([anchor,anchor]),new THREE.LineBasicMaterial({color:0x7e95ae,transparent:true,opacity:0.55,depthTest:false}))
      leader.renderOrder = 1; labels.add(leader); sprite.userData.leader = leader
    }
    leader.visible = false
    if (!sprite.visible || originalX < 0 || originalX > width || originalY < 0 || originalY > height) continue
    const vehicleRect = vehicleRects.get(sprite)
    // Screen-space placement keeps "right of the vehicle" consistent at any yaw.
    const candidates = vehicleRect ? [vehicleRect.right+8+w/2,vehicleRect.left-8-w/2] : [originalX]
    const xs = candidates.map(x=>Math.max(w/2+5,Math.min(width-w/2-5,x)))
    let placed
    for (let offset=0; offset<height; offset+=8) {
      for (const x of xs) {
        for (const y of offset ? [originalY-offset,originalY+offset] : [originalY]) {
          const rect = {left:x-w/2,right:x+w/2,top:y-h/2,bottom:y+h/2}
          if (rect.top<4 || rect.bottom>height-4 || occupied.some(r=>overlaps(rect,r))) continue
          placed = {rect,x,y}; break
        }
        if (placed) break
      }
      if (placed) break
    }
    if (!placed) { sprite.material.visible = false; continue }
    occupied.push(placed.rect)
    const x = placed.x
    sprite.position.addScaledVector(right,(x-originalX)*units).addScaledVector(up,(originalY-placed.y)*units)
    if (Math.hypot(x-originalX,placed.y-originalY)>6) {
      const edge = sprite.position.clone()
      if (vehicleRect) edge.addScaledVector(right,(x > originalX ? -w/2 : w/2)*units)
      leader.geometry.setFromPoints([anchor,edge]); leader.visible = true
    }
  }
}
