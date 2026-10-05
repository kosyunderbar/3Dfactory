import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { ConsoleFeed, displayState } from '../src/feed.js'
const example=JSON.parse(readFileSync(new URL('../../../contracts/v1/examples/monitoring-examples.json',import.meta.url),'utf8')).snapshot
const bundle=(revision,seq=30,epoch=example.serverEpoch) => ({...structuredClone(example),revision,sourceSeq:seq,serverEpoch:epoch})
const turn=() => new Promise(resolve=>setImmediate(resolve))
class Source {
  constructor(){this.listeners=new Map();this.readyState=1;this.closed=false}
  addEventListener(name,listener){this.listeners.set(name,listener)}
  send(view){this.listeners.get('factory-snapshot')({data:JSON.stringify(view),lastEventId:`${view.serverEpoch}:${view.revision}`})}
  close(){this.closed=true}
}
function setup(){
  let clock=0;const sources=[],reads=[],changes=[],timeouts=new Map();let next=0
  const timers={setTimeout(fn,ms){const id=++next;timeouts.set(id,{fn,ms});return id},clearTimeout(id){timeouts.delete(id)},setInterval(){return ++next},clearInterval(){}}
  const feed=new ConsoleFeed({onChange:state=>changes.push(state),now:()=>clock,timers,eventSource:()=>{const source=new Source();sources.push(source);return source},fetcher:()=>new Promise(resolve=>reads.push(resolve))})
  const resolve=(index,view)=>reads[index]({ok:true,text:async()=>JSON.stringify(view)})
  return {feed,sources,reads,changes,timeouts,resolve,time(value){clock=value}}
}
test('generation, first SSE epoch and revisions prevent stale REST/run/sequence replacement',async()=>{
  const env=setup(),{feed,sources}=env;feed.select(example.runId);sources[0].onopen();sources[0].send(bundle(2));env.resolve(0,bundle(1));await turn();assert.equal(feed.view.revision,2)
  sources[0].onopen();sources[0].send(bundle(3));const old=sources[0];feed.reconnect();const retry=[...env.timeouts.values()].find(item=>item.ms===2000);retry.fn();sources[1].onopen()
  const epoch='22222222-2222-4222-8222-222222222222';sources[1].send(bundle(1,31,epoch));env.resolve(1,bundle(999));await turn();assert.equal(feed.view.serverEpoch,epoch)
  old.send(bundle(1000));assert.equal(feed.view.revision,1)
  env.resolve(2,bundle(2,31,epoch));await turn();assert.equal(feed.view.revision,2)
  sources[1].send(bundle(3,30,epoch));assert.equal(feed.connection,'RECONNECTING');assert.equal(feed.view.sourceSeq,31)
  feed.select('run-20261005-another');old.send(bundle(1001));assert.equal(feed.view,null);assert.equal(sources[1].closed,true);feed.close()
})
test('duplicate/heartbeat/open alone do not refresh observation; 3s/10s stop normal display',()=>{
  const env=setup(),{feed,sources}=env;feed.select(example.runId);sources[0].onopen();assert.equal(feed.view,null)
  sources[0].send(bundle(1));env.time(2900);sources[0].send(bundle(1));assert.equal(feed.receiptAt,0)
  assert.equal(displayState(feed.view,0,2500,'OPEN').stale,true) // 500ms source age +2500ms receipt age
  assert.match(displayState(feed.view,0,3000,'OPEN').label,/마지막 확인값/)
  env.time(10000);feed.checkSilence();assert.equal(sources[0].closed,true);assert.equal(feed.connection,'RECONNECTING');assert.equal(feed.view.revision,1)
  assert.match(displayState(feed.view,0,10000,'RECONNECTING').label,/화면 연결 확인/)
  const archived={...bundle(2),dataStatus:'FINISHED',freshness:{...example.freshness,state:'ARCHIVED'}}
  assert.match(displayState(archived,9000,10000,'OPEN').label,/종료 확인/);assert.equal(example.dataStatus,'LIVE');feed.close()
})
