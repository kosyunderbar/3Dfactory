import {spawn} from 'node:child_process'
import {existsSync,createWriteStream,writeFileSync,mkdirSync} from 'node:fs'
import {resolve} from 'node:path'
import {randomUUID} from 'node:crypto'

// Development-only process launcher. Never accept executable paths or CLI arguments from HTTP.
export function simulationLauncher(env,{spawnProcess=spawn,fetchSnapshot=fetch}={}) {
 const python=env.FACTORY_SIMULATOR_PYTHON
 const service=resolve(import.meta.dirname,'../factory-simulator')
 const enabled=Boolean(python && existsSync(python))
 let active=null,last=null
 const status=()=>({enabled,running:Boolean(active),runId:active?.runId ?? last?.runId ?? null,scenario:active?.scenario ?? last?.scenario ?? null,maintenance:(active ?? last)?.maintenance ?? null,state:active ? (active.stopping ? 'STOPPING' : 'RUNNING') : last?.state ?? 'IDLE'})
 return {name:'local-simulation-launcher',configureServer(server){
  server.middlewares.use('/__simulation',async(req,res)=>{
   const reply=(code,value)=>{res.statusCode=code;res.setHeader('Content-Type','application/json; charset=utf-8');res.setHeader('Cache-Control','no-store');res.end(JSON.stringify(value))}
   if(req.url!=='/' && req.url!==''){reply(404,{message:'경로를 찾을 수 없습니다.'});return}
   if(req.method==='GET'){reply(200,status());return}
   if(req.method!=='POST'){reply(405,{message:'지원하지 않는 요청입니다.'});return}
   // Browser launches must come from this local site's origin and use JSON.
   const origin=req.headers.origin
   let originUrl
   try{originUrl=new URL(origin)}catch{}
   if(!originUrl || originUrl.protocol!=='http:' || !['127.0.0.1','localhost','[::1]'].includes(originUrl.hostname) || originUrl.host!==req.headers.host || req.headers['content-type']!=='application/json') {reply(403,{message:'현재 관제 화면에서 다시 시도하세요.'});return}
   if(!enabled){reply(503,{message:'시뮬레이터 실행환경을 준비한 뒤 개발 서버를 다시 켜세요.'});return}
   let input=''
   try {
    for await(const chunk of req){input+=chunk.toString('utf8');if(input.length>256)throw Error()}
    const body=JSON.parse(input)
    if(['inspect','repair'].includes(body?.action)){
     if(Object.keys(body).length!==3 || typeof body.runId!=='string' || typeof body.faultId!=='string')throw Error()
     const job=active
     if(!job || job.stopping || job.runId!==body.runId || job.scenario!=='demo-maintenance'){reply(409,{message:'현재 실행 중인 수동 복구 시나리오에서만 조작할 수 있습니다.'});return}
     const fault=job.maintenance?.faults.find(item=>item.faultId===body.faultId)
     if(!fault || fault.stage!==({inspect:'DETECTED',repair:'INSPECTING'}[body.action])){reply(409,{message:'장애 상태가 변경됐습니다. 최신 상태를 확인하세요.'});return}
     if(job.pendingCommand){reply(409,{message:'앞선 조작을 처리하고 있습니다.'});return}
     const requestId=randomUUID()
     const result=await new Promise(resolve=>{
      const finish=value=>{clearTimeout(job.pendingCommand?.timer);job.pendingCommand=null;resolve(value)}
      job.pendingCommand={requestId,finish,timer:setTimeout(()=>finish({ok:false,message:'조작 결과 확인이 지연됩니다. 상태를 다시 확인하세요.'}),5000)}
      job.child.stdin.write(JSON.stringify({...body,requestId})+'\n',error=>{if(error && job.pendingCommand?.requestId===requestId)finish({ok:false,message:'시뮬레이터와의 제어 연결이 끊겼습니다.'})})
     })
     reply(result.ok ? 200 : 409,{...status(),message:result.message});return
    }
    if(body?.action==='stop'){
     if(Object.keys(body).length!==2 || typeof body.runId!=='string')throw Error()
     if(!active || !active.runId || body.runId!==active.runId){reply(409,{message:'중단할 실행이 현재 실행과 다릅니다.',...status()});return}
     if(!active.stopping){
      const job=active;job.stopping=true
      try{if(job.child.kill('SIGTERM')===false)throw Error()}catch{job.stopping=false;reply(502,{message:'중단 신호를 보내지 못했습니다.',...status()});return}
     }
     reply(202,status());return
    }
    if(Object.keys(body).length!==1 || !['demo','demo-three','demo-p0','demo-maintenance'].includes(body.scenario))throw Error()
    // Recheck after reading the body: concurrent POSTs must not start two children.
    if(active){reply(409,{message:'시뮬레이션이 이미 실행 중입니다.',...status()});return}
    const flag={demo:'--connected-demo','demo-three':'--connected-three-demo','demo-p0':'--connected-p0-demo','demo-maintenance':'--connected-maintenance-demo'}[body.scenario]
    const child=spawnProcess(python,['-m','factory_simulator',flag,'--traffic'],{cwd:service,shell:false,windowsHide:true,env:{...process.env,PYTHONUTF8:'1',PYTHONIOENCODING:'utf-8',INGESTION_TCP_HOST:'127.0.0.1',INGESTION_TCP_PORT:'9090'}})
    const job={child,runId:null,scenario:body.scenario};active=job
    const stateDir=resolve(service,'../../.build-cache/windows-dev')
    mkdirSync(resolve(stateDir,'logs'),{recursive:true})
    const recordFile=resolve(stateDir,'web-simulator.json')
    const record={id:child.pid,path:python,startedAtMs:Date.now()}
    if(Number.isInteger(child.pid))writeFileSync(recordFile,JSON.stringify(record))
    const logfile=resolve(stateDir,'logs/web-simulator.log')
    const log=createWriteStream(logfile,{flags:'a'});log.on('error',()=>{})
    child.stdin?.on('error',()=>job.pendingCommand?.finish({ok:false,message:'시뮬레이터와의 제어 연결이 끊겼습니다.'}))
    child.stdout.setEncoding('utf8')
    let first='',settled=false
    const failure=message=>{if(!settled){settled=true;reply(502,{message})}}
    const timeout=setTimeout(()=>failure('시뮬레이션 시작 확인이 지연되고 있습니다. 잠시 후 실행 목록을 확인하세요.'),15000)
    child.stdout.on('data',async chunk=>{
     log.write(chunk)
     first+=chunk.toString('utf8');if(first.length>8192){failure('시뮬레이터 시작 응답을 확인하지 못했습니다.');return}
     let newline
     while((newline=first.indexOf('\n'))>=0){
      const line=first.slice(0,newline);first=first.slice(newline+1)
      let info
      try{info=JSON.parse(line)}catch{failure('시뮬레이터 응답을 확인하지 못했습니다.');continue}
      if(info.type==='maintenance' && info.maintenance?.runId===job.runId){
       job.maintenance=info.maintenance
       const result=info.maintenance.lastCommand
       if(result && job.pendingCommand && result.requestId===job.pendingCommand.requestId)job.pendingCommand.finish(result)
       continue
      }
      if(job.runId)continue
      try {
      if(!/^run-[0-9]{8}-[A-Za-z0-9-]+$/.test(info.runId))throw Error()
      job.runId=info.runId
      // Wait for actual operations registration before switching the browser to the new run.
      for(let i=0;i<50 && !settled;i++){
       try {const response=await fetchSnapshot(`${env.OPERATIONS_PROXY_TARGET || 'http://127.0.0.1:8082'}/api/v1/runs/${info.runId}/snapshot`,{signal:AbortSignal.timeout(1000)});if(response.ok){settled=true;clearTimeout(timeout);reply(201,status());break}}catch{}
       await new Promise(resolve=>setTimeout(resolve,200))
      }
     }catch{failure('시뮬레이터 시작 응답을 확인하지 못했습니다.')}
     }
    })
    child.stderr.on('data',chunk=>log.write(chunk))
    child.on('error',()=>{job.pendingCommand?.finish({ok:false,message:'시뮬레이터 실행에 실패했습니다.'});if(active===job)active=null;last={runId:job.runId,scenario:job.scenario,maintenance:job.maintenance,state:'FAILED'};clearTimeout(timeout);failure('시뮬레이터를 실행하지 못했습니다. 실행환경을 확인하세요.');log.end()})
    child.on('exit',code=>{job.pendingCommand?.finish({ok:false,message:'시뮬레이션이 종료됐습니다.'});if(active===job)active=null;last={runId:job.runId,scenario:job.scenario,maintenance:job.maintenance,state:job.stopping?'STOPPED':code===0?'FINISHED':'FAILED'};clearTimeout(timeout);failure('시뮬레이터가 시작 중 종료됐습니다. 서버 연결을 확인하세요.');log.end()})
   }catch{reply(400,{message:'시나리오를 선택해 다시 시도하세요.'})}
  })
  // Vite restart/shutdown must not leave an untracked production process running.
  server.httpServer?.on('close',()=>active?.child.kill())
 }}
}
