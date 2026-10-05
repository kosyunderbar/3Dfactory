/* Browser-only, deterministic domain model. No hardware or server connection. */
(function (root) {
  'use strict';
  const CELL_IDS = ['ASM-01', 'ASM-02', 'QC-01'];
  const DURATIONS = [4, 6, 3];
  const NEXT = { 'ASM-01': 'ASM-02', 'ASM-02': 'QC-01' };
  const clone = value => JSON.parse(JSON.stringify(value));

  function create(mode = 'normal') {
    const s = {
      mode, seconds: 0, revision: 0, serial: 0, transportSerial: 0,
      startTime: Date.now(), cells: {}, bays: {}, bodies: {}, transports: {},
      vehicles: {}, inspections: [], events: [], alarms: [], capacityStep: 0,
      kitsDelivered: 0, runId: 'DEMO-CELL-01'
    };
    CELL_IDS.forEach((id, i) => {
      s.cells[id] = { id, name: ['기초 조립', '모듈 조립', '최종 검사'][i],
        duration: DURATIONS[i], elapsed: 0, bodyId: null, down: false, reason: null };
      s.bays[id] = { id: 'BAY-' + id, cellId: id, capacity: 3,
        slots: Array.from({ length: 3 }, (_, n) => ({ id: id + '-S' + (n + 1), state: 'FREE', bodyId: null, transportId: null })) };
    });
    ['AGV-001', 'AGV-002'].forEach(id => { s.vehicles[id] = {
      id, kind: 'BODY', phase: 'IDLE', elapsed: 0, duration: 0,
      bodyId: null, transportId: null, source: null, destination: null, battery: 87
    }; });
    s.vehicles['AMR-001'] = { id: 'AMR-001', kind: 'PARTS', phase: 'TO_SUPPLY',
      elapsed: 0, duration: 7, bodyId: null, partsKitId: 'KIT-001', battery: 92 };

    function event(type, message, related = []) {
      s.events.unshift({ id: 'E-' + (++s.revision), seconds: s.seconds, type, message, related });
      s.events = s.events.slice(0, 120);
    }
    function body(locationType = 'INPUT', locationId = 'BODY-IN') {
      const n = ++s.serial, id = 'body-' + String(n).padStart(5, '0');
      s.bodies[id] = { id, tagId: 'tag-' + String(n).padStart(5, '0'),
        model: n % 2 ? 'EV-A' : 'EV-B', spec: n % 2 ? '롱레인지 · RWD' : '스탠다드 · AWD',
        locationType, locationId, status: 'WAITING', vehicleId: null,
        currentProcess: null, completedProcesses: [], nextProcess: 'ASM-01',
        inspection: 'NOT_INSPECTED', updatedAt: s.seconds, history: [] };
      record(s.bodies[id], '가상 스마트태그 등록');
      return s.bodies[id];
    }
    function record(b, message) {
      b.updatedAt = s.seconds;
      b.history.unshift({ seconds: s.seconds, message });
      b.history = b.history.slice(0, 24);
    }
    function placeCell(b, id, elapsed = 0) {
      const c = s.cells[id];
      c.bodyId = b.id; c.elapsed = elapsed; c.reason = null;
      b.locationType = 'CELL'; b.locationId = id; b.status = 'PROCESSING';
      b.currentProcess = id; b.nextProcess = NEXT[id] || 'GOOD / HOLD';
      record(b, id + ' 작업 시작');
    }
    function placeBay(b, id) {
      const slot = s.bays[id].slots.find(x => x.state === 'FREE');
      if (!slot) throw new Error('No physical slot');
      slot.state = 'OCCUPIED'; slot.bodyId = b.id;
      b.locationType = 'BUFFER'; b.locationId = s.bays[id].id; b.status = 'WAITING';
      b.currentProcess = null; b.nextProcess = id;
      record(b, s.bays[id].id + ' 대기');
    }
    function counts(id) {
      const bay = s.bays[id], waiting = bay.slots.filter(x => x.state === 'OCCUPIED').length;
      const reserved = bay.slots.filter(x => x.state === 'RESERVED').length;
      return { capacity: bay.capacity, waiting, reserved, available: bay.capacity - waiting - reserved };
    }
    // Check and claim the slot and vehicle in one synchronous operation.
    // R includes TO_PICKUP/LOADING, before the body physically leaves its source.
    function reserve(bodyId, source, destination, vehicleId) {
      const b = s.bodies[bodyId], v = vehicleId ? s.vehicles[vehicleId] :
        Object.values(s.vehicles).find(x => x.kind === 'BODY' && x.phase === 'IDLE');
      if (!b) return { ok: false, reason: 'BODY_NOT_FOUND' };
      if (Object.values(s.transports).some(t => t.bodyId === bodyId && ['ASSIGNED', 'IN_TRANSIT'].includes(t.status)))
        return { ok: false, reason: 'ALREADY_ASSIGNED' };
      if (source === 'BODY-IN' ? b.locationType !== 'INPUT' :
        !s.cells[source] || s.cells[source].bodyId !== b.id || b.status !== 'WAITING_UNLOAD' || s.cells[source].down)
        return { ok: false, reason: 'SOURCE_NOT_READY' };
      const bay = s.bays[destination];
      const slot = bay && bay.slots.find(x => x.state === 'FREE');
      if (bay && !slot) return { ok: false, reason: 'BUFFER_FULL' };
      if (!v || v.kind !== 'BODY' || v.phase !== 'IDLE') return { ok: false, reason: 'NO_VEHICLE' };
      const id = 'TR-' + String(++s.transportSerial).padStart(4, '0');
      const t = { id, bodyId, vehicleId: v.id, source, destination,
        slotId: slot ? slot.id : null, status: 'ASSIGNED' };
      s.transports[id] = t;
      if (slot) Object.assign(slot, { state: 'RESERVED', bodyId, transportId: id });
      Object.assign(v, { phase: 'TO_PICKUP', elapsed: 0, duration: 1.2,
        bodyId: null, transportId: id, source, destination });
      if (s.cells[source]) s.cells[source].reason = 'WAITING_PICKUP';
      b.nextProcess = destination;
      record(b, v.id + ' 배차 · ' + destination + (slot ? ' 슬롯 예약' : ' 반출'));
      event('RESERVATION', b.id + ' → ' + destination + ' / ' + v.id + ' 배차', [bodyId, source, destination, v.id]);
      return { ok: true, transportId: id };
    }
    function pickup(t) {
      const b = s.bodies[t.bodyId], v = s.vehicles[t.vehicleId];
      if (s.cells[t.source]) {
        s.cells[t.source].bodyId = null; s.cells[t.source].elapsed = 0; s.cells[t.source].reason = null;
      }
      b.locationType = 'VEHICLE'; b.locationId = v.id; b.vehicleId = v.id;
      if (b.inspection === 'NOT_INSPECTED') b.status = 'IN_TRANSIT';
      b.currentProcess = null;
      v.bodyId = b.id; t.status = 'IN_TRANSIT';
      record(b, v.id + ' 적재 완료 · 이동 시작');
    }
    function arrive(transportId) {
      const t = s.transports[transportId];
      if (!t || t.status !== 'IN_TRANSIT') return false;
      const b = s.bodies[t.bodyId], v = s.vehicles[t.vehicleId], bay = s.bays[t.destination];
      if (bay) {
        const slot = bay.slots.find(x => x.transportId === t.id);
        if (!slot || slot.state !== 'RESERVED') throw new Error('Missing reservation');
        // R--, W++: arrival alone never creates a free slot.
        Object.assign(slot, { state: 'OCCUPIED', transportId: null });
        b.locationType = 'BUFFER'; b.locationId = bay.id; b.status = 'WAITING'; b.nextProcess = t.destination;
      } else {
        b.locationType = 'RESULT'; b.locationId = t.destination; b.status = 'COMPLETED';
      }
      b.vehicleId = null; t.status = 'COMPLETED';
      Object.assign(v, { phase: 'RETURNING', bodyId: null, elapsed: 0, duration: 1 });
      record(b, t.destination + ' 인계 완료');
      event('ARRIVAL', b.id + ' · ' + t.destination + ' 도착', [b.id, t.destination, v.id]);
      return true;
    }
    function enter(id) {
      const c = s.cells[id];
      if (c.bodyId || c.down) return false;
      const slot = s.bays[id].slots.find(x => x.state === 'OCCUPIED');
      if (!slot) return false;
      const b = s.bodies[slot.bodyId];
      Object.assign(slot, { state: 'FREE', bodyId: null, transportId: null });
      placeCell(b, id);
      event('CELL_ENTRY', b.id + ' → ' + id + ' / 버퍼 슬롯 반환', [b.id, id]);
      return true;
    }
    function cancel(id) {
      const t = s.transports[id];
      if (!t || t.status !== 'ASSIGNED') return false;
      const v = s.vehicles[t.vehicleId], bay = s.bays[t.destination];
      if (bay) {
        const slot = bay.slots.find(x => x.transportId === id);
        if (slot) Object.assign(slot, { state: 'FREE', bodyId: null, transportId: null });
      }
      t.status = 'CANCELLED';
      Object.assign(v, { phase: 'IDLE', bodyId: null, transportId: null, source: null, destination: null, elapsed: 0 });
      record(s.bodies[t.bodyId], '출발 전 배차 취소 · 예약 반환');
      if (s.cells[t.source]) s.cells[t.source].reason = null;
      event('CANCEL', id + ' 출발 전 취소', [t.bodyId, t.vehicleId, t.source, t.destination]);
      return true;
    }
    function finish(c) {
      const b = s.bodies[c.bodyId];
      if (b.status !== 'PROCESSING') return;
      b.completedProcesses.push(c.id); b.status = 'WAITING_UNLOAD';
      if (c.id === 'QC-01') {
        b.inspection = Number(b.id.slice(-5)) % 17 === 0 ? 'FAIL' : 'PASS';
        b.status = 'COMPLETED'; b.nextProcess = b.inspection === 'PASS' ? 'GOOD' : 'HOLD';
        s.inspections.push({ bodyId: b.id, result: b.inspection, seconds: s.seconds, fixture: false });
      }
      record(b, c.id + ' 작업 완료' + (c.id === 'QC-01' ? ' · ' + b.inspection : ''));
      event('WORK_COMPLETE', b.id + ' · ' + c.id + ' 완료', [b.id, c.id]);
    }
    function dispatch() {
      CELL_IDS.slice().reverse().forEach(id => {
        const c = s.cells[id], b = s.bodies[c.bodyId];
        if (!b || c.down || b.status === 'PROCESSING') return;
        const destination = NEXT[id] || (b.inspection === 'PASS' ? 'GOOD' : 'HOLD');
        // COMPLETED refers to inspection, and can still be in CELL or VEHICLE.
        const existing = Object.values(s.transports).find(t => t.bodyId === b.id && ['ASSIGNED', 'IN_TRANSIT'].includes(t.status));
        if (existing) { c.reason = 'WAITING_PICKUP'; return; }
        if (s.bays[destination] && counts(destination).available === 0) { c.reason = 'BUFFER_FULL'; return; }
        const oldStatus = b.status;
        b.status = 'WAITING_UNLOAD';
        const result = reserve(b.id, id, destination);
        b.status = oldStatus;
        c.reason = result.ok ? 'WAITING_PICKUP' : result.reason;
      });
      if (s.serial < 100 && counts('ASM-01').available > 0 &&
        Object.values(s.vehicles).some(v => v.kind === 'BODY' && v.phase === 'IDLE')) {
        let b = Object.values(s.bodies).find(x => x.locationType === 'INPUT' &&
          !Object.values(s.transports).some(t => t.bodyId === x.id && t.status === 'ASSIGNED'));
        if (!b) b = body();
        reserve(b.id, 'BODY-IN', 'ASM-01');
      }
    }
    function setDown(id, value) {
      const c = s.cells[id]; c.down = value;
      let a = s.alarms.find(x => x.cellId === id && !x.resolved);
      if (value && !a) {
        a = { id: 'AL-' + (s.alarms.length + 1), cellId: id, message: id + ' 셀 정지', acknowledged: false, resolved: false, seconds: s.seconds };
        s.alarms.unshift(a); event('DOWN', id + ' 정지 · 작업/셀 진입 중단', [id]);
      } else if (!value && a) {
        a.resolved = true; event('RECOVERY', id + ' 복구', [id]);
      }
    }
    function acknowledge(id) {
      const a = s.alarms.find(x => x.id === id);
      if (a) { a.acknowledged = true; event('ACK', a.message + ' · 운영자 확인', [a.cellId]); }
    }
    function tick(dt) {
      if (s.mode === 'capacity') return; // The guided fixture advances only via explicit steps.
      s.seconds += dt;
      Object.values(s.vehicles).forEach(v => {
        if (v.phase === 'IDLE') return;
        v.elapsed += dt;
        if (v.elapsed + 1e-8 < v.duration) return;
        v.elapsed = 0;
        if (v.kind === 'PARTS') {
          if (v.phase === 'TO_SUPPLY') { v.phase = 'DELIVERING'; v.duration = 1; }
          else if (v.phase === 'DELIVERING') { s.kitsDelivered++; v.phase = 'RETURNING'; v.duration = 6;
            event('PARTS', v.partsKitId + ' → 부품 도크 인계 / 차체 버퍼 미사용', [v.id, 'ASM-02']); }
          else { v.phase = 'TO_SUPPLY'; v.duration = 7; v.partsKitId = 'KIT-' + String(s.kitsDelivered + 1).padStart(3, '0'); }
          return;
        }
        const t = s.transports[v.transportId];
        if (v.phase === 'TO_PICKUP') { v.phase = 'LOADING'; v.duration = 0.8; }
        else if (v.phase === 'LOADING') { pickup(t); v.phase = 'MOVING'; v.duration = 3; }
        else if (v.phase === 'MOVING') { v.phase = 'UNLOADING'; v.duration = 0.6; }
        else if (v.phase === 'UNLOADING') arrive(t.id);
        else { Object.assign(v, { phase: 'IDLE', transportId: null, source: null, destination: null, duration: 0 }); }
      });
      CELL_IDS.forEach(id => {
        const c = s.cells[id], b = s.bodies[c.bodyId];
        if (b && b.status === 'PROCESSING' && !c.down) { c.elapsed += dt; if (c.elapsed >= c.duration) finish(c); }
        enter(id);
      });
      dispatch();
    }
    function cellState(id) {
      const c = s.cells[id];
      return c.down ? 'DOWN' : !c.bodyId ? 'IDLE' : s.bodies[c.bodyId].status === 'PROCESSING' ? 'RUNNING' : 'BLOCKED';
    }
    function seedNormal() {
      CELL_IDS.forEach((id, i) => {
        const b = body(); b.completedProcesses = CELL_IDS.slice(0, i);
        placeCell(b, id, [2, 3, 1][i]);
      });
      placeBay(body(), 'ASM-01');
      const b = body(); b.completedProcesses = ['ASM-01']; placeBay(b, 'ASM-02');
      const q = body(); q.completedProcesses = ['ASM-01', 'ASM-02']; placeBay(q, 'QC-01');
      body();
    }
    if (mode === 'capacity') {
      const upstream = body(); placeCell(upstream, 'ASM-01', 4); finish(s.cells['ASM-01']);
      for (let i = 0; i < 2; i++) { const b = body(); b.completedProcesses = ['ASM-01']; placeBay(b, 'ASM-02'); }
      const incoming = body(); incoming.completedProcesses = ['ASM-01'];
      const assigned = reserve(incoming.id, 'BODY-IN', 'ASM-02', 'AGV-001');
      const t = s.transports[assigned.transportId];
      // Seed an already-departed prior body; ASM-01 now holds the next completed body.
      t.source = 'ASM-01';
      Object.assign(s.vehicles['AGV-001'], { source: 'ASM-01', phase: 'MOVING', elapsed: 1.5, duration: 3, bodyId: incoming.id });
      t.status = 'IN_TRANSIT';
      Object.assign(incoming, { locationType: 'VEHICLE', locationId: 'AGV-001', vehicleId: 'AGV-001', status: 'IN_TRANSIT' });
      record(incoming, 'AGV-001 · 이전 ASM-01 작업 완료 차체 이동 중');
      s.cells['ASM-01'].reason = 'BUFFER_FULL';
      event('BLOCKED', 'ASM-01 배출 차단 · 대기 2 + 예약 1 = 3 / 3', ['ASM-01', 'ASM-02', upstream.id]);
    } else {
      seedNormal();
      if (mode === 'down') setDown('ASM-02', true);
      if (mode === 'quality') {
        // Explicit historical fixture. Unique body/tag pairs, one inspection per body.
        for (let i = 0; i < 100; i++) {
          const id = 'sample-' + String(i + 1).padStart(5, '0');
          const b = { id, tagId: 'sample-tag-' + String(i + 1).padStart(5, '0'), model: 'EV-A', spec: '품질 시나리오 표본',
            locationType: 'RESULT', locationId: i < 20 ? 'HOLD' : 'GOOD', status: 'COMPLETED', vehicleId: null,
            currentProcess: null, completedProcesses: CELL_IDS.slice(), nextProcess: null,
            inspection: i < 20 ? 'FAIL' : 'PASS', updatedAt: -1, history: [{ seconds: -1, message: '최근 5분 검사 이력 샘플' }] };
          s.bodies[id] = b;
          s.inspections.push({ bodyId: id, result: b.inspection, seconds: -1 - i * 2.8, fixture: true });
        }
        event('QUALITY_FIXTURE', '과거 검사 샘플 100대 / FAIL 20대 주입', ['QC-01']);
      }
    }
    function stepCapacity() {
      if (s.mode !== 'capacity' || s.capacityStep >= 2) return false;
      s.seconds += 1;
      if (s.capacityStep === 0) {
        const t = Object.values(s.transports).find(x => x.status === 'IN_TRANSIT');
        arrive(t.id); s.capacityStep = 1;
        event('BLOCKED', '차량 도착 후에도 대기 3 + 예약 0 = 3 / 3 · 배출 차단 유지', ['ASM-01', 'ASM-02']);
      } else {
        enter('ASM-02');
        const b = s.bodies[s.cells['ASM-01'].bodyId];
        reserve(b.id, 'ASM-01', 'ASM-02', 'AGV-002'); s.capacityStep = 2;
        event('RESUME', '셀 진입으로 1칸 반환 → 배차 1건 승인 → 다시 예약 포함 3 / 3', ['ASM-01', 'ASM-02']);
      }
      return true;
    }
    function snapshot() {
      const out = clone(s);
      CELL_IDS.forEach(id => { out.cells[id].state = cellState(id); out.bays[id].counts = counts(id); });
      return out;
    }
    return { tick, snapshot, reserve, arrive, cancel, enter, setDown, acknowledge, stepCapacity, counts };
  }
  root.FactoryDemo = { create, CELL_IDS };
})(typeof globalThis !== 'undefined' ? globalThis : this);
