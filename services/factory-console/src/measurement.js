// Development-only observer. It never changes the physical bundle or product UI.
const enabled = import.meta.env.DEV && import.meta.env.VITE_FACTORY_MEASUREMENT === 'true'
let queue = [], timer, started = false, lastFrame = null,frameHandle,observer
const context = () => ({visibility:document.visibilityState,focused:document.hasFocus(),width:innerWidth,height:innerHeight,dpr:devicePixelRatio,clockOffsetMs:Date.now()-(performance.timeOrigin+performance.now())})
function append(row) { if (queue.length < 1000) queue.push(row) }
function flush() {
  if (!queue.length) return
  const rows=queue;queue=[]
  fetch('/__measurement',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(rows),keepalive:true}).catch(()=>{ /* Missing samples are detected in the measurement report. */ })
}
export function startMeasurement() {
  if (!enabled || started) return
  started=true;timer=setInterval(flush,2000)
  function frame(at) {
    if(lastFrame!==null)append({kind:'frame',at:performance.timeOrigin+at,intervalMs:at-lastFrame,...context()})
    lastFrame=at;frameHandle=requestAnimationFrame(frame)
  }
  frameHandle=requestAnimationFrame(frame)
  if (typeof PerformanceObserver==='function') {
    try {observer=new PerformanceObserver(list=>{for(const e of list.getEntries())append({kind:'longtask',at:performance.timeOrigin+e.startTime,durationMs:e.duration,...context()})});observer.observe({type:'longtask',buffered:true})} catch { /* Unsupported browser, reported by environment capture. */ }
  }
  addEventListener('pagehide',stopMeasurement,{once:true})
}
function stopMeasurement(){flush();clearInterval(timer);cancelAnimationFrame(frameHandle);observer?.disconnect();removeEventListener('pagehide',stopMeasurement)}
if(import.meta.hot)import.meta.hot.dispose(stopMeasurement)
export async function measureRender(view, receiptAt, nextTick) {
  if(!enabled || !view || receiptAt===null)return
  const start=performance.now(), runId=view.runId,revision=view.revision,sourceSeq=view.sourceSeq
  await nextTick()
  requestAnimationFrame(at=>append({kind:'render',runId,revision,sourceSeq,serverEpoch:view.serverEpoch,
    receivedAt:performance.timeOrigin+receiptAt,renderedAt:performance.timeOrigin+at,
    vueToFrameMs:at-start,receiveToFrameMs:at-receiptAt,
    clockOffsetMs:Date.now()-(performance.timeOrigin+performance.now()),...context()}))
}

export function measureTask(name,runId,action) {
  if(!enabled)return action()
  const start=performance.now()
  try{return action()}
  finally{append({kind:'task',name,runId,at:performance.timeOrigin+start,durationMs:performance.now()-start,...context()})}
}
