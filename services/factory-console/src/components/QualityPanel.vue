<script setup>
import {computed,onMounted,onUnmounted,ref,watch,nextTick} from 'vue'
import * as echarts from 'echarts/core'
import {BarChart} from 'echarts/charts'
import {GridComponent,TooltipComponent,LegendComponent,AriaComponent} from 'echarts/components'
import {SVGRenderer} from 'echarts/renderers'
import {ScopedQueries,apiPath} from '../resources.js'
import {periodWindow,date,percent} from '../presentation.js'
import {measureTask} from '../measurement.js'
echarts.use([BarChart,GridComponent,TooltipComponent,LegendComponent,AriaComponent,SVGRenderer])
const props=defineProps({run:String,view:Object})
const period=ref(5),busy=ref(false),result=ref(null),error=ref(''),host=ref(null)
const queries=new ScopedQueries();let chart,observer,timer,context='',requestVersion=0
const rows=computed(()=>result.value?.trends.buckets ?? [])
async function load(){
 const run=props.run,epoch=props.view?.serverEpoch,window=periodWindow(props.view?.viewAsOfAt,Number(period.value))
 if(!run || !epoch || !window)return
 const ticket=++requestVersion;busy.value=true;error.value=''
 try{
  const values=await queries.group('quality',run,[{path:apiPath(run,'quality',window)},{path:apiPath(run,'trends',{...window,bucketMs:60000})}],values=>values.every(v=>v.window.start===window.from && v.window.end===window.to) && Array.isArray(values[1].buckets))
  if(values && ticket===requestVersion){result.value={quality:values[0],trends:values[1]};await nextTick();draw()}
 }catch{if(ticket===requestVersion)error.value='품질 조회에 실패했습니다. 마지막 조회값과 기간을 확인하세요.'}
 finally{if(ticket===requestVersion)busy.value=false}
}
function draw(){if(!chart)return;measureTask('echarts-set-option',props.run,()=>chart.setOption({animation:false,aria:{enabled:true,label:{description:result.value ? `동일 기간의 검사 ${result.value.quality.quality.inspectedCount}건, PASS ${result.value.quality.quality.passCount}건, FAIL ${result.value.quality.quality.failCount}건, 불량률 ${percent(result.value.quality.quality.failRate)}. 시간별 수치는 아래 표에서 확인할 수 있습니다.` : '검사 집계를 기다립니다.'}},color:['#315db2','#102950'],tooltip:{trigger:'axis',renderMode:'richText'},legend:{top:0,data:['PASS','FAIL'],textStyle:{color:'#172b4d'}},grid:{left:42,right:18,top:38,bottom:30},xAxis:{type:'category',data:rows.value.map(row=>new Date(row.start).toLocaleTimeString('ko-KR',{hour:'2-digit',minute:'2-digit'})),axisLabel:{color:'#475b7a'}},yAxis:{type:'value',minInterval:1,axisLabel:{color:'#475b7a'},splitLine:{lineStyle:{color:'#e6edf7'}}},series:['PASS','FAIL'].map((name,index)=>({name,type:'bar',stack:'inspection',data:rows.value.map(row=>row.quality[index ? 'failCount':'passCount'])}))},true))}
watch(()=>[props.run,props.view?.serverEpoch],([run,epoch])=>{
 const next=`${run}:${epoch}`;if(next===context)return;context=next;queries.reset(next);requestVersion++;busy.value=false;result.value=null;error.value='';draw();load()
},{immediate:true})
watch(period,()=>{result.value=null;draw();load()})
onMounted(()=>{chart=echarts.init(host.value,null,{renderer:'svg'});observer=new ResizeObserver(()=>chart.resize());observer.observe(host.value);draw();timer=setInterval(()=>{if(!busy.value && props.view)load()},10000)})
onUnmounted(()=>{requestVersion++;queries.close();clearInterval(timer);observer?.disconnect();chart?.dispose()})
</script>
<template>
 <section class="panel" aria-labelledby="quality-title"><div class="panel-head"><div><p class="eyebrow">QUALITY</p><h2 id="quality-title">검사 결과와 품질 추이</h2></div><div class="controls"><label>조회 기간<select v-model="period" aria-label="품질 조회 기간"><option :value="5">최근 5분</option><option :value="15">최근 15분</option><option :value="60">최근 1시간</option></select></label><button @click="load" :disabled="busy || !view">{{busy ? '조회 중…' : '품질 새로고침'}}</button></div></div>
  <p v-if="error" class="notice" role="status">{{error}}</p>
  <dl class="quality-metrics" data-testid="quality-metrics"><div><dt>검사</dt><dd>{{result?.quality.quality.inspectedCount ?? '—'}}<small>건</small></dd></div><div><dt>PASS</dt><dd>{{result?.quality.quality.passCount ?? '—'}}<small>건</small></dd></div><div><dt>FAIL</dt><dd>{{result?.quality.quality.failCount ?? '—'}}<small>건</small></dd></div><div><dt>불량률</dt><dd>{{percent(result?.quality.quality.failRate)}}</dd></div></dl>
  <p class="small" v-if="result">{{date(result.quality.window.start)}} ~ {{date(result.quality.window.end)}} · 끝 시각 미포함 · 동일 기간의 검사 사실 기준</p><p v-else class="small">기간의 검사 집계를 기다립니다. 검사 0건의 불량률은 ‘—’입니다.</p>
  <div ref="host" class="quality-chart" aria-label="PASS/FAIL 시간별 검사 수 차트" data-testid="quality-chart"></div>
  <details v-if="result"><summary>차트 수치를 표로 보기</summary><div class="table-scroll"><table><caption>같은 기간의 시간별 검사 결과</caption><thead><tr><th>시작</th><th>종료</th><th>검사</th><th>PASS</th><th>FAIL</th><th>불량률</th></tr></thead><tbody><tr v-for="row in rows" :key="row.start"><td>{{date(row.start)}}</td><td>{{date(row.end)}}</td><td>{{row.quality.inspectedCount}}</td><td>{{row.quality.passCount}}</td><td>{{row.quality.failCount}}</td><td>{{percent(row.quality.failRate)}}</td></tr></tbody></table></div></details>
 </section>
</template>
