<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { vehicleFlag } from '../scene3d/status.js'
import { createFactoryScene } from '../scene3d/factory-scene.js'
const props = defineProps({ config: Object, view: Object, live: Boolean, statusLabel: String, showParts: { type: Boolean, default: true }, showcase: Boolean, active: { type: Boolean, default: true } })
const emit = defineEmits(['select', 'fallback'])
const host = ref(null), error = ref(''), ready = ref(false), labels = ref(true), routes = ref(true), entries = ref([]), selected = ref('')
const driving = ref(''), cameraMode = ref('third')
const vehicles = computed(() => (props.config?.vehicles ?? []).filter(v => props.showParts || v.kind === 'AGV'))
const driver = computed(() => props.view?.vehicles?.find(v => v.vehicleId === driving.value))
const driverStatus = computed(() => driver.value ? vehicleFlag(driver.value, props.view?.activeTransports ?? [], props.config, props.view?.equipment ?? []).detail : '관측 대기')
function available(id) { return props.view?.vehicles?.some(v => v.vehicleId === id) }
function drive(id, mode = cameraMode.value) {
  if (vehicles.value.find(v => v.vehicleId === id)?.kind === 'AMR') mode = 'third'
  if (scene?.drive(id, mode)) { driving.value = id; cameraMode.value = mode }
}
function overview(top = false) { driving.value = ''; top ? scene?.top() : scene?.reset() }
watch(driver, value => { if (driving.value && !value) overview() })
let scene
function destroy() { scene?.dispose(); scene = null; ready.value = false; entries.value = [] }
function initialize() {
  destroy(); error.value = ''; selected.value = ''; driving.value = ''
  if (!host.value || !props.config) return
  try {
    scene = createFactoryScene(host.value, props.config, {
      showParts: props.showParts, showcase: props.showcase,
      onSelect: item => { selected.value = item.id; emit('select', item) },
      onError: message => { error.value = message; ready.value = false },
    })
    scene.update(props.view, props.live)
    entries.value = [...scene.entries]
    scene.labels(labels.value); scene.routes(routes.value); scene.setActive(props.active)
    ready.value = true
  } catch (cause) {
    console.error('Factory 3D initialization failed', cause)
    destroy()
    error.value = '이 환경에서 3D 화면을 열지 못했습니다. 브라우저의 그래픽 가속을 확인하거나 2D 지도를 이용하세요.'
  }
}
watch(() => [props.config, props.showParts, props.showcase], initialize)
watch(() => [props.view, props.live], () => { scene?.update(props.view, props.live); if (scene) entries.value = [...scene.entries] })
watch(() => props.active, value => scene?.setActive(value))
watch(labels, value => scene?.labels(value))
watch(routes, value => scene?.routes(value))
onMounted(initialize)
onUnmounted(destroy)
</script>
<template>
  <section class="scene-shell" aria-label="3D 공장 관제">
    <div class="scene-topbar">
      <div class="scene-caption"><span class="scene-dot"></span><strong>공장 배치</strong><span class="scene-mode">{{showcase ? '디자인 미리보기' : (statusLabel || '관측값 대기')}}</span></div>
      <div class="scene-toggles"><label v-if="!driving"><input type="checkbox" v-model="labels" /> 이름</label><label><input type="checkbox" v-model="routes" /> 경로</label></div>
    </div>
    <div v-if="!showcase" class="driver-picker" aria-label="차량 추적 시점">
      <span>차량 시점</span><button :aria-pressed="!driving" @click="overview()" :disabled="!ready">전체 공장</button>
      <button v-for="vehicle in vehicles" :key="vehicle.vehicleId" :aria-pressed="driving===vehicle.vehicleId" :disabled="!ready || !available(vehicle.vehicleId)" @click="drive(vehicle.vehicleId)">{{vehicle.vehicleId}}</button>
      <div v-if="driving" class="view-modes" aria-label="차량 카메라 방식">
        <button :aria-pressed="cameraMode==='third'" @click="drive(driving, 'third')">3인칭 추적</button>
        <button v-if="driver?.kind==='AGV'" :aria-pressed="cameraMode==='first'" @click="drive(driving, 'first')">1인칭 전면</button>
      </div>
    </div>
    <div class="scene-stage">
      <div ref="host" class="scene-canvas" data-testid="factory-scene-3d"></div>
      <div v-if="!config && !error" class="scene-message" role="status">공장 배치 설정을 기다립니다.</div>
      <div v-if="error" class="scene-message" role="alert"><strong>3D 화면을 사용할 수 없습니다</strong><p>{{error}}</p><div><button @click="initialize">다시 불러오기</button><button @click="emit('fallback')">2D 지도 보기</button></div></div>
      <div v-if="ready && !driving" class="scene-corner"><span>{{showcase ? 'STATIC MODEL' : 'FACTORY / 01'}}</span><span>{{showcase ? '차량·차체는 배치 예시입니다' : config?.traffic ? '충돌 회피 적용 · 호박색 링은 양보 대기' : '과거 실행 · 충돌 규칙 미적용'}}</span></div>
      <div v-if="driving" class="driver-hud" aria-live="polite"><div><span>{{cameraMode==='third' ? '3인칭 추적 카메라' : '가상 전면 카메라'}}</span><strong>{{driving}}</strong><p>{{driverStatus}}</p><small>{{live ? '현재 관측값' : statusLabel || '마지막 관측값'}} · 적재 {{driver?.bodyId || driver?.partsKitId || '없음'}}</small></div><div class="driver-actions"><button v-if="cameraMode==='third'" @click="drive(driving, 'third')">시점 초기화</button><button @click="overview()">전체 공장으로 돌아가기</button></div></div>
      <div v-if="!driving" class="scene-compass" aria-hidden="true"><span>↑</span>공정 흐름 →</div>
    </div>

    <div v-if="!driving" class="scene-toolbar">
      <div class="camera-actions" aria-label="3D 카메라 조작">
        <button :disabled="!ready" @click="overview()">기본 시점</button><button :disabled="!ready" @click="overview(true)">평면 보기</button>
        <button :disabled="!ready" @click="scene?.rotate(-Math.PI / 8)" aria-label="왼쪽으로 회전">↶</button><button :disabled="!ready" @click="scene?.rotate(Math.PI / 8)" aria-label="오른쪽으로 회전">↷</button>
        <button :disabled="!ready" @click="scene?.zoom(1.2)" aria-label="확대">＋</button><button :disabled="!ready" @click="scene?.zoom(1 / 1.2)" aria-label="축소">−</button>
      </div>
      <label class="scene-object-picker">대상 살펴보기<select :value="selected" :disabled="!ready" @change="scene?.select($event.target.value)"><option value="">설비 · Bay · 차량 선택</option><option v-for="entry in entries" :key="entry.id" :value="entry.id">{{entry.title}}</option></select></label>
    </div>
    <p class="scene-help">{{driving ? (cameraMode==='third' ? '차량을 따라가는 3인칭 시점입니다. 드래그로 둘러보고 휠로 거리를 조절하세요. 시점 초기화로 뒤쪽 시점에 돌아갑니다.' : '차량의 위치와 방향을 따르는 가상 전면 카메라입니다. 관측이 멈추면 화면도 정지합니다.') : '드래그로 회전 · 휠로 확대 · 설비나 차량을 클릭하면 상세 정보를 볼 수 있습니다.'}}</p>
  </section>
</template>
<style scoped>
.scene-shell{border:1px solid #d4dfeb;border-radius:16px;overflow:hidden;background:#fff;min-width:0}
.scene-topbar{display:flex;align-items:center;justify-content:space-between;gap:16px;padding:17px 22px;border-bottom:1px solid #e1e8f0}
.scene-caption{display:flex;align-items:center;gap:9px;font-size:12px;flex-wrap:wrap}.scene-dot{width:7px;height:7px;background:#3467c7;border-radius:50%}.scene-mode{font-size:11px;color:#667a90;margin-left:7px}
.scene-toggles{display:flex;gap:15px;font-size:11px;color:#52687f;flex-shrink:0}.scene-toggles label{display:flex;align-items:center;gap:5px;cursor:pointer}.scene-toggles input{accent-color:#3467c7}
.scene-stage{position:relative;background:#f0f4f8}.scene-canvas{width:100%;height:clamp(360px,58vh,780px)}.scene-canvas :deep(canvas){display:block;width:100%;height:100%;touch-action:none}
.scene-corner{position:absolute;left:23px;top:20px;display:flex;flex-direction:column;gap:5px;pointer-events:none;color:#778a9d;font-size:10px}.scene-corner span:first-child{letter-spacing:2px;font-size:9px;font-weight:700}
.scene-compass{position:absolute;bottom:21px;right:23px;color:#8192a6;font-size:10px;pointer-events:none;display:flex;align-items:center;gap:9px}.scene-compass span{display:grid;place-items:center;border:1px solid #cbd6e2;border-radius:50%;width:28px;height:28px;font-size:16px}
.scene-toolbar{display:flex;align-items:center;justify-content:space-between;gap:16px;padding:15px 20px;border-top:1px solid #e1e8f0;flex-wrap:wrap}.camera-actions{display:flex;gap:6px;flex-wrap:wrap}.camera-actions button{background:#fff;border-color:#d4dfeb;font-size:11px;padding:8px 11px;min-width:34px}.camera-actions button:hover{background:#edf3fb}
.scene-object-picker{display:flex;gap:8px;align-items:center;font-size:10px;color:#657b91}.scene-object-picker select{font-size:11px;padding:8px;width:185px}.scene-help{font-size:10px;color:#72859a;margin:0;padding:0 20px 14px}
.scene-message{position:absolute;inset:0;display:flex;justify-content:center;align-items:center;flex-direction:column;padding:30px;text-align:center;background:#f0f4f8;color:#52687f;font-size:13px}.scene-message div{display:flex;gap:10px}.scene-message p{max-width:420px}
@media(max-width:760px){.scene-topbar{padding:14px;align-items:start}.scene-mode{margin-left:0;width:100%}.scene-canvas{height:430px}.scene-toolbar{padding:12px}.scene-help{padding:0 12px 13px}.scene-object-picker{width:100%;justify-content:space-between}.scene-object-picker select{flex:1;max-width:260px}.scene-corner{left:14px;top:15px}.scene-caption{max-width:210px}.scene-compass{right:14px}}
.driver-picker{display:flex;gap:6px;align-items:center;flex-wrap:wrap;padding:9px 16px;border-bottom:1px solid #e1e8f0}.driver-picker>span{font-size:11px;color:#6c7e91;margin-right:10px}.driver-picker button{background:#fff;border-color:#d5dfe9;font-size:11px;padding:7px 12px}.driver-picker button[aria-pressed=true]{background:#203955;border-color:#203955;color:#fff}.driver-hud{position:absolute;top:18px;left:20px;right:20px;display:flex;justify-content:space-between;gap:14px;align-items:start;pointer-events:none}.driver-hud>div:not(.driver-actions){background:#203955ed;color:#fff;border:1px solid #ffffff20;padding:14px 18px;border-radius:8px;min-width:210px;box-shadow:0 4px 16px #18263818}.driver-hud span{display:block;font-size:9px;color:#b6c8dc;letter-spacing:.8px}.driver-hud strong{font-size:18px;font-weight:600;display:block;margin-top:3px}.driver-hud p{font-size:12px;margin:5px 0}.driver-hud small{font-size:10px;color:#c2d0df}.driver-hud button{pointer-events:auto;background:#fff;font-size:11px;box-shadow:0 3px 12px #172b4d0a}.scene-toggles{font-size:11px}.scene-shell{border-radius:10px}
@media(max-width:600px){.driver-hud{top:12px;left:12px;right:12px}.driver-hud>div:not(.driver-actions){min-width:0;padding:10px 12px}.driver-hud button{max-width:106px;padding:8px}.driver-picker{padding:10px 12px}.driver-picker>span{width:100%}.scene-canvas{height:410px}}
.view-modes{display:flex;gap:6px;margin-left:auto;padding-left:12px;border-left:1px solid #d5dfe9}.driver-actions{display:flex;gap:6px;flex-wrap:wrap;justify-content:flex-end}.driver-actions button{pointer-events:auto}
@media(max-width:600px){.view-modes{margin-left:0;padding-left:0;border:0;width:100%}.driver-actions{max-width:120px}}
</style>
