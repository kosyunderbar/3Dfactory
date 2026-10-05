const MAX_BYTES = 524288
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/
export const runPattern = /^run-\d{8}-[a-z0-9]{3,32}$/
const states = new Set(['WAITING','RESTORING','UNKNOWN','BLOCKED','PAUSED','LIVE','STALE','DISCONNECTED','CATCHING_UP','FINISHED'])
const instant = value => typeof value === 'string' && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/.test(value) && Number.isFinite(Date.parse(value))
export function validBundle(view, run) {
  return view && view.schemaVersion === 1 && view.runId === run && /^simulator-\d{2,4}$/.test(view.sourceId)
    && UUID.test(view.serverEpoch) && Number.isSafeInteger(view.revision) && view.revision > 0
    && (view.sourceSeq === null || Number.isSafeInteger(view.sourceSeq) && view.sourceSeq > 0)
    && states.has(view.dataStatus) && instant(view.viewAsOfAt) && instant(view.publishedAt)
    && (view.snapshotCapturedAt === null || instant(view.snapshotCapturedAt))
    && view.freshness && (view.freshness.sourceAgeMs === null || Number.isFinite(view.freshness.sourceAgeMs) && view.freshness.sourceAgeMs >= 0)
    && view.delivery && ['AVAILABLE','UNAVAILABLE'].includes(view.delivery.diagnosticState)
    && ['equipment','buffers','bodies','vehicles','activeTransports','alarms','recentEvents'].every(key => Array.isArray(view[key]))
    && view.metrics && typeof view.metrics === 'object'
}

// Display-only freshness: never mutate the server's DTO, physical coordinates or counters.
export function displayState(view, receiptAt, now, connection) {
  if (!view) return { label: '관측 대기', stale: true, receiveAge: null, sourceAge: null }
  const age = Math.max(0, now - receiptAt)
  const sourceAge = view.freshness.sourceAgeMs === null ? null : view.freshness.sourceAgeMs + age
  if (age >= 10000) return { label: '화면 연결 확인 필요 · 마지막 확인값', stale: true, receiveAge: age, sourceAge }
  if (connection !== 'OPEN' || age >= 3000) return { label: '화면 수신 지연 · 마지막 확인값', stale: true, receiveAge: age, sourceAge }
  if (view.freshness.state !== 'ARCHIVED' && sourceAge !== null && sourceAge >= 3000 && view.dataStatus === 'LIVE')
    return { label: '보고 지연 · 마지막 확인값', stale: true, receiveAge: age, sourceAge }
  const labels = { LIVE:'실시간 관측', FINISHED:'종료 확인 · 보관값', WAITING:'첫 관측 대기', RESTORING:'서버 복원 중', UNKNOWN:'진단 확인 필요', BLOCKED:'업무 반영 중단', PAUSED:'공장 일시정지', STALE:'보고 지연 · 마지막 확인값', DISCONNECTED:'소스 연결 확인 필요 · 마지막 확인값', CATCHING_UP:'업무 반영 대기' }
  return { label: labels[view.dataStatus], stale: view.dataStatus !== 'LIVE', receiveAge: age, sourceAge }
}

export class ConsoleFeed {
  constructor({ onChange, fetcher = (...args) => fetch(...args), eventSource = url => new EventSource(url), now = () => performance.now(), timers = globalThis }) {
    this.onChange=onChange; this.fetcher=fetcher; this.eventSource=eventSource; this.now=now; this.timers=timers
    this.run=null; this.view=null; this.receiptAt=null; this.connection='CLOSED'; this.error=''; this.generation=0
    this.source=null; this.retry=null; this.abort=null; this.firstEpoch=null; this.openedAt=0; this.watch=null
  }
  emit() { this.onChange({ view:this.view, receiptAt:this.receiptAt, connection:this.connection, error:this.error }) }
  select(run) {
    this.closeTransport(); this.generation++; this.run=run; this.view=null; this.receiptAt=null; this.error=''
    if (!runPattern.test(run || '')) { this.connection='CLOSED'; this.emit(); return }
    this.watch=this.timers.setInterval(() => this.checkSilence(),250); this.connect()
  }
  closeTransport() {
    this.source?.close(); this.source=null; this.abort?.abort(); this.abort=null
    if (this.retry !== null) this.timers.clearTimeout(this.retry)
    if (this.watch !== null) this.timers.clearInterval(this.watch)
    this.retry=null; this.watch=null
  }
  connect() {
    this.generation++; this.abort?.abort(); this.firstEpoch=null; this.connection='CONNECTING'; this.openedAt=this.now(); this.emit()
    const source=this.eventSource(`/api/v1/runs/${encodeURIComponent(this.run)}/stream`); this.source=source
    source.onopen=() => {
      if (this.source!==source) return
      this.generation++; this.abort?.abort(); this.firstEpoch=null; this.openedAt=this.now(); this.connection='OPEN'; this.error=''; this.emit()
      this.loadSnapshot(this.generation,source)
    }
    source.addEventListener('factory-snapshot',event => {
      if (this.source!==source) return
      try {
        if (new TextEncoder().encode(event.data).length>MAX_BYTES) throw new Error('size')
        const view=JSON.parse(event.data)
        if (!validBundle(view,this.run) || event.lastEventId!==`${view.serverEpoch}:${view.revision}`) throw new Error('bundle')
        this.accept(view,true)
      } catch { this.reconnect('상태 묶음의 형식이나 순서를 확인해야 합니다.') }
    })
    source.onerror=() => {
      if (this.source!==source) return
      this.connection='RECONNECTING'; this.emit()
      if (source.readyState===2) this.reconnect('화면 연결을 다시 확인합니다.')
    }
  }
  async loadSnapshot(generation,source) {
    const abort=new AbortController(); this.abort=abort
    const timer=this.timers.setTimeout(() => abort.abort(),4000)
    try {
      const response=await this.fetcher(`/api/v1/runs/${encodeURIComponent(this.run)}/snapshot`,{signal:abort.signal,cache:'no-store'})
      if (!response.ok) return
      const text=await response.text()
      if (new TextEncoder().encode(text).length>MAX_BYTES) return
      const view=JSON.parse(text)
      if (generation!==this.generation || this.source!==source || !validBundle(view,this.run)) return
      // Only the first valid SSE bundle establishes this connection's epoch.
      if (this.firstEpoch===null) return
      this.accept(view,false)
    } catch { /* SSE remains authoritative; a failed REST read never clears the last valid bundle. */ }
    finally { this.timers.clearTimeout(timer) }
  }
  accept(view,sse) {
    if (sse && this.firstEpoch===null) this.firstEpoch=view.serverEpoch
    if (view.serverEpoch!==this.firstEpoch) { if (sse) this.reconnect('관제 서버가 바뀌어 최신 상태를 다시 확인합니다.'); return }
    if (this.view && view.serverEpoch===this.view.serverEpoch) {
      if (view.revision<=this.view.revision) return
      if (this.view.sourceSeq!==null && (view.sourceSeq===null || view.sourceSeq<this.view.sourceSeq)) {
        this.reconnect('보고 순서가 바뀌어 상태를 다시 확인합니다.'); return
      }
    }
    this.view=view; this.receiptAt=this.now(); this.error=''; this.emit()
  }
  reconnect(message='') {
    this.generation++; this.source?.close(); this.source=null; this.abort?.abort(); this.firstEpoch=null; this.connection='RECONNECTING'; this.error=message; this.emit()
    if (this.retry===null) this.retry=this.timers.setTimeout(() => { this.retry=null; if (this.run) this.connect() },2000)
  }
  checkSilence() {
    if (this.retry!==null || !this.source) return
    if (this.now()-Math.max(this.openedAt,this.receiptAt ?? 0)>=10000) this.reconnect('유효한 상태가 도착하지 않아 다시 연결합니다.')
  }
  close() { this.run=null; this.generation++; this.closeTransport(); this.connection='CLOSED'; this.emit() }
}
