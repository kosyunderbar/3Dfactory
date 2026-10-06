<script setup>
import {computed,defineAsyncComponent,nextTick,onMounted,onUnmounted,ref,watch} from 'vue'
import {ConsoleFeed,displayState,runPattern} from './feed.js'
import {ScopedQueries,apiPath} from './resources.js'
import {filteredBodies,bodyLabels,cellLabels,reasonLabels,vehicleLabels,date,runLabel} from './presentation.js'
import FactoryMap from './components/FactoryMap.vue'
import EntityDetails from './components/EntityDetails.vue'
const QualityPanel=defineAsyncComponent(()=>import('./components/QualityPanel.vue'))
import AlarmPanel from './components/AlarmPanel.vue'
import RecordPanel from './components/RecordPanel.vue'
import {startMeasurement,measureRender} from './measurement.js'
const runs=ref([]),run=ref(''),runInput=ref(''),view=ref(null),receiptAt=ref(null),connection=ref('CLOSED'),error=ref('')
const layout=ref(null),layoutError=ref(''),listError=ref(''),loading=ref(false),now=ref(performance.now())
const showParts=ref(false)
const visibleVehicles=computed(()=>(view.value?.vehicles ?? []).filter(vehicle=>showParts.value || vehicle.kind!=='AMR'))
watch(view,value=>{if(value?.activeTransports?.some(transport=>transport.cargoType==='PARTS') || value?.vehicles?.some(vehicle=>vehicle.kind==='AMR' && (vehicle.state!=='IDLE' || vehicle.partsKitId)))showParts.value=true})
const simulation=ref({enabled:false,running:false}),scenario=ref('demo-p0'),starting=ref(false),startError=ref('')
let simulationTimer
async function loadSimulation(){try{const response=await fetch('/__simulation',{cache:'no-store'});if(response.ok)simulation.value=await response.json()}catch{}}
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
const selection=ref(null),detailDialog=ref(null),tagQuery=ref(''),bodyStatus=ref(''),panel=ref('factory'),qualityVisited=ref(false)
const queries=new ScopedQueries();let listAbort,timer,listVersion=0,measuredView=null
const feed=new ConsoleFeed({onChange:state=>{const changed=state.view!==measuredView;measuredView=state.view;view.value=state.view;receiptAt.value=state.receiptAt;connection.value=state.connection;error.value=state.error;if(changed)measureRender(state.view,state.receiptAt,nextTick)}})
const visible=computed(()=>displayState(view.value,receiptAt.value,now.value,connection.value))
const selectedRunLabel=computed(()=>{
 const item=runs.value.find(item=>item.runId===run.value)
 if(!item)return run.value ? '직접 연결한 실행 · 시작 시각 미확인' : '실행을 선택하거나 새 시뮬레이션을 시작하세요.'
 return runLabel({...item,finishedAt:item.finishedAt || (view.value?.runState==='FINISHED' ? view.value.snapshotCapturedAt : null)})
})
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
 <main class="console">
  <header class="masthead"><div class="brand"><span class="brand-icon" aria-hidden="true">F</span>FACTORY CONSOLE</div><span class="phase">독립 셀 · 가상 제조공장</span></header>
  <section class="intro"><p class="eyebrow">FACTORY OBSERVATION</p><h1>차체의 여정과<br />공장의 상태를 한곳에서.</h1><p class="lede">독립 작업 셀과 AGV·AMR의 실제 보고를 관측합니다. 스마트태그로 차체를 찾고, 목적지 Bay의 여유 슬롯과 검사 결과를 함께 확인하세요.</p></section>
  <section v-if="simulation.enabled" class="simulation-controls" aria-label="새 시뮬레이션"><div><p class="eyebrow">NEW SIMULATION</p><strong>새로운 공장 실행</strong><p class="small">새 실행을 시작하면 관측 화면이 자동으로 연결됩니다.</p></div><label>시나리오<select v-model="scenario" aria-label="시뮬레이션 시나리오" :disabled="starting || simulation.running"><option value="demo-p0">5대 · 버퍼·장애·복구·부품 운송</option><option value="demo">1대 · 정상 생산</option><option value="demo-three">3대 · 정상 생산</option></select></label><button class="start-simulation" @click="startSimulation" :disabled="starting || simulation.running">{{starting ? '시작하는 중…' : simulation.running ? '시뮬레이션 실행 중' : '새 시뮬레이션 시작'}}</button><p v-if="simulation.running" class="small simulation-message" role="status">진행 중인 실행이 완료되면 다시 시작할 수 있습니다.</p><p v-else-if="simulation.state==='FAILED'" class="small simulation-message" role="status">이전 시뮬레이션이 중단됐습니다. 서버 연결을 확인한 뒤 다시 시작하세요.</p><p v-if="startError" class="notice simulation-message" role="alert">{{startError}}</p></section>
  <section class="run-picker" aria-label="관측 실행 선택">
   <div class="run-picker-main"><label>시뮬레이션 기록<select aria-label="실행 목록" :value="run" @change="observe($event.target.value)"><option value="" disabled>실행을 선택하세요</option><option v-if="run && !runs.some(item=>item.runId===run)" :value="run">직접 연결한 실행 · 시작 시각 미확인</option><option v-for="item in runs" :key="item.runId" :value="item.runId">{{runLabel(item)}}</option></select></label><button @click="loadRuns" :disabled="loading">{{loading ? '읽는 중…' : '목록 새로고침'}}</button></div>
   <details class="run-advanced"><summary>실행 ID로 직접 연결</summary><p class="small">실행 ID는 시뮬레이션 기록을 구분하는 내부 식별자입니다. 다른 실행을 직접 찾거나 로그를 확인할 때 사용합니다.</p><form @submit.prevent="observe(runInput)"><label>실행 ID<input v-model.trim="runInput" placeholder="run-YYYYMMDD-…" aria-label="실행 ID" /></label><button :disabled="!runPattern.test(runInput)">관측 연결</button></form></details>
  </section>
  <p v-if="listError" class="notice" role="status">{{listError}}</p>
  <section class="observation" :class="{muted:visible.stale}" aria-labelledby="status-title"><div><p class="eyebrow" id="status-title">관측 상태</p><h2 data-testid="data-status">{{visible.label}}</h2><p class="small">{{selectedRunLabel}}</p></div><dl class="timing"><div><dt>브라우저 수신</dt><dd data-testid="connection">{{connectionLabels[connection]}}</dd></div><div><dt>공장 보고 시각</dt><dd>{{date(view?.snapshotCapturedAt)}}</dd></div><div><dt>마지막 보고 후 경과 시간</dt><dd>{{view?.freshness.state==='ARCHIVED' ? '종료된 실행' : seconds(visible.sourceAge)}}</dd></div><div><dt>전달 대기</dt><dd>{{view?.delivery.diagnosticState==='AVAILABLE' ? `${view.delivery.pendingCount}건` : '진단 미확인'}}</dd></div></dl></section>
  <p v-if="error" class="notice" role="status">{{error}}</p>
  <nav class="workspace-nav" aria-label="관제 화면 선택"><button :aria-pressed="panel==='factory'" @click="panel='factory'">공장 · 스마트태그</button><button :aria-pressed="panel==='quality'" @click="qualityVisited=true;panel='quality'">품질 · 알람</button><button :aria-pressed="panel==='history'" @click="panel='history'">기록 조회</button></nav>
  <div id="workspace" tabindex="-1">
   <section v-show="panel==='factory'" aria-label="공장과 스마트태그 관측">
    <div class="section-heading"><div><p class="eyebrow">FACTORY MAP</p><h2>독립 셀과 운송 지도</h2></div><span class="small">{{visible.stale ? '마지막 확인값' : '같은 시점의 관측값'}}</span></div>
    <p v-if="layoutError" class="notice" role="status">{{layoutError}} <button @click="loadLayout">지도 다시 조회</button></p>
    <FactoryMap :config="layout" :view="view" :stale="visible.stale" :selection="selection" :show-parts="showParts" @select="selectEntity" />
    <p v-if="!view || view.sourceSeq===null" class="empty">첫 공장 관측을 기다립니다. 관측 부재를 0대·0칸이나 정상 상태로 추정하지 않습니다.</p>
    <template v-else>
     <div class="section-heading"><div><p class="eyebrow">WORK CELLS & BAYS</p><h2>셀과 목적지 슬롯</h2></div><span class="small">W + R ≥ C 즉시 신규 배출 차단</span></div>
     <div class="cells"><article v-for="cell in view.equipment" :key="cell.equipmentId" class="cell" :data-testid="`cell-${cell.cellId}`"><div class="cell-head"><button class="text-button" @click="selectEntity({kind:'cell',id:cell.cellId})">{{cell.cellId}}</button><span class="state" :class="cell.state.toLowerCase()">{{cellLabels[cell.state]}}</span></div><p class="cell-body">{{cell.bodyId || '차체 없음'}}</p><p class="small">{{reasonLabels[cell.blockedReason] || (cell.state==='RUNNING' ? '공정을 진행 중입니다.' : '다음 작업을 기다립니다.')}}</p><template v-if="bufferFor(cell)"><dl class="slots"><div><dt>대기 W</dt><dd>{{bufferFor(cell).waitingCount}}</dd></div><div><dt>예약 R</dt><dd>{{bufferFor(cell).reservedInboundCount}}</dd></div><div><dt>여유 A</dt><dd>{{bufferFor(cell).availableSlots}}</dd></div><div><dt>전체 C</dt><dd>{{bufferFor(cell).capacity}}</dd></div></dl><button class="bay-button" @click="selectEntity({kind:'buffer',id:bufferFor(cell).bufferId,cellId:cell.cellId})">{{bufferFor(cell).availableSlots===0 ? '만석 · 신규 예약 차단' : 'Bay 슬롯 상세'}}</button></template></article></div>
     <div class="vehicle-strip"><button v-for="vehicle in visibleVehicles" :key="vehicle.vehicleId" @click="selectEntity({kind:'vehicle',id:vehicle.vehicleId})"><strong>{{vehicle.vehicleId}}</strong><span>{{vehicleLabels[vehicle.state] || vehicle.state}}</span><span class="small">실제 적재 {{vehicle.bodyId || vehicle.partsKitId || '없음'}}</span></button></div>
     <div class="section-heading"><div><p class="eyebrow">SMART TAGS</p><h2>차체와 가상 스마트태그</h2></div><span class="small">{{bodies.length}} / {{view.bodies.length}}대</span></div>
     <div class="controls search-controls"><label>태그 · 차체 검색<input v-model="tagQuery" type="search" aria-label="태그 또는 차체 검색" placeholder="tag-00001, body-00001, 모델·사양" /></label><label>차체 상태<select v-model="bodyStatus" aria-label="차체 상태"><option value="">전체 상태</option><option v-for="(label,status) in bodyLabels" :key="status" :value="status">{{label}}</option></select></label><button @click="tagQuery='';bodyStatus=''">검색 초기화</button></div>
     <p v-if="bodies.length===0" class="empty">검색 조건에 맞는 관측 차체가 없습니다.</p>
     <div class="bodies"><button v-for="item in bodies" :key="item.bodyId" class="body-card" @click="selectEntity({kind:'body',id:item.bodyId})" :data-testid="`body-${item.bodyId}`"><span class="tag">{{item.tagId}}</span><strong>{{item.bodyId}}</strong><span>{{bodyLabels[item.status]}} · {{item.locationId}}</span><span class="small">{{item.inspectionResult==='NOT_INSPECTED' ? '검사 전' : item.inspectionResult}} ↗</span></button></div>
     <p class="small provenance">수신 순번 {{view.sourceSeq}} · 관제 기준 {{date(view.viewAsOfAt)}} · 예약·배출·물리 상태는 시뮬레이터가 결정합니다.</p>
    </template>
   </section>
   <section v-show="panel==='quality'" aria-label="품질과 상태 알람"><QualityPanel v-if="qualityVisited" :run="run" :view="view" /><AlarmPanel :run="run" :view="view" /></section>
   <section v-show="panel==='history'" aria-label="기록 조회"><RecordPanel :run="run" :view="view" /></section>
  </div>
  <dialog ref="detailDialog" class="detail" aria-labelledby="detail-title" @close="selection=null"><div class="detail-head"><div><p class="eyebrow">FACTORY DETAIL</p><h2 id="detail-title">{{titles[selection?.kind] || '상세'}}</h2></div><button @click="detailDialog.close()" aria-label="상세 닫기">닫기</button></div><EntityDetails v-if="selection" :run="run" :view="view" :selection="selection" :label="visible.label" @select="selectEntity" /></dialog>
  <footer>가상 스마트태그는 차체 정보를 연결하는 식별자입니다. 실제 무선 장치나 위치 측정 시스템을 재현하지 않습니다.</footer>
 </main>
</template>
