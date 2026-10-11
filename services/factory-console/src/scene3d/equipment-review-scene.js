import * as T from 'three'
import { OrbitControls } from 'three/addons/controls/OrbitControls.js'
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js'
import { block,lettering,detailedAgv,detailedAssembly,detailedCargo,colors } from './equipment-models.js'

export const stages=[{name:'접안',at:0,end:4,description:'전면 센서를 향해 전진하고, 이송 레일에 정렬합니다.'},{name:'차체 인계',at:4,end:9,description:'같은 높이의 롤러를 따라 차체와 운반 팔레트가 지그로 이동합니다.'},{name:'고정 · 조립',at:9,end:18,description:'클램프로 차체를 고정하고 두 로봇팔이 작업합니다.'},{name:'회수',at:18,end:25,description:'고정을 해제한 뒤 팔레트가 AGV 적재부로 돌아옵니다.'}]
const smooth=t=>{t=T.MathUtils.clamp(t,0,1);return t*t*(3-2*t)}
export function createEquipmentReview(host,onProgress,onError){
 const scene=new T.Scene();scene.background=new T.Color(0xf0f4f8)
 const renderer=new T.WebGLRenderer({antialias:true});renderer.setPixelRatio(Math.min(devicePixelRatio||1,2));renderer.shadowMap.enabled=true;renderer.shadowMap.type=T.PCFShadowMap;renderer.toneMapping=T.ACESFilmicToneMapping;renderer.toneMappingExposure=1.05
 host.appendChild(renderer.domElement);renderer.domElement.setAttribute('role','img');renderer.domElement.setAttribute('aria-label','AGV와 ASM-01 상세 모델. 드래그로 회전하고 휠로 확대합니다.')
 const pmrem=new T.PMREMGenerator(renderer),room=new RoomEnvironment();const environment=pmrem.fromScene(room,.04);scene.environment=environment.texture;scene.environmentIntensity=.45;room.dispose();pmrem.dispose()
 const camera=new T.PerspectiveCamera(35,1,.1,100);const controls=new OrbitControls(camera,renderer.domElement);controls.minDistance=5;controls.maxDistance=32;controls.maxPolarAngle=Math.PI*.46;controls.enableDamping=false
 const agv=detailedAgv(),assembly=detailedAssembly(),cargo=detailedCargo();assembly.group.position.x=2.2;scene.add(agv.group,assembly.group,cargo)
 block(scene,[17,.2,10.2],[-.35,-.16,0],0xe0e7ee,.08);block(scene,[16.94,.025,10.14],[-.35,-.045,0],0xf1f4f7,.015)
 for(let x=-8;x<8;x++)block(scene,[.012,.006,10.1],[x,-.028,0],0xdde4eb,0)
 for(let z=-5;z<=5;z++)block(scene,[16.9,.006,.012],[-.35,-.028,z],0xdde4eb,0)
 for(const z of [-3.05,3.05])block(scene,[6.8,.012,.045],[2.2,-.003,z],0x88a3bf,0)
 for(const x of [-1.2,5.6])block(scene,[.045,.012,6.14],[x,-.003,0],0x88a3bf,0)
 for(const z of [-1.25,1.25])for(let x=-7.4;x<-1.35;x+=.7)block(scene,[.36,.015,.045],[x,.002,z],0x90a9c7,0)
 for(let x=-.3;x<4.8;x+=.36){const stripe=block(scene,[.14,.014,.23],[x,.002,2.88],colors.amber,0);stripe.rotation.y=-.5}
 const fl=lettering(scene,'02  /  AGV DOCK',[-4,.01,2.15],2.4,.33,'#6883a0','#f1f4f7');fl.rotation.x=-Math.PI/2
 const sl=lettering(scene,'ASM–01   /   ASSEMBLY',[2.2,.013,-3.55],3.5,.35,'#6883a0','#f1f4f7');sl.rotation.x=-Math.PI/2
 scene.add(new T.HemisphereLight(0xf5f9ff,0x8995a3,1.7))
 const key=new T.DirectionalLight(0xfffaf3,3.1);key.position.set(-3,12,8);key.castShadow=true;key.shadow.mapSize.set(2048,2048);Object.assign(key.shadow.camera,{left:-11,right:11,top:9,bottom:-9,near:1,far:35});key.shadow.normalBias=.025;key.shadow.bias=-.0001;key.shadow.radius=3;scene.add(key)
 const rim=new T.DirectionalLight(0xb9d4ff,1.3);rim.position.set(3,8,-6);scene.add(rim)
 let elapsed=0,playing=false,frame=0,last=0,disposed=false,noticeAt=-1
 function apply(){
  const dock=-2.4;const drive=smooth(elapsed/4);agv.group.position.x=T.MathUtils.lerp(-6.3,dock,drive)
  let transfer=elapsed<9?smooth((elapsed-4)/5):elapsed<18?1:1-smooth((elapsed-20)/5)
  cargo.position.set(T.MathUtils.lerp(agv.group.position.x,2.2,transfer),1.065,0)
  const work=smooth((elapsed-9)/1.5)*(1-smooth((elapsed-18)/2));assembly.pose(work,elapsed*1.35)
  agv.wheels.forEach(w=>w.rotation.z=-(agv.group.position.x+6.3)/.255)
  const stage=Math.min(3,stages.findIndex(s=>elapsed<s.end)===-1?3:stages.findIndex(s=>elapsed<s.end))
  if(Math.abs(elapsed-noticeAt)>.08 || !playing){noticeAt=elapsed;onProgress({elapsed,playing,stage})}
 }
 function render(){frame=0;if(disposed)return;renderer.render(scene,camera)}
 function invalidate(){if(!frame && !disposed)frame=requestAnimationFrame(loop)}
 function loop(now){frame=0;if(disposed)return;if(playing && !document.hidden){elapsed=Math.min(25,elapsed+(last?Math.min((now-last)/1000,.1):0));if(elapsed===25)playing=false}last=now;apply();render();if(playing && !document.hidden)invalidate()}
 function view(kind='all'){
  const target=kind==='agv'?new T.Vector3(agv.group.position.x,.7,0):kind==='asm'?new T.Vector3(2.2,1,0):new T.Vector3(-.5,.5,0)
  controls.target.copy(target);camera.position.copy(target).add(kind==='top'?new T.Vector3(0,19,.01):kind==='all'?new T.Vector3(10,10,14):new T.Vector3(5.3,4.5,6.4));camera.lookAt(target);controls.update();invalidate()
 }
 function resize(){const w=host.clientWidth,h=host.clientHeight;if(!w||!h)return;renderer.setSize(w,h);camera.aspect=w/h;camera.updateProjectionMatrix();invalidate()}
 function visibility(){last=0;if(!document.hidden)invalidate()}
 function lost(e){e.preventDefault();playing=false;onError('3D 화면 연결이 끊겼습니다. 페이지를 새로고침해 주세요.')}
 controls.addEventListener('change',invalidate);document.addEventListener('visibilitychange',visibility);renderer.domElement.addEventListener('webglcontextlost',lost)
 const observer=new ResizeObserver(resize);observer.observe(host);view();resize();apply()
 return {view,toggle(){if(elapsed>=25)elapsed=0;playing=!playing;last=0;apply();invalidate()},seek(value){elapsed=T.MathUtils.clamp(value,0,25);playing=false;last=0;apply();invalidate()},dispose(){disposed=true;cancelAnimationFrame(frame);observer.disconnect();controls.dispose();document.removeEventListener('visibilitychange',visibility);renderer.domElement.removeEventListener('webglcontextlost',lost);const geometries=new Set(),materials=new Set(),textures=new Set();scene.traverse(o=>{if(o.geometry)geometries.add(o.geometry);for(const m of (Array.isArray(o.material)?o.material:o.material?[o.material]:[])){materials.add(m);if(m.map)textures.add(m.map)}});geometries.forEach(g=>g.dispose());materials.forEach(m=>m.dispose());textures.forEach(t=>t.dispose());environment.dispose();renderer.dispose();renderer.domElement.remove()}}
}
