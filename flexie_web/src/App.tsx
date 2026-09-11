import { useState, useEffect, useRef } from 'react'
import './App.css'

type Provider = {
  id: string
  label: string
  env: string
  modelEnv: string
  placeholder: string
  help: string
  defaultModel: string
  models: string[]
}

const PROVIDERS: Provider[] = [
  { id: 'groq', label: 'Groq', env: 'GROQ_API_KEY', modelEnv: 'GROQ_MODEL', placeholder: 'gsk_...', help: 'console.groq.com/keys', defaultModel: 'llama-3.1-8b-instant', models: ['llama-3.1-8b-instant','llama-3.3-70b-versatile','llama-3.1-70b-versatile','mixtral-8x7b-32768','gemma2-9b-it'] },
  { id: 'openai', label: 'OpenAI (GPT)', env: 'OPENAI_API_KEY', modelEnv: 'OPENAI_MODEL', placeholder: 'sk-...', help: 'platform.openai.com/api-keys', defaultModel: 'gpt-4o-mini', models: ['gpt-4o-mini','gpt-4o','gpt-4-turbo','gpt-3.5-turbo','o1-mini'] },
  { id: 'deepseek', label: 'DeepSeek', env: 'DEEPSEEK_API_KEY', modelEnv: 'DEEPSEEK_MODEL', placeholder: 'sk-...', help: 'platform.deepseek.com/api_keys', defaultModel: 'deepseek-chat', models: ['deepseek-chat','deepseek-reasoner'] },
  { id: 'gemini', label: 'Google Gemini', env: 'GEMINI_API_KEY', modelEnv: 'GEMINI_MODEL', placeholder: 'AIza...', help: 'aistudio.google.com/app/apikey', defaultModel: 'gemini-1.5-flash', models: ['gemini-1.5-flash','gemini-1.5-flash-8b','gemini-1.5-pro','gemini-2.0-flash'] },
  { id: 'anthropic', label: 'Anthropic Claude', env: 'ANTHROPIC_API_KEY', modelEnv: 'ANTHROPIC_MODEL', placeholder: 'sk-ant-...', help: 'console.anthropic.com/settings/keys', defaultModel: 'claude-3-5-sonnet-20241022', models: ['claude-3-5-sonnet-20241022','claude-3-5-haiku-20241022','claude-3-opus-20240229'] },
  { id: 'mistral', label: 'Mistral AI', env: 'MISTRAL_API_KEY', modelEnv: 'MISTRAL_MODEL', placeholder: 'xxx...', help: 'console.mistral.ai/api-keys', defaultModel: 'mistral-small-latest', models: ['mistral-small-latest','mistral-large-latest','open-mistral-7b'] },
]

const ICONS: Record<string,string> = { groq:'⚡', openai:'🤖', deepseek:'🧠', gemini:'✦', anthropic:'◆', mistral:'🌬️', ollama:'💻' }

export default function App() {
  const [active, setActive] = useState('auto')
  const [keys, setKeys] = useState<Record<string,string>>({})
  const [models, setModels] = useState<Record<string,string>>({})
  const [showKeys, setShowKeys] = useState<Record<string,boolean>>({})
  const [filter, setFilter] = useState('')
  const [status, setStatus] = useState('')
  const [wsStatus, setWsStatus] = useState('◯ connecting…')
  const wsRef = useRef<WebSocket|null>(null)

  useEffect(() => {
    const saved = localStorage.getItem('flexie_keys')
    if (saved) try { setKeys(JSON.parse(saved)) } catch {}
    const savedModels = localStorage.getItem('flexie_models')
    if (savedModels) try { setModels(JSON.parse(savedModels)) } catch {}
    const savedActive = localStorage.getItem('flexie_active')
    if (savedActive) setActive(savedActive)
    // WebSocket to bridge
    try {
      const ws = new WebSocket('ws://localhost:8765')
      ws.onopen = () => setWsStatus('● live')
      ws.onclose = () => setWsStatus('○ offline (local save only)')
      ws.onerror = () => setWsStatus('○ offline')
      ws.onmessage = (e) => setStatus(String(e.data).slice(0,120))
      wsRef.current = ws
    } catch { setWsStatus('○ offline') }
    return () => wsRef.current?.close()
  }, [])

  const send = (msg: string) => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) wsRef.current.send(msg)
  }

  const save = () => {
    const updates: Record<string,string> = {}
    PROVIDERS.forEach(p => {
      if (keys[p.id]) updates[p.env] = keys[p.id]
      if (models[p.id]) updates[p.modelEnv] = models[p.id]
    })
    if (Object.keys(updates).length === 0 && active === (localStorage.getItem('flexie_active')||'auto')) {
      setStatus('No changes')
      return
    }
    localStorage.setItem('flexie_keys', JSON.stringify(keys))
    localStorage.setItem('flexie_models', JSON.stringify(models))
    localStorage.setItem('flexie_active', active)
    // Send via WS → UDP → orchestrator
    Object.entries(updates).forEach(([env, val]) => {
      const prov = PROVIDERS.find(p => p.env===env || p.modelEnv===env)
      if (!prov) return
      if (env.endsWith('_API_KEY')) send(`SET_API_KEY:${prov.id}:${val}`)
      else send(`SET_MODEL:${prov.id}:${val}`)
    })
    send(`SET_ACTIVE_PROVIDER:${active}`)
    send('RELOAD_BRAIN')
    setStatus(`Saved ${Object.keys(updates).length} change(s) • Active: ${active} • Reloading brain…`)
    setTimeout(()=> setStatus('✅ Brain reloaded'), 1500)
  }

  const filtered = PROVIDERS.filter(p => !filter || p.id.includes(filter.toLowerCase()) || p.label.toLowerCase().includes(filter.toLowerCase()))

  return (
    <div style={{minHeight:'100vh', background:'radial-gradient(1200px 600px at 50% -10%, rgba(0,210,255,0.12), transparent), #0a0f19', color:'#fff', fontFamily:"'Inter','Segoe UI',sans-serif"}}>
      <header style={{position:'sticky', top:0, zIndex:10, backdropFilter:'blur(16px)', background:'rgba(10,15,25,0.85)', borderBottom:'1px solid rgba(255,255,255,0.08)', padding:'14px 24px', display:'flex', alignItems:'center', gap:16}}>
        <div style={{fontWeight:800, letterSpacing:3, fontSize:18}}>FLEXIE <span style={{color:'#00D2FF'}}>2.0</span></div>
        <div style={{marginLeft:'auto', display:'flex', gap:8, alignItems:'center', fontSize:12, opacity:0.8}}>
          <span style={{padding:'4px 10px', borderRadius:20, background:'rgba(0,210,255,0.12)', border:'1px solid rgba(0,210,255,0.25)'}}>{wsStatus}</span>
          <span style={{padding:'4px 10px', borderRadius:20, background:'rgba(255,255,255,0.06)', border:'1px solid rgba(255,255,255,0.1)'}}>⚡ {active.toUpperCase()}</span>
        </div>
      </header>

      <main style={{maxWidth:980, margin:'0 auto', padding:'24px 20px 60px'}}>
        <div style={{textAlign:'center', margin:'18px 0 20px'}}>
          <h1 style={{fontSize:22, fontWeight:800, letterSpacing:2, margin:0}}>🔑 AI PROVIDER KEYS + MODELS</h1>
          <p style={{opacity:0.6, fontSize:12, margin:'6px 0 0'}}>Fallback chain: Groq(1) → OpenAI(2) → DeepSeek(3) → Gemini(4) → Claude(5) → Ollama • Change without restart</p>
        </div>

        <div style={{display:'flex', gap:12, flexWrap:'wrap', alignItems:'center', marginBottom:16, background:'rgba(255,255,255,0.06)', border:'1px solid rgba(255,255,255,0.08)', borderRadius:12, padding:12}}>
          <label style={{fontSize:12, fontWeight:700, opacity:0.9}}>⚡ Active Provider</label>
          <select value={active} onChange={e=>setActive(e.target.value)} style={{flex:1, minWidth:160, background:'rgba(0,0,0,0.5)', color:'#fff', border:'1px solid rgba(255,255,255,0.15)', borderRadius:8, padding:'8px 10px'}}>
            <option value="auto">auto (fallback chain)</option>
            {PROVIDERS.map(p=> <option key={p.id} value={p.id}>{p.label}</option>)}
            <option value="ollama">Ollama (local)</option>
          </select>
          <input placeholder="🔍 Filter providers…" value={filter} onChange={e=>setFilter(e.target.value)} style={{flex:1, minWidth:160, background:'rgba(0,0,0,0.5)', color:'#fff', border:'1px solid rgba(255,255,255,0.15)', borderRadius:8, padding:'8px 12px'}}/>
        </div>

        <div style={{display:'grid', gridTemplateColumns:'repeat(auto-fill, minmax(300px, 1fr))', gap:14}}>
          {filtered.map(p => {
            const hasKey = !!keys[p.id]
            return (
              <div key={p.id} style={{background:'rgba(255,255,255,0.06)', border: hasKey? '1px solid rgba(0,255,65,0.25)':'1px solid rgba(255,255,255,0.08)', borderRadius:14, padding:14, display:'flex', flexDirection:'column', gap:10}}>
                <div style={{display:'flex', alignItems:'center', gap:8}}>
                  <span style={{fontSize:18}}>{ICONS[p.id]||'●'}</span>
                  <span style={{fontWeight:700, fontSize:13}}>{p.label}</span>
                  <span style={{fontSize:10, opacity:0.5}}>{p.env}</span>
                  <span style={{marginLeft:'auto', fontSize:14, color: hasKey?'#00FF41':'rgba(255,255,255,0.3)'}}>●</span>
                </div>
                <div style={{display:'flex', gap:6}}>
                  <input type={showKeys[p.id]?'text':'password'} placeholder={p.placeholder + ' — saved locally'} value={keys[p.id]||''} onChange={e=> setKeys(s=>({...s, [p.id]: e.target.value}))} style={{flex:1, background:'rgba(0,0,0,0.6)', color:'#fff', border: hasKey? '1px solid rgba(0,255,65,0.3)':'1px solid rgba(255,255,255,0.12)', borderRadius:8, padding:'8px 10px', fontSize:12}}/>
                  <button onClick={()=> setShowKeys(s=>({...s, [p.id]: !s[p.id]}))} style={{width:36, borderRadius:8, border:'1px solid rgba(255,255,255,0.12)', background:'rgba(255,255,255,0.06)', color:'#fff', cursor:'pointer'}}>{showKeys[p.id]?'🙈':'👁'}</button>
                </div>
                <div style={{display:'flex', gap:6, alignItems:'center'}}>
                  <span style={{fontSize:11, opacity:0.7}}>Model</span>
                  <select value={models[p.id]||p.defaultModel} onChange={e=> setModels(s=>({...s, [p.id]: e.target.value}))} style={{flex:1, background:'rgba(0,0,0,0.5)', color:'#fff', border:'1px solid rgba(255,255,255,0.12)', borderRadius:8, padding:'6px 8px', fontSize:11}}>
                    {p.models.map(m=> <option key={m} value={m}>{m}</option>)}
                  </select>
                </div>
                <a href={'https://' + p.help} target="_blank" rel="noreferrer" style={{fontSize:10, color:'rgba(0,210,255,0.8)', textDecoration:'none'}}>↗ {p.help}</a>
              </div>
            )
          })}
          <div style={{background:'rgba(255,255,255,0.06)', border:'1px solid rgba(255,255,255,0.08)', borderRadius:14, padding:14, display:'flex', flexDirection:'column', gap:10}}>
            <div style={{display:'flex', alignItems:'center', gap:8}}>
              <span style={{fontSize:18}}>💻</span><span style={{fontWeight:700, fontSize:13}}>Ollama (Local)</span><span style={{fontSize:10, opacity:0.5}}>OLLAMA</span><span style={{marginLeft:'auto', color:'#00FF41'}}>●</span>
            </div>
            <input placeholder="http://localhost:11434/api/generate" onChange={()=>{}} style={{background:'rgba(0,0,0,0.6)', color:'#fff', border:'1px solid rgba(255,255,255,0.12)', borderRadius:8, padding:'8px 10px', fontSize:12}} defaultValue="http://localhost:11434/api/generate"/>
            <select style={{background:'rgba(0,0,0,0.5)', color:'#fff', border:'1px solid rgba(255,255,255,0.12)', borderRadius:8, padding:'6px 8px', fontSize:11}}>
              {['tinyllama:latest','llama3:latest','mistral:latest','gemma2:latest'].map(m=> <option key={m}>{m}</option>)}
            </select>
            <span style={{fontSize:10, opacity:0.5}}>↗ ollama.com</span>
          </div>
        </div>

        <div style={{position:'sticky', bottom:16, marginTop:20, display:'flex', gap:10, justifyContent:'center', background:'rgba(10,15,25,0.9)', backdropFilter:'blur(12px)', border:'1px solid rgba(255,255,255,0.08)', borderRadius:14, padding:12}}>
          <button onClick={()=> setStatus(['✅ groq:llama-3.1-8b-instant','✅ openai:gpt-4o-mini','⚪ deepseek','⚪ gemini'].join(' • '))} style={{padding:'10px 14px', borderRadius:10, border:'1px solid rgba(255,255,255,0.12)', background:'rgba(255,255,255,0.06)', color:'#fff', cursor:'pointer'}}>🧪 Test</button>
          <button onClick={save} style={{padding:'10px 20px', borderRadius:10, border:'none', background:'linear-gradient(90deg,#0095FF,#0055FF)', color:'#fff', fontWeight:700, cursor:'pointer', flex:1, maxWidth:320}}>💾 Save & Reload Brain</button>
        </div>
        {status && <div style={{marginTop:14, textAlign:'center', padding:'10px', borderRadius:10, background:'rgba(0,210,255,0.08)', border:'1px solid rgba(0,210,255,0.2)', fontSize:12, color:'#00D2FF'}}>{status}</div>}
      </main>
    </div>
  )
}
