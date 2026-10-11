<script setup>
import {onMounted,onUnmounted,ref,watch} from 'vue'
import {createAmrLayoutReview} from './scene3d/amr-layout-review.js'
const host=ref(null),mode=ref('all'),labels=ref(true),error=ref('')
let scene
onMounted(()=>{try{scene=createAmrLayoutReview(host.value)}catch(e){console.error(e);error.value='3D 시안을 불러오지 못했습니다. 그래픽 가속 설정을 확인해 주세요.'}})
onUnmounted(()=>scene?.dispose())
watch(labels,value=>scene?.labels(value))
function view(value){mode.value=value;scene?.view(value)}
</script>
<template>
 <main class="amr-review">
  <header><a href="/">← 공장 관제</a><span>배치 검토 · 미적용</span></header>
  <div class="amr-heading"><div><h1>ASM 뒤편 부품 공급 배치</h1><p>앞쪽은 차체 운송, 뒤쪽은 부품 공급. 기존 설비와 Bay 위치를 유지한 배치안입니다.</p></div><small>LAYOUT / 03</small></div>
  <section class="amr-drawing" aria-label="AMR 배치 미리보기">
   <div class="amr-tools"><div><button v-for="item in [{id:'all',name:'전체 배치'},{id:'rear',name:'부품 구역 확대'},{id:'top',name:'평면 배치'}]" :key="item.id" :aria-pressed="mode===item.id" @click="view(item.id)">{{item.name}}</button></div><label><input v-model="labels" type="checkbox" />이름 표시</label></div>
   <div ref="host" class="amr-canvas"></div><p v-if="error" role="alert">{{error}}</p>
   <div class="amr-legend"><span><i class="new"></i>제안하는 AMR 통로</span><span><i class="existing"></i>기존 AGV 통로</span><span>차량·부품은 배치 예시</span><small>드래그로 회전 · 휠로 확대</small></div>
  </section>
  <section class="amr-notes" aria-label="배치 설명"><article><span>01</span><div><h2>부품 창고와 대기 자리</h2><p>왼쪽 위에 배치합니다. AMR이 창고에서 키트를 받고, 공급 후 전용 자리로 복귀합니다.</p></div></article><article><span>02 · 03</span><div><h2>ASM별 후면 도킹</h2><p>ASM-01·02 뒤편에 키트 한 개를 놓는 공급대를 두고, AMR 정차 지점을 통로 쪽에 마련했습니다.</p></div></article><article><span>동선</span><div><h2>차체 통로와 분리</h2><p>위쪽 가로 통로에서 각 공급대로 진입합니다. QC 앞과 기존 Bay 사이로 AMR이 지나가지 않는 안입니다.</p></div></article></section>
  <footer>위치와 간격을 검토하는 정적 시안입니다. 실제 부품 소비·재보급·배차 규칙과 메인 관제에는 아직 적용하지 않았습니다.</footer>
 </main>
</template>
<style scoped>
.amr-review{max-width:1700px;margin:auto;padding:20px 32px;color:#263b50}.amr-review header{display:flex;justify-content:space-between;align-items:center;border-bottom:1px solid #e1e8ef;padding:0 0 16px;font-size:11px}.amr-review header a{color:#59728d;text-decoration:none}.amr-review header>span{color:#7b6746;background:#f9f4e9;border:1px solid #e5d9be;padding:4px 10px;border-radius:5px}.amr-heading{display:flex;justify-content:space-between;align-items:center;margin:20px 0}.amr-heading h1{font-size:24px;letter-spacing:-.6px;margin:0 0 7px;font-weight:650}.amr-heading p{font-size:12px;color:#74869a;margin:0}.amr-heading small{font-size:9px;letter-spacing:1.5px;color:#8a9aaa}.amr-drawing{border:1px solid #dbe4ed;border-radius:10px;overflow:hidden;background:#fff}.amr-tools{display:flex;justify-content:space-between;align-items:center;padding:12px 16px}.amr-tools>div{display:flex;gap:6px}.amr-tools button{font-size:11px;padding:7px 12px;border-radius:5px;background:#fff;border-color:#d7e1eb;color:#667c93}.amr-tools button[aria-pressed=true]{background:#203955;border-color:#203955;color:white}.amr-tools label{display:flex;align-items:center;gap:5px;font-size:11px;color:#718397}.amr-canvas{height:clamp(430px,61vh,740px);background:#f0f4f8}.amr-canvas:deep(canvas){display:block;width:100%;height:100%;touch-action:none}.amr-legend{display:flex;align-items:center;gap:24px;padding:12px 16px;font-size:10px;color:#71879a;flex-wrap:wrap}.amr-legend>span{display:flex;align-items:center;gap:7px}.amr-legend i{width:18px;border-top:3px solid #438f92}.amr-legend i.existing{border-color:#7b99c4}.amr-legend small{margin-left:auto;font-size:10px}.amr-notes{display:grid;grid-template-columns:repeat(3,1fr);gap:28px;margin:20px 0}.amr-notes article{display:flex;gap:13px}.amr-notes article>span{font-size:10px;color:#438185;padding-top:3px;white-space:nowrap}.amr-notes h2{font-size:13px;margin:0 0 6px;font-weight:600}.amr-notes p{font-size:11px;line-height:1.8;color:#7e8ea1;margin:0;max-width:360px}.amr-review footer{font-size:10px;color:#8a9aab;border-color:#e4ebf2;margin-top:18px;padding-top:14px}
@media(max-width:700px){.amr-review{padding:16px 12px}.amr-heading h1{font-size:20px}.amr-heading small{display:none}.amr-heading p{font-size:11px;line-height:1.8}.amr-notes{grid-template-columns:1fr;gap:16px}.amr-tools{padding:10px;gap:6px}.amr-tools button{padding:7px 9px;font-size:10px}.amr-tools label{font-size:10px}.amr-canvas{height:440px}.amr-legend{gap:12px}.amr-legend small{display:none}}
</style>
