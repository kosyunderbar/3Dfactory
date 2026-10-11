import fs from 'node:fs'
import assert from 'node:assert/strict'
import { compatibleFrames,framePositions,sampleMotion } from '../services/factory-console/src/scene3d/motion.js'
const input=process.argv[2]
if(!input) throw new Error('Usage: node scripts/verify-3d-motion.mjs <originals.ndjson>')
const rows=fs.readFileSync(input,'utf8').trim().split('\n').map(JSON.parse)
const config=rows.find(e=>e.eventType==='RUN_STARTED').payload.config
const frames=rows.filter(e=>e.eventType==='FACTORY_SNAPSHOT').map(e=>({...e.payload,runId:e.runId,sourceId:e.sourceId,serverEpoch:'verified-source'}))
const requireForward=process.argv.includes('--require-forward')
const requireFinalHome=process.argv.includes('--require-final-home')
const finalReturns=new Set()
let loadedLegs=0,compatible=0,samples=0,minDistance=Infinity
for(let i=0;i<frames.length;i++) {
 const b=frames[i],a=frames[i-1],can=compatibleFrames(a,b)
 for(const v of b.vehicles) if(v.traffic) {
  const home=config.vehicles.find(c=>c.vehicleId===v.vehicleId)?.initialPosition
  const goal=v.traffic.path.at(-1)
  if(requireFinalHome && v.kind==='AGV' && v.state==='RETURNING' && home && goal.x===home.x && goal.y===home.y){
   assert(b.bodies.every(body=>body.locationType==='RESULT') && !b.activeTransports.length,'Final return cannot start before all production and transports finish')
   assert(!v.bodyId && !v.partsKitId,'Final return must be empty')
   for(const corner of [{x:845,y:650},{x:0,y:650}])assert(v.traffic.path.some(p=>p.x===corner.x && p.y===corner.y),'Final return must use the outer aisle')
   finalReturns.add(v.vehicleId)
  }
  if(requireForward && (v.bodyId || v.partsKitId)) {
   for(let j=0;j<(v.traffic.segments?.length ?? 0);j++) {
    const a=v.traffic.path[j],b=v.traffic.path[j+1],s=v.traffic.segments[j]
    const dx=b.x-a.x,dy=b.y-a.y
    if(Math.hypot(dx,dy)>1e-8){assert(dx*Math.cos(s.heading)+dy*Math.sin(s.heading)>0, `Loaded vehicle reverses: ${v.vehicleId}`);loadedLegs++}
   }
  }
  const p=sampleMotion(v.traffic)
  assert(Math.hypot(p.x-v.position.x,p.y-v.position.y)<1e-6, `Renderer/source pose mismatch: ${v.vehicleId}`)
 }
 if(can)compatible++
 for(const f of [0,.1,.25,.5,.75,.9,1]) {
  const vs=framePositions(b,can?a:null,f)
  for(const v of vs) {
   const p=v.position,r=config.traffic.vehicleRadius
   assert(p.x-r>=config.traffic.bounds.minX && p.x+r<=config.traffic.bounds.maxX)
   assert(p.y-r>=config.traffic.bounds.minY && p.y+r<=config.traffic.bounds.maxY)
   for(const o of config.traffic.obstacles) assert(p.x<o.minX-r || p.x>o.maxX+r || p.y<o.minY-r || p.y>o.maxY+r)
  }
  for(let j=0;j<vs.length;j++)for(let k=j+1;k<vs.length;k++) {
   const d=Math.hypot(vs[j].position.x-vs[k].position.x,vs[j].position.y-vs[k].position.y)
   minDistance=Math.min(minDistance,d);assert(d>=2*config.traffic.vehicleRadius+config.traffic.clearance-1e-6)
  }
  samples++
 }
}
if(requireFinalHome)for(const v of frames.at(-1).vehicles.filter(v=>v.kind==='AGV')){
 const home=config.vehicles.find(c=>c.vehicleId===v.vehicleId).initialPosition
 assert.deepEqual(v.position,home,'Finished AGVs must be at their own initial positions')
 assert.equal(v.state,'IDLE')
}
const result={requireForward,requireFinalHome,finalReturns:[...finalReturns],loadedLegObservations:loadedLegs,runId:rows[0].runId,events:rows.length,snapshots:frames.length,compatiblePairs:compatible,renderedFleetSamples:samples,minVehicleCenterDistance:minDistance,finished:frames.at(-1).runState==='FINISHED',bodyResults:frames.at(-1).bodies.map(b=>({id:b.bodyId,result:b.inspectionResult,location:b.locationId})),maxFrameBytes:Math.max(...rows.map(e=>Buffer.byteLength(JSON.stringify(e))))}
assert(result.finished, 'Use a completed source run for final verification')
console.log(JSON.stringify(result,null,2))
