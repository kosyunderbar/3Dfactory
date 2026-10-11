import * as THREE from 'three'
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js'
import { vehicleCameraPose, vehicleFollowPose, followHeading } from './vehicle-camera.js'
import { OrbitControls } from 'three/addons/controls/OrbitControls.js'
import { createLiveScene } from './live-scene.js'
import { layoutStatusLabels } from './label-layout.js'
import { solidPosition } from './motion.js'
import { toWorld, floorBounds, modelScale } from './coordinates.js'
import { box, cellModel, bodyModel, vehicleModel, storageModel, partsDockModel, label, palette, disposeTree } from './models.js'

// One scene for the approved design and authoritative live snapshots.
export function createFactoryScene(host, config, { showParts = true, showcase = false, onSelect, onError } = {}) {
  const scene = new THREE.Scene()
  scene.background = new THREE.Color(0xf0f4f8)
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false })
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2))
  renderer.shadowMap.enabled = true
  renderer.shadowMap.type = THREE.PCFShadowMap
  renderer.toneMapping = THREE.ACESFilmicToneMapping
  renderer.toneMappingExposure = 1
  renderer.domElement.setAttribute('aria-label', '3D 공장 배치. 드래그로 회전하고 마우스 휠로 확대합니다. 아래 버튼으로도 시점을 바꿀 수 있습니다.')
  renderer.domElement.setAttribute('role', 'img')
  host.appendChild(renderer.domElement)
  const pmrem = new THREE.PMREMGenerator(renderer), room = new RoomEnvironment()
  const environment = pmrem.fromScene(room, .04)
  scene.environment = environment.texture; scene.environmentIntensity = .4
  room.dispose(); pmrem.dispose()
  const driverCamera = new THREE.PerspectiveCamera(68, 1, .05, 500)
  let drivingId = '', cameraMode = 'third', labelsEnabled = true, followedYaw = 0, cameraTime = 0
  const followControls = new OrbitControls(driverCamera, renderer.domElement)
  followControls.enabled = false
  followControls.enablePan = false
  followControls.minPolarAngle = .2
  followControls.maxPolarAngle = Math.PI * .43
  followControls.minDistance = 6 * modelScale(config)
  followControls.maxDistance = 18 * modelScale(config)
  const cameraRay = new THREE.Ray(), cameraHit = new THREE.Vector3(), cameraBounds = [], up = new THREE.Vector3(0, 1, 0)
  const camera = new THREE.OrthographicCamera(-40, 40, 25, -25, 0.1, 500)
  const controls = new OrbitControls(camera, renderer.domElement)
  controls.enableDamping = false
  controls.minPolarAngle = 0.05
  controls.maxPolarAngle = Math.PI * 0.46
  controls.minZoom = 0.65
  controls.maxZoom = 5
  controls.screenSpacePanning = true
  const bounds = floorBounds(config, showParts)
  const width = bounds.maxX - bounds.minX, depth = bounds.maxZ - bounds.minZ
  const cx = (bounds.minX + bounds.maxX) / 2, cz = (bounds.minZ + bounds.maxZ) / 2
  const labels = new THREE.Group(), routes = new THREE.Group(), objects = new THREE.Group()
  scene.add(labels, routes, objects)
  const targets = [], entries = [], equipment = new Map(), slots = new Map(), partsDocks = new Map()
  let liveScene
  let disposed = false, pending = 0, highlight = null, pointerStart = null, active = true
  const render = () => {
    pending = 0
    if (disposed || !active || document.hidden || host.clientWidth === 0 || host.clientHeight === 0) return
    const now = performance.now(), animating = liveScene?.draw(now)
    let activeCamera = camera, settling = false, unobstructedEye = null
    if (drivingId) {
      const vehicle = liveScene?.vehicle(drivingId)
      if (vehicle) {
        if (cameraMode === 'first') {
          const pose = vehicleCameraPose(vehicle.position, vehicle.rotation.y, modelScale(config))
          driverCamera.position.set(pose.eye.x, pose.eye.y, pose.eye.z)
          driverCamera.lookAt(pose.target.x, pose.target.y, pose.target.z)
        } else {
          const yaw = followHeading(followedYaw, vehicle.rotation.y, Math.min((now-cameraTime)/1000, .1))
          const offset = driverCamera.position.clone().sub(followControls.target).applyAxisAngle(up, yaw-followedYaw)
          followControls.target.copy(vehicle.position).addScaledVector(up, 1.15*modelScale(config))
          driverCamera.position.copy(followControls.target).add(offset)
          followedYaw = yaw
          settling = Math.abs(Math.atan2(Math.sin(vehicle.rotation.y-yaw),Math.cos(vehicle.rotation.y-yaw))) > .001
          followControls.update()
          // Pull the lens in if an equipment model would hide the tracked vehicle.
          unobstructedEye = driverCamera.position.clone()
          const direction = driverCamera.position.clone().sub(followControls.target), distance = direction.length()
          cameraRay.set(followControls.target, direction.normalize())
          let nearest = distance
          // Static equipment envelopes avoid raycasting every bolt/roller mesh
          // on every camera frame. The actual vehicle geometry stays unchanged.
          for (const bounds of cameraBounds) {
            const hit = cameraRay.intersectBox(bounds, cameraHit)
            if (hit) nearest = Math.min(nearest, hit.distanceTo(followControls.target))
          }
          if (nearest < distance) driverCamera.position.copy(followControls.target).addScaledVector(direction, Math.max(.5, nearest-.3))
          driverCamera.lookAt(followControls.target)
        }
        cameraTime = now
      }
      activeCamera = driverCamera
    }
    activeCamera.updateMatrixWorld()
    labels.visible = labelsEnabled && !drivingId
    if (!drivingId) layoutStatusLabels(labels, camera, host.clientWidth, host.clientHeight)
    if (highlight) { highlight.visible = !drivingId; highlight.update() }
    renderer.render(scene, activeCamera)
    if (unobstructedEye) driverCamera.position.copy(unobstructedEye)
    if (animating || settling) invalidate()
  }
  const invalidate = () => { if (!disposed && !pending) pending = requestAnimationFrame(render) }
  const select = item => {
    if (highlight) { scene.remove(highlight); disposeTree(highlight); highlight = null }
    const object = targets.find(group => group.userData.entry.id === item.id)
    if (object) {
      highlight = new THREE.BoxHelper(object, palette.blue)
      highlight.material.depthTest = false
      highlight.renderOrder = 3
      scene.add(highlight)
    }
    onSelect?.(item); invalidate()
  }
  function target(group, entry) {
    group.userData.entry = entry
    targets.push(group)
    entries.push(entry)
  }
  function place(group, location, height = 0) {
    const p = toWorld(solidPosition(config, location), height)
    group.position.set(p.x, p.y, p.z)
    group.scale.setScalar(modelScale(config))
    objects.add(group)
    return p
  }
  const floor = box(scene, width, 0.48, depth, cx, -0.3, cz, 0xe0e8f0)
  floor.castShadow = false
  box(scene, width - 0.25, 0.045, depth - 0.25, cx, -0.035, cz, 0xf7f9fc).castShadow = false
  for (let x = bounds.minX + 1; x < bounds.maxX; x += 3) box(scene, 0.018, 0.012, depth - 0.5, x, 0.003, cz, 0xe2e9f1).castShadow = false
  for (let z = bounds.minZ + 1; z < bounds.maxZ; z += 3) box(scene, width - 0.5, 0.012, 0.018, cx, 0.003, z, 0xe2e9f1).castShadow = false
  // Raised edges keep the diorama readable without enclosing walls.
  box(scene, width, 0.13, 0.12, cx, 0.04, bounds.minZ, 0xb4c4d6)
  box(scene, 0.12, 0.13, depth, bounds.minX, 0.04, cz, 0xb4c4d6)
  label(labels, 'FACTORY / 01', bounds.minX + 7, 0.45, bounds.maxZ - 1.7, { width: 8, color: '#60758d', background: '#f7f9fc' })

  // Persistent, muted aisle guides distinguish allowed lanes from the blue trip route.
  const laneKeys = new Set()
  for (const lane of config.traffic?.lanes ?? []) {
    if (!showParts && Math.max(lane.start.y, lane.end.y) > (config.traffic.policyVersion>=4 ? 700 : 600)) continue
    const key = [JSON.stringify(lane.start), JSON.stringify(lane.end)].sort().join('|')
    if (laneKeys.has(key)) continue
    laneKeys.add(key)
    const a = toWorld(lane.start), b = toWorld(lane.end), length = Math.hypot(b.x-a.x,b.z-a.z)
    const rear=config.partsSupply && Math.max(lane.start.y,lane.end.y)<0
    if(config.partsSupply && (Math.min(lane.start.y,lane.end.y)<0 && !rear))continue
    const strip = box(objects, length, 0.012, rear ? .18 : .11, (a.x+b.x)/2, 0.025, (a.z+b.z)/2, rear ? 0x679c97 : 0xc3d0df)
    strip.rotation.y = -Math.atan2(b.z-a.z,b.x-a.x); strip.castShadow = false
    const direction = new THREE.Vector3(b.x-a.x,0,b.z-a.z).normalize()
    const reverse = config.traffic.lanes.some(e => e.start.x===lane.end.x && e.start.y===lane.end.y && e.end.x===lane.start.x && e.end.y===lane.start.y)
    if (!reverse) objects.add(new THREE.ArrowHelper(direction,new THREE.Vector3((a.x+b.x)/2,0.04,(a.z+b.z)/2),0.9,0x9eb1c8,0.45,0.32))
  }

  for (const route of (config.traffic && !showcase ? [] : config.routes)) {
    if (!showParts && route.cargoType === 'PARTS') continue
    const points = route.points.map(p => { const w = toWorld(p, 0.06); return new THREE.Vector3(w.x, w.y, w.z) })
    const geometry = new THREE.BufferGeometry().setFromPoints(points)
    const line = new THREE.Line(geometry, route.cargoType === 'PARTS'
      ? new THREE.LineDashedMaterial({ color: 0x91a8c0, dashSize: 0.5, gapSize: 0.35 })
      : new THREE.LineBasicMaterial({ color: 0x4978c5 }))
    line.computeLineDistances()
    routes.add(line)
    if (points.length > 1) {
      const end = points[points.length - 1], before = points[points.length - 2]
      const direction = new THREE.Vector3().subVectors(end, before).normalize()
      const arrow = new THREE.ArrowHelper(direction, end.clone().addScaledVector(direction, -1.4), 1.05, route.cargoType === 'PARTS' ? 0x91a8c0 : 0x4978c5, 0.42, 0.3)
      routes.add(arrow)
    }
  }
  const locationById = new Map(config.locations.map(p => [p.locationId, p]))
  for (const cell of config.equipment) {
    const location = locationById.get(cell.cellId)
    if (!location) continue
    const g = cellModel(cell.cellId.startsWith('QC'), cell.cellId)
    equipment.set(cell.cellId, g)
    const p = place(g, location)
    target(g, { kind: 'cell', id: cell.cellId, title: cell.cellId, subtitle: cell.cellId.startsWith('QC') ? '최종 검사 셀' : '독립 조립 셀', description: `작업 시간 ${cell.workDurationMs / 1000}초 · 공장 설정 기준. 설비의 작업 상태는 관측값을 따르며 로봇팔 동작은 시각화입니다.` })
    g.userData.statusLabel = label(labels, cell.cellId, p.x, 6.2 * modelScale(config), p.z - 2.3, showcase ? { width: 6 } : { width: 6, detail: '관측 대기', minScreenWidth: 104, maxScreenWidth: 124 })
  }
  for (const buffer of config.buffers) {
    const location = locationById.get(buffer.bufferId)
    if (!location) continue
    const g = new THREE.Group(), p = place(g, location)
    for (let i = 0; i < buffer.capacity; i++) {
      const z = (i - (buffer.capacity - 1) / 2) * 1.55
      const color = showcase && buffer.cellId === 'ASM-02' && i === 2 ? 0xe6eefc : 0xeaf0f6
      slots.set(buffer.slotIds[i], box(g, 3.2, 0.08, 1.48, 0, 0.06, z, color))
      for (const dx of [-1.58, 1.58]) box(g, 0.045, 0.025, 1.48, dx, 0.11, z, palette.steel)
      for (const dz of [-0.74, 0.74]) box(g, 3.15, 0.025, 0.045, 0, 0.11, z + dz, palette.steel)
      for (const dx of [-1.3, 1.3]) for (const dz of [-.57, .57]) box(g, .15, .06, .15, dx, .12, z+dz, palette.dark)
      if (showcase && buffer.cellId === 'ASM-02' && i < 2) {
        const body = bodyModel(i === 0 ? palette.white : palette.pale)
        body.position.set(0, 0.16, z)
        g.add(body)
      }
      if (showcase && buffer.cellId === 'ASM-02' && i === 2) {
        for (let x = -1.35; x < 1.4; x += 0.45) for (const dz of [-0.64, 0.64]) box(g, 0.24, 0.035, 0.05, x, 0.13, z + dz, palette.blue)
      }
    }
    target(g, { kind: 'buffer', id: buffer.bufferId, cellId: buffer.cellId, title: buffer.bufferId, subtitle: `${buffer.capacity}개 슬롯 · 공정 대기 구역`, description: showcase && buffer.cellId === 'ASM-02' ? '형태 확인용 예시: 점유 차체 2대와 예약 칸 1개. 실제 관측값이 아닙니다.' : '슬롯별 여유·예약·점유를 현재 관측값으로 표시합니다.' })
    label(labels, buffer.bufferId, p.x, 0.85, p.z + 4.2 * modelScale(config), { width: 6.8, color: '#62758b', background: '#edf2f8' })
  }
  for (const location of config.locations) {
    if (['CELL', 'BUFFER'].includes(location.locationType)) continue
    if (!showParts && ['STORE', 'PARTS_DOCK'].includes(location.locationType)) continue
    const g = new THREE.Group(), p = place(g, location)
    if(config.partsSupply && location.locationType==='PARTS_DOCK'){
      const table=partsDockModel(config.partsSupply.capacity);g.add(table)
      const text=label(labels,location.locationId,p.x,6.2*modelScale(config),p.z-2.3,{width:6,detail:'관측 대기',minScreenWidth:100,maxScreenWidth:115,compact:true,color:'#326c70',background:'#f4fbfa'})
      partsDocks.set(location.locationId,{table,text})
      continue
    }
    const parts = ['STORE', 'PARTS_DOCK'].includes(location.locationType)
    const w = parts ? 4.3 : 4.6, d = parts ? 3.5 : 4.2
    box(g, w, 0.08, d, 0, 0.06, 0, location.locationId === 'HOLD' ? 0xf3e9d8 : 0xe0eaf5)
    for (const x of [-w / 2, w / 2]) box(g, 0.06, 0.04, d, x, 0.12, 0, parts ? palette.steel : palette.blue)
    g.add(storageModel(location.locationId, location.locationType === 'STORE'))
    if (showcase && location.locationId === 'GOOD') g.add(bodyModel())
    label(labels, config.partsSupply && location.locationType==='STORE' ? '부품 공급 구역' : location.locationId, p.x, parts ? 3.8 : 2.5, p.z - 1.3, { width: parts ? 6 : 5.2 })
  }
  if(config.partsSupply && showParts){
    const home=config.vehicles.find(v=>v.kind==='AMR').initialPosition,p=toWorld(home)
    box(objects,5.25,.025,3.3,p.x,.02,p.z,0xc5dedb)
    label(labels,'AMR 대기',p.x,.6,p.z-3,{width:5,color:'#326c70',minScreenWidth:90,maxScreenWidth:110})
  }
  if (showcase) {
    // Explicit design-only examples, deliberately separate from observed vehicle state.
    const examples = [{ x: 45, y: 150, id: 'AGV-001', cargo: true }, { x: 430, y: 145, id: 'AGV-002' }]
    if (showParts) examples.push({ x: 180, y: 300, id: 'AMR-001', parts: true })
    for (const example of examples) {
      const g = vehicleModel(example.parts, example.id), p = place(g, example)
      if (example.cargo) { const body = bodyModel(); body.position.y = 1.065; g.add(body) }
      label(labels, example.id, p.x, 2.8, p.z + 1.3, { width: 5, color: '#3467c7' })
      target(g, { kind: 'vehicle', id: example.id, title: example.id, subtitle: example.parts ? '부품 운반 AMR · 모델 예시' : '차체 운반 AGV · 모델 예시', description: '외형·크기·적재 표현을 확인하기 위한 정적 샘플입니다. 표시 위치와 적재물은 실시간 공장 데이터가 아닙니다.' })
    }
  }
  objects.updateMatrixWorld(true)
  for (const object of objects.children) if (object.isGroup) cameraBounds.push(new THREE.Box3().setFromObject(object).expandByScalar(.1))
  if (!showcase) liveScene = createLiveScene({ scene, labels, routes, targets, entries, config, showParts, invalidate, equipment, slots, partsDocks })
  scene.add(new THREE.HemisphereLight(0xffffff, 0xb7c7db, 1.8))
  const sun = new THREE.DirectionalLight(0xffffff, 2.3)
  sun.position.set(cx - 16, 48, cz - 25)
  sun.target.position.set(cx, 0, cz)
  sun.castShadow = true
  sun.shadow.mapSize.set(2048, 2048)
  Object.assign(sun.shadow.camera, { left: -55, right: 55, top: 40, bottom: -40, near: 1, far: 130 })
  sun.shadow.normalBias = 0.035
  scene.add(sun, sun.target)

  function fit(mode = 'perspective') {
    drivingId = ''; controls.enabled = true; followControls.enabled = false
    controls.target.set(cx, 0, cz)
    camera.up.set(0, 1, 0)
    camera.position.set(cx + (mode === 'top' ? 0 : 18), mode === 'top' ? 75 : 40, cz + (mode === 'top' ? 0.01 : 75))
    camera.lookAt(controls.target)
    camera.updateMatrixWorld()
    let halfX = 0, halfY = 0
    for (const x of [bounds.minX, bounds.maxX]) for (const z of [bounds.minZ, bounds.maxZ]) for (const y of [0, 8]) {
      const p = new THREE.Vector3(x, y, z).applyMatrix4(camera.matrixWorldInverse)
      halfX = Math.max(halfX, Math.abs(p.x)); halfY = Math.max(halfY, Math.abs(p.y))
    }
    const aspect = Math.max(host.clientWidth, 1) / Math.max(host.clientHeight, 1)
    const halfHeight = Math.max(halfY, halfX / aspect) * 1.08
    camera.left = -halfHeight * aspect; camera.right = halfHeight * aspect
    camera.top = halfHeight; camera.bottom = -halfHeight
    camera.zoom = 1
    camera.updateProjectionMatrix()
    controls.update()
    invalidate()
  }
  let previousAspect = 0
  function resize() {
    const w = host.clientWidth, h = host.clientHeight
    if (!w || !h) return
    renderer.setSize(w, h)
    driverCamera.aspect = w / h; driverCamera.updateProjectionMatrix()
    const aspect = w / h
    if (!previousAspect) fit()
    else {
      // Preserve vertical span and camera orientation on resize; reset button fits all.
      const halfHeight = camera.top
      camera.left = -halfHeight * aspect; camera.right = halfHeight * aspect
      camera.updateProjectionMatrix()
    }
    previousAspect = aspect
    invalidate()
  }
  const raycaster = new THREE.Raycaster(), pointer = new THREE.Vector2()
  function pointerDown(event) { pointerStart = { x: event.clientX, y: event.clientY } }
  function pointerUp(event) {
    if (drivingId || !pointerStart || Math.hypot(event.clientX - pointerStart.x, event.clientY - pointerStart.y) > 5) return
    pointerStart = null
    const rect = renderer.domElement.getBoundingClientRect()
    pointer.set((event.clientX - rect.left) / rect.width * 2 - 1, -(event.clientY - rect.top) / rect.height * 2 + 1)
    raycaster.setFromCamera(pointer, camera)
    let object = raycaster.intersectObjects(targets.filter(target => target.visible), true)[0]?.object
    while (object && !object.userData.entry) object = object.parent
    if (object) select(object.userData.entry)
  }
  function contextLost(event) { event.preventDefault(); active = false; onError?.('3D 그래픽 연결이 중단됐습니다. 다시 불러오거나 2D 지도로 돌아갈 수 있습니다.') }
  function visibility() { liveScene?.stop(); if (!document.hidden) invalidate() }
  controls.addEventListener('change', invalidate)
  followControls.addEventListener('change', invalidate)
  renderer.domElement.addEventListener('pointerdown', pointerDown)
  renderer.domElement.addEventListener('pointerup', pointerUp)
  renderer.domElement.addEventListener('webglcontextlost', contextLost)
  document.addEventListener('visibilitychange', visibility)
  const observer = new ResizeObserver(resize)
  observer.observe(host)
  resize()
  return {
    entries,
    update(frame, live) { liveScene?.setFrame(frame, live); invalidate() },
    reset: () => fit(),
    drive(id, mode = 'third') {
      if (!id) { fit(); return true }
      const vehicle = liveScene?.vehicle(id)
      if (!vehicle) return false
      drivingId = id; cameraMode = mode; controls.enabled = false
      followControls.enabled = mode === 'third'
      driverCamera.fov = mode === 'third' ? 48 : 68; driverCamera.updateProjectionMatrix()
      followedYaw = vehicle.rotation.y; cameraTime = performance.now()
      const pose = vehicleFollowPose(vehicle.position, followedYaw, modelScale(config))
      driverCamera.position.set(pose.eye.x, pose.eye.y, pose.eye.z)
      followControls.target.set(pose.target.x, pose.target.y, pose.target.z)
      driverCamera.lookAt(followControls.target); followControls.update()
      invalidate(); return true
    },
    top: () => fit('top'),
    zoom(factor) { if (drivingId) return; camera.zoom = THREE.MathUtils.clamp(camera.zoom * factor, controls.minZoom, controls.maxZoom); camera.updateProjectionMatrix(); invalidate() },
    rotate(angle) { if (drivingId) return; const offset = camera.position.clone().sub(controls.target); offset.applyAxisAngle(new THREE.Vector3(0, 1, 0), angle); camera.position.copy(controls.target).add(offset); controls.update(); invalidate() },
    labels(value) { labelsEnabled = value; invalidate() },
    routes(value) { routes.visible = value; invalidate() },
    setActive(value) { active = value; if (!value) liveScene?.stop(); if (active) { resize(); invalidate() } },
    select(id) { const entry = entries.find(item => item.id === id); if (entry) select(entry) },
    dispose() {
      disposed = true
      cancelAnimationFrame(pending)
      observer.disconnect()
      controls.removeEventListener('change', invalidate)
      controls.dispose()
      followControls.removeEventListener('change', invalidate)
      followControls.dispose()
      document.removeEventListener('visibilitychange', visibility)
      renderer.domElement.removeEventListener('pointerdown', pointerDown)
      renderer.domElement.removeEventListener('pointerup', pointerUp)
      renderer.domElement.removeEventListener('webglcontextlost', contextLost)
      disposeTree(scene)
      environment.dispose()
      renderer.dispose()
      renderer.forceContextLoss()
      renderer.domElement.remove()
    },
  }
}
