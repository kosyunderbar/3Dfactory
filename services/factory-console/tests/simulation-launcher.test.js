import test from 'node:test'
import assert from 'node:assert/strict'
import {createServer} from 'node:http'
import {EventEmitter} from 'node:events'
import {PassThrough} from 'node:stream'
import {simulationLauncher} from '../simulation-launcher.js'

test('local launch validates origin/scenario, prevents duplicate children and tracks completion',async()=>{
 let starts=0,child,command
 const plugin=simulationLauncher({FACTORY_SIMULATOR_PYTHON:process.execPath},{
  spawnProcess:(exe,args,options)=>{
   starts++;command={exe,args,options};child=new EventEmitter();child.stdout=new PassThrough();child.stderr=new PassThrough();child.kill=()=>{}
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
  assert.deepEqual(command.args,['-m','factory_simulator','--connected-demo']);assert.equal(command.options.shell,false)
  assert.equal((await post({scenario:'demo-p0'})).status,409);assert.equal(starts,1)
  child.emit('exit',0)
  const finished=await (await fetch(origin)).json();assert.equal(finished.running,false);assert.equal(finished.state,'FINISHED')
  const three=await post({scenario:'demo-three'});assert.equal(three.status,201)
  assert.deepEqual(command.args,['-m','factory_simulator','--connected-three-demo'])
  child.emit('exit',0)
 }finally{server.closeAllConnections();await new Promise(resolve=>server.close(resolve))}
})
