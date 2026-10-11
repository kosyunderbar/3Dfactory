import test from 'node:test'
import assert from 'node:assert/strict'
import { cellFlag, vehicleFlag } from '../src/scene3d/status.js'

test('equipment completion means finished work still waiting for handover, not idle or failed', () => {
 const complete = {state:'BLOCKED',bodyId:'body-1',remainingWorkMs:0,blockedReason:'BUFFER_FULL'}
 assert.equal(cellFlag(complete).detail,'작업 완료 · 다음 Bay 만석')
 assert.match(cellFlag({...complete,state:'DOWN'}).detail,/고장/)
 assert.equal(cellFlag({...complete,state:'IDLE',bodyId:null}).detail,'대기 · 차체 없음')
 assert.equal(cellFlag({...complete,state:'RUNNING',remainingWorkMs:2400}).detail,'작업 중 · 2.4초')
 assert.doesNotMatch(cellFlag({...complete,remainingWorkMs:100}).detail,/완료/)
 assert.equal(cellFlag(null).detail,'관측 대기')
})
test('vehicle labels show the current pickup/dropoff/return leg and preserve destination while yielding', () => {
 const trips=[{transportId:'t1',vehicleId:'AGV-001',source:{locationId:'ASM-01'},destination:{locationId:'BAY-ASM-02'}}]
 const v={vehicleId:'AGV-001',transportId:'t1',state:'TO_PICKUP'}
 assert.equal(vehicleFlag(v,trips).detail,'픽업 → ASM-01')
 assert.equal(vehicleFlag({...v,state:'LOADING'},trips).detail,'상차 중 · ASM-01')
 assert.equal(vehicleFlag({...v,state:'MOVING'},trips).detail,'운반 → BAY-ASM-02')
 assert.equal(vehicleFlag({...v,state:'UNLOADING'},trips).detail,'하차 중 · BAY-ASM-02')
 assert.equal(vehicleFlag({...v,traffic:{waiting:true}},trips).detail,'양보 · 픽업 → ASM-01')
 assert.equal(vehicleFlag({...v,state:'RETURNING',transportId:null},trips,{traffic:{}}).detail,'복귀 → 전용 주차')
 assert.equal(vehicleFlag({...v,state:'RETURNING',transportId:null},trips,{vehicles:[{vehicleId:'AGV-001',home:{locationId:'BODY-IN'}}]}).detail,'복귀 → BODY-IN')
 assert.equal(vehicleFlag({...v,state:'IDLE',transportId:null},trips).detail,'대기 · 배정 없음')
 assert.equal(vehicleFlag({...v,vehicleId:'AGV-002'},trips).detail,'목적지 확인 중')
})

test('policy 4 distinguishes local standby moves and waiting at a running cell',()=>{
 const config={traffic:{policyVersion:4},locations:[{locationType:'CELL',locationId:'ASM-01',x:150,y:100}]}
 const v={state:'IDLE',position:{x:150,y:100}}
 assert.equal(vehicleFlag(v,[],config,[{cellId:'ASM-01',state:'RUNNING',remainingWorkMs:700}]).detail,'완료 대기 · ASM-01')
 assert.equal(vehicleFlag(v,[],config,[{cellId:'ASM-01',state:'DOWN'}]).detail,'대기 · 배정 없음')
 assert.equal(vehicleFlag({...v,state:'RETURNING'},[],config).detail,'이동 → 대기 지점')
})

test('final outer return is distinct from temporary local standby',()=>{
 const config={traffic:{policyVersion:4},vehicles:[{vehicleId:'AGV-002',initialPosition:{x:-90,y:420}}]}
 const v={vehicleId:'AGV-002',state:'RETURNING',traffic:{path:[{x:780,y:340},{x:845,y:650},{x:0,y:650},{x:-90,y:420}]}}
 assert.equal(vehicleFlag(v,[],config).detail,'최종 복귀 → 초기 위치')
 assert.equal(vehicleFlag({...v,traffic:{path:[{x:700,y:70},{x:780,y:340}]}},[],config).detail,'이동 → 대기 지점')
})
