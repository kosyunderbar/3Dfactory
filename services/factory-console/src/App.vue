<script setup>
import {computed,defineAsyncComponent,nextTick,onMounted,onUnmounted,ref,shallowRef,watch} from 'vue'
import {ConsoleFeed,displayState,runPattern} from './feed.js'
import {ScopedQueries,apiPath} from './resources.js'
import {filteredBodies,bodyLabels,cellLabels,reasonLabels,date,runLabel} from './presentation.js'
import FactoryMap from './components/FactoryMap.vue'
import {vehicleFlag} from './scene3d/status.js'
import './console-layout.css'
const FactoryScene3D=defineAsyncComponent(()=>import('./components/FactoryScene3D.vue'))
const mapMode=ref(new URLSearchParams(location.search).get('view')==='2d' ? '2d' : '3d')
import EntityDetails from './components/EntityDetails.vue'
const QualityPanel=defineAsyncComponent(()=>import('./components/QualityPanel.vue'))
import AlarmPanel from './components/AlarmPanel.vue'
import RecordPanel from './components/RecordPanel.vue'
import MaintenancePanel from './components/MaintenancePanel.vue'
import {startMeasurement,measureRender} from './measurement.js'
const runs=ref([]),run=ref(''),runInput=ref(''),view=shallowRef(null),receiptAt=ref(null),connection=ref('CLOSED'),error=ref('')
const layout=shallowRef(null),layoutError=ref(''),listError=ref(''),loading=ref(false),now=ref(performance.now())
const showParts=ref(false)
const visibleVehicles=computed(()=>(view.value?.vehicles ?? []).filter(vehicle=>showParts.value || vehicle.kind!=='AMR'))
watch(view,value=>{if(value?.partsSupply?.length || value?.activeTransports?.some(transport=>transport.cargoType==='PARTS') || value?.vehicles?.some(vehicle=>vehicle.kind==='AMR' && (vehicle.state!=='IDLE' || vehicle.partsKitId)))showParts.value=true})
const simulation=ref({enabled:false,running:false}),scenario=ref('demo-maintenance'),starting=ref(false),stopping=ref(false),startError=ref(''),simulationConnected=ref(false)
let simulationTimer
let simulationVersion=0
async function loadSimulation(){const version=++simulationVersion;try{const response=await fetch('/__simulation',{cache:'no-store',signal:AbortSignal.timeout(3000)});if(!response.ok)throw Error();const value=await response.json();if(version!==simulationVersion)return;simulation.value=value;simulationConnected.value=true;if(value.running && value.scenario)scenario.value=value.scenario}catch{if(version===simulationVersion)simulationConnected.value=false}}
async function startSimulation(){
 if(starting.value || simulation.value.running)return
 starting.value=true;startError.value=''
 try{
  const response=await fetch('/__simulation',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({scenario:scenario.value})})
  const result=await response.json()
  if(!response.ok)throw new Error(result.message || '시뮬레이션을 시작하지 못했습니다.')
  simulation.value=result;observe(result.runId);await loadRuns();panel.value='factory'
 }catch(error){startError.value=error.message}
 finally{starting.value=false;await loadSimulation()}
}
async function stopSimulation(){
 if(stopping.value || !simulation.value.running || !simulation.value.runId)return
 stopping.value=true;startError.value=''
 try{
  const response=await fetch('/__simulation',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'stop',runId:simulation.value.runId})})
  const result=await response.json()
  if(!response.ok)throw new Error(result.message || '시뮬레이션을 중단하지 못했습니다.')
  simulation.value=result
 }catch(error){startError.value=error.message}
 finally{stopping.value=false;await loadSimulation()}
}
const selection=ref(null),detailDialog=ref(null),tagQuery=ref(''),bodyStatus=ref(''),panel=ref('factory'),qualityVisited=ref(false)
const queries=new ScopedQueries();let listAbort,timer,listVersion=0,measuredView=null
const feed=new ConsoleFeed({onChange:state=>{const changed=state.view!==measuredView;measuredView=state.view;view.value=state.view;receiptAt.value=state.receiptAt;connection.value=state.connection;error.value=state.error;if(changed)measureRender(state.view,state.receiptAt,nextTick)}})
const visible=computed(()=>displayState(view.value,receiptAt.value,now.value,connection.value))
const selectedRunLabel=computed(()=>{
 const item=runs.value.find(item=>item.runId===run.value)
 if(!item)return run.value ? '직접 연결한 실행 · 시작 시각 미확인' : '실행을 선택하거나 새 시뮬레이션을 시작하세요.'
 return executionLabel(item)
})
const hasObservation=computed(()=>view.value?.sourceSeq !== null && view.value?.sourceSeq !== undefined)
const metrics=computed(()=>[
 {label:'투입 차체',value:hasObservation.value ? view.value.bodies.length : '—',unit:'대'},
 {label:'작업 중인 설비',value:hasObservation.value ? view.value.equipment.filter(c=>c.state==='RUNNING').length : '—',unit:'곳'},
 {label:'검사 통과',value:hasObservation.value ? view.value.bodies.filter(b=>b.inspectionResult==='PASS').length : '—',unit:'대'},
 {label:'검사 보류',value:hasObservation.value ? view.value.bodies.filter(b=>b.inspectionResult==='FAIL').length : '—',unit:'대'}
])
function vehicleSummary(vehicle){return vehicleFlag(vehicle,view.value?.activeTransports ?? [],layout.value,view.value?.equipment ?? []).detail}
function executionLabel(item){
 const finishedAt=item.finishedAt || (item.runId===run.value && view.value?.runState==='FINISHED' ? view.value.snapshotCapturedAt : null)
 const label=runLabel({...item,finishedAt})
 if(!finishedAt && item.runId===simulation.value.runId && simulation.value.running)return label.replace('종료 미확인','실행 중')
 if(!finishedAt && item.runId===simulation.value.runId && simulation.value.state==='STOPPED')return label.replace('종료 미확인','중단')
 return label
}
const bodies=computed(()=>filteredBodies(view.value,tagQuery.value,bodyStatus.value))
const titles={body:'차체 · 스마트태그 상세',cell:'작업 셀 상세',buffer:'Bay · 슬롯 상세',vehicle:'차량 · 운송 상세'}
const connectionLabels={CONNECTING:'연결 중',OPEN:'화면 연결됨',RECONNECTING:'재연결 중',CLOSED:'연결 전'}
function bufferFor(cell){return view.value?.buffers.find(item=>item.cellId===cell.cellId)}
function seconds(value){return value===null ? '—' : `${(value/1000).toFixed(1)}초`}
function observe(id){
 if(!runPattern.test(id))return
 if(id===run.value){feed.reconnect('최신 상태를 다시 연결합니다.');return}
 detailDialog.value?.close();selection.value=null;showParts.value=false;run.value=id;runInput.value=id;layout.value=null;layoutError.value='';feed.select(id)
 const url=new URL(location.href);url.searchParams.set('run',id);history.replaceState(null,'',url)
}
async function selectEntity(item){selection.value=item;await nextTick();if(!detailDialog.value.open)detailDialog.value.showModal()}
async function loadLayout(){
 const id=run.value,epoch=view.value?.serverEpoch,source=view.value?.sourceId
 if(!id || !epoch)return
 layoutError.value=''
 try{const value=await queries.one('layout',id,`/api/v1/factory/layout?runId=${encodeURIComponent(id)}`);if(value){if(value.sourceId!==source || !Array.isArray(value.config?.locations) || !Array.isArray(value.config?.routes))throw new Error();layout.value=value.config}}
 catch{layoutError.value='지도 설정을 읽지 못했습니다. 관제 연결을 확인하고 다시 조회하세요.'}
}
async function loadPartsUsage(){
 const id=run.value,captured=view.value?.snapshotCapturedAt
 if(!id || !captured || !layout.value)return
 const amrs=(layout.value.vehicles ?? []).filter(vehicle=>vehicle.kind==='AMR')
 if(!amrs.length)return
 const to=new Date(captured).toISOString(),from=new Date(new Date(captured).getTime()-86400000).toISOString()
 try{
  const pages=await queries.group('parts',id,amrs.map(vehicle=>({path:apiPath(id,'events',{vehicleId:vehicle.vehicleId,eventType:'TRANSPORT_ASSIGNED',from,to,limit:1})})))
  if(pages?.some(page=>page.items?.length))showParts.value=true
 }catch{if(id===run.value)showParts.value=true}
}
watch(()=>`${run.value}:${view.value?.serverEpoch}`,()=>{queries.reset(`${run.value}:${view.value?.serverEpoch}`);layout.value=null;loadLayout()})
watch(()=>`${run.value}:${view.value?.serverEpoch}:${Boolean(view.value?.snapshotCapturedAt)}:${Boolean(layout.value)}`,loadPartsUsage)
async function loadRuns(){
 const token=++listVersion;listAbort?.abort();listAbort=new AbortController();loading.value=true;listError.value=''
 const abort=listAbort,timeout=setTimeout(()=>abort.abort(),4000)
 try{const response=await fetch('/api/v1/runs?limit=20',{cache:'no-store',signal:abort.signal});if(!response.ok)throw new Error();const page=await response.json();if(token!==listVersion)return;runs.value=page.items;if(!run.value && runs.value.length)observe(runs.value[0].runId)}
 catch{if(token===listVersion)listError.value='실행 목록을 읽지 못했습니다. 관제 연결을 확인하세요.'}
 finally{clearTimeout(timeout);if(token===listVersion)loading.value=false}
}
onMounted(()=>{startMeasurement();const id=new URLSearchParams(location.search).get('run');if(runPattern.test(id || ''))observe(id);loadRuns();loadSimulation();simulationTimer=setInterval(loadSimulation,2000);timer=setInterval(()=>{now.value=performance.now()},250)})
onUnmounted(()=>{feed.close();queries.close();listVersion++;listAbort?.abort();clearInterval(timer);clearInterval(simulationTimer)})
</script>
<template>
 <a class="skip-link" href="#workspace">관제 화면으로 건너뛰기</a>
 <main class="console operations-console">
  <header class="masthead">
   <div class="brand"><span class="brand-icon" aria-hidden="true">F</span><div>공장 관제<small>FACTORY CONSOLE</small></div></div>
   <nav class="workspace-nav" aria-label="관제 화면 선택"><button :aria-pressed="panel==='factory'" @click="panel='factory'">공장</button><button :aria-pressed="panel==='tags'" @click="panel='tags'">차체 조회</button><button :aria-pressed="panel==='quality'" @click="qualityVisited=true;panel='quality'">품질 · 알람</button><button :aria-pressed="panel==='history'" @click="panel='history'">기록</button></nav>
   <div class="connection-badge" :class="{stale:visible.stale}"><i></i><span data-testid="data-status">{{visible.label}}</span></div>
  </header>
  <section class="operations-heading"><div><h1>{{{factory:'공장 현황',tags:'차체 조회',quality:'품질과 알람',history:'실행 기록'}[panel]}}</h1><p>{{selectedRunLabel}}</p></div><dl v-if="panel==='factory'" class="production-summary"><div v-for="metric in metrics" :key="metric.label"><dt>{{metric.label}}</dt><dd>{{metric.value}}<small>{{metric.unit}}</small></dd></div></dl><span v-else class="report-age">{{view?.freshness.state==='ARCHIVED' ? '종료된 실행의 기록' : hasObservation ? `마지막 공장 보고 ${seconds(visible.sourceAge)} 전` : '공장 보고 대기'}}</span></section>
  <section class="command-bar" aria-label="시뮬레이션 조작">
   <label class="run-select">실행<select aria-label="실행 목록" :value="run" @change="observe($event.target.value)"><option value="" disabled>실행 선택</option><option v-if="run && !runs.some(item=>item.runId===run)" :value="run">직접 연결한 실행</option><option v-for="item in runs" :key="item.runId" :value="item.runId">{{executionLabel(item)}}</option></select></label>
   <template v-if="simulation.enabled"><label class="scenario-select">시나리오<select v-model="scenario" aria-label="시뮬레이션 시나리오" :disabled="starting || simulation.running"><option value="demo">1대 · 정상 생산</option><option value="demo-three">3대 · 정상 생산</option><option value="demo-maintenance">5대 · 장애 / 수동 복구</option></select></label><button class="start-simulation" @click="startSimulation" :disabled="starting || simulation.running">{{starting ? '시작 중…' : simulation.running ? '실행 중' : '시뮬레이션 시작'}}</button><button v-if="simulation.running" class="stop-simulation" @click="stopSimulation" :disabled="stopping || simulation.state==='STOPPING' || !simulation.runId">{{stopping || simulation.state==='STOPPING' ? '중단 중…' : '중단'}}</button></template>
   <button class="refresh-runs" @click="loadRuns" :disabled="loading" aria-label="실행 목록 새로고침">{{loading ? '조회 중' : '새로고침'}}</button>
  </section>
  <p v-if="simulation.running && simulation.runId!==run" class="notice" role="status">다른 실행의 기록을 보고 있습니다. <button @click="observe(simulation.runId)">현재 시뮬레이션 보기</button></p>
  <p v-if="startError || listError || error" class="notice" role="status">{{startError || listError || error}}</p>
  <p v-if="simulation.state==='STOPPED'" class="run-message" role="status">시뮬레이션을 중단했습니다. 마지막 관측 기록은 보존됩니다.</p><p v-else-if="simulation.state==='FAILED'" class="notice" role="status">시뮬레이션이 비정상 종료됐습니다. 연결 상태를 확인해 주세요.</p>
  <details class="connection-details"><summary>연결 정보 · 실행 ID</summary><div class="connection-content"><dl class="timing"><div><dt>브라우저 연결</dt><dd data-testid="connection">{{connectionLabels[connection]}}</dd></div><div><dt>공장 보고 시각</dt><dd>{{date(view?.snapshotCapturedAt)}}</dd></div><div><dt>전달 대기</dt><dd>{{view?.delivery.diagnosticState==='AVAILABLE' ? `${view.delivery.pendingCount}건` : '진단 미확인'}}</dd></div></dl><form @submit.prevent="observe(runInput)"><label>실행 ID<input v-model.trim="runInput" placeholder="run-YYYYMMDD-…" aria-label="실행 ID" /></label><button :disabled="!runPattern.test(runInput)">연결</button></form></div></details>
  <div id="workspace" tabindex="-1">
   <MaintenancePanel :simulation="simulation" :run="run" :connected="simulationConnected" @refresh="loadSimulation" />
   <section v-show="panel==='factory'" aria-label="공장 현황">
    <div class="factory-workspace">
     <div class="factory-main">
      <div class="map-view-switch" aria-label="지도 보기 방식"><button :aria-pressed="mapMode==='3d'" @click="mapMode='3d'">3D 공장</button><button :aria-pressed="mapMode==='2d'" @click="mapMode='2d'">2D 지도</button><span>설비와 차량을 선택해 상세 확인</span></div>
      <p v-if="layoutError" class="notice" role="status">{{layoutError}} <button @click="loadLayout">다시 조회</button></p>
      <FactoryMap v-if="mapMode==='2d'" :config="layout" :view="view" :stale="visible.stale" :selection="selection" :show-parts="showParts" @select="selectEntity" />
      <FactoryScene3D v-else :config="layout" :view="view" :live="view?.dataStatus==='LIVE' && !visible.stale" :status-label="visible.label" :show-parts="showParts" :active="panel==='factory'" @select="selectEntity" @fallback="mapMode='2d'" />
      <div class="floor-legend"><span><i class="legend-route"></i>운송 경로</span><span><i class="legend-bay"></i>예약 슬롯</span><span><i class="legend-wait"></i>양보 대기</span><small>{{visible.stale ? '마지막 관측값 표시' : '관측 위치 기준'}}</small></div>
     </div>
     <aside class="plant-sidebar" aria-label="설비와 차량 현황">
      <section v-if="view?.partsSupply?.length" class="parts-summary"><h2>부품 공급 <small>AMR</small></h2><article v-for="stock in view.partsSupply" :key="stock.cellId"><div><strong>{{stock.cellId}}</strong><span>{{stock.available}} / {{stock.capacity}} 키트</span></div><p>{{stock.inbound ? `보급 중 ${stock.inbound}키트` : stock.available ? '공급 준비' : '보유 키트 없음'}} · 사용 {{stock.consumed}}<small>부품 대기 {{(stock.stockoutMs/1000).toFixed(1)}}초</small></p></article><details><summary>재고 기준</summary><p>시작 재고는 공정별 {{view.partsSupply[0].initialStock}}키트입니다. 조립 시작 시 1키트를 사용하고, 남은 생산량에 맞춰 AMR이 보충합니다.</p></details></section>
      <section><h2>설비 <small>{{hasObservation ? view.equipment.length : '—'}}</small></h2><p v-if="!hasObservation" class="sidebar-empty">첫 관측을 기다립니다.</p><article v-for="cell in view?.equipment ?? []" :key="cell.equipmentId" class="equipment-row" :data-testid="`cell-${cell.cellId}`"><button class="equipment-select" @click="selectEntity({kind:'cell',id:cell.cellId})"><span>{{cell.cellId}}</span><span class="state" :class="cell.state.toLowerCase()">{{cell.state==='BLOCKED' && cell.remainingWorkMs===0 && cell.bodyId ? '작업 완료' : cellLabels[cell.state]}}</span></button><p>{{cell.bodyId || '대기 중'}}<small v-if="cell.state==='RUNNING'">{{seconds(cell.remainingWorkMs)}}</small></p><p v-if="cell.blockedReason" class="block-reason">{{reasonLabels[cell.blockedReason] || cell.blockedReason}}</p><button v-if="bufferFor(cell)" class="bay-summary" @click="selectEntity({kind:'buffer',id:bufferFor(cell).bufferId,cellId:cell.cellId})"><span>Bay 여유</span><strong>{{bufferFor(cell).availableSlots}} / {{bufferFor(cell).capacity}}</strong><span aria-hidden="true">↗</span></button></article></section>
      <section class="fleet-summary"><h2>운송 차량 <small>{{hasObservation ? visibleVehicles.length : '—'}}</small></h2><button v-for="vehicle in visibleVehicles" :key="vehicle.vehicleId" @click="selectEntity({kind:'vehicle',id:vehicle.vehicleId})"><strong>{{vehicle.vehicleId}}<span aria-hidden="true">↗</span></strong><span>{{vehicleSummary(vehicle)}}</span><small>{{vehicle.bodyId || vehicle.partsKitId || '빈 차량'}}</small></button></section>
     </aside>
    </div>
    <p v-if="!hasObservation" class="empty">실행을 선택하거나 시뮬레이션을 시작하면 공장 상태가 표시됩니다.</p>
   </section>
   <section v-show="panel==='tags'" aria-label="차체와 스마트태그 조회">
    <div class="section-heading"><h2>차체 목록</h2><span class="small">{{bodies.length}} / {{view?.bodies.length ?? '—'}}대</span></div>
    <div class="controls search-controls"><label>태그 · 차체 검색<input v-model="tagQuery" type="search" aria-label="태그 또는 차체 검색" placeholder="태그, 차체 번호, 모델·사양" /></label><label>상태<select v-model="bodyStatus" aria-label="차체 상태"><option value="">전체 상태</option><option v-for="(label,status) in bodyLabels" :key="status" :value="status">{{label}}</option></select></label><button @click="tagQuery='';bodyStatus=''">초기화</button></div>
    <p v-if="bodies.length===0" class="empty">검색 조건에 맞는 관측 차체가 없습니다.</p>
    <div class="bodies"><button v-for="item in bodies" :key="item.bodyId" class="body-card" @click="selectEntity({kind:'body',id:item.bodyId})" :data-testid="`body-${item.bodyId}`"><span class="tag">{{item.tagId}}</span><strong>{{item.bodyId}}</strong><span>{{bodyLabels[item.status]}} · {{item.locationId}}</span><span class="small">{{item.inspectionResult==='NOT_INSPECTED' ? '검사 전' : item.inspectionResult}} ↗</span></button></div>
   </section>
   <section v-show="panel==='quality'" aria-label="품질과 상태 알람"><QualityPanel v-if="qualityVisited" :run="run" :view="view" /><AlarmPanel :run="run" :view="view" /></section>
   <section v-show="panel==='history'" aria-label="기록 조회"><RecordPanel :run="run" :view="view" /></section>
  </div>
  <dialog ref="detailDialog" class="detail" aria-labelledby="detail-title" @close="selection=null"><div class="detail-head"><div><p class="eyebrow">상세 정보</p><h2 id="detail-title">{{titles[selection?.kind] || '상세'}}</h2></div><button @click="detailDialog.close()" aria-label="상세 닫기">닫기</button></div><EntityDetails v-if="selection" :run="run" :view="view" :selection="selection" :label="visible.label" @select="selectEntity" /></dialog>
  <footer class="console-footer"><span>가상 제조공장 · 시뮬레이션 관제</span><span>{{hasObservation ? `관측 순번 ${view.sourceSeq}` : '관측 대기'}}</span></footer>
 </main>
</template>
