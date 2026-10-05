// Drawing coordinates only: never change reported locations, cargo or slot counts.
const overlaps=(a,b,gap=12)=>a.x<b.x+b.width+gap && a.x+a.width+gap>b.x && a.y<b.y+b.height+gap && a.y+a.height+gap>b.y
const box=(x,y,width,height)=>({x,y,width,height})

export function layoutMap(config,entities){
 if(!config || !entities)return null
 const points=[...config.locations,...config.routes.flatMap(route=>route.points)]
 const minX=Math.min(0,...points.map(p=>p.x)),minY=Math.min(...points.map(p=>p.y))
 const project=p=>({x:150+(p.x-minX)*1.4,y:200+(p.y-minY)*2})
 const width=Math.max(1100,...points.map(p=>project(p).x+230))
 let height=Math.max(620,...points.map(p=>project(p).y+110))
 const occupied=[]
 function reserve(rect){occupied.push(rect);height=Math.max(height,rect.y+rect.height+28);return rect}
 // Try nearby callouts first; move to a free row if the map is crowded.
 function place(preferred,offsets){
  for(const [dx,dy] of offsets){
   const candidate={...preferred,x:Math.max(16,Math.min(width-preferred.width-16,preferred.x+dx)),y:Math.max(16,preferred.y+dy)}
   if(!occupied.some(other=>overlaps(candidate,other)))return reserve(candidate)
  }
  return reserve({...preferred,x:Math.max(16,Math.min(width-preferred.width-16,preferred.x)),y:height+16})
 }
 const cells=entities.cells.filter(c=>c.position).map(cell=>{
  const anchor=project(cell.position),rect=reserve(box(anchor.x-79,anchor.y-184,158,98))
  return {...cell,anchor,rect}
 })
 const buffers=entities.buffers.filter(b=>b.position).map(buffer=>{
  const anchor=project(buffer.position),rect=reserve(box(anchor.x-88,anchor.y+84,176,66+buffer.slots.length*26))
  return {...buffer,anchor,rect}
 })
 const locations=config.locations.filter(p=>!['CELL','BUFFER'].includes(p.locationType))
 const docks=locations.filter(p=>!['INPUT','RESULT'].includes(p.locationType)).map(location=>{
  const anchor=project(location),rect=reserve(box(anchor.x-84,anchor.y+20,168,30))
  return {...location,anchor,rect}
 })
 const places=locations.filter(p=>['INPUT','RESULT'].includes(p.locationType)).map(location=>{
  const anchor=project(location),bodies=entities.bodies.filter(b=>b.locationId===location.locationId).sort((a,b)=>a.bodyId.localeCompare(b.bodyId))
  const visibleBodies=bodies.slice(0,4),rows=Math.ceil(visibleBodies.length/2)
  const preferred=box(location.locationType==='INPUT' ? anchor.x-130 : anchor.x+22,location.locationType==='INPUT' ? anchor.y+36 : anchor.y-62,168,70+rows*28)
  const rect=place(preferred,Array.from({length:16},(_,index)=>[0,index*24]))
  return {...location,anchor,rect,bodies:visibleBodies,bodyCount:bodies.length,hiddenCount:bodies.length-visibleBodies.length}
 })
 const offsets=[[0,0],[0,-72],[0,72],[-142,0],[142,0],[-142,-72],[142,-72],[-142,72],[142,72],[0,-144],[0,144]]
 const vehicles=[...entities.vehicles].filter(v=>v.position).sort((a,b)=>a.vehicleId.localeCompare(b.vehicleId)).map(vehicle=>{
  const anchor=project(vehicle.position),rect=place(box(anchor.x-63,anchor.y-70,126,56),offsets)
  return {...vehicle,anchor,rect}
 })
 const routes=config.routes.map(route=>({...route,points:route.points.map(project)}))
 return {width,height,cells,buffers,docks,places,vehicles,routes}
}
