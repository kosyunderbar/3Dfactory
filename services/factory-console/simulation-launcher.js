import {spawn} from 'node:child_process'
import {existsSync,createWriteStream,writeFileSync,mkdirSync} from 'node:fs'
import {resolve} from 'node:path'

// Development-only process launcher. Never accept executable paths or CLI arguments from HTTP.
export function simulationLauncher(env,{spawnProcess=spawn,fetchSnapshot=fetch}={}) {
 const python=env.FACTORY_SIMULATOR_PYTHON
 const service=resolve(import.meta.dirname,'../factory-simulator')
 const enabled=Boolean(python && existsSync(python))
 let active=null,last=null
 const status=()=>({enabled,running:Boolean(active),runId:active?.runId ?? last?.runId ?? null,state:active ? 'RUNNING' : last?.state ?? 'IDLE'})
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
   if(active){reply(409,{message:'시뮬레이션이 이미 실행 중입니다.',...status()});return}
   let input=''
   try {
    for await(const chunk of req){input+=chunk.toString('utf8');if(input.length>256)throw Error()}
    const body=JSON.parse(input)
    if(Object.keys(body).length!==1 || !['demo','demo-three','demo-p0'].includes(body.scenario))throw Error()
    // Recheck after reading the body: concurrent POSTs must not start two children.
    if(active){reply(409,{message:'시뮬레이션이 이미 실행 중입니다.',...status()});return}
    const flag={demo:'--connected-demo','demo-three':'--connected-three-demo','demo-p0':'--connected-p0-demo'}[body.scenario]
    const child=spawnProcess(python,['-m','factory_simulator',flag],{cwd:service,shell:false,windowsHide:true,env:{...process.env,PYTHONUTF8:'1',PYTHONIOENCODING:'utf-8',INGESTION_TCP_HOST:'127.0.0.1',INGESTION_TCP_PORT:'9090'}})
    const job={child,runId:null};active=job
    const stateDir=resolve(service,'../../.build-cache/windows-dev')
    mkdirSync(resolve(stateDir,'logs'),{recursive:true})
    const recordFile=resolve(stateDir,'web-simulator.json')
    const record={id:child.pid,path:python,startedAtMs:Date.now()}
    if(Number.isInteger(child.pid))writeFileSync(recordFile,JSON.stringify(record))
    const logfile=resolve(stateDir,'logs/web-simulator.log')
    const log=createWriteStream(logfile,{flags:'a'});log.on('error',()=>{})
    let first='',settled=false
    const failure=message=>{if(!settled){settled=true;reply(502,{message})}}
    const timeout=setTimeout(()=>failure('시뮬레이션 시작 확인이 지연되고 있습니다. 잠시 후 실행 목록을 확인하세요.'),15000)
    child.stdout.on('data',async chunk=>{
     log.write(chunk)
     if(job.runId)return
     first+=chunk.toString('utf8');if(first.length>8192){failure('시뮬레이터 시작 응답을 확인하지 못했습니다.');return}
     const newline=first.indexOf('\n');if(newline<0)return
     try {
      const info=JSON.parse(first.slice(0,newline))
      if(!/^run-[0-9]{8}-[A-Za-z0-9-]+$/.test(info.runId))throw Error()
      job.runId=info.runId
      // Wait for actual operations registration before switching the browser to the new run.
      for(let i=0;i<50 && !settled;i++){
       try {const response=await fetchSnapshot(`${env.OPERATIONS_PROXY_TARGET || 'http://127.0.0.1:8082'}/api/v1/runs/${info.runId}/snapshot`,{signal:AbortSignal.timeout(1000)});if(response.ok){settled=true;clearTimeout(timeout);reply(201,status());return}}catch{}
       await new Promise(resolve=>setTimeout(resolve,200))
      }
     }catch{failure('시뮬레이터 시작 응답을 확인하지 못했습니다.')}
    })
    child.stderr.on('data',chunk=>log.write(chunk))
    child.on('error',()=>{if(active===job)active=null;last={runId:job.runId,state:'FAILED'};clearTimeout(timeout);failure('시뮬레이터를 실행하지 못했습니다. 실행환경을 확인하세요.');log.end()})
    child.on('exit',code=>{if(active===job)active=null;last={runId:job.runId,state:code===0?'FINISHED':'FAILED'};clearTimeout(timeout);failure('시뮬레이터가 시작 중 종료됐습니다. 서버 연결을 확인하세요.');log.end()})
   }catch{reply(400,{message:'시나리오를 선택해 다시 시도하세요.'})}
  })
  // Vite restart/shutdown must not leave an untracked production process running.
  server.httpServer?.on('close',()=>active?.child.kill())
 }}
}
