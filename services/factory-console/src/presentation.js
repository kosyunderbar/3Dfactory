export const cellLabels={IDLE:'대기',RUNNING:'작업 중',BLOCKED:'배출 대기',DOWN:'설비 정지'}
export const bodyLabels={WAITING:'대기',PROCESSING:'작업 중',WAITING_UNLOAD:'배출 대기',IN_TRANSIT:'운송 중',COMPLETED:'공정 완료'}
export const vehicleLabels={IDLE:'대기',TO_PICKUP:'픽업 이동',LOADING:'적재 중',MOVING:'적재 운반',UNLOADING:'인계 중',RETURNING:'빈 차 귀환'}
export const reasonLabels={BUFFER_FULL:'목적지 슬롯 만석',NO_VEHICLE:'빈 AGV 대기',WAITING_PICKUP:'픽업 차량 대기'}
export const slotLabels={FREE:'여유',RESERVED:'예약',OCCUPIED:'대기'}
export const alarmLabels={BUFFER_FULL:'Bay 만석',EQUIPMENT_DOWN:'설비 정지',SOURCE_STALE:'보고 지연',SOURCE_DISCONNECTED:'소스 연결 끊김',PROCESSING_BLOCKED:'업무 반영 중단',QUALITY_WARNING:'품질 주의'}
export function date(value){return value ? new Date(value).toLocaleString('ko-KR',{hour12:false}) : '—'}
export function percent(value){return value===null || value===undefined ? '—' : `${(value*100).toFixed(1)}%`}
export function filteredBodies(view,query='',status=''){
 const needle=query.trim().toLowerCase()
 return (view?.bodies ?? []).filter(body=>(!status || body.status===status) && (!needle || `${body.bodyId} ${body.tagId} ${body.modelCode} ${body.specCode}`.toLowerCase().includes(needle)))
}
// Every physical value comes from this one bundle. Layout contributes coordinates only.
export function mapEntities(config,view){
 if(!config || !view || view.sourceSeq===null)return null
 const location=new Map(config.locations.map(item=>[item.locationId,item]))
 return {
  cells:view.equipment.map(item=>({...item,position:location.get(item.cellId)})),
  buffers:view.buffers.map(item=>({...item,position:location.get(item.bufferId)})),
  vehicles:view.vehicles.map(item=>({...item,transport:view.activeTransports.find(t=>t.transportId===item.transportId) ?? null})),
  bodies:view.bodies.filter(item=>item.locationType!=='VEHICLE').map(item=>({...item,position:location.get(item.locationId)}))
 }
}
export function eventFilter(selection){
 if(!selection)return {}
 if(selection.kind==='body')return {bodyId:selection.id}
 if(selection.kind==='vehicle')return {vehicleId:selection.id}
 return {cellId:selection.kind==='buffer' ? selection.cellId : selection.id}
}
export function periodWindow(asOf,minutes){
 const end=new Date(asOf).getTime()
 if(!Number.isFinite(end) || ![5,15,60].includes(Number(minutes)))return null
 return {from:new Date(end-Number(minutes)*60000).toISOString(),to:new Date(end).toISOString()}
}
