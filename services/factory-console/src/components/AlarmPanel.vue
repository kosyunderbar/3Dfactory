<script setup>
import {computed,onUnmounted,ref,watch} from 'vue'
import {ScopedQueries} from '../resources.js'
import {alarmLabels,date} from '../presentation.js'
const props=defineProps({run:String,view:Object})
const operator=ref('operator-01'),filter=ref('active'),pending=ref(null),message=ref(''),queries=new ScopedQueries()
let ticket=0
const alarms=computed(()=>(props.view?.alarms ?? []).filter(a=>filter.value==='all' || (filter.value==='active' ? a.conditionActive : !a.conditionActive)))
async function acknowledge(alarm){
 const id=alarm.alarmId,run=props.run,token=++ticket;pending.value=id;message.value=''
 try{
  const result=await queries.one('ack',run,`/api/v1/alarms/${encodeURIComponent(id)}/acknowledge`,{method:'POST',body:{operatorId:operator.value}})
  if(result && token===ticket)message.value='확인 기록을 저장했습니다. 다음 관제 묶음에서 표시를 갱신합니다.'
 }catch{if(token===ticket)message.value='확인 기록을 저장하지 못했습니다. 연결을 확인하고 다시 시도하세요.'}
 finally{if(token===ticket)pending.value=null}
}
watch(()=>`${props.run}:${props.view?.serverEpoch}`,()=>{ticket++;queries.reset(`${props.run}:${props.view?.serverEpoch}`);pending.value=null;message.value=''},{immediate:true})
onUnmounted(()=>{ticket++;queries.close()})
</script>
<template>
 <section class="panel" aria-labelledby="alarms-title"><div class="panel-head"><div><p class="eyebrow">ALARMS</p><h2 id="alarms-title">상태 알람</h2></div><span class="small">활성 {{view?.metrics.alarmSummary.activeCount ?? '—'}} · 활성 미확인 {{view?.metrics.alarmSummary.unacknowledgedActiveCount ?? '—'}}</span></div>
  <div class="controls"><label>알람 표시<select v-model="filter" aria-label="알람 표시"><option value="active">활성</option><option value="resolved">복구됨</option><option value="all">전체 최근 알람</option></select></label><label>확인자<input v-model.trim="operator" aria-label="알람 확인자" maxlength="64" placeholder="operator-01" /></label></div>
  <p class="small">확인은 읽었다는 기록입니다. 고장 복구와 슬롯 반환은 새 공장 보고로만 확인합니다. 전체 알람은 기록 조회에서 볼 수 있습니다.</p>
  <p v-if="message" class="notice" role="status">{{message}}</p>
  <p v-if="!view" class="empty">알람 관측을 기다립니다.</p><p v-else-if="alarms.length===0" class="empty">현재 표시 조건에 맞는 최근 알람이 없습니다.</p>
  <ul class="alarm-list" data-testid="alarm-list"><li v-for="alarm in alarms" :key="alarm.alarmId" :class="{resolved:!alarm.conditionActive}"><div><div class="event-heading"><strong>{{alarmLabels[alarm.type]}}</strong><span class="state">{{alarm.conditionActive ? '활성' : '복구됨'}} · {{alarm.severity}}</span></div><p>{{alarm.targetId}} · {{alarm.message}}</p><p class="small">발생 {{date(alarm.occurredAt)}}<span v-if="alarm.resolvedAt"> · 복구 {{date(alarm.resolvedAt)}}</span></p><p class="small" v-if="alarm.acknowledgedAt">확인 {{alarm.acknowledgedBy}} · {{date(alarm.acknowledgedAt)}}</p></div><button v-if="!alarm.acknowledgedAt" @click="acknowledge(alarm)" :disabled="!!pending || !/^[a-zA-Z0-9_-]{1,64}$/.test(operator)">{{pending===alarm.alarmId ? '저장 중…' : '알람 확인'}}</button></li></ul>
 </section>
</template>
