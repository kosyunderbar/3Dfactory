const LIMIT=524288
export class QueryError extends Error {constructor(code){super(code);this.code=code}}
// Read-only responses never replace physical SSE state. Scope, request version and abort fence late replies.
export class ScopedQueries {
 constructor({fetcher=(...args)=>fetch(...args),timers=globalThis}={}){this.fetcher=fetcher;this.timers=timers;this.scope='';this.version=0;this.channels=new Map()}
 reset(scope){if(scope===this.scope)return;this.close();this.scope=scope}
 close(){this.version++;for(const task of this.channels.values()){task.abort.abort();this.timers.clearTimeout(task.timer)}this.channels.clear()}
 async group(channel,run,requests,validate=()=>true){
  const prior=this.channels.get(channel);if(prior){prior.abort.abort();this.timers.clearTimeout(prior.timer)}
  const task={abort:new AbortController(),version:this.version,timer:null};this.channels.set(channel,task)
  task.timer=this.timers.setTimeout(()=>task.abort.abort(),5000)
  const current=()=>this.version===task.version && this.channels.get(channel)===task
  try{
   const values=await Promise.all(requests.map(async ({path,method='GET',body})=>{
    const response=await this.fetcher(path,{method,signal:task.abort.signal,cache:'no-store',...(body ? {headers:{'Content-Type':'application/json'},body:JSON.stringify(body)} : {})})
    if(!response.ok){let code=`HTTP_${response.status}`;try{const text=await response.text();if(text.length<LIMIT)code=JSON.parse(text).code || code}catch{}throw new QueryError(code)}
    const text=await response.text();if(new TextEncoder().encode(text).length>LIMIT)throw new QueryError('PAYLOAD_TOO_LARGE')
    const value=JSON.parse(text);if(value.schemaVersion!==1 || value.runId!==run)throw new QueryError('INVALID_RESPONSE');return value
   }))
   if(!current())return null
   if(!validate(values))throw new QueryError('INVALID_RESPONSE')
   return values
  }catch(error){if(!current())return null;throw error}
  finally{this.timers.clearTimeout(task.timer);if(current())this.channels.delete(channel)}
 }
 async one(channel,run,path,options={}){const values=await this.group(channel,run,[{path,...options}]);return values?.[0] ?? null}
}
export function apiPath(run,collection,query={}){
 const values=new URLSearchParams(Object.entries(query).filter(([,value])=>value!=='' && value!==null && value!==undefined))
 return `/api/v1/runs/${encodeURIComponent(run)}/${collection}${values.size ? '?'+values : ''}`
}
