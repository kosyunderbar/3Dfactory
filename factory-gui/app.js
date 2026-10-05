/* Standalone UI adapter; all values come from one observed model snapshot. */
(() => {
  'use strict';
  const $ = selector => document.querySelector(selector);
  const $$ = selector => [...document.querySelectorAll(selector)];
  const esc = value => String(value ?? '—').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const fmt = n => n.toLocaleString('ko-KR');
  const time = n => new Date(n).toLocaleTimeString('en-GB', { timeZone: 'Asia/Seoul', hour12: false });
  const labels = { RUNNING: '가동', IDLE: '대기', BLOCKED: '배출 대기', DOWN: '정지',
    PROCESSING: '작업 중', WAITING: '대기', WAITING_UNLOAD: '배출 대기', IN_TRANSIT: '이동 중', COMPLETED: '검사 완료',
    BUFFER_FULL: '다음 셀 버퍼 만석', NO_VEHICLE: '가용 AGV 대기', WAITING_PICKUP: '예약 완료 · 픽업 대기',
    TO_PICKUP: '픽업 이동', LOADING: '적재 중', MOVING: '차체 이동', UNLOADING: '인계 중', RETURNING: '복귀 중',
    TO_SUPPLY: '부품 공급 이동', DELIVERING: '부품 인계', NOT_INSPECTED: '미검사', PASS: '양품', FAIL: '불량',
    CELL: '작업 셀', BUFFER: 'Parking Bay', VEHICLE: '차량', INPUT: '투입 구역', RESULT: '반출 구역' };
  const tone = value => ['DOWN', 'FAIL'].includes(value) ? 'red' : ['BLOCKED', 'WAITING_UNLOAD', 'RESERVED'].includes(value) ? 'amber' :
    ['RUNNING', 'PROCESSING', 'PASS', 'OCCUPIED'].includes(value) ? 'mint' : 'gray';
  const badge = value => `<span class="badge ${tone(value)}">${esc(labels[value] || value)}</span>`;
  const bodyButton = id => id ? `<button class="body-link" data-body="${esc(id)}">${esc(id)} ↗</button>` : '<span class="muted">차체 없음</span>';
  const positions = { 'BODY-IN': [65, 333], 'ASM-01': [265, 333], 'ASM-02': [510, 333], 'QC-01': [755, 333], GOOD: [936, 320], HOLD: [936, 373] };
  const home = { 'AGV-001': [170, 385], 'AGV-002': [450, 385] };
  let model = FactoryDemo.create(), view = model.snapshot(), paused = false, offline = false;
  let selected = { kind: 'cell', id: 'ASM-01' }, activeTab = 'events', eventFilter = null, dialogBody = null;
  let lastReceipt = Date.now(), receivedMono = performance.now(), lastTick = performance.now(), lastPublish = 0;
  let scene = 'normal', toastTimer, accumulator = 0;
  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  function toast(message) {
    $('#toast').textContent = message; $('#toast').classList.add('visible');
    clearTimeout(toastTimer); toastTimer = setTimeout(() => $('#toast').classList.remove('visible'), 3500);
  }
  function receivedTime(seconds) { return time(view.startTime + seconds * 1000); }
  function publish() {
    view = model.snapshot(); lastReceipt = Date.now(); receivedMono = performance.now(); render();
  }
  function render() {
    renderMetrics(); renderMap(); renderDetail(); renderBays(); renderBodies(); renderChart(); renderActivity(); renderGuide();
    $('#live-label').textContent = offline ? 'STALE' : paused ? 'PAUSED' : scene === 'capacity' ? 'GUIDED' : 'LIVE';
    $('#live-dot').className = 'live-dot' + (offline ? ' red' : paused || scene === 'capacity' ? ' amber' : '');
    $('#map-status').textContent = offline ? '현재 상태 미확인' : paused ? '시뮬레이터 일시정지' : scene === 'capacity' ? '단계 버튼으로 진행' : '스냅샷 500 ms';
    $('#offline-overlay').hidden = !offline;
    $('[data-scenario="offline"]').textContent = offline ? '재연결' : '통신 단절';
    $('#updated').textContent = '마지막 수신 ' + time(lastReceipt);
    $('#fresh-summary').textContent = offline ? '마지막 수신값' : paused ? '일시정지' : '수신 정상';
    $('#pause').textContent = paused ? '▶ 다시 시작' : 'Ⅱ 일시정지';
    $('#pause').disabled = scene === 'capacity';
    $$('.scenario-buttons button').forEach(b => { b.classList.toggle('active', b.dataset.scenario === (offline ? 'offline' : scene)); b.setAttribute('aria-pressed', String(b.classList.contains('active'))); });
    if (dialogBody && $('#body-dialog').open) renderBodyDialog();
  }
  function renderMetrics() {
    const recent = view.inspections.filter(i => i.seconds > view.seconds - 300), fail = recent.filter(i => i.result === 'FAIL').length;
    $('#total').textContent = fmt(view.inspections.length); $('#passed').textContent = fmt(view.inspections.filter(i => i.result === 'PASS').length);
    $('#defect').textContent = recent.length ? (100 * fail / recent.length).toFixed(1) : '—';
    $('#sample').textContent = `검사 ${recent.length} · 불량 ${fail}`;
    $('#quality-tag').textContent = recent.length ? fail / recent.length >= .1 ? '주의' : '양호' : '표본 없음';
    $('#quality-tag').className = 'badge ' + (recent.length && fail / recent.length >= .1 ? 'amber' : 'gray');
    const cells = Object.values(view.cells), running = cells.filter(c => c.state === 'RUNNING').length;
    $('#running').textContent = offline ? '—' : running;
    $('#cell-summary').textContent = `대기 ${cells.filter(c => c.state === 'IDLE').length} · 배출 대기 ${cells.filter(c => c.state === 'BLOCKED').length} · 정지 ${cells.filter(c => c.down).length}`;
    $('#moving').textContent = offline ? '—' : Object.values(view.vehicles).filter(v => v.kind === 'BODY' && v.phase === 'MOVING').length;
    const counts = Object.values(view.bays).map(b => b.counts);
    $('#buffer-summary').textContent = `대기 ${counts.reduce((n, c) => n + c.waiting, 0)} · 예약 ${counts.reduce((n, c) => n + c.reserved, 0)}`;
    const alarms = view.alarms.filter(a => !a.resolved);
    $('#alarm-count').textContent = alarms.length; $('#alarm-summary').textContent = offline ? '연결 단절 · 현재 상태 미확인' : alarms.length ? '미복구 ' + alarms.length + '건' : '활성 알람 없음';
    $('#nav-alarm').textContent = alarms.length; $('#nav-alarm').hidden = !alarms.length;
    $('#tab-count').textContent = alarms.length;
  }
  function mapTarget(kind, id, label, content, transform = '') {
    return `<g role="button" tabindex="0" data-map="${kind}" data-id="${esc(id)}" aria-label="${esc(label)}" ${transform ? `transform="${transform}"` : ''} class="map-target ${selected.kind === kind && selected.id === id ? 'selected' : ''}">${content}</g>`;
  }
  function renderMap() {
    const svg = $('#factory-map'), focus = document.activeElement;
    const focused = svg.contains(focus) ? { kind: focus.dataset.map, id: focus.dataset.id } : null;
    const filter = $('#cell-filter').value;
    let html = '<defs><pattern id="floor-grid" width="25" height="25" patternUnits="userSpaceOnUse"><path d="M25 0H0V25" fill="none" stroke="#dbe5f3" stroke-width=".5"/></pattern></defs><rect width="1000" height="435" fill="url(#floor-grid)"/><path d="M104 333H915" class="body-route"/><path d="M100 58H610V86" class="parts-route"/><text x="110" y="27" class="map-small">PARTS-IN → 부품 도크 · 차체 버퍼와 분리</text><rect x="591" y="78" width="39" height="15" rx="3" class="parts-dock"/><text x="638" y="90" class="map-small">부품 인계</text>';
    html += `<g class="boundary"><rect x="24" y="286" width="80" height="91" rx="10"/><text x="64" y="309">BODY-IN</text><text x="64" y="334" class="boundary-icon">↓</text><text x="64" y="360" class="map-small">차체 투입</text></g><g class="boundary"><rect x="915" y="293" width="70" height="48" rx="8"/><text x="950" y="313">GOOD</text><text x="950" y="331" class="map-small">양품 반출</text><rect x="915" y="350" width="70" height="48" rx="8"/><text x="950" y="370">HOLD</text><text x="950" y="388" class="map-small">불량 격리</text></g>`;
    FactoryDemo.CELL_IDS.forEach(id => {
      const c = view.cells[id], bay = view.bays[id], x = positions[id][0], b = view.bodies[c.bodyId];
      const dim = filter !== 'ALL' && filter !== id ? ' dimmed' : '';
      html += `<g class="cell-island${dim}"><path d="M${x} 281V333" class="body-route"/>`;
      html += mapTarget('cell', id, `${id} ${labels[c.state]} 상세`, `<rect width="180" height="110" rx="10" class="cell-shell ${tone(c.state)}"/><text x="15" y="25" class="cell-id">${id}</text><text x="165" y="25" text-anchor="end" class="state-text ${tone(c.state)}">${labels[c.state]}</text><text x="15" y="46" class="map-small">${c.name} · ${c.duration}초</text><text x="15" y="71" class="map-body">${b ? b.id : 'EMPTY · 다음 차체 대기'}</text><rect x="15" y="88" width="150" height="4" rx="2" fill="#dfeaff"/><rect x="15" y="88" width="${b ? Math.min(c.elapsed / c.duration, 1) * 150 : 0}" height="4" rx="2" class="progress ${tone(c.state)}"/>`, `translate(${x - 90},107)`);
      if (b) html += mapTarget('body', b.id, `${b.id} 가상 태그 상세`, '<rect width="160" height="27" rx="5" fill="transparent"/>', `translate(${x - 80},162)`);
      html += mapTarget('bay', id, `${bay.id} 버퍼 상세`, `<rect width="180" height="61" rx="8" class="bay-shell ${bay.counts.available ? '' : 'full'}"/><text x="10" y="19" class="map-small">BAY · ${bay.counts.waiting} 대기 + ${bay.counts.reserved} 예약</text><text x="170" y="19" text-anchor="end" class="state-text ${bay.counts.available ? 'mint' : 'amber'}">여유 ${bay.counts.available}</text>` + bay.slots.map((slot, i) => `<rect x="${10 + i * 55}" y="28" width="50" height="24" rx="4" class="map-slot ${slot.state.toLowerCase()}"/><text x="${35 + i * 55}" y="44" text-anchor="middle" class="slot-label">${slot.state === 'FREE' ? '빈 칸' : slot.state === 'RESERVED' ? '↘ 예약' : '#' + slot.bodyId.slice(-3)}</text>`).join(''), `translate(${x - 90},224)`);
      html += '</g>';
    });
    Object.values(view.vehicles).forEach(v => {
      const color = v.kind === 'PARTS' ? 'parts' : 'body';
      html += mapTarget('vehicle', v.id, `${v.id} ${labels[v.phase]} 상세`, `<text y="-23" text-anchor="middle" class="vehicle-id">${v.id}</text><rect x="-35" y="-17" width="70" height="34" rx="8" class="vehicle-shell ${color}"/><rect x="-40" y="-10" width="5" height="9" rx="2" fill="#7186a8"/><rect x="35" y="-10" width="5" height="9" rx="2" fill="#7186a8"/><rect x="-40" y="5" width="5" height="9" rx="2" fill="#7186a8"/><rect x="35" y="5" width="5" height="9" rx="2" fill="#7186a8"/><text y="5" text-anchor="middle" class="vehicle-cargo">${v.kind === 'PARTS' ? 'PARTS KIT' : v.bodyId ? '#' + v.bodyId.slice(-3) : 'EMPTY'}</text>`);
    });
    svg.innerHTML = html; updateVehiclePositions(0);
    if (focused) [...svg.querySelectorAll('[data-map]')].find(el => el.dataset.map === focused.kind && el.dataset.id === focused.id)?.focus({ preventScroll: true });
  }
  const lerp = (from, to, p) => [from[0] + (to[0] - from[0]) * p, from[1] + (to[1] - from[1]) * p];
  function updateVehiclePositions(extra) {
    Object.values(view.vehicles).forEach(v => {
      const p = Math.min((v.elapsed + extra) / (v.duration || 1), 1), source = positions[v.source] || home[v.id], destination = positions[v.destination] || home[v.id];
      let pos;
      if (v.kind === 'PARTS') pos = v.phase === 'TO_SUPPLY' ? lerp([115, 58], [570, 58], p) : v.phase === 'DELIVERING' ? [570, 58] : lerp([570, 58], [115, 58], p);
      else pos = v.phase === 'IDLE' ? home[v.id] : v.phase === 'TO_PICKUP' ? lerp(home[v.id], source, p) : v.phase === 'LOADING' ? source : v.phase === 'MOVING' ? lerp(source, destination, p) : v.phase === 'UNLOADING' ? destination : lerp(destination, home[v.id], p);
      const el = $(`[data-map="vehicle"][data-id="${v.id}"]`); if (el) el.setAttribute('transform', `translate(${pos[0]},${pos[1]})`);
    });
  }
  const field = (label, value) => `<div class="detail-field"><dt>${label}</dt><dd>${value}</dd></div>`;
  function renderDetail() {
    let eyebrow, title, state, fields, foot = '', description;
    if (selected.kind === 'cell') {
      const c = view.cells[selected.id], b = view.bodies[c.bodyId];
      eyebrow = 'WORK CELL'; title = c.id; state = c.state; description = c.name + ' · 작업 자리 1대';
      fields = field('현재 차체', bodyButton(c.bodyId)) + field('배출 조건', esc(c.reason ? labels[c.reason] : c.state === 'RUNNING' ? '작업 진행 중' : c.down ? '셀 복구 필요' : '다음 차체 대기')) +
        field('다음 공정', esc(b?.nextProcess || (c.id === 'QC-01' ? 'GOOD / HOLD' : c.id === 'ASM-01' ? 'ASM-02' : 'QC-01'))) + field('작업 시간', `${Math.min(c.elapsed, c.duration).toFixed(1)} / ${c.duration}초`);
      foot = `<div class="detail-progress"><span style="width:${b ? Math.min(c.elapsed / c.duration, 1) * 100 : 0}%"></span></div><button class="button wide" data-select-bay="${c.id}">진입 버퍼 · 슬롯 보기 ↗</button>`;
      if (c.down) foot += '<button class="button wide" id="recover-cell" ' + (offline ? 'disabled' : '') + '>ASM-02 복구</button>';
    } else if (selected.kind === 'bay') {
      const bay = view.bays[selected.id], n = bay.counts;
      eyebrow = 'PHYSICAL BUFFER'; title = bay.id; state = n.available ? 'IDLE' : 'BLOCKED'; description = '셀 진입로 / 임시 Parking Bay';
      fields = field('전체 슬롯 C', n.capacity + '칸') + field('현재 대기 W', n.waiting + '대') + field('도착 예약 R', n.reserved + '대') + field('남은 슬롯 A', `<strong>${n.available}칸</strong>`);
      foot = `<div class="formula">A = C − W − R<br><strong>${n.capacity} − ${n.waiting} − ${n.reserved} = ${n.available}</strong></div>` +
        bay.slots.map((slot, i) => `<div class="slot-detail"><span>S${i + 1} · ${slot.state === 'FREE' ? 'FREE' : slot.state === 'RESERVED' ? 'RESERVED' : 'OCCUPIED'}</span>${slot.bodyId ? bodyButton(slot.bodyId) : '<small>가용 슬롯</small>'}${slot.transportId ? `<small>${view.transports[slot.transportId].vehicleId} · ${view.transports[slot.transportId].status}</small>` : ''}</div>`).join('');
    } else {
      const v = view.vehicles[selected.id], t = view.transports[v.transportId];
      eyebrow = v.kind === 'PARTS' ? 'PARTS AMR' : 'BODY AGV'; title = v.id; state = v.phase; description = v.kind === 'PARTS' ? '부품 키트 전용 · 차체 슬롯 제외' : '차체 운반 · 1회 1대';
      fields = field('적재 차체', bodyButton(v.bodyId)) + field('배차 차체', t && !['COMPLETED', 'CANCELLED'].includes(t.status) ? bodyButton(t.bodyId) : '—') +
        field('출발 → 목적지', v.kind === 'PARTS' ? 'PARTS-IN → 부품 도크' : `${esc(v.source)} → ${esc(v.destination)}`) +
        field('예약 / 운송 ID', esc(t && t.status !== 'COMPLETED' ? t.id : null)) + field('부품 키트', esc(v.partsKitId)) + field('배터리', v.battery + '%');
      foot = `<p class="detail-note">${v.kind === 'PARTS' ? `부품 ${view.kitsDelivered}회 인계 · P0에서는 재고가 충분하다고 가정합니다.` : '예약은 픽업 전부터 유지됩니다. 도착 시 대기 슬롯으로 전환하고 차량은 복귀합니다.'}</p>`;
    }
    const focus = document.activeElement, focusKey = $('#detail-card').contains(focus) ? focus.dataset.body || focus.id || focus.dataset.selectBay : null;
    $('#detail-card').innerHTML = `<div class="detail-heading"><span class="eyebrow">${eyebrow}</span>${badge(state)}</div><h2>${title}</h2><p class="detail-description">${description}</p><div class="receipt-label">${offline ? '마지막 수신값 · 현재 상태 미확인' : '관측 시각 ' + time(lastReceipt)}</div><dl>${fields}</dl>${foot}<button class="text-button related-events" data-related="${selected.id}">관련 이벤트 보기 →</button>`;
    if (focusKey) [...$('#detail-card').querySelectorAll('button')].find(el => (el.dataset.body || el.id || el.dataset.selectBay) === focusKey)?.focus({ preventScroll: true });
  }
  function renderBays() {
    const host = $('#bay-grid'), focused = host.contains(document.activeElement) ? document.activeElement.dataset.bay : null;
    host.innerHTML = Object.values(view.bays).map(b => {
      const c = b.counts;
      return `<button class="bay-card ${c.available ? '' : 'full'} ${selected.kind === 'bay' && selected.id === b.cellId ? 'selected' : ''}" data-bay="${b.cellId}" aria-label="${b.id}: 대기 ${c.waiting}, 예약 ${c.reserved}, 여유 ${c.available}. 상세 보기"><div class="bay-card-head"><strong>${b.id}</strong><span>${c.available ? '신규 배차 가능' : '신규 배출 차단'} ↗</span></div><div class="bay-numbers"><span><b>${c.waiting}</b> 대기</span><i>+</i><span><b>${c.reserved}</b> 예약</span><i>/</i><span><b>${c.capacity}</b> 전체</span><em>여유 ${c.available}</em></div><div class="slots">${b.slots.map(slot => `<span class="slot ${slot.state.toLowerCase()}">${slot.state === 'FREE' ? 'FREE' : slot.state === 'RESERVED' ? '↘ RESERVED' : '● OCCUPIED'}</span>`).join('')}</div></button>`;
    }).join('');
    if (focused) host.querySelector(`[data-bay="${focused}"]`)?.focus({ preventScroll: true });
  }
  function renderBodies() {
    const active = Object.values(view.bodies).filter(b => b.locationType !== 'RESULT').slice(0, 6);
    const host = $('#body-list'), focused = host.contains(document.activeElement) ? document.activeElement.dataset.body : null;
    host.innerHTML = active.map(b => `<button class="body-card" data-body="${b.id}"><span class="body-card-tag">⌁ ${b.tagId}</span><strong>${b.id} <span>↗</span></strong><span>${esc(b.locationId)} <small>· ${labels[b.status]}</small></span></button>`).join('') || '<p class="empty-state">현재 실행의 모든 차체가 반출되었습니다. 초기화하면 새 실행을 시작합니다.</p>';
    if (focused) host.querySelector(`[data-body="${focused}"]`)?.focus({ preventScroll: true });
  }
  function renderGuide() {
    $('#scenario-guide').hidden = scene !== 'capacity';
    if (scene !== 'capacity') return;
    const step = view.capacityStep;
    $('#guide-title').textContent = ['① 대기 2 + 이동 예약 1 = 3 / 3 → 배출 차단', '② 차량 도착 → 대기 3 + 예약 0 = 3 / 3', '③ 셀 진입 → 1칸 반환 → 새 배차 1건 승인'][step];
    $('#guide-description').textContent = ['ASM-01은 작업을 마쳤지만 차체를 유지합니다. AGV-002가 비어 있어도 목적지 슬롯이 없으면 배출할 수 없습니다.', '도착한 차체가 예약 칸을 점유합니다. 여유는 계속 0이므로 ASM-01의 배출 차단도 유지됩니다.', 'ASM-02가 대기 차체 1대를 받아 여유 1칸이 생깁니다. 그 칸을 AGV-002가 예약하면 다시 여유 0. ASM-01 차체는 실제 픽업 전까지 셀에 남습니다.'][step];
    $('#capacity-step').textContent = ['예약 차량 도착시키기 →', '차체를 셀로 투입 · 배차 재개 →', '검증 완료 · 다시 보기 ↻'][step];
    $('#capacity-step').disabled = offline;
  }
  function renderChart() {
    const bins = Array.from({ length: 5 }, (_, i) => {
      const start = view.seconds - (5 - i) * 60, end = start + 60;
      const items = view.inspections.filter(x => x.seconds > start && x.seconds <= end);
      return { total: items.length, fail: items.filter(x => x.result === 'FAIL').length, label: i === 4 ? '최근 1분' : (5 - i) + '분 전' };
    });
    const max = Math.max(5, ...bins.map(b => b.total)), height = 105;
    $('#throughput').textContent = bins[4].total;
    $('#chart-note').textContent = view.inspections.some(i => i.fixture) ? '샘플 이력 + 새 검사 · 동일 5분 구간' : '검사 이벤트에서 집계';
    $('#production-chart').innerHTML = `<svg viewBox="0 0 500 150" aria-hidden="true"><path d="M28 16V121H483" fill="none" stroke="#dbe5f3"/><text x="22" y="24" text-anchor="end" class="chart-axis">${max}</text><text x="22" y="122" text-anchor="end" class="chart-axis">0</text>${bins.map((b, i) => `<rect x="${55 + i * 90}" y="${121 - height * b.total / max}" width="30" height="${height * b.total / max}" rx="3" fill="#245ac4"/><rect x="${87 + i * 90}" y="${121 - height * b.fail / max}" width="13" height="${height * b.fail / max}" rx="2" fill="#172b4d"/><text x="${76 + i * 90}" y="143" text-anchor="middle" class="chart-axis">${b.label}</text><text x="${68 + i * 90}" y="${115 - height * b.total / max}" text-anchor="middle" class="chart-axis">${b.total}</text>`).join('')}</svg>`;
    $('#production-chart').setAttribute('aria-label', bins.map(b => `${b.label} 검사 ${b.total}대, 불량 ${b.fail}대`).join('; '));
  }
  function renderActivity() {
    $$('.tabs button').forEach(b => { const on = b.dataset.tab === activeTab; b.classList.toggle('active', on); b.setAttribute('aria-selected', String(on)); b.tabIndex = on ? 0 : -1; });
    $('#activity-content').setAttribute('aria-labelledby', 'tab-' + activeTab);
    $('#event-filter').textContent = eventFilter ? '필터: ' + eventFilter : '차체 · 예약 · 이동 · 작업 이력';
    const focus = document.activeElement, ackFocus = $('#activity-content').contains(focus) ? focus.dataset.ack : null;
    if (activeTab === 'events') {
      const events = view.events.filter(e => !eventFilter || e.related.includes(eventFilter)).slice(0, 8);
      $('#activity-content').innerHTML = events.length ? events.map(e => `<div class="event-row"><time>${receivedTime(e.seconds)}</time><span class="event-kind">${esc(e.type)}</span><span>${esc(e.message)}</span></div>`).join('') : '<div class="empty-state">아직 기록이 없습니다. 작업과 이동이 발생하면 표시합니다.</div>';
    } else {
      $('#activity-content').innerHTML = `<p class="alarm-help">버퍼 만석과 가용 AGV 대기는 흐름 상태입니다. 셀 정지만 고장 알람으로 표시합니다.</p>` + (view.alarms.length ? view.alarms.map(a => `<div class="alarm-row"><span class="legend-dot ${a.resolved ? 'gray' : 'red'}"></span><div><strong>${esc(a.message)}</strong><small>${receivedTime(a.seconds)} · ${a.resolved ? '복구됨' : '미복구'} · ${a.acknowledged ? '확인 완료' : '미확인'}</small></div><button class="button" data-ack="${a.id}" ${a.acknowledged || offline ? 'disabled' : ''}>${a.acknowledged ? '확인 완료' : '확인'}</button></div>`).join('') : '<div class="empty-state">발생한 셀 고장 알람이 없습니다.</div>');
    }
    if (ackFocus) $('#activity-content').querySelector(`[data-ack="${ackFocus}"]`)?.focus({ preventScroll: true });
  }
  function renderBodyDialog() {
    const b = view.bodies[dialogBody];
    if (!b) return;
    const focusedVehicle = $('#body-dialog-content').contains(document.activeElement) ? document.activeElement.dataset.dialogVehicle : null;
    $('#body-dialog-title').textContent = b.id;
    const assigned = Object.values(view.transports).find(t => t.bodyId === b.id && ['ASSIGNED', 'IN_TRANSIT'].includes(t.status));
    $('#body-dialog-content').innerHTML = `<div class="tag-banner"><div><small>SMART TAG ID · 가상 식별자</small><strong>${b.tagId}</strong></div>${badge(b.status)}</div><p class="dialog-observed">${offline ? '통신 단절 · 마지막으로 관측한 상태' : '관측 시각 ' + time(lastReceipt)} · 차체 상태와 함께 태그 조회 정보 갱신</p><dl class="body-fields">${field('차체 ID', esc(b.id))}${field('모델 / 사양', esc(b.model + ' / ' + b.spec))}${field('현재 위치', esc(labels[b.locationType] + ' · ' + b.locationId))}${field('운반 차량', b.vehicleId ? `<button class="body-link" data-dialog-vehicle="${b.vehicleId}">${b.vehicleId} ↗</button>` : '없음')}${field('현재 공정', esc(b.currentProcess))}${field('완료 공정', esc(b.completedProcesses.join(' → ') || '없음'))}${field('다음 공정 / 목적지', esc(b.nextProcess))}${field('검사 결과', badge(b.inspection))}${field('배차 / 예약', assigned ? esc(assigned.id + ' · ' + assigned.vehicleId + ' → ' + assigned.destination) : '없음')}${field('마지막 상태 변경', receivedTime(b.updatedAt))}</dl><div class="dialog-history"><h3>이 차체의 이력</h3>${b.history.map(e => `<div><time>${receivedTime(e.seconds)}</time><span>${esc(e.message)}</span></div>`).join('')}</div><p class="detail-note">실물 RFID/UWB 리더가 없는 가상 태그입니다. 위치와 상태는 차체 시뮬레이션에서 갱신합니다.</p>`;
    if (focusedVehicle) $('#body-dialog-content').querySelector(`[data-dialog-vehicle="${focusedVehicle}"]`)?.focus({ preventScroll: true });
  }
  function openBody(id) {
    if (!view.bodies[id]) { toast('현재 수신 화면에 없는 차체입니다.'); return; }
    dialogBody = id; renderBodyDialog();
    if (!$('#body-dialog').open) $('#body-dialog').showModal();
  }
  function select(kind, id) {
    if (kind === 'body') { openBody(id); return; }
    selected = { kind, id }; renderMap(); renderDetail(); renderBays();
  }
  function startScene(next) {
    if (next === 'offline') {
      offline = !offline;
      if (!offline) publish(); else render();
      toast(offline ? '수신을 중단했습니다. 마지막 스냅샷을 유지합니다.' : '재연결 · 최신 스냅샷을 받았습니다.');
      return;
    }
    if ($('#body-dialog').open) $('#body-dialog').close();
    model = FactoryDemo.create(next); scene = next; offline = false; paused = false; eventFilter = null; accumulator = 0;
    selected = next === 'capacity' ? { kind: 'bay', id: 'ASM-02' } : { kind: 'cell', id: next === 'down' ? 'ASM-02' : 'ASM-01' };
    activeTab = next === 'down' ? 'alarms' : 'events';
    $('#search-result').textContent = ''; $('#tag-search').value = '';
    publish();
  }
  document.addEventListener('click', e => {
    const b = e.target.closest('button, [data-map]'); if (!b) return;
    if (b.dataset.body) openBody(b.dataset.body);
    else if (b.dataset.map) select(b.dataset.map, b.dataset.id);
    else if (b.dataset.bay || b.dataset.selectBay) select('bay', b.dataset.bay || b.dataset.selectBay);
    else if (b.dataset.scenario) startScene(b.dataset.scenario);
    else if (b.dataset.tab) { activeTab = b.dataset.tab; renderActivity(); }
    else if (b.dataset.ack && !offline) { model.acknowledge(b.dataset.ack); publish(); }
    else if (b.dataset.related) { eventFilter = b.dataset.related; activeTab = 'events'; renderActivity(); $('#activity-panel').scrollIntoView({ behavior: 'smooth', block: 'nearest' }); }
    else if (b.dataset.dialogVehicle) { $('#body-dialog').close(); select('vehicle', b.dataset.dialogVehicle); $('#detail-card').scrollIntoView({ behavior: 'smooth', block: 'nearest' }); }
    else if (b.dataset.nav) {
      $$('.rail-item').forEach(el => el.classList.toggle('active', el === b));
      if (b.dataset.nav === 'cells') select('cell', 'ASM-01');
      if (b.dataset.nav === 'logistics') select('vehicle', 'AGV-001');
      if (b.dataset.nav === 'alarms') { activeTab = 'alarms'; renderActivity(); }
      const target = b.dataset.nav === 'quality' ? '#trend-panel' : b.dataset.nav === 'alarms' ? '#activity-panel' : '#map-card';
      $(target).scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  });
  $('#pause').addEventListener('click', () => { paused = !paused; render(); });
  $('#reset').addEventListener('click', () => { startScene('normal'); toast('새 실행으로 초기화했습니다.'); });
  $('#cell-filter').addEventListener('change', renderMap);
  $('#show-alarms').addEventListener('click', () => { activeTab = 'alarms'; renderActivity(); $('#activity-panel').scrollIntoView({ behavior: 'smooth', block: 'center' }); });
  $('#all-events').addEventListener('click', () => { eventFilter = null; activeTab = 'events'; renderActivity(); });
  $('#capacity-step').addEventListener('click', () => { if (view.capacityStep === 2) startScene('capacity'); else { model.stepCapacity(); publish(); } });
  $('#detail-card').addEventListener('click', e => { if (e.target.id === 'recover-cell' && !offline) { model.setDown('ASM-02', false); publish(); toast('셀을 복구했습니다. 알람 확인 여부는 유지됩니다.'); } });
  function setExpanded(on) {
    $('#map-card').classList.toggle('expanded', on);
    $('#expand').setAttribute('aria-label', on ? '공장 맵 축소' : '공장 맵 확대'); $('#expand').setAttribute('aria-pressed', String(on));
  }
  $('#expand').addEventListener('click', () => setExpanded(!$('#map-card').classList.contains('expanded')));
  $('#close-body').addEventListener('click', () => $('#body-dialog').close());
  $('#body-dialog').addEventListener('close', () => { dialogBody = null; });
  $('#body-dialog').addEventListener('click', e => { if (e.target === $('#body-dialog')) { const r = e.target.getBoundingClientRect(); if (e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom) e.target.close(); } });
  $('#body-search').addEventListener('submit', e => {
    e.preventDefault(); const term = $('#tag-search').value.trim().toLowerCase();
    const b = Object.values(view.bodies).find(x => x.id.toLowerCase() === term || x.tagId.toLowerCase() === term);
    $('#search-result').textContent = b ? b.id + ' · 상세 창을 열었습니다.' : '일치하는 차체/태그가 없습니다. 현재 실행의 전체 ID를 입력해 주세요.';
    if (b) openBody(b.id);
  });
  document.addEventListener('keydown', e => {
    const map = e.target.closest?.('[data-map]');
    if (map && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); select(map.dataset.map, map.dataset.id); }
    if (e.key === 'Escape') setExpanded(false);
    if (e.target.matches('.tabs button') && ['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(e.key)) {
      e.preventDefault(); activeTab = activeTab === 'events' ? 'alarms' : 'events'; renderActivity(); $('#tab-' + activeTab).focus();
    }
  });
  function loop(now) {
    const dt = Math.min((now - lastTick) / 1000, .5); lastTick = now;
    if (!paused) {
      accumulator += dt;
      while (accumulator + 1e-8 >= .1) { model.tick(.1); accumulator -= .1; }
    } else accumulator = 0;
    if (!offline && now - lastPublish >= 500) { publish(); lastPublish = now; }
    // Never extrapolate positions while disconnected, paused, or in the guided fixture.
    const extra = !reducedMotion && !offline && !paused && scene !== 'capacity' ? Math.min((now - receivedMono) / 1000, .5) : 0;
    updateVehiclePositions(extra); $('#clock').textContent = time(Date.now());
    requestAnimationFrame(loop);
  }
  publish(); requestAnimationFrame(loop);
})();
