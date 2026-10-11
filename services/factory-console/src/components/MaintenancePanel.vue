<script setup>
import {computed,ref,watch} from 'vue'
const props=defineProps({simulation:Object,run:String,connected:Boolean})
const emit=defineEmits(['refresh'])
const opened=ref(false),busy=ref(false),error=ref('')
const state=computed(()=>props.simulation?.runId===props.run ? props.simulation.maintenance : null)
const fault=computed(()=>state.value?.faults?.[0])
const stageLabels={DETECTED:'점검 대기',INSPECTING:'현장 조치 중',VERIFYING:'재가동 확인 중',RESOLVED:'복구 완료'}
const actorLabels={SCENARIO:'장애 발생',USER:'사용자 조작',SIMULATOR:'동작 확인'}
const enabled=computed(()=>props.connected && props.simulation.running && props.simulation.state==='RUNNING')
watch(()=>props.run,()=>{opened.value=false;error.value=''})
function seconds(ms){return `${(ms/1000).toFixed(1)}초`}
async function command(action){
 if(busy.value || !enabled.value)return
 const runId=props.run
 busy.value=true;error.value=''
 try{
  const response=await fetch('/__simulation',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action,runId,faultId:fault.value.faultId})})
  const result=await response.json()
  if(!response.ok)throw Error(result.message || '조작을 처리하지 못했습니다.')
 }catch(reason){if(runId===props.run)error.value=reason.message}
 finally{busy.value=false;emit('refresh')}
}
</script>
<template>
 <section v-if="state" class="maintenance-panel" :class="{fault: fault && fault.stage!=='RESOLVED'}" aria-label="수동 장애 복구">
  <div class="maintenance-summary">
   <div><span class="maintenance-dot" :class="{resolved:fault?.stage==='RESOLVED'}"></span><strong>{{fault ? `${fault.cellId} · ${stageLabels[fault.stage]}` : '수동 복구 시나리오'}}</strong><span class="maintenance-description">{{fault ? fault.cause : '조립 중 설비 장애가 한 차례 발생합니다. 발견 후 직접 점검하고 복구하세요.'}}</span></div>
   <button v-if="fault" @click="opened=!opened" :aria-expanded="opened">{{opened ? '접기' : fault.stage==='RESOLVED' ? '조치 이력' : '장애 확인'}}</button>
  </div>
  <div v-if="fault && opened" class="maintenance-detail">
   <div class="maintenance-context"><p class="maintenance-caption">시뮬레이션 장애 · {{fault.code}}</p><h3>{{fault.cause}}</h3><p>{{fault.explanation}}</p><dl><div><dt>영향</dt><dd>{{fault.bodyId}} 조립 {{seconds(fault.elapsedWorkMs)}} / {{seconds(fault.requiredWorkMs)}}에서 정지</dd></div><div><dt>필요 조치</dt><dd>{{fault.action}}</dd></div><div v-if="fault.resolvedMs!==null"><dt>정지 시간</dt><dd>{{seconds(fault.resolvedMs-fault.occurredMs)}} · 시뮬레이션 시간 기준</dd></div></dl>
    <p class="maintenance-help" v-if="fault.stage==='DETECTED'">자동 복구되지 않습니다. 현장 점검을 시작해 원인을 확인하세요.</p>
    <p class="maintenance-help" v-else-if="fault.stage==='INSPECTING'">엔지니어가 위 조치를 마쳤다고 가정한 뒤 완료 버튼을 누르세요. 그전까지 설비는 정지 상태를 유지합니다.</p>
    <p class="maintenance-help" v-else-if="fault.stage==='VERIFYING'">재가동 전 동작 확인 중입니다. 확인이 끝나면 남은 조립 작업을 이어갑니다.</p>
    <p class="maintenance-help" v-else>사용자 조치 후 동작 확인을 마쳤습니다. 보존된 작업 진행량에서 생산을 재개했습니다.</p>
    <button v-if="fault.stage==='DETECTED'" :disabled="busy || !enabled" @click="command('inspect')">{{busy ? '처리 중…' : '현장 점검 시작'}}</button>
    <button v-else-if="fault.stage==='INSPECTING'" :disabled="busy || !enabled" @click="command('repair')">{{busy ? '처리 중…' : '조치 완료 · 재가동'}}</button>
    <p v-if="!simulation.running && fault.stage!=='RESOLVED'" class="maintenance-help">종료된 실행의 기록입니다. 복구 조작은 실행 중에만 가능합니다.</p>
    <p v-if="!connected" class="maintenance-help">제어 연결을 확인하고 있습니다. 연결이 복구되면 조작할 수 있습니다.</p>
    <p v-if="error" role="alert">{{error}}</p>
   </div>
   <ol class="maintenance-history" aria-label="장애와 조치 이력"><li v-for="(entry,index) in fault.history" :key="index"><div><strong>{{stageLabels[entry.stage]}}</strong><span>{{seconds(entry.simElapsedMs)}} · {{actorLabels[entry.actor]}}</span></div><p>{{entry.message}}</p></li></ol>
  </div>
 </section>
</template>
<style scoped>
.maintenance-panel{margin:14px 0;border:1px solid #dce3e9;border-radius:8px;background:#f7f9fb;color:#334155;font-size:13px}.maintenance-panel.fault{border-color:#e5c8a1;background:#fffbf5}.maintenance-summary{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:12px 16px}.maintenance-summary>div{display:flex;align-items:center;gap:10px;flex-wrap:wrap}.maintenance-summary button,.maintenance-detail button{font-size:12px;padding:7px 12px;white-space:nowrap}.maintenance-dot{width:7px;height:7px;border-radius:50%;background:#718096}.fault .maintenance-dot{background:#c17a29}.maintenance-dot.resolved{background:#38816e}.maintenance-description{color:#64748b}.maintenance-detail{display:grid;grid-template-columns:1fr 1fr;gap:30px;padding:4px 18px 20px;border-top:1px solid #e5ddd1}.maintenance-caption{font-size:10px;letter-spacing:.4px;color:#7c705f;margin:16px 0 6px}.maintenance-context h3{font-size:16px;margin:0}.maintenance-context p{line-height:1.65}.maintenance-context dl>div{display:flex;gap:14px;margin:8px 0}.maintenance-context dt{min-width:56px;color:#64748b}.maintenance-context dd{margin:0}.maintenance-help{color:#64748b;font-size:12px}.maintenance-history{list-style:none;margin:18px 0 0;padding:0 0 0 16px;border-left:1px solid #d5cec3}.maintenance-history li+li{margin-top:16px}.maintenance-history li>div{display:flex;justify-content:space-between;gap:10px}.maintenance-history span{font-size:11px;color:#64748b}.maintenance-history p{margin:4px 0;font-size:12px;color:#64748b}@media(max-width:760px){.maintenance-detail{grid-template-columns:1fr;gap:8px}.maintenance-summary{align-items:flex-start}.maintenance-description{width:100%}}
</style>
