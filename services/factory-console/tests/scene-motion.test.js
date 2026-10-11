import test from 'node:test'
import assert from 'node:assert/strict'
import { samplePath, sampleMotion, compatibleFrames, framePositions, bodyPlacement } from '../src/scene3d/motion.js'

test('motion follows corners on observed path and never extrapolates', () => {
 const path=[{x:0,y:0},{x:10,y:0},{x:10,y:10}]
 assert.deepEqual(samplePath(path,.75),{x:10,y:5,yaw:-Math.PI/2})
 assert.equal(samplePath(path,2).y,10)
 const a={runId:'a',sourceId:'s',serverEpoch:'e',simElapsedMs:100,vehicles:[{vehicleId:'AGV',state:'MOVING',bodyId:'body',traffic:{path,elapsedMs:100,durationMs:1000}}]}
 const b=structuredClone(a);b.simElapsedMs=600;b.vehicles[0].traffic.elapsedMs=600
 assert.equal(compatibleFrames(a,b),true)
 assert.equal(framePositions(b,a,.5)[0].position.x,7)
 for(const mutate of [v=>v.runId='other',v=>v.serverEpoch='new',v=>v.vehicles[0].bodyId=null,v=>v.vehicles[0].state='RETURNING',v=>v.vehicles[0].traffic.path=[{x:0,y:0},{x:10,y:10}],v=>v.simElapsedMs=5000]){
  const changed=structuredClone(b);mutate(changed);assert.equal(compatibleFrames(a,changed),false)
 }
})
test('cargo belongs to vehicle, Bay uses actual slot, bulk storage has one counted representative',()=>{
 const config={locations:[{locationId:'BAY',x:100,y:100},{locationId:'GOOD',x:700,y:70}],buffers:[{bufferId:'BAY',slotIds:['S1','S2'],capacity:2}]}
 const cargo={bodyId:'a',locationType:'VEHICLE',locationId:'AGV'}
 assert.deepEqual(bodyPlacement(cargo,config,[cargo]),{vehicleId:'AGV'})
 const bay={bodyId:'b',locationType:'BUFFER',locationId:'BAY',locationSlotId:'S2'}
 assert.ok(bodyPlacement(bay,config,[bay]).y>100)
 assert.equal(bodyPlacement({...bay,locationSlotId:'missing'},config,[bay]),null)
 const good=[{bodyId:'c',locationType:'RESULT',locationId:'GOOD'},{bodyId:'d',locationType:'RESULT',locationId:'GOOD'}]
 assert.equal(bodyPlacement(good[0],config,good).count,2)
 assert.equal(bodyPlacement(good[1],config,good),null)
})


test('lane profile rotates in place, accelerates, brakes and preserves parked heading', () => {
 const motion={path:[{x:0,y:0},{x:100,y:0}],durationMs:4100,elapsedMs:0,heading:Math.PI/2,
  segments:[{turnMs:800,travelMs:3300,rampMs:500,initialHeading:Math.PI/2,heading:0,peakSpeed:100/2800}]}
 const halfTurn=sampleMotion(motion,400)
 assert.equal(halfTurn.x,0);assert.equal(halfTurn.y,0);assert.equal(halfTurn.yaw,-Math.PI/4)
 assert.ok(sampleMotion(motion,900).x < sampleMotion(motion,1000).x/2)
 assert.equal(sampleMotion(motion,4100).x,100)
 assert.equal(sampleMotion(motion,9999).x,100)
 assert.equal(sampleMotion({path:[{x:3,y:4},{x:3,y:4}],heading:1.2,segments:[],durationMs:100,elapsedMs:0}).yaw,-1.2)
 const a={runId:'a',sourceId:'s',serverEpoch:'e',simElapsedMs:100,vehicles:[{vehicleId:'AGV',state:'MOVING',traffic:motion}]}
 const b=structuredClone(a);b.simElapsedMs=200;b.vehicles[0].traffic.segments[0].turnMs=900
 assert.equal(compatibleFrames(a,b),false,'different timing cannot blend despite identical geometry')
})


test('body-only view includes the final outer return aisle and cargo clearance',async()=>{
 const {floorBounds,WORLD_SCALE}=await import('../src/scene3d/coordinates.js')
 const config={traffic:{policyVersion:4,bounds:{minX:-160,maxX:880,minY:-100,maxY:820}}}
 assert.ok(floorBounds(config,false).maxZ>=(650+33)*WORLD_SCALE)
})
