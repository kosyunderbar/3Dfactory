import * as T from 'three'
import {OrbitControls} from 'three/addons/controls/OrbitControls.js'
import {RoomEnvironment} from 'three/addons/environments/RoomEnvironment.js'
import baseline from './amr-review-baseline.json'
import {box,cellModel,vehicleModel,storageModel,label,disposeTree} from './models.js'
import {block,lettering,colors} from './equipment-models.js'
import {solidPosition} from './motion.js'
import {toWorld,modelScale} from './coordinates.js'
import {layoutStatusLabels} from './label-layout.js'

// Design coordinates only. Never imported by the live scene or simulator.
export const proposal={
 bounds:{minX:-160,maxX:880,minY:-300,maxY:700},
 store:{x:-87.5,y:-140},storeDock:{x:0,y:-140},parking:{x:-90,y:-240},
 docks:[{id:'PARTS-ASM-01',x:150,y:-80},{id:'PARTS-ASM-02',x:350,y:-80}],
 branches:[[[0,-140],[0,-220],[350,-220]],[[150,-220],[150,-140]],[[350,-220],[350,-140]],[[-90,-240],[0,-240],[0,-220]]],
}
export function createAmrLayoutReview(host){
 const scene=new T.Scene();scene.background=new T.Color(0xf0f4f8)
 const renderer=new T.WebGLRenderer({antialias:true});renderer.setPixelRatio(Math.min(devicePixelRatio||1,2));renderer.shadowMap.enabled=true;renderer.shadowMap.type=T.PCFShadowMap;renderer.toneMapping=T.ACESFilmicToneMapping
 host.appendChild(renderer.domElement);renderer.domElement.setAttribute('role','img');renderer.domElement.setAttribute('aria-label','AMR 후면 부품 공급 배치 시안. 실제 차량 위치가 아닌 정적 배치 예시입니다.')
 const pmrem=new T.PMREMGenerator(renderer),room=new RoomEnvironment(),env=pmrem.fromScene(room,.04);scene.environment=env.texture;scene.environmentIntensity=.4;room.dispose();pmrem.dispose()
 const camera=new T.OrthographicCamera(-50,50,35,-35,.1,500),controls=new OrbitControls(camera,renderer.domElement)
 controls.minZoom=.6;controls.maxZoom=4;controls.maxPolarAngle=Math.PI*.46;controls.enableDamping=false
 const labels=new T.Group();scene.add(labels)
 const scale=modelScale(baseline),teal=0x438f92,blue=0x7b99c4
 let frame=0,disposed=false,viewMode='all',labelVisible=true
 function put(g,x,y){const p=toWorld({x,y});g.position.set(p.x,0,p.z);g.scale.setScalar(scale);scene.add(g);return g}
 function caption(text,x,y,h=2,width=6,color='#50677f',bg='#ffffff'){
  const p=toWorld({x,y});return label(labels,text,p.x,h,p.z,{width,color,background:bg,minScreenWidth:100,maxScreenWidth:128})
 }
 function segment(a,b,color,width=.12,height=.024){
  const pa=toWorld({x:a[0],y:a[1]}),pb=toWorld({x:b[0],y:b[1]});const line=box(scene,Math.hypot(pb.x-pa.x,pb.z-pa.z),.013,width,(pa.x+pb.x)/2,height,(pa.z+pb.z)/2,color)
  line.rotation.y=-Math.atan2(pb.z-pa.z,pb.x-pa.x);line.castShadow=false
 }
 function pad(x,y,w,d,color){const p=toWorld({x,y});const m=box(scene,w,.017,d,p.x,.017,p.z,color);m.castShadow=false;return m}
 const b=proposal.bounds,cx=(b.minX+b.maxX)*.045,cz=(b.minY+b.maxY)*.045,w=(b.maxX-b.minX)*.09,d=(b.maxY-b.minY)*.09
 box(scene,w,.3,d,cx,-.2,cz,0xdce5ee);box(scene,w-.12,.025,d-.12,cx,-.032,cz,0xf5f7fa).castShadow=false
 for(let x=b.minX+10;x<b.maxX;x+=40)segment([x,b.minY],[x,b.maxY],0xe1e7ee,.013,-.01)
 for(let y=b.minY+10;y<b.maxY;y+=40)segment([b.minX,y],[b.maxX,y],0xe1e7ee,.013,-.01)
 // Rear service area is visibly distinct; all original body equipment stays put.
 pad(180,-162,61.2,21.5,0xe3f0ef)
 for(const y of [-281,-43])segment([-160,y],[520,y],0xb0cece,.05,.03)
 for(const path of proposal.branches)for(let i=1;i<path.length;i++){
  segment(path[i-1],path[i],0xcce1df,5.8,.031)
  segment(path[i-1],path[i],teal,.16,.045)
 }
 const guide=lettering(scene,'AMR  /  PARTS SUPPLY',[18,.06,-24],14,.58,'#438185','#e3f0ef');guide.rotation.x=-Math.PI/2
 const seen=new Set()
 for(const lane of baseline.traffic.lanes){
  const a=lane.start,b=lane.end
  const front=a.y>=70 && b.y>=70 && Math.max(a.y,b.y)<=340
  const outer=(a.x===845 && b.x===845) || (a.y===650 && b.y===650)
  if(!front && !outer)continue
  const key=[`${a.x},${a.y}`,`${b.x},${b.y}`].sort().join(':');if(seen.has(key))continue;seen.add(key)
  segment([a.x,a.y],[b.x,b.y],blue,.09,.038)
 }
 for(const cell of baseline.equipment){
  const location=baseline.locations.find(l=>l.locationId===cell.cellId),p=solidPosition(baseline,location)
  put(cellModel(cell.cellId.startsWith('QC'),cell.cellId),p.x,p.y)
  caption(cell.cellId,p.x,p.y+48,1.3,5.7)
 }
 for(const bay of baseline.buffers){
  const loc=baseline.locations.find(l=>l.locationId===bay.bufferId),p=solidPosition(baseline,loc),g=new T.Group()
  for(let i=0;i<bay.capacity;i++){
   const z=(i-(bay.capacity-1)/2)*1.55
   block(g,[3.2,.08,1.48],[0,.06,z],0xe5edf5)
   for(const x of [-1.59,1.59])block(g,[.035,.04,1.48],[x,.12,z],colors.steel,0)
   for(const dz of [-.74,.74])block(g,[3.2,.04,.035],[0,.12,z+dz],colors.steel,0)
  }
  put(g,p.x,p.y);caption(bay.bufferId,p.x,p.y+56,.6,6.8)
 }
 for(const loc of baseline.locations.filter(l=>['INPUT','RESULT'].includes(l.locationType))){
  const p=solidPosition(baseline,loc),g=storageModel(loc.locationId);block(g,[4.6,.06,4.2],[0,.02,0],loc.locationId==='HOLD'?0xf0e7d8:0xe1eaf5)
  put(g,p.x,p.y);caption(loc.locationId,p.x,p.y-30,1.4,5)
 }
 const rack=storageModel('PARTS-STORE',true);put(rack,proposal.store.x,proposal.store.y)
 caption('01  부품 창고',-87.5,-113,4.5,7,'#326c70')
 const park=put(new T.Group(),proposal.parking.x,proposal.parking.y)
 block(park,[4.2,.035,2.65],[0,.015,0],0xc5dedb);for(const z of [-1.33,1.33])block(park,[4.2,.025,.055],[0,.05,z],teal,0)
 block(park,[.22,.55,1.2],[-2.24,.28,0],colors.navy)
 caption('AMR 대기 · 복귀',-90,-270,.8,7,'#326c70')
 put(vehicleModel(true,'AMR-001'),0,-220)
 const amrLabel=caption('AMR-001 · 배치 예시',0,-220,1.5,8,'#326c70')
 amrLabel.userData.vehicleEnvelope={radius:2.2*scale,halfHeight:1.15*scale}
 for(const [index,dock] of proposal.docks.entries()){
  const g=new T.Group();block(g,[3.6,.12,2.5],[0,.07,0],0xc6deda)
  for(const x of [-1.35,1.35])for(const z of [-.85,.85])block(g,[.15,.75,.15],[x,.47,z],colors.navy)
  block(g,[3.25,.12,2.1],[0,.9,0],colors.steel)
  block(g,[2.3,.65,1.35],[0,1.285,0],0xdce7f2);block(g,[2.34,.06,1.4],[0,1.64,0],colors.steel)
  lettering(g,'PARTS / 1 KIT',[0,1.32, .685],1.5,.22)
  put(g,dock.x,dock.y)
  const text=caption(`0${index+2}  ${dock.id}`,dock.x,dock.y,4.1,9,'#326c70','#f4fbfa')
  text.userData.planAnchor=text.position.clone()
  // Dock stop marker ends before the rack. Dashed continuation denotes planned feed to ASM.
  segment([dock.x-22,-140],[dock.x+22,-140],teal,.1,.06)
  for(let y=-53;y<-24;y+=8)segment([dock.x,y],[dock.x,y+4],0xa6b9ba,.08,.05)
 }
 for(const [i,y] of [260,420].entries())put(vehicleModel(false,`AGV-00${i+1}`),-90,y)
 caption('기존 AGV · 차체 통로',320,240,.3,10,'#617ea3','#f4f7fc')
 scene.add(new T.HemisphereLight(0xffffff,0xb8c6d7,1.8))
 const sun=new T.DirectionalLight(0xffffff,2.3);sun.position.set(0,65,30);sun.castShadow=true;sun.shadow.mapSize.set(2048,2048);Object.assign(sun.shadow.camera,{left:-65,right:65,top:65,bottom:-65,near:1,far:160});sun.shadow.normalBias=.035;scene.add(sun)
 function render(){frame=0;if(disposed||document.hidden)return;camera.updateMatrixWorld();labels.visible=labelVisible;if(labelVisible)layoutStatusLabels(labels,camera,host.clientWidth,host.clientHeight);renderer.render(scene,camera)}
 function invalidate(){if(!disposed&&!frame)frame=requestAnimationFrame(render)}
 function fit(kind=viewMode){
  viewMode=kind
  for(const text of labels.children)if(text.userData.planAnchor){text.userData.labelAnchor.copy(text.userData.planAnchor);if(kind==='top')text.userData.labelAnchor.z+=3.4}
  const r=kind==='rear'?{minX:-160,maxX:600,minY:-295,maxY:130}:b
  const x=(r.minX+r.maxX)*.045,z=(r.minY+r.maxY)*.045
  controls.target.set(x,0,z);camera.position.set(x+(kind==='top'?0:12),kind==='top'?95:65,z+(kind==='top'?.01:85));camera.lookAt(controls.target);camera.updateMatrixWorld()
  let hx=0,hy=0;for(const px of [r.minX,r.maxX])for(const pz of [r.minY,r.maxY])for(const py of [0,7]){const p=new T.Vector3(px*.09,py,pz*.09).applyMatrix4(camera.matrixWorldInverse);hx=Math.max(hx,Math.abs(p.x));hy=Math.max(hy,Math.abs(p.y))}
  const aspect=host.clientWidth/Math.max(1,host.clientHeight),h=Math.max(hy,hx/aspect)*1.055
  camera.left=-h*aspect;camera.right=h*aspect;camera.top=h;camera.bottom=-h;camera.zoom=1;camera.updateProjectionMatrix();controls.update();invalidate()
 }
 function resize(){if(!host.clientWidth||!host.clientHeight)return;renderer.setSize(host.clientWidth,host.clientHeight);fit()}
 controls.addEventListener('change',invalidate);document.addEventListener('visibilitychange',invalidate)
 const observer=new ResizeObserver(resize);observer.observe(host);resize()
 return {view:fit,labels(value){labelVisible=value;invalidate()},dispose(){disposed=true;cancelAnimationFrame(frame);observer.disconnect();controls.dispose();document.removeEventListener('visibilitychange',invalidate);disposeTree(scene);env.dispose();renderer.dispose();renderer.domElement.remove()}}
}
