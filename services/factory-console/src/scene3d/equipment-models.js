import * as T from 'three'
import { RoundedBoxGeometry } from 'three/addons/geometries/RoundedBoxGeometry.js'

export const colors={blue:0x3467c7,navy:0x203955,white:0xf0f3f7,steel:0x9cabb9,dark:0x293440,rubber:0x202830,amber:0xe8af50}
const materials=new Map()
function material(color,metal=.25,rough=.48){const k=[color,metal,rough].join();if(!materials.has(k))materials.set(k,new T.MeshStandardMaterial({color,metalness:metal,roughness:rough}));return materials.get(k)}
export function block(g,size,pos,color=colors.white,r=.035){const m=new T.Mesh(r ? new RoundedBoxGeometry(...size,2,r) : new T.BoxGeometry(...size),material(color));m.position.set(...pos);m.castShadow=true;m.receiveShadow=true;g.add(m);return m}
export function drum(g,r,h,pos,color=colors.steel){const m=new T.Mesh(new T.CylinderGeometry(r,r,h,24),material(color,.55));m.position.set(...pos);m.castShadow=true;m.receiveShadow=true;g.add(m);return m}
function beam(g,a,b,r,color){const m=drum(g,r,1,[0,0,0],color);return ()=>{const p=new T.Vector3(...a()),q=new T.Vector3(...b()),d=q.clone().sub(p);m.position.copy(p.add(q).multiplyScalar(.5));m.scale.y=d.length();m.quaternion.setFromUnitVectors(new T.Vector3(0,1,0),d.normalize())}}
export function lettering(g,text,pos,w=.8,h=.18,color='#203955',background='#f0f3f7'){
 const c=document.createElement('canvas');c.width=768;c.height=128;const ctx=c.getContext('2d');ctx.fillStyle=background;ctx.fillRect(0,0,c.width,c.height);ctx.fillStyle=color;ctx.font='600 65px system-ui';ctx.textAlign='center';ctx.textBaseline='middle';ctx.fillText(text,384,66,730)
 const t=new T.CanvasTexture(c);t.colorSpace=T.SRGBColorSpace;const p=new T.Mesh(new T.PlaneGeometry(w,h),new T.MeshBasicMaterial({map:t,side:T.DoubleSide}));p.position.set(...pos);g.add(p);return p
}
function fasteners(g,xs,zs,y){for(const x of xs)for(const z of zs)drum(g,.034,.018,[x,y,z],colors.dark)}
export function detailedAgv(id = 'AGV-002'){
 const g=new T.Group(),wheels=[]
 block(g,[3.65,.36,1.94],[0,.48,0],colors.navy,.14)
 block(g,[3.48,.19,1.85],[0,.73,0],colors.blue,.09)
 block(g,[3.26,.1,1.7],[0,.88,0],colors.steel)
 for(const z of [-.67,.67]){block(g,[3.0,.08,.17],[0,.97,z],colors.dark);for(let x=-1.25;x<=1.25;x+=.25){const roll=drum(g,.065,.32,[x,1.04,z],colors.steel);roll.rotation.x=Math.PI/2}}
 for(const x of [-1.14,1.14])for(const z of [-.86,.86]){const wheel=new T.Group();wheel.position.set(x,.28,z);const tyre=drum(wheel,.255,.16,[0,0,0],colors.rubber);tyre.rotation.x=Math.PI/2;const hub=drum(wheel,.135,.17,[0,0,0],colors.steel);hub.rotation.x=Math.PI/2;block(wheel,[.18,.035,.19],[0,0,0],colors.navy);g.add(wheel);wheels.push(wheel)}
 for(const x of [-1.83,1.83]){block(g,[.1,.2,1.67],[x,.4,0],colors.rubber,.045);block(g,[.03,.075,.64],[x*1.004,.61,0],x>0?0xabe4f0:0xc96560,.012)}
 for(const z of [-.7,.7]){block(g,[.04,.11,.2],[1.835,.72,z],0xd9f5ff);block(g,[.07,.14,.18],[-1.84,.71,z],0xc85c55)}
 drum(g,.15,.12,[1.51,.99,0],colors.dark);drum(g,.145,.04,[1.51,1.06,0],0x80cbde)
 drum(g,.09,.07,[-1.42,.99,.55],colors.amber);drum(g,.065,.055,[-1.4,.995,-.55],0xc34840)
 for(const z of [-.975,.975]){
  block(g,[1.2,.17,.018],[0,.5,z],colors.dark,.01)
  for(let x=-.47;x<.5;x+=.13)block(g,[.035,.115,.022],[x,.5,z*1.002],colors.steel,.005)
  const l=lettering(g,id.replace('-', ' / '),[.15,.75,z],1.1,.14,'#ffffff','#3467c7');if(z<0)l.rotation.y=Math.PI
 }
 fasteners(g,[-1.4,1.4],[-.74,.74],.94)
 const arrow=new T.Shape();arrow.moveTo(-.32,-.13);arrow.lineTo(.05,-.13);arrow.lineTo(.05,-.25);arrow.lineTo(.38,0);arrow.lineTo(.05,.25);arrow.lineTo(.05,.13);arrow.lineTo(-.32,.13)
 const mark=new T.Mesh(new T.ShapeGeometry(arrow),new T.MeshBasicMaterial({color:0xd7e8ff,side:T.DoubleSide}));mark.rotation.x=-Math.PI/2;mark.position.set(.82,.943,0);g.add(mark)
 g.userData.wheels=wheels
 return {group:g,wheels}
}
export function detailedCargo(color = colors.white){
 const g=new T.Group()
 block(g,[3.06,.13,1.42],[0,.08,0],colors.steel)
 for(const x of [-1.2,1.2])for(const z of [-.56,.56])block(g,[.25,.13,.16],[x,.18,z],colors.dark)
 const bodyStart=g.children.length
 block(g,[2.9,.34,1.22],[0,.41,0],0xe7ecf2,.16)
 block(g,[1.48,.54,1.08],[-.2,.81,0],0xe9edf4,.16)
 block(g,[.72,.13,1.13],[.96,.63,0],0xf6f8fb,.06)
 block(g,[.32,.2,1.13],[-1.22,.56,0],0xf6f8fb,.04)
 for(const z of [-.551,.551]){
  block(g,[.54,.28,.018],[.08,.85,z],0x425d76,.035);block(g,[.49,.28,.018],[-.55,.85,z],0x425d76,.035)
  block(g,[.035,.55,.022],[-.25,.69,z*1.12],colors.steel,.007)
  for(const x of [-.61,.11])block(g,[.11,.025,.025],[x,.65,z*1.13],colors.steel,.005)
  for(const x of [-.94,.94]){const w=drum(g,.265,.13,[x,.29,z*1.1],colors.rubber);w.rotation.x=Math.PI/2;const h=drum(g,.15,.138,[x,.29,z*1.1],colors.steel);h.rotation.x=Math.PI/2}
 }
 const windshield=block(g,[.07,.34,.9],[.54,.9,0],0x425d76,.015);windshield.rotation.z=.35
 const rear=block(g,[.04,.29,.9],[-.94,.89,0],0x425d76,.01);rear.rotation.z=-.25
 for(const z of [-.4,.4])block(g,[.025,.1,.25],[1.448,.49,z],0xc4e5f2,.015)
 g.userData.paint=[]
 for(const part of g.children.slice(bodyStart)){
  part.position.y+=.125
  if ([0xe7ecf2,0xe9edf4,0xf6f8fb].includes(part.material?.color?.getHex())) {
   part.material=part.material.clone();part.material.color.setHex(color);g.userData.paint.push(part.material)
  }
 }
 return g
}
function robot(g,x,z,mirror){
 const root=new T.Group();root.position.set(x,0,z);g.add(root)
 block(root,[.72,.19,.72],[0,.18,0],colors.navy);fasteners(root,[-.27,.27],[-.27,.27],.28)
 drum(root,.27,.42,[0,.46,0],colors.steel);drum(root,.3,.17,[0,.75,0],colors.blue)
 const joints=[new T.Vector3(0,.85,0),new T.Vector3(),new T.Vector3(),new T.Vector3()]
 const caps=joints.slice(1).map(()=>drum(root,.19,.24,[0,0,0],colors.navy));caps.forEach(m=>m.rotation.z=Math.PI/2)
 const links=[0,1,2].map(i=>beam(root,()=>joints[i].toArray(),()=>joints[i+1].toArray(),i===2?.105:.16,colors.blue))
 const tool=block(root,[.17,.26,.42],[0,0,0],colors.steel)
 const hoses=[0,1].map(i=>beam(root,()=>joints[i].clone().add(new T.Vector3(.18,0,0)).toArray(),()=>joints[i+1].clone().add(new T.Vector3(.18,0,0)).toArray(),.033,colors.dark))
 return function pose(work=0,phase=0){
  joints[1].set(.12,1.83,-mirror*.15)
  joints[2].set(.36+Math.sin(phase)*.22*work,2.4,-mirror*(.25+work*.55))
  joints[3].set(.45+Math.sin(phase)*.22*work,1.9+work*.1,-mirror*(.25+work*.8))
  links.forEach(fn=>fn());hoses.forEach(fn=>fn());caps.forEach((m,i)=>m.position.copy(joints[i+1]));tool.position.copy(joints[3])
 }
}
export function detailedAssembly(id = 'ASM-01', inspection = false){
 const g=new T.Group(),clamps=[]
 block(g,[5.7,.13,5.1],[0,.04,0],0xd9e2ec)
 for(const x of [-1.75,1.75])for(const z of [-.72,.72]){block(g,[.17,.75,.17],[x,.43,z],colors.navy);block(g,[.42,.055,.4],[x,.12,z],colors.steel)}
 block(g,[4.5,.18,1.86],[0,.87,0],colors.navy)
 for(const z of [-.69,.69]){block(g,[4.48,.08,.18],[0,.98,z],colors.steel);for(let x=-2.1;x<2.2;x+=.23){const r=drum(g,.063,.34,[x,1.045,z],colors.steel);r.rotation.x=Math.PI/2}}
 for(const x of [-1.1,1.1])for(const z of [-.95,.95]){
  const c=new T.Group();c.position.set(x,1.04,z);g.add(c);block(c,[.24,.16,.27],[0,0,0],colors.blue);block(c,[.09,.16,.29],[0,.14,-Math.sign(z)*.09],colors.steel);clamps.push({group:c,z})
 }
 const robots=inspection ? [] : [robot(g,-.65,-1.92,-1),robot(g,.5,1.92,1)]
 let scanner
 if(inspection){
  for(const x of [-1.2,1.2]) {
   for(const z of [-1.22,1.22])block(g,[.16,2.7,.19],[x,1.5,z],colors.navy)
   block(g,[.28,.24,2.75],[x,2.91,0],colors.blue)
   for(const z of [-.9,0,.9]){block(g,[.16,.17,.18],[x,2.69,z],colors.dark);block(g,[.1,.025,.12],[x,2.59,z],0x88d4df)}
  }
  scanner=block(g,[.06,.035,1.5],[0,2.51,0],0x7cdae1)
 }

 block(g,[.85,1.6,.62],[2.18,.94,-1.87],colors.white,.07)
 lettering(g,id,[2.18,1.39,-1.548],.62,.16)
 for(let y=.5;y<.9;y+=.09)block(g,[.57,.025,.035],[2.18,y,-1.548],colors.steel)
 block(g,[.2,.08,.06],[2.43,1.04,-1.51],colors.dark)
 drum(g,.028,.7,[2.2,2.06,-1.87],colors.steel)
 const lights=[0x56b49b,colors.amber,0xc7655e].map((c,i)=>drum(g,.085,.11,[2.2,2.48+i*.12,-1.87],c))
 block(g,[.13,1.25,.13],[-1.97,.7,2.12],colors.steel)
 const panel=block(g,[.75,.51,.09],[-1.97,1.49,2.12],colors.navy)
 lettering(g,id+' / CONTROL',[-1.97,1.5,2.17],.65,.17,'#a6e4d9','#203955')
 drum(g,.055,.035,[-1.69,1.25,2.18],0xc34840).rotation.x=Math.PI/2
 for(const x of [-2.65,0,2.65]){block(g,[.075,2.35,.075],[x,1.22,-2.45],colors.steel);block(g,[.26,.05,.26],[x,.08,-2.45],colors.navy)}
 for(const x of [-1.325,1.325]){
  const pane=new T.Mesh(new T.PlaneGeometry(2.57,1.86),new T.MeshPhysicalMaterial({color:0xc0d6e8,transparent:true,opacity:.14,roughness:.2,side:T.DoubleSide,depthWrite:false}));pane.position.set(x,1.33,-2.45);g.add(pane)
  for(const y of [.39,2.27])block(g,[2.61,.04,.055],[x,y,-2.45],colors.steel)
 }
 for(const z of [-.99,.99]){block(g,[.08,1.35,.08],[-2.52,.76,z],colors.dark);for(let y=.3;y<1.4;y+=.17)block(g,[.015,.025,.095],[-2.565,y,z],0x70bace)}
 lights[0].material=lights[0].material.clone()
 g.userData.lamp=lights[0]
 function pose(work=0,time=0){
  robots.forEach((fn,i)=>fn(work,time+i*2))
  for(const c of clamps)c.group.position.z=c.z-Math.sign(c.z)*work*.16
  if(scanner){scanner.visible=work>.1;scanner.position.x=Math.sin(time)*.85}
 }
 g.userData.pose=pose;pose()
 return {group:g,pose}

}
