<script setup>
import {computed} from 'vue'
import {mapEntities,cellLabels,vehicleLabels,slotLabels} from '../presentation.js'
import {layoutMap} from '../map-layout.js'
const props=defineProps({config:Object,view:Object,stale:Boolean,selection:Object})
const emit=defineEmits(['select'])
const layout=computed(()=>layoutMap(props.config,mapEntities(props.config,props.view)))
const shortBody=id=>id?.replace('body-','B-') || '차체 없음'
const shortLabel=value=>value.length>18 ? `${value.slice(0,17)}…` : value
function choose(kind,item){emit('select',{kind,id:item[`${kind}Id`] || item.equipmentId,cellId:item.cellId})}
function selected(kind,id){return props.selection?.kind===kind && props.selection.id===id}
</script>
<template>
 <div class="map-wrap" tabindex="0" aria-label="공장 지도. 작은 화면에서는 좌우로 스크롤할 수 있습니다.">
  <svg v-if="layout" class="factory-map" :viewBox="`0 0 ${layout.width} ${layout.height}`" role="group" aria-labelledby="map-title map-description" data-testid="factory-map">
   <title id="map-title">독립 셀·Bay·AGV·AMR 공장 지도</title>
   <desc id="map-description">클릭 또는 Enter로 상세를 엽니다. 차량 카드는 겹침을 피해 배치하고 연결선 끝의 점이 실제 보고 위치를 나타냅니다. 차체가 많은 구역은 최대 네 대와 전체 대수를 표시합니다.</desc>
   <g class="routes" aria-hidden="true">
    <polyline v-for="route in layout.routes" :key="route.routeId" :points="route.points.map(p=>`${p.x},${p.y}`).join(' ')" :class="{parts:route.cargoType==='PARTS'}" />
   </g>
   <g v-for="cell in layout.cells" :key="cell.equipmentId" class="map-target map-cell" :class="[cell.state.toLowerCase(),{selected:selected('cell',cell.cellId)}]" :transform="`translate(${cell.rect.x},${cell.rect.y})`" role="button" tabindex="0" :aria-label="`${cell.cellId} ${cellLabels[cell.state]} ${cell.bodyId || '차체 없음'} 상세`" @click="choose('cell',cell)" @keydown.enter.prevent="choose('cell',cell)" @keydown.space.prevent="choose('cell',cell)">
    <line x1="79" y1="98" x2="79" y2="178" />
    <rect width="158" height="98" rx="12" />
    <text x="79" y="29" text-anchor="middle" class="map-strong">{{cell.cellId}}</text>
    <text x="79" y="53" text-anchor="middle">{{cellLabels[cell.state]}}</text>
    <text x="79" y="78" text-anchor="middle" class="map-secondary">{{shortBody(cell.bodyId)}}</text>
   </g>
   <g v-for="buffer in layout.buffers" :key="buffer.bufferId" class="map-target map-buffer" :class="{full:buffer.availableSlots===0,selected:selected('buffer',buffer.bufferId)}" :transform="`translate(${buffer.rect.x},${buffer.rect.y})`" role="button" tabindex="0" :aria-label="`${buffer.bufferId} 대기 ${buffer.waitingCount} 예약 ${buffer.reservedInboundCount} 여유 ${buffer.availableSlots} 전체 ${buffer.capacity} 상세`" @click="choose('buffer',buffer)" @keydown.enter.prevent="choose('buffer',buffer)" @keydown.space.prevent="choose('buffer',buffer)">
    <line x1="88" y1="-78" x2="88" y2="0" />
    <rect width="176" :height="buffer.rect.height" rx="12" />
    <text x="88" y="25" text-anchor="middle" class="map-strong">{{buffer.cellId}} Bay</text>
    <text x="88" y="46" text-anchor="middle" class="map-secondary">W{{buffer.waitingCount}} / R{{buffer.reservedInboundCount}} / A{{buffer.availableSlots}} / C{{buffer.capacity}}</text>
    <g v-for="(slot,index) in buffer.slots" :key="slot.slotId" :transform="`translate(12,${58+index*26})`" :class="`map-slot ${slot.status.toLowerCase()}`">
     <rect width="152" height="22" rx="5" />
     <text x="8" y="15">{{index+1}} {{slotLabels[slot.status]}} {{slot.bodyId ? shortBody(slot.bodyId) : ''}}</text>
    </g>
   </g>
   <g v-for="dock in layout.docks" :key="dock.locationId" class="map-place" aria-hidden="true">
    <circle :cx="dock.anchor.x" :cy="dock.anchor.y" r="5" />
    <rect :x="dock.rect.x" :y="dock.rect.y" width="168" height="30" rx="7" />
    <text :x="dock.rect.x+84" :y="dock.rect.y+20" text-anchor="middle">{{shortLabel(dock.locationId)}}</text>
   </g>
   <g v-for="place in layout.places" :key="place.locationId" class="map-place">
    <line :x1="place.anchor.x" :y1="place.anchor.y" :x2="place.rect.x+84" :y2="place.rect.y" />
    <circle :cx="place.anchor.x" :cy="place.anchor.y" r="5" />
    <rect :x="place.rect.x" :y="place.rect.y" width="168" :height="place.rect.height" rx="10" />
    <text :x="place.rect.x+14" :y="place.rect.y+24" class="map-strong">{{shortLabel(place.locationId)}}</text>
    <text :x="place.rect.x+14" :y="place.rect.y+44" class="map-secondary">차체 {{place.bodyCount}}대</text>
    <g v-for="(body,index) in place.bodies" :key="body.bodyId" class="map-target map-body" :class="{selected:selected('body',body.bodyId)}" :transform="`translate(${place.rect.x+12+(index%2)*74},${place.rect.y+52+Math.floor(index/2)*28})`" role="button" tabindex="0" :aria-label="`${body.tagId} ${body.locationId} 상세`" @click="choose('body',body)" @keydown.enter.prevent="choose('body',body)" @keydown.space.prevent="choose('body',body)">
     <rect width="70" height="22" rx="5" /><text x="35" y="15" text-anchor="middle">{{shortBody(body.bodyId)}}</text>
    </g>
    <text v-if="place.hiddenCount" :x="place.rect.x+14" :y="place.rect.y+place.rect.height-7" class="map-note">외 {{place.hiddenCount}}대 · 아래 태그에서 조회</text>
   </g>
   <g class="vehicle-positions" aria-hidden="true">
    <g v-for="vehicle in layout.vehicles" :key="vehicle.vehicleId">
     <line :x1="vehicle.anchor.x" :y1="vehicle.anchor.y" :x2="vehicle.rect.x+63" :y2="vehicle.rect.y+28" />
     <circle :cx="vehicle.anchor.x" :cy="vehicle.anchor.y" r="4" />
    </g>
   </g>
   <g v-for="vehicle in layout.vehicles" :key="vehicle.vehicleId" class="map-target map-vehicle" :class="{loaded:vehicle.bodyId || vehicle.partsKitId,selected:selected('vehicle',vehicle.vehicleId)}" :transform="`translate(${vehicle.rect.x},${vehicle.rect.y})`" role="button" tabindex="0" :aria-label="`${vehicle.vehicleId} ${vehicleLabels[vehicle.state] || vehicle.state} ${vehicle.bodyId || vehicle.partsKitId || '빈 차량'} 상세`" :data-vehicle="vehicle.vehicleId" :data-cargo="vehicle.bodyId || vehicle.partsKitId || ''" :data-state="vehicle.state" @click="choose('vehicle',vehicle)" @keydown.enter.prevent="choose('vehicle',vehicle)" @keydown.space.prevent="choose('vehicle',vehicle)">
    <rect width="126" height="56" rx="9" />
    <text x="12" y="19" class="map-vehicle-name">{{vehicle.vehicleId}}</text>
    <text x="12" y="35" class="map-secondary">{{vehicleLabels[vehicle.state] || vehicle.state}}</text>
    <text x="12" y="49" class="map-note">{{vehicle.bodyId ? shortBody(vehicle.bodyId) : vehicle.partsKitId ? shortLabel(vehicle.partsKitId) : '빈 차량'}}</text>
   </g>
  </svg>
  <p v-else class="empty">지도 설정과 첫 공장 관측을 기다립니다.</p>
 </div>
 <p class="map-legend small">실선: 차체 경로 · 점선: 부품 경로 · W 대기 / R 예약 / A 여유 / C 전체 · {{stale ? '마지막 확인 위치' : '관측 시각의 위치'}}</p>
 <p class="map-legend small">차량 카드의 연결선 끝 점이 보고 위치입니다. 같은 위치의 차량도 각각 선택할 수 있습니다. 구역 차체는 최대 4대 표시하며 전체 목록은 아래 스마트태그에서 조회합니다.</p>
</template>
