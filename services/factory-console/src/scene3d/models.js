import * as THREE from 'three'
import { detailedAgv, detailedAssembly, detailedCargo, block, lettering, colors } from './equipment-models.js'

export const palette = { navy: 0x203955, blue: 0x3467c7, pale: 0xdce7f2, white: 0xfafcff, steel: 0x93a7b9, dark: 0x354458, amber: 0xe6ad51 }

export function box(parent, width, height, depth, x, y, z, color, options = {}) {
  const mesh = new THREE.Mesh(new THREE.BoxGeometry(width, height, depth), new THREE.MeshStandardMaterial({ color, roughness: 0.64, metalness: 0.12, ...options }))
  mesh.position.set(x, y, z)
  mesh.castShadow = true
  mesh.receiveShadow = true
  parent.add(mesh)
  return mesh
}

export function cylinder(parent, radius, height, x, y, z, color) {
  const mesh = new THREE.Mesh(new THREE.CylinderGeometry(radius, radius, height, 16), new THREE.MeshStandardMaterial({ color, roughness: 0.6, metalness: 0.25 }))
  mesh.position.set(x, y, z)
  mesh.castShadow = true
  parent.add(mesh)
  return mesh
}

// Preserve the traffic footprint: detail grows inside the existing solid envelope.
export function cellModel(inspection = false, id = inspection ? 'QC-01' : 'ASM-01') {
  const model = detailedAssembly(id, inspection).group
  model.rotation.y = -Math.PI / 2
  const wrapper = new THREE.Group()
  wrapper.scale.set(4.2 / 5.1, 1, 5.2 / 5.7)
  wrapper.add(model)
  const g = new THREE.Group(); g.add(wrapper)
  g.userData.lamp = model.userData.lamp
  g.userData.pose = model.userData.pose
  return g
}

export function bodyModel(color = palette.white) { return detailedCargo(color) }

export function vehicleModel(parts = false, id = parts ? 'AMR-001' : 'AGV-001') {
  const g = detailedAgv(id).group
  if(parts) g.add(partsLoad())
  return g
}

export function partsLoad() {
  const g = new THREE.Group()
  for(const x of [-.68,.68]) {
    block(g,[1.15,.62,1.32],[x,1.4,0],colors.pale ?? 0xdce7f2)
    block(g,[1.18,.055,1.35],[x,1.74,0],colors.steel)
    for(const z of [-.66,.66]) {
      block(g,[.4,.1,.025],[x,1.52,z],colors.navy)
      for(const dx of [-.45,.45])block(g,[.035,.46,.025],[x+dx,1.39,z],colors.steel)
    }
  }
  return g
}

export function storageModel(id, rack = false) {
  const g = new THREE.Group()
  if(rack) {
    for(const x of [-1.7,1.7])for(const z of [-1.12,1.12])block(g,[.12,2.95,.12],[x,1.51,z],colors.navy)
    for(const y of [.25,1.25,2.25]) {
      block(g,[3.55,.12,2.35],[0,y,0],colors.steel)
      for(const x of [-.85,.85]) {
        block(g,[1.35,.58,1.55],[x,y+.37,0],0xdce7f2)
        lettering(g,'PARTS',[x,y+.42,.78],.6,.12)
      }
    }
    lettering(g,id,[0,2.91,1.19],2.6,.22)
  } else {
    for(const z of [-.76,.76]) {
      block(g,[3.35,.13,.12],[0,.17,z],colors.steel)
      for(const x of [-1.4,1.4])block(g,[.22,.16,.28],[x,.08,z],colors.navy)
    }
  }
  return g
}

export function partsDockModel(capacity=2) {
  const g=new THREE.Group(), kits=[]
  box(g,3.6,.12,2.5,0,.07,0,0xc6deda)
  for(const x of [-1.35,1.35])for(const z of [-.85,.85])box(g,.15,.75,.15,x,.47,z,palette.navy)
  box(g,3.25,.12,2.1,0,.9,0,palette.steel)
  for(let i=0;i<capacity;i++){
    const kit=new THREE.Group();kit.position.x=(i-(capacity-1)/2)*1.5
    box(kit,1.3,.6,1.35,0,1.26,0,palette.pale)
    box(kit,1.34,.06,1.4,0,1.59,0,palette.steel)
    box(kit,.35,.1,.03,0,1.3,.69,palette.navy)
    kit.visible=false;g.add(kit);kits.push(kit)
  }
  g.userData.kits=kits
  return g
}

export function label(parent, text, x, y, z, { width = 5, color = '#203955', background = '#ffffff', detail, minScreenWidth = 0, maxScreenWidth = Infinity, compact = false } = {}) {
  const canvas = document.createElement('canvas')
  const multiline = detail !== undefined
  canvas.width = 512
  canvas.height = multiline ? (compact ? 144 : 160) : 128
  const ctx = canvas.getContext('2d')
  const texture = new THREE.CanvasTexture(canvas)
  texture.colorSpace = THREE.SRGBColorSpace
  const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: texture, depthTest: false, toneMapped: false }))
  let previous = ''
  sprite.userData.updateLabel = (title, options = {}) => {
    const next = { color, background, detail, ...options }
    const signature = JSON.stringify([title, next])
    if (signature === previous) return
    previous = signature
    ctx.clearRect(0, 0, canvas.width, canvas.height)
    ctx.fillStyle = next.background
    ctx.beginPath(); ctx.roundRect(2, 2, 508, canvas.height - 4, 18); ctx.fill()
    ctx.textAlign = 'center'; ctx.textBaseline = 'middle'; ctx.fillStyle = next.color
    ctx.font = `600 ${multiline ? (compact ? 44 : 38) : 52}px system-ui, sans-serif`
    ctx.fillText(title, 256, multiline ? (compact ? 40 : 45) : 65, 478)
    if (multiline) {
      ctx.font = '600 36px system-ui, sans-serif'
      ctx.fillText(next.detail || '', 256, compact ? 104 : 112, 478)
    }
    texture.needsUpdate = true
  }
  sprite.userData.updateLabel(text)
  sprite.position.set(x, y, z)
  sprite.userData.labelAnchor = sprite.position.clone()
  sprite.scale.set(width * 1.15, width * 1.15 * canvas.height / canvas.width, 1)
  sprite.userData.labelSize = { width: width * 1.15, aspect: canvas.height / canvas.width, minScreenWidth, maxScreenWidth }
  sprite.renderOrder = 2
  parent.add(sprite)
  return sprite
}

export function updateLabel(sprite, text, options) {
  sprite?.userData.updateLabel?.(text, options)
}

export function disposeTree(root) {
  const geometries = new Set(), materials = new Set(), textures = new Set()
  root.traverse(object => {
    if (object.isLight) object.dispose?.()
    if (object.geometry) geometries.add(object.geometry)
    for (const material of (Array.isArray(object.material) ? object.material : [object.material])) {
      if (!material) continue
      materials.add(material)
      for (const value of Object.values(material)) if (value?.isTexture) textures.add(value)
    }
  })
  textures.forEach(texture => texture.dispose())
  materials.forEach(material => material.dispose())
  geometries.forEach(geometry => geometry.dispose())
}
