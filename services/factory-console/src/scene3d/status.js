// Labels describe the current authoritative state, including the current leg
// of a transport; an assigned drop-off is not the vehicle's pickup target.
export function cellFlag(cell) {
  if (!cell) return { detail: '관측 대기', color: '#62758b', background: '#edf2f8' }
  if (cell.state === 'DOWN') return { detail: '고장 · 정지', color: '#ac4e43', background: '#fbe9e5' }
  if (cell.state === 'RUNNING') return { detail: `작업 중 · ${(cell.remainingWorkMs / 1000).toFixed(1)}초`, color: '#3467c7', background: '#e6eefc' }
  if (cell.state === 'BLOCKED' && cell.bodyId && cell.remainingWorkMs === 0) {
    const reason = { BUFFER_FULL: '다음 Bay 만석', NO_VEHICLE: '차량 대기', WAITING_PICKUP: '픽업 대기' }[cell.blockedReason] || '인계 대기'
    return { detail: `작업 완료 · ${reason}`, color: '#237b62', background: '#e3f3ec' }
  }
  if (cell.state === 'IDLE') return { detail: '대기 · 차체 없음', color: '#62758b', background: '#edf2f8' }
  return { detail: '배출 대기', color: '#96651d', background: '#fff0d5' }
}

export function vehicleFlag(vehicle, transports, config, equipment=[]) {
  const trip = transports.find(t => t.transportId === vehicle.transportId && t.vehicleId === vehicle.vehicleId)
  let detail
  if (vehicle.state === 'IDLE') {
    const dock=config?.traffic?.policyVersion>=4 && config.locations?.find(l=>l.locationType==='CELL' && l.x===vehicle.position?.x && l.y===vehicle.position?.y)
    const working=dock && equipment.some(c=>c.cellId===dock.locationId && c.state==='RUNNING' && c.remainingWorkMs<=8000)
    detail = working ? `완료 대기 · ${dock.locationId}` : '대기 · 배정 없음'
  }
  else if (vehicle.state === 'RETURNING' && config?.traffic?.policyVersion>=4) {
    const home=config.vehicles?.find(v=>v.vehicleId===vehicle.vehicleId)?.initialPosition
    const goal=vehicle.traffic?.path?.at(-1)
    detail=home && goal && goal.x===home.x && goal.y===home.y ? (vehicle.kind==='AMR' ? '복귀 → 부품 대기 구역' : '최종 복귀 → 초기 위치') : '이동 → 대기 지점'
  }
  else if (vehicle.state === 'RETURNING') detail = `복귀 → ${config?.traffic ? '전용 주차' : config?.vehicles?.find(v => v.vehicleId === vehicle.vehicleId)?.home.locationId || '기지'}`
  else if (!trip) detail = '목적지 확인 중'
  else if (vehicle.state === 'TO_PICKUP') detail = `픽업 → ${trip.source.locationId}`
  else if (vehicle.state === 'LOADING') detail = `상차 중 · ${trip.source.locationId}`
  else if (vehicle.state === 'UNLOADING') detail = `하차 중 · ${trip.destination.locationId}`
  else detail = `운반 → ${trip.destination.locationId}`
  return vehicle.traffic?.waiting
    ? { detail: `양보 · ${detail}`, color: '#96651d', background: '#fff0d5' }
    : { detail, color: '#3467c7', background: '#ffffff' }
}
