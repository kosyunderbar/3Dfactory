import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'
import {appendFile} from 'node:fs/promises'
import {simulationLauncher} from './simulation-launcher.js'

function measurements(env) {
  if(env.VITE_FACTORY_MEASUREMENT!=='true' || !env.FACTORY_BROWSER_MEASUREMENT_FILE)return []
  let writing=Promise.resolve(),bytes=0
  return [{name:'local-measurements',configureServer(server){
    server.middlewares.use('/__measurement',(req,res)=>{
      if(req.method!=='POST'){res.statusCode=405;res.end();return}
      let body='',size=0
      req.on('data',chunk=>{size+=chunk.length;if(size>262144)req.destroy();else body+=chunk.toString('utf8')})
      req.on('end',()=>{
        try {
          const rows=JSON.parse(body)
          if(!Array.isArray(rows)||rows.length>1000)throw Error()
          const text=rows.map(row=>JSON.stringify(row)).join('\n')+'\n'
          bytes+=Buffer.byteLength(text);if(bytes>67108864)throw Error()
          writing=writing.then(()=>appendFile(env.FACTORY_BROWSER_MEASUREMENT_FILE,text)).catch(error=>server.config.logger.error('Local measurement write failed: '+error.code))
          res.statusCode=204;res.end()
        }catch{res.statusCode=400;res.end()}
      })
    })
  }}]
}

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const target = env.OPERATIONS_PROXY_TARGET || 'http://127.0.0.1:8082'
  return {
    plugins: [vue(),simulationLauncher(env),...measurements(env)],
    server: {
      port: 5173,
      strictPort: true,
      proxy: { '/readyz': target, '/api': target },
    },
    preview: { port: 4173, strictPort: true, proxy: { '/readyz': target, '/api': target } },
  }
})
