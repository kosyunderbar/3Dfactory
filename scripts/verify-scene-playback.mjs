import fs from 'node:fs'
import assert from 'node:assert/strict'
import { createPlayback } from '../services/factory-console/src/scene3d/playback.js'
const events=fs.readFileSync(process.argv[2],'utf8').trim().split('\n').map(JSON.parse)
const config=events.find(e=>e.eventType==='RUN_STARTED').payload.config
const frames=events.filter(e=>e.eventType==='FACTORY_SNAPSHOT').map(e=>({...e.payload,runId:e.runId,sourceId:e.sourceId,sourceSeq:e.sourceSeq,serverEpoch:'replay'}))
const offsets=[0,35,-20,45,-30,15], start=frames[0].simElapsedMs
const arrivals=frames.map((frame,i)=>({frame,at:frame.simElapsedMs-start+offsets[i%offsets.length]}))
const playback=createPlayback();let index=0,samples=0,minDistance=Infinity,lastTime=-Infinity
for(let now=0;now<=arrivals.at(-1).at+700;now+=1000/60){
 while(index<arrivals.length && arrivals[index].at<=now){const {frame,at}=arrivals[index++];playback.push(frame,true,at)}
 const sample=playback.sample(now)
 assert(sample.simElapsedMs>=lastTime,'presentation time must not rewind');lastTime=sample.simElapsedMs
 for(const v of sample.vehicles){
  const {x,y}=v.position,r=config.traffic.vehicleRadius
  assert(x-r>=config.traffic.bounds.minX && x+r<=config.traffic.bounds.maxX)
  assert(y-r>=config.traffic.bounds.minY && y+r<=config.traffic.bounds.maxY)
  for(const o of config.traffic.obstacles)assert(x<o.minX-r || x>o.maxX+r || y<o.minY-r || y>o.maxY+r)
 }
 for(let i=0;i<sample.vehicles.length;i++)for(let j=i+1;j<sample.vehicles.length;j++){
  const a=sample.vehicles[i].position,b=sample.vehicles[j].position,d=Math.hypot(a.x-b.x,a.y-b.y)
  minDistance=Math.min(minDistance,d)
  assert(d>=2*config.traffic.vehicleRadius+config.traffic.clearance-1e-6,'fleet clearance')
 }
 for(const body of sample.frame?.bodies ?? [])if(body.locationType==='VEHICLE')assert(sample.vehicles.find(v=>v.vehicleId===body.locationId)?.bodyId===body.bodyId,'cargo handoff must be atomic')
 samples++
}
assert.equal(playback.sample(Infinity).frame.runState,'FINISHED')
console.log(JSON.stringify({runId:events[0].runId,mode:'recorded source replay with receipt jitter, not new connected production',snapshots:frames.length,renderSamples:samples,minVehicleCenterDistance:minDistance,monotonicPresentation:true,cargoConsistent:true,finished:true},null,2))
