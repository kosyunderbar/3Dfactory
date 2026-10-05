import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import {mapEntities,filteredBodies,eventFilter,percent} from '../src/presentation.js'
const fixture=JSON.parse(fs.readFileSync(new URL('../../../contracts/v1/examples/monitoring-examples.json',import.meta.url))).snapshot
const config=JSON.parse(fs.readFileSync(new URL('../../factory-simulator/factory_simulator/config/default-run.json',import.meta.url))).config
test('one observed bundle preserves reservation versus cargo, body location and search/detail identity',()=>{
 const original=JSON.stringify(fixture),first=mapEntities(config,fixture)
 const pickup=first.vehicles.find(v=>v.vehicleId==='AGV-001')
 assert.equal(pickup.state,'LOADING');assert.equal(pickup.bodyId,null);assert.equal(pickup.transport.bodyId,'body-00042')
 const bay=first.buffers.find(b=>b.cellId==='ASM-02');assert.equal(bay.waitingCount+bay.reservedInboundCount,bay.capacity);assert.equal(bay.availableSlots,0)
 const target=filteredBodies(fixture,'TAG-00042')[0];assert.equal(target.bodyId,'body-00042');assert.equal(target.locationType,'CELL')
 assert.deepEqual(eventFilter({kind:'buffer',id:bay.bufferId,cellId:bay.cellId}),{cellId:'ASM-02'})
 assert.equal(JSON.stringify(fixture),original);assert.equal(percent(null),'—');assert.equal(percent(.2),'20.0%')
 assert.equal(mapEntities(config,{...fixture,sourceSeq:null}),null)
})
