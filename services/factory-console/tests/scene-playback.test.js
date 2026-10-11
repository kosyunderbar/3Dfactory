import test from 'node:test'
import assert from 'node:assert/strict'
import { createPlayback } from '../src/scene3d/playback.js'
import { compatibleFrames } from '../src/scene3d/motion.js'

function frame(time) {
 return {runId:'run',sourceId:'source',serverEpoch:'epoch',sourceSeq:time+1,simElapsedMs:time,
  vehicles:[{vehicleId:'AGV',state:'MOVING',bodyId:'body',position:{x:time/100,y:0},traffic:{path:[{x:0,y:0},{x:100,y:0}],elapsedMs:time,durationMs:10000}}],
  bodies:[{bodyId:'body',locationType:'VEHICLE',locationId:'AGV'}],equipment:[],buffers:[]}
}
test('jitter and health republishes do not rewind or restart observed motion',()=>{
 const playback=createPlayback(), arrivals=[[0,0],[510,500],[980,1000],[1530,1500],[1990,2000],[2510,2500]]
 let index=0,last=-Infinity,stalls=0
 for(let now=0;now<=3000;now+=10){
  while(index<arrivals.length && arrivals[index][0]<=now){playback.push(frame(arrivals[index][1]),true,arrivals[index][0]);index++}
  if(now===1200)playback.push({...frame(1000),revision:99},true,now)
  const sample=playback.sample(now),x=sample.vehicles[0].position.x
  assert.ok(x>=last,`rewound at ${now}`)
  if(now>620 && now<2990 && x===last)stalls++
  assert.ok(x<=arrivals[index-1][1]/100,'must not extrapolate')
  last=x
 }
 assert.equal(stalls,0,'buffer absorbs 470–550ms arrival intervals')
})
test('a stationary cargo handoff leaves the other vehicle moving and changes cargo atomically',()=>{
 const a=frame(0),b=frame(500)
 const dock={vehicleId:'AMR',state:'IDLE',partsKitId:null,position:{x:200,y:0},traffic:{path:[{x:200,y:0}],segments:[],heading:0,durationMs:1,elapsedMs:0}}
 a.vehicles.push(dock);b.vehicles.push({...dock,state:'TRANSPORTING',partsKitId:'kit'})
 assert.equal(compatibleFrames(a,b),true)
 const player=createPlayback();player.push(a,true,0);player.push(b,true,500)
 const mid=player.sample(850)
 assert.equal(mid.vehicles[0].position.x,2.5)
 assert.equal(mid.vehicles[1].partsKitId,null)
 assert.equal(mid.frame,a)
 assert.equal(player.sample(1100).vehicles[1].partsKitId,'kit')
})
test('different paths never cut corners, disconnect freezes, and scope changes discard the buffer',()=>{
 const player=createPlayback(),a=frame(0),b=frame(500)
 b.vehicles[0].traffic.path=[{x:0,y:0},{x:0,y:100}];b.vehicles[0].position={x:0,y:5}
 player.push(a,true,0);player.push(b,true,500)
 assert.deepEqual(player.sample(850).vehicles[0].position,{x:0,y:0,yaw:-0})
 player.push(b,false,900)
 const frozen=player.sample(900)
 assert.equal(frozen.vehicles[0].position.y,5)
 assert.equal(frozen.animating,false)
 assert.deepEqual(player.sample(9000),frozen)
 const other={...frame(20),serverEpoch:'new'};player.push(other,true,9100)
 assert.equal(player.sample(9100).frame,other)
 player.push(null,false,9200);assert.equal(player.sample(9200).vehicles.length,0)
})
test('buffer underrun stops at the last observed pose and equipment time; no unlimited prediction',()=>{
 const player=createPlayback();player.push(frame(0),true,0);player.push(frame(500),true,500)
 const last=player.sample(2500)
 assert.equal(last.simElapsedMs,500);assert.equal(last.vehicles[0].position.x,5);assert.equal(last.animating,false)
 player.push(frame(1000),true,2600)
 assert.ok(player.sample(2600).vehicles[0].position.x>=5)
 player.stop();assert.equal(player.sample(2700).animating,false)
})
