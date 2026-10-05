<script setup>
import {computed,onUnmounted,ref,watch} from 'vue'
import {ScopedQueries,apiPath} from '../resources.js'
import {periodWindow,date,eventFilter,alarmLabels} from '../presentation.js'
const props=defineProps({run:String,view:Object,selection:Object,compact:Boolean})
const queries=new ScopedQueries(),period=ref(15),collection=ref('events'),eventType=ref(''),alarmState=ref(''),severity=ref('')
const items=ref([]),cursor=ref(null),busy=ref(false),error=ref(''),asOf=ref(null),window=ref(null)
let ticket=0,filters=null
const fixedFilter=computed(()=>eventFilter(props.selection))
async function load(more=false){
 const run=props.run,epoch=props.view?.serverEpoch
 if(!run || !epoch || !props.view?.viewAsOfAt)return
 const token=++ticket;busy.value=true;error.value=''
 if(!more){items.value=[];cursor.value=null;asOf.value=null;window.value=periodWindow(props.view.viewAsOfAt,Number(period.value));filters={...window.value,limit:20,...(collection.value==='events' ? {...fixedFilter.value,eventType:eventType.value} : {conditionActive:alarmState.value,severity:severity.value})}}
 const requestedCollection=collection.value
 try{
  const page=await queries.one('page',run,apiPath(run,requestedCollection,{...filters,...(more ? {cursor:cursor.value} : {})}))
  if(page && token===ticket){if(!Array.isArray(page.items))throw new Error();items.value=more ? [...items.value,...page.items] : page.items;cursor.value=page.nextCursor;asOf.value=page.viewAsOfAt}
 }catch(e){if(token===ticket){error.value=['CURSOR_EXPIRED','CURSOR_MISMATCH'].includes(e.code) ? '조회 기준이 바뀌었습니다. 기록 새로고침으로 새 조회를 시작하세요.' : '기록 조회에 실패했습니다. 연결을 확인하고 다시 조회하세요.';if(['CURSOR_EXPIRED','CURSOR_MISMATCH'].includes(e.code))cursor.value=null}}
 finally{if(token===ticket)busy.value=false}
}
watch(()=>JSON.stringify([props.run,props.view?.serverEpoch,props.selection?.kind,props.selection?.id,period.value,collection.value,eventType.value,alarmState.value,severity.value]),()=>{queries.reset(`${props.run}:${props.view?.serverEpoch}:${JSON.stringify(fixedFilter.value)}`);ticket++;busy.value=false;load()},{immediate:true})
onUnmounted(()=>{ticket++;queries.close()})
</script>
<template>
 <section class="panel" :class="{compact}" :aria-label="selection ? '선택한 대상의 관련 사건 이력' : '공장 기록 조회'">
  <div class="panel-head"><div><p class="eyebrow">HISTORY</p><h2>{{selection ? '관련 사건 이력' : '사건과 알람 기록'}}</h2></div><button @click="load(false)" :disabled="busy || !view">기록 새로고침</button></div>
  <div class="controls history-controls"><label v-if="!selection">기록 종류<select v-model="collection"><option value="events">사건</option><option value="alarms">알람</option></select></label><label>기간<select v-model="period"><option :value="5">최근 5분</option><option :value="15">최근 15분</option><option :value="60">최근 1시간</option></select></label><label v-if="collection==='events'">사건 종류<select v-model="eventType"><option value="">전체 사건</option><option value="OPERATION_COMPLETED">공정 완료</option><option value="INSPECTION_COMPLETED">최종 검사</option><option value="TRANSPORT_ASSIGNED">배차</option><option value="TRANSPORT_STARTED">적재 운반 시작</option><option value="TRANSPORT_COMPLETED">인계 완료</option><option value="SLOT_RESERVED">슬롯 예약</option><option value="SLOT_RELEASED">슬롯 반환</option><option value="EQUIPMENT_STATE_CHANGED">설비 상태</option></select></label><template v-else><label>알람 상태<select v-model="alarmState"><option value="">전체</option><option value="true">활성</option><option value="false">복구됨</option></select></label><label>심각도<select v-model="severity"><option value="">전체</option><option value="CRITICAL">CRITICAL</option><option value="WARNING">WARNING</option></select></label></template></div>
  <p class="small" v-if="window">{{date(window.from)}} ~ {{date(window.to)}} · 새 보고와 별도로 조회 시점을 유지합니다.</p>
  <p v-if="selection?.kind==='buffer'" class="small">이 Bay가 연결된 셀의 사건입니다. 슬롯 번호와 운송 번호는 사건 내용에서 확인합니다.</p>
  <p v-if="error" class="notice" role="status">{{error}}</p><p v-if="busy" class="small" role="status">기록을 읽고 있습니다.</p>
  <p v-if="!busy && !error && items.length===0" class="empty">이 기간과 조건에 맞는 기록이 없습니다.</p>
  <ol class="event-list" data-testid="event-history"><li v-for="item in items" :key="item.eventId || item.alarmId"><div class="event-heading"><strong>{{item.eventType || alarmLabels[item.type] || item.type}}</strong><time>{{date(item.occurredAt)}}</time></div><p class="small">{{item.bodyId || item.targetId || ''}} {{item.cellId || ''}} {{item.vehicleId || ''}} <span v-if="item.sourceSeq">· 순번 {{item.sourceSeq}}</span></p><template v-if="item.alarmId"><p>{{item.message}}</p><p class="small">{{item.conditionActive ? '활성' : '복구됨'}} · {{item.acknowledgedAt ? `확인: ${item.acknowledgedBy}` : '미확인'}}</p></template><details v-else><summary>사건 내용</summary><pre>{{JSON.stringify(item.payload,null,2)}}</pre></details></li></ol>
  <div class="pager"><span class="small">{{items.length}}건 · 조회 기준 {{date(asOf)}}</span><button v-if="cursor" @click="load(true)" :disabled="busy || items.length>=100">{{items.length>=100 ? '100건 표시 · 조건을 좁혀 다시 조회' : '기록 더 보기'}}</button></div>
 </section>
</template>
