import test from 'node:test'
import assert from 'node:assert/strict'
import {createServer} from 'node:http'
import {EventEmitter} from 'node:events'
import {PassThrough} from 'node:stream'
import {simulationLauncher} from '../simulation-launcher.js'

test('local launch validates origin/scenario, prevents duplicate children and tracks completion',async()=>{
 let starts=0,kills=0,child,command
 const plugin=simulationLauncher({FACTORY_SIMULATOR_PYTHON:process.execPath},{
  spawnProcess:(exe,args,options)=>{
   starts++;command={exe,args,options};child=new EventEmitter();child.stdout=new PassThrough();child.stderr=new PassThrough();child.stdin=new PassThrough();child.kill=signal=>{assert.equal(signal,'SIGTERM');kills++;return true}
   setImmediate(()=>child.stdout.write(JSON.stringify({runId:'run-20261006-button-test'})+'\n'))
   return child
  },fetchSnapshot:async()=>({ok:true})
 })
 let handler
 const server=createServer((req,res)=>{req.url='/';handler(req,res)})
 plugin.configureServer({middlewares:{use:(path,fn)=>{handler=fn}},httpServer:server})
 await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve))
 const origin=`http://127.0.0.1:${server.address().port}`
 const post=(body,source=origin)=>fetch(origin,{method:'POST',headers:{'Content-Type':'application/json',Origin:source},body:JSON.stringify(body)})
 try{
  assert.equal((await post({scenario:'demo'},'http://malicious.example')).status,403)
  assert.equal((await post({scenario:'demo'},'invalid origin')).status,403)
  assert.equal((await post({scenario:'arbitrary-command'})).status,400)
  assert.equal((await post({scenario:'demo',arguments:['anything']})).status,400)
  assert.equal(starts,0)
  const started=await post({scenario:'demo'});assert.equal(started.status,201)
  assert.equal((await started.json()).runId,'run-20261006-button-test')
  assert.deepEqual(command.args,['-m','factory_simulator','--connected-demo','--traffic']);assert.equal(command.options.shell,false)
  assert.equal((await post({scenario:'demo-p0'})).status,409);assert.equal(starts,1)
  child.emit('exit',0)
  const manual=await post({scenario:'demo-maintenance'});assert.equal(manual.status,201)
  assert.deepEqual(command.args,['-m','factory_simulator','--connected-maintenance-demo','--traffic'])
  const maintenance={runId:'run-20261006-button-test',mode:'MANUAL',faults:[{faultId:'fault-00001',stage:'DETECTED',cause:'위치 센서 불일치'}],lastCommand:null}
  child.stdout.write(JSON.stringify({type:'maintenance',maintenance})+'\n')
  assert.equal((await (await fetch(origin)).json()).maintenance.faults[0].stage,'DETECTED')
  assert.equal((await post({action:'inspect',runId:'run-stale',faultId:'fault-00001'})).status,409)
  assert.equal((await post({action:'repair',runId:maintenance.runId,faultId:'fault-00001'})).status,409)
  assert.equal((await post({action:'inspect',runId:maintenance.runId,faultId:'fault-00001'},'http://malicious.example')).status,403)
  let commands=0
  child.stdin.on('data',chunk=>{
   commands++
   const command=JSON.parse(chunk.toString())
   maintenance.faults[0].stage=command.action==='inspect' ? 'INSPECTING' : 'VERIFYING'
   maintenance.lastCommand={requestId:command.requestId,ok:true,message:null}
   child.stdout.write(JSON.stringify({type:'maintenance',maintenance})+'\n')
  })
  const inspected=await post({action:'inspect',runId:maintenance.runId,faultId:'fault-00001'})
  assert.equal(inspected.status,200);assert.equal((await inspected.json()).maintenance.faults[0].stage,'INSPECTING')
  assert.equal((await post({action:'inspect',runId:maintenance.runId,faultId:'fault-00001'})).status,409)
  assert.equal((await post({action:'repair',runId:maintenance.runId,faultId:'fault-00001'})).status,200)
  assert.equal(commands,2)
  maintenance.faults[0].stage='RESOLVED';child.stdout.write(JSON.stringify({type:'maintenance',maintenance})+'\n')
  child.emit('exit',0)
  assert.equal((await (await fetch(origin)).json()).maintenance.faults[0].stage,'RESOLVED')
  const finished=await (await fetch(origin)).json();assert.equal(finished.running,false);assert.equal(finished.state,'FINISHED')
  const three=await post({scenario:'demo-three'});assert.equal(three.status,201);assert.equal((await three.json()).scenario,'demo-three')
  assert.deepEqual(command.args,['-m','factory_simulator','--connected-three-demo','--traffic'])
  assert.equal((await post({action:'stop',runId:'run-stale'})).status,409)
  assert.equal((await post({action:'stop',runId:'run-20261006-button-test'},'http://malicious.example')).status,403)
  assert.equal(kills,0)
  const stopped=await post({action:'stop',runId:'run-20261006-button-test'})
  assert.equal(stopped.status,202);assert.equal((await stopped.json()).state,'STOPPING')
  assert.equal((await post({action:'stop',runId:'run-20261006-button-test'})).status,202)
  assert.equal(kills,1)
  assert.equal((await post({scenario:'demo'})).status,409)
  child.emit('exit',2)
  const state=await (await fetch(origin)).json();assert.equal(state.running,false);assert.equal(state.state,'STOPPED')
  assert.equal((await post({action:'stop',runId:state.runId})).status,409)
  assert.equal((await post({scenario:'demo'})).status,201)
  child.emit('exit',0)
 }finally{server.closeAllConnections();await new Promise(resolve=>server.close(resolve))}
})
