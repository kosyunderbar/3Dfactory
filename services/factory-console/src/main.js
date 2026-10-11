import { createApp } from 'vue'
import './style.css'

// Review mode never creates a live feed or a simulation run.
const preview = new URLSearchParams(location.search).get('preview')
const review = preview === '3d'
const equipment = preview === 'equipment'
const amr = preview === 'amr'
if (amr) document.title = 'AMR 후면 공급 · 배치 검토'
if (equipment) document.title = 'Factory 3D · 설비 디테일 시안'
if (review) document.title = 'Factory 3D · 1차 디자인 확인'
const { default: App } = await (amr ? import('./AmrLayoutReview.vue') : equipment ? import('./EquipmentReview.vue') : review ? import('./SceneReview.vue') : import('./App.vue'))
createApp(App).mount('#app')
