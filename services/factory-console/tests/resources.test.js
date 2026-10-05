import test from 'node:test'
import assert from 'node:assert/strict'
import {ScopedQueries,apiPath} from '../src/resources.js'
const run='run-20261005-test', other='run-20261005-other'
const turn=()=>new Promise(resolve=>setTimeout(resolve,0))
const response=value=>({ok:true,text:async()=>JSON.stringify(value)})
test('late read and page responses cannot cross request, filter, run or epoch fences',async()=>{
 const replies=[];const queries=new ScopedQueries({fetcher:(path,options)=>new Promise(resolve=>replies.push({resolve,options,path}))})
 queries.reset(`${run}:epoch1`)
 const old=queries.one('page',run,apiPath(run,'events',{bodyId:'body-00001',cursor:'a+b/='}))
 const fresh=queries.one('page',run,apiPath(run,'events',{bodyId:'body-00002'}))
 assert.equal(replies[0].options.signal.aborted,true)
 replies[1].resolve(response({schemaVersion:1,runId:run,items:['fresh']}));assert.deepEqual((await fresh).items,['fresh'])
 replies[0].resolve(response({schemaVersion:1,runId:run,items:['old']}));assert.equal(await old,null)
 const epochOld=queries.one('layout',run,'/layout');queries.reset(`${other}:epoch2`)
 assert.equal(replies[2].options.signal.aborted,true)
 replies[2].resolve(response({schemaVersion:1,runId:run,config:{}}));assert.equal(await epochOld,null)
 const invalid=queries.one('layout',other,'/layout');replies[3].resolve(response({schemaVersion:1,runId:run}));await assert.rejects(invalid,/INVALID_RESPONSE/)
 assert.match(replies[0].path,/cursor=a%2Bb%2F%3D/);queries.close()
})
test('quality and trends publish only one validated period, never a partial or obsolete pair',async()=>{
 const replies=[];const queries=new ScopedQueries({fetcher:()=>new Promise(resolve=>replies.push(resolve))});queries.reset(run)
 const window={start:'2026-10-05T00:00:00.000Z',end:'2026-10-05T00:05:00.000Z'}
 const first=queries.group('quality',run,[{path:'/quality'},{path:'/trends'}],v=>v.every(x=>x.window.start===window.start && x.window.end===window.end))
 let published=false;first.then(()=>published=true)
 replies[0](response({schemaVersion:1,runId:run,window}));await turn();assert.equal(published,false)
 const fresh=queries.group('quality',run,[{path:'/quality'},{path:'/trends'}])
 replies[2](response({schemaVersion:1,runId:run,window}));replies[3](response({schemaVersion:1,runId:run,window}));assert.equal((await fresh).length,2)
 replies[1](response({schemaVersion:1,runId:run,window}));assert.equal(await first,null);queries.close()
})
