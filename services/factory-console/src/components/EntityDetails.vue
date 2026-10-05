<script setup>
import {computed} from 'vue'
import {bodyLabels,cellLabels,vehicleLabels,reasonLabels,slotLabels,date} from '../presentation.js'
import RecordPanel from './RecordPanel.vue'
const props=defineProps({run:String,view:Object,selection:Object,label:String})
const emit=defineEmits(['select'])
const item=computed(()=>{
 const s=props.selection,v=props.view;if(!s || !v)return null
 const [collection,key]={body:['bodies','bodyId'],cell:['equipment','cellId'],buffer:['buffers','bufferId'],vehicle:['vehicles','vehicleId']}[s.kind]
 return v[collection].find(item=>item[key]===s.id) ?? null
})
const transport=computed(()=>props.view?.activeTransports.find(t=>t.transportId===item.value?.transportId))
</script>
<template>
 <p class="detail-status">{{label}}</p>
 <p v-if="!item">현재 묶음에서 선택한 대상의 관측값을 찾지 못했습니다.</p>
 <template v-else>
  <dl v-if="selection.kind==='body'" class="body-detail" data-testid="tag-detail"><div><dt>차체 / 태그</dt><dd>{{item.bodyId}} / {{item.tagId}}</dd></div><div><dt>모델 / 사양</dt><dd>{{item.modelCode}} / {{item.specCode}}</dd></div><div><dt>현재 위치</dt><dd>{{item.locationId}} · {{item.locationType}} {{item.locationSlotId || ''}}</dd></div><div><dt>현재 상태</dt><dd>{{bodyLabels[item.status]}}</dd></div><div><dt>완료 공정</dt><dd>{{item.completedCellIds.join(' → ') || '없음'}}</dd></div><div><dt>다음 공정</dt><dd>{{item.nextCellId || '공정 완료'}}</dd></div><div><dt>운송 / 차량</dt><dd>{{item.transportId || '—'}} / {{transport?.vehicleId || '—'}}</dd></div><div><dt>슬롯 예약</dt><dd>{{item.reservationId || '—'}}</dd></div><div><dt>최종 검사</dt><dd>{{item.inspectionResult==='NOT_INSPECTED' ? '검사 전' : item.inspectionResult}} · {{date(item.inspectedAt)}}</dd></div><div><dt>관측 시각</dt><dd>{{date(item.lastObservedAt)}}</dd></div></dl>
  <dl v-else-if="selection.kind==='cell'" class="body-detail"><div><dt>셀 / 설비</dt><dd>{{item.cellId}} / {{item.equipmentId}}</dd></div><div><dt>상태</dt><dd>{{cellLabels[item.state]}}</dd></div><div><dt>차체</dt><dd><button v-if="item.bodyId" @click="emit('select',{kind:'body',id:item.bodyId})">{{item.bodyId}} 상세</button><span v-else>차체 없음</span></dd></div><div><dt>작업</dt><dd>{{item.operationId || '—'}}</dd></div><div><dt>남은 작업</dt><dd>{{(item.remainingWorkMs/1000).toFixed(1)}}초</dd></div><div><dt>배출 대기 이유</dt><dd>{{reasonLabels[item.blockedReason] || '—'}}</dd></div><div><dt>목적지</dt><dd>{{item.destinationCellId || '—'}}</dd></div></dl>
  <template v-else-if="selection.kind==='buffer'"><dl class="body-detail"><div><dt>Bay / 셀</dt><dd>{{item.bufferId}} / {{item.cellId}}</dd></div><div><dt>대기 / 예약</dt><dd>{{item.waitingCount}} / {{item.reservedInboundCount}}</dd></div><div><dt>여유 / 전체</dt><dd>{{item.availableSlots}} / {{item.capacity}}</dd></div><div><dt>배출 승인 기준</dt><dd>W + R &lt; C · 예약에는 픽업 전과 이동 중을 포함</dd></div></dl><ul class="slot-list"><li v-for="slot in item.slots" :key="slot.slotId"><strong>{{slot.slotId}} · {{slotLabels[slot.status]}}</strong><button v-if="slot.bodyId" @click="emit('select',{kind:'body',id:slot.bodyId})">{{slot.bodyId}} 상세</button><span>{{slot.vehicleId || '—'}} / {{slot.transportId || '—'}} / {{slot.reservationId || '—'}}</span></li></ul></template>
  <dl v-else class="body-detail"><div><dt>차량 / 종류</dt><dd>{{item.vehicleId}} / {{item.kind}}</dd></div><div><dt>차량 단계</dt><dd>{{vehicleLabels[item.state] || item.state}}</dd></div><div><dt>관측 좌표</dt><dd>{{item.position.x.toFixed(1)}}, {{item.position.y.toFixed(1)}}</dd></div><div><dt>실제 적재 차체</dt><dd><button v-if="item.bodyId" @click="emit('select',{kind:'body',id:item.bodyId})">{{item.bodyId}} 상세</button><span v-else>없음</span></dd></div><div><dt>적재 부품</dt><dd>{{item.partsKitId || '없음'}}</dd></div><div><dt>운송</dt><dd>{{item.transportId || '—'}}</dd></div><div><dt>배정된 운송</dt><dd>{{transport?.status || '—'}} · {{transport?.bodyId || transport?.partsKitId || '—'}}</dd></div><div><dt>출발 / 목적지</dt><dd>{{transport?.source.locationId || '—'}} → {{transport?.destination.locationId || '—'}}</dd></div></dl>
 </template>
 <p class="small">지도와 상세는 같은 관측 묶음입니다. 아래 이력은 별도 조회 시점의 기록입니다.</p>
 <RecordPanel :run="run" :view="view" :selection="selection" compact />
</template>
