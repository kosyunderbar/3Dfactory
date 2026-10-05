/* Load after model.js in a JS runtime. Throws on failure; no production side effects. */
(function () {
  'use strict';
  function assert(condition, message) { if (!condition) throw new Error(message); }
  let checks = 0;
  function invariant(s) {
    const places = {};
    function locate(id, type, location) {
      assert(!places[id], id + ' has duplicate physical ownership');
      places[id] = true;
      assert(s.bodies[id].locationType === type && s.bodies[id].locationId === location, id + ' location disagrees with owner');
    }
    Object.values(s.cells).forEach(c => { if (c.bodyId) locate(c.bodyId, 'CELL', c.id); });
    Object.values(s.bays).forEach(bay => {
      const n = bay.counts;
      assert(n.waiting + n.reserved <= n.capacity && n.available >= 0, 'Buffer exceeds capacity');
      assert(n.waiting + n.reserved + n.available === n.capacity, 'Slot conservation');
      bay.slots.forEach(slot => {
        if (slot.state === 'OCCUPIED') locate(slot.bodyId, 'BUFFER', bay.id);
        if (slot.state === 'RESERVED') {
          const t = s.transports[slot.transportId];
          assert(t && ['ASSIGNED', 'IN_TRANSIT'].includes(t.status) && t.bodyId === slot.bodyId, 'Invalid reservation owner');
          assert(s.vehicles[t.vehicleId].kind === 'BODY', 'Parts AMR consumed body slot');
        }
        if (slot.state === 'FREE') assert(!slot.bodyId && !slot.transportId, 'Free slot has owner');
      });
    });
    Object.values(s.vehicles).forEach(v => { if (v.bodyId) locate(v.bodyId, 'VEHICLE', v.id); });
    Object.values(s.bodies).forEach(b => {
      if (['INPUT', 'RESULT'].includes(b.locationType)) { assert(!places[b.id], 'Boundary body has another owner'); places[b.id] = true; }
      assert(places[b.id], b.id + ' has no owner');
    });
    assert(new Set(Object.values(s.bodies).map(b => b.tagId)).size === Object.keys(s.bodies).length, 'Duplicate tag ID');
    assert(new Set(s.inspections.map(i => i.bodyId)).size === s.inspections.length, 'Duplicate inspection');
    checks++;
  }
  const capacity = FactoryDemo.create('capacity');
  let s = capacity.snapshot(); invariant(s);
  assert(s.bays['ASM-02'].counts.waiting === 2 && s.bays['ASM-02'].counts.reserved === 1, 'Fixture W2 R1');
  assert(capacity.reserve('body-00001', 'ASM-01', 'ASM-02', 'AGV-002').reason === 'BUFFER_FULL', 'Must block while reserved slot is in transit');
  const moving = Object.values(s.transports).find(t => t.status === 'IN_TRANSIT');
  assert(!capacity.cancel(moving.id), 'Cannot cancel a departed transport');
  capacity.stepCapacity(); s = capacity.snapshot(); invariant(s);
  assert(s.bays['ASM-02'].counts.waiting === 3 && s.bays['ASM-02'].counts.reserved === 0 && s.bays['ASM-02'].counts.available === 0, 'Arrival must not release capacity');
  assert(!capacity.arrive(moving.id), 'Repeated arrival must be ignored');
  assert(capacity.enter('ASM-02'), 'Bay can feed empty cell');
  s = capacity.snapshot(); invariant(s);
  assert(s.bays['ASM-02'].counts.available === 1, 'Cell entry releases one slot');
  const approved = capacity.reserve('body-00001', 'ASM-01', 'ASM-02', 'AGV-002');
  assert(approved.ok, 'Exactly one new assignment should fit');
  s = capacity.snapshot(); invariant(s);
  assert(s.bodies['body-00001'].locationType === 'CELL', 'Reserved body must remain in upstream cell before pickup');
  assert(capacity.reserve('body-00001', 'ASM-01', 'ASM-02', 'AGV-002').reason === 'ALREADY_ASSIGNED', 'Duplicate assignment');
  assert(capacity.cancel(approved.transportId), 'Can cancel before departure');
  assert(!capacity.cancel(approved.transportId), 'Cancellation must be idempotent'); invariant(capacity.snapshot());

  // A downstream stop must eventually fill the finite buffer and block its upstream cell.
  const race = FactoryDemo.create('normal');
  race.setDown('ASM-02', true); race.setDown('QC-01', true);
  for (let i = 0; i < 1000; i++) race.tick(.1);
  s = race.snapshot(); invariant(s);
  assert(s.cells['ASM-01'].reason === 'BUFFER_FULL', 'Downstream stop must propagate via finite buffer');
  const fullCount = s.bays['ASM-02'].counts;
  assert(fullCount.waiting + fullCount.reserved === fullCount.capacity, 'Downstream bay should fill');
  // Main run verifies all 100 bodies reach a result once, across 20,000 steps.
  const normal = FactoryDemo.create('normal');
  for (let i = 0; i < 20000; i++) { normal.tick(.1); if (i % 10 === 0) invariant(normal.snapshot()); }
  s = normal.snapshot(); invariant(s);
  assert(s.inspections.length === 100, 'Normal run should inspect every body exactly once');
  assert(Object.values(s.bodies).every(b => b.locationType === 'RESULT'), 'Normal run must drain without deadlock');
  assert(s.kitsDelivered > 0, 'Parts AMR should deliver separately');
  const quality = FactoryDemo.create('quality').snapshot(); invariant(quality);
  assert(quality.inspections.length === 100 && quality.inspections.filter(i => i.result === 'FAIL').length === 20, 'Quality sample must be 100 / 20');
  const alarm = FactoryDemo.create('down');
  const alarmId = alarm.snapshot().alarms[0].id; alarm.acknowledge(alarmId);
  assert(!alarm.snapshot().alarms[0].resolved, 'Acknowledgement is not recovery');
  alarm.setDown('ASM-02', false);
  assert(alarm.snapshot().alarms[0].resolved && alarm.snapshot().alarms[0].acknowledged, 'Recovery should preserve acknowledgement');
  console.log('Model verification passed: ' + checks + ' invariant snapshots; capacity, cancellation, propagation, 100-body drain, quality, alarms.');
})();
