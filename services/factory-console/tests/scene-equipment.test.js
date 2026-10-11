import test from 'node:test'
import assert from 'node:assert/strict'
import * as THREE from 'three'
import { vehicleCameraPose } from '../src/scene3d/vehicle-camera.js'
import { cellModel, vehicleModel, bodyModel, palette, disposeTree } from '../src/scene3d/models.js'

// Text textures need a canvas; geometry validation does not need a GPU context.
globalThis.document = {createElement: () => ({width:0,height:0,getContext:()=>({fillRect(){},fillText(){}})})}

test('front camera follows all headings and stays ahead of bumper and cargo', () => {
 for (const yaw of [0,Math.PI/2,Math.PI,-Math.PI/2,Math.PI*.75]) {
  for (const scale of [1,1.25]) {
   const origin={x:12,y:0,z:-7}, {eye,target}=vehicleCameraPose(origin,yaw,scale)
   const forward=new THREE.Vector3(1,0,0).applyAxisAngle(new THREE.Vector3(0,1,0),yaw)
   const mount=new THREE.Vector3(eye.x-origin.x,0,eye.z-origin.z)
   const look=new THREE.Vector3(target.x-eye.x,0,target.z-eye.z).normalize()
   assert.ok(mount.dot(forward)>1.9*scale)
   assert.ok(look.dot(forward)>.999999)
   assert.equal(eye.y,1.18*scale)
  }
 }
 const frozen={x:20,y:0,z:30}
 assert.deepEqual(vehicleCameraPose(frozen,-1.2),vehicleCameraPose(frozen,-1.2),'no clock or extrapolation in camera placement')
})

test('detailed cells and loaded vehicles stay within existing traffic envelopes', () => {
 for (const inspection of [false,true]) {
  const g=cellModel(inspection)
  for(const work of [0,1])for(const phase of [0,Math.PI/2,Math.PI,Math.PI*1.5]){
   g.userData.pose(work,phase)
   const bounds=new THREE.Box3().setFromObject(g)
   assert.ok(bounds.min.x>=-2.16 && bounds.max.x<=2.16,'cell fits 48*0.09 footprint during work')
   assert.ok(bounds.min.z>=-2.7 && bounds.max.z<=2.7,'cell fits 60*0.09 footprint during work')
  }
  disposeTree(g)
 }
 const g=vehicleModel(false,'AGV-002'),body=bodyModel();body.position.y=1.065;g.add(body)
 const bounds=new THREE.Box3().setFromObject(g)
 for(const x of [bounds.min.x,bounds.max.x])for(const z of [bounds.min.z,bounds.max.z])assert.ok(Math.hypot(x,z)<24*.09,'loaded model fits yaw-independent traffic radius')
 disposeTree(g)
})

test('inspection paint and equipment lamps remain independent per object', () => {
 const first=bodyModel(),second=bodyModel()
 first.userData.paint.forEach(m=>m.color.setHex(palette.amber))
 assert.ok(second.userData.paint.every(m=>m.color.getHex()===palette.white))
 const a=cellModel(false,'ASM-01'),b=cellModel(false,'ASM-02')
 a.userData.lamp.material.color.setHex(0xff0000)
 assert.notEqual(b.userData.lamp.material.color.getHex(),0xff0000)
 for(const g of [first,second,a,b])disposeTree(g)
})

test('third-person camera frames the whole loaded vehicle across headings and screen sizes', async () => {
 const {vehicleFollowPose,followHeading}=await import('../src/scene3d/vehicle-camera.js')
 const vehicle=vehicleModel(false,'AGV-001'),cargo=bodyModel();cargo.position.y=1.065;vehicle.add(cargo)
 for(const yaw of [0,Math.PI/2,-Math.PI/2,Math.PI])for(const scale of [1,1.25])for(const aspect of [.8,1.8,2.7]){
  vehicle.position.set(15,0,-20);vehicle.rotation.y=yaw;vehicle.scale.setScalar(scale)
  const bounds=new THREE.Box3().setFromObject(vehicle),pose=vehicleFollowPose(vehicle.position,yaw,scale)
  const camera=new THREE.PerspectiveCamera(48,aspect,.05,500)
  camera.position.set(pose.eye.x,pose.eye.y,pose.eye.z);camera.lookAt(pose.target.x,pose.target.y,pose.target.z);camera.updateMatrixWorld()
  for(const x of [bounds.min.x,bounds.max.x])for(const y of [bounds.min.y,bounds.max.y])for(const z of [bounds.min.z,bounds.max.z]){
   const p=new THREE.Vector3(x,y,z).project(camera)
   assert.ok(Math.abs(p.x)<.95 && Math.abs(p.y)<.95 && p.z<1,'full cargo and wheels must remain in frame')
  }
 }
 const from=Math.PI-.01,to=-Math.PI+.01,next=followHeading(from,to,1/60)
 assert.ok(next>from && next-from<.02,'cross the wrap boundary by the short turn')
 assert.equal(followHeading(1,1,1),1,'stationary heading never drifts')
 assert.equal(followHeading(0,1,0),0,'zero elapsed time cannot advance the camera')
 disposeTree(vehicle)
})
