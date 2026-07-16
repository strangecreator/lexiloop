import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import {
  BookOpen, BrainCircuit, Check, ChevronDown, ChevronLeft, ChevronRight, CircleDollarSign,
  Clock3, Edit3, Flame, FolderPlus, Gauge, Library, LogOut, Moon, Plus, Search,
  Settings as SettingsIcon, Sparkles, Sun, Trash2, Volume2, X, Zap, Layers3, RotateCcw,
  ShieldCheck, KeyRound, WandSparkles, CircleHelp, ArrowRight, ListPlus, Save,
  PanelLeftClose, PanelLeftOpen, Palette, Ban, Unlock, Copy, GitMerge, MoreVertical, AlertTriangle, RefreshCw,
  Image as ImageIcon, ImagePlus, Upload, PencilLine
} from 'lucide-react'
import { api, apiBlob, apiPage, ApiError, list, setToken, token } from './api'
import type { AccentColor, Analytics, BulkJob, Card, Direction, JudgeResult, ModelOption, Overview, Pool, Settings, Theme } from './types'

type Page = 'home'|'study'|'library'|'analytics'|'settings'|'notfound'
type Toast = {message:string; kind:'success'|'error'}

const PAGE_TITLES:Record<Page,string> = {
  home:'Overview', study:'Study', library:'Library', analytics:'AI usage', settings:'Settings', notfound:'Not found'
}
const PAGE_PATHS:Record<Exclude<Page,'notfound'>,string> = {
  home:'/overview', study:'/study', library:'/library', analytics:'/analytics', settings:'/settings'
}
function pageFromPath(path:string):Page{
  const clean=path.replace(/\/+$/,'')||'/'
  if(clean==='/'||clean==='/overview')return 'home'
  if(clean==='/study')return 'study'
  if(clean==='/library')return 'library'
  if(clean==='/analytics')return 'analytics'
  if(clean==='/settings')return 'settings'
  if(clean==='/auth'||clean==='/register')return 'home'
  return 'notfound'
}
function authModeFromPath(path:string):'login'|'register'{return path.replace(/\/+$/,'')==='/register'?'register':'login'}
const ACCENTS:AccentColor[]=['emerald','blue','teal','indigo','violet','rose','orange']

const emptySettings:Settings = {
  theme:'system', accent_color:'emerald', study_directions:['term_to_definition','definition_to_term'], generation_model:'external:deepseek-chat', has_generation_token:false,
  judge_model:'external:deepseek-chat', has_judge_token:false, token_status:{}, judge_acceptance_score:5,
  sentence_judge_model:'', has_sentence_token:false, sentence_acceptance_score:5, show_images_term_to_sentence:true,
  image_model:'', has_image_token:false, show_card_images:true,
  show_images_term_to_definition:true, show_images_definition_to_term:true, image_animations:['mist','ripple','drift'],
  image_animation_durations:{}, image_prefetch_count:2,
  daily_new_limit:20, learning_steps_minutes:[1,10], relearning_steps_minutes:[10], graduating_interval_days:1,
  easy_interval_days:4, easy_bonus:1.3, hard_multiplier:1.2, lapse_multiplier:.5, minimum_ease:1.3,
  term_to_definition_easy_seconds:12, term_to_definition_good_seconds:35,
  definition_to_term_easy_seconds:6, definition_to_term_good_seconds:18,
  term_to_sentence_easy_seconds:20, term_to_sentence_good_seconds:60
}
function initialSettings():Settings{
  const theme=localStorage.getItem('lexiloop_theme') as Theme|null
  const accent=localStorage.getItem('lexiloop_accent') as AccentColor|null
  return {
    ...emptySettings,
    theme:theme&&['dark','light','system'].includes(theme)?theme:emptySettings.theme,
    accent_color:accent&&ACCENTS.includes(accent)?accent:emptySettings.accent_color,
  }
}

export default function App() {
  const [authenticated,setAuthenticated]=useState(Boolean(token()))
  const [username,setUsername]=useState('')
  const [settings,setSettings]=useState<Settings>(initialSettings)
  const [pools,setPools]=useState<Pool[]>([])
  const [activePool,setActivePool]=useState<number|null>(null)
  const [page,setPageState]=useState<Page>(()=>pageFromPath(window.location.pathname))
  const [sidebar,setSidebar]=useState(false)
  const [sidebarCollapsed,setSidebarCollapsed]=useState(()=>localStorage.getItem('lexiloop_sidebar_collapsed')==='1')
  const [toast,setToast]=useState<Toast|null>(null)
  const notify=(message:string,kind:Toast['kind']='success')=>{setToast({message,kind});window.setTimeout(()=>setToast(null),3800)}
  const navigate=(next:Page,replace=false)=>{
    setPageState(next)
    if(next!=='notfound'){
      const path=PAGE_PATHS[next]
      if(window.location.pathname!==path){replace?history.replaceState(null,'',path):history.pushState(null,'',path)}
    }
  }
  useEffect(()=>{const pop=()=>setPageState(pageFromPath(window.location.pathname));window.addEventListener('popstate',pop);return()=>window.removeEventListener('popstate',pop)},[])

  const loadShell=useCallback(async()=>{
    try {
      const me=await api<{username:string;settings:Settings}>('/auth/me/')
      const poolData=await api<Pool[]|{results:Pool[]}>('/pools/')
      const p=list(poolData)
      setUsername(me.username);setSettings(me.settings);setPools(p)
      setActivePool(current=>current && p.some(x=>x.id===current) ? current : p[0]?.id ?? null)
      applyAppearance(me.settings.theme,me.settings.accent_color)
    } catch (e) {
      if (e instanceof ApiError && e.status===401) {setToken('');setAuthenticated(false)}
      else notify((e as Error).message,'error')
    }
  },[])
  useEffect(()=>{if(authenticated) void loadShell()},[authenticated,loadShell])
  useEffect(()=>{if(authenticated)document.title=`LexiLoop · ${PAGE_TITLES[page]}`},[authenticated,page])
  useEffect(()=>{
    applyAppearance(settings.theme,settings.accent_color)
    if(settings.theme!=='system')return
    const media=matchMedia('(prefers-color-scheme: dark)')
    const listener=()=>applyAppearance('system',settings.accent_color)
    media.addEventListener('change',listener)
    return()=>media.removeEventListener('change',listener)
  },[settings.theme,settings.accent_color])

  const setCollapsed=(value:boolean)=>{setSidebarCollapsed(value);localStorage.setItem('lexiloop_sidebar_collapsed',value?'1':'0')}
  const changeTheme=async(theme:Theme)=>{
    try{const next=await api<Settings>('/settings/',{method:'PATCH',body:JSON.stringify({theme})});setSettings(next);applyAppearance(next.theme,next.accent_color)}
    catch(e){notify((e as Error).message,'error')}
  }
  const signOut=async()=>{try{await api('/auth/logout/',{method:'POST'})}catch{}setToken('');setAuthenticated(false);setPools([]);history.replaceState(null,'','/auth')}
  if(!authenticated) return <Auth initialMode={authModeFromPath(window.location.pathname)} onAuthenticated={(name)=>{setUsername(name);setAuthenticated(true);navigate(page==='notfound'?'home':page,true)}} />
  return <div className={`app-shell ${sidebarCollapsed?'sidebar-collapsed':''}`}>
    <Sidebar open={sidebar} collapsed={sidebarCollapsed} onToggleCollapsed={()=>setCollapsed(!sidebarCollapsed)} page={page} setPage={(p)=>{navigate(p);setSidebar(false)}} pools={pools} activePool={activePool}
      setActivePool={(id)=>{setActivePool(id);setSidebar(false)}} onCreated={async()=>{await loadShell()}}
      username={username} onSignOut={signOut} theme={settings.theme} onThemeChange={changeTheme} notify={notify}/>
    <button className="icon-button floating-sidebar-button" title="Open navigation" onClick={()=>{setCollapsed(false);setSidebar(true)}}><PanelLeftOpen size={20}/></button>
    <main className={`main ${sidebarCollapsed?'sidebar-collapsed':''}`}>
      <section className={`page page-${page}`}>
        {page==='home' && <Home pools={pools} activePool={activePool} setActivePool={setActivePool} go={navigate} refreshPools={loadShell}/>} 
        {page==='study' && <Study activePool={activePool} notify={notify}/>} 
        {page==='library' && <LibraryPage activePool={activePool} pools={pools} notify={notify} refreshPools={loadShell}/>} 
        {page==='analytics' && <AnalyticsPage pools={pools}/>} 
        {page==='settings' && <SettingsPage value={settings} onSaved={s=>{setSettings(s);applyAppearance(s.theme,s.accent_color);notify('Settings saved')}} notify={notify}/>} 
        {page==='notfound' && <NotFound onHome={()=>navigate('home')}/>} 
      </section>
    </main>
    {sidebar && <div className="scrim" onClick={()=>setSidebar(false)}/>} 
    {toast && <div className={`toast ${toast.kind}`}>{toast.kind==='success'?<Check size={17}/>:<CircleHelp size={17}/>} {toast.message}</div>}
  </div>
}

function Auth({initialMode,onAuthenticated}:{initialMode:'login'|'register';onAuthenticated:(u:string)=>void}) {
  const [mode,setModeState]=useState<'login'|'register'>(initialMode)
  const setMode=(next:'login'|'register')=>{setModeState(next);const path=next==='login'?'/auth':'/register';if(window.location.pathname!==path)history.pushState(null,'',path)}
  const [username,setUsername]=useState('')
  const [password,setPassword]=useState('')
  const [busy,setBusy]=useState(false)
  const [error,setError]=useState('')
  const usernamePlaceholder=useMemo(()=>['snowy_camomile','tasty_banana','meticulous_learner','curious_fox','patient_polyglot'][Math.floor(Math.random()*5)],[])
  useEffect(()=>{document.title=`LexiLoop · ${mode==='login'?'Sign in':'Create account'}`},[mode])
  useEffect(()=>{const path=mode==='login'?'/auth':'/register';if(!['/auth','/register'].includes(window.location.pathname))history.replaceState(null,'',path)},[])
  const submit=async(e:React.FormEvent)=>{e.preventDefault();setBusy(true);setError('');try{
    const result=await api<{token:string;username:string}>(`/auth/${mode}/`,{method:'POST',body:JSON.stringify({username,password})})
    setToken(result.token);onAuthenticated(result.username)
  }catch(err){setError((err as Error).message)}finally{setBusy(false)}}
  return <div className="auth-page">
    <div className="auth-orb one"/><div className="auth-orb two"/>
    <div className="auth-brand"><Logo/><span>LexiLoop</span></div>
    <div className="auth-grid">
      <div className="auth-copy">
        <span className="badge"><Sparkles size={14}/> AI-assisted learning</span>
        <h1>Remember words.<br/><em>Actually use them.</em></h1>
        <p>Beautiful flashcards, semantic answer checking, and spaced repetition that adapts after every review.</p>
        <div className="feature-row"><BrainCircuit/><div><b>Meaning, not exact wording</b><span>An LLM judges free-form definitions fairly.</span></div></div>
        <div className="feature-row"><Gauge/><div><b>Adaptive scheduling</b><span>Hard words return sooner. Stable memories wait.</span></div></div>
      </div>
      <form className="auth-card" onSubmit={submit}>
        <div className="auth-tabs"><button type="button" className={mode==='login'?'active':''} onClick={()=>setMode('login')}>Sign in</button><button type="button" className={mode==='register'?'active':''} onClick={()=>setMode('register')}>Create account</button></div>
        <div><h2>{mode==='login'?'Welcome back':'Start your learning loop'}</h2><p>No email required. Your username is enough.</p></div>
        <label>Username<input autoFocus value={username} onChange={e=>setUsername(e.target.value)} minLength={3} autoComplete="username" placeholder={usernamePlaceholder}/></label>
        <label>Password<input type="password" value={password} onChange={e=>setPassword(e.target.value)} minLength={8} autoComplete={mode==='login'?'current-password':'new-password'} placeholder="At least 8 characters"/></label>
        {error && <div className="form-error">{error}</div>}
        <button className="primary big" disabled={busy}>{busy?'Working…':mode==='login'?'Sign in':'Create account'}<ArrowRight size={18}/></button>
        <small>Provider tokens are encrypted before storage.</small>
      </form>
    </div>
  </div>
}

function Logo(){return <div className="logo"><Layers3 size={21}/></div>}
function effectiveTheme(theme:Theme):'dark'|'light'{return theme==='system'?(matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light'):theme}
function applyAppearance(theme:Theme,accent:AccentColor){
  const effective=effectiveTheme(theme)
  document.documentElement.dataset.theme=effective
  document.documentElement.dataset.accent=accent
  localStorage.setItem('lexiloop_theme',theme)
  localStorage.setItem('lexiloop_accent',accent)
  document.querySelector('meta[name="theme-color"]')?.setAttribute('content',effective==='dark'?'#0a0b0f':'#f5f5f8')
}
function ThemeButton({theme,onChange}:{theme:Theme;onChange:(v:Theme)=>void}){
  const effective=effectiveTheme(theme)
  const next=effective==='dark'?'light':'dark'
  return <button className="nav-link theme-switcher" title={`Switch to ${next} mode`} onClick={()=>onChange(next)}>
    {effective==='dark'?<Moon/>:<Sun/>}<span>{effective==='dark'?'Dark mode':'Light mode'}</span>
  </button>
}

function Sidebar({open,collapsed,onToggleCollapsed,page,setPage,pools,activePool,setActivePool,onCreated,username,onSignOut,theme,onThemeChange,notify}:{open:boolean;collapsed:boolean;onToggleCollapsed:()=>void;page:Page;setPage:(p:Page)=>void;pools:Pool[];activePool:number|null;setActivePool:(id:number)=>void;onCreated:()=>void;username:string;onSignOut:()=>void;theme:Theme;onThemeChange:(theme:Theme)=>void;notify:(m:string,k?:Toast['kind'])=>void}){
  const [creating,setCreating]=useState(false)
  const [context,setContext]=useState<{pool:Pool;x:number;y:number}|null>(null)
  const [transfer,setTransfer]=useState<{pool:Pool;mode:'copy'|'move'}|null>(null)
  const [deleting,setDeleting]=useState<Pool|null>(null)
  const [editing,setEditing]=useState<Pool|null>(null)
  useEffect(()=>{const close=()=>setContext(null);const key=(e:KeyboardEvent)=>{if(e.key==='Escape')setContext(null)};window.addEventListener('pointerdown',close);window.addEventListener('keydown',key);window.addEventListener('resize',close);window.addEventListener('scroll',close,true);return()=>{window.removeEventListener('pointerdown',close);window.removeEventListener('keydown',key);window.removeEventListener('resize',close);window.removeEventListener('scroll',close,true)}},[])
  const showMenu=(pool:Pool,x:number,y:number)=>{const scale=Number.parseFloat(getComputedStyle(document.body).zoom||'1')||1;const menuWidth=244,menuHeight=260;const left=Math.max(8,Math.min(x/scale,window.innerWidth/scale-menuWidth-8));const top=Math.max(8,Math.min(y/scale,window.innerHeight/scale-menuHeight-8));setContext({pool,x:left,y:top})}
  return <aside className={`sidebar ${open?'open':''} ${collapsed?'collapsed':''}`}>
    <div className="brand"><Logo/><div><strong>LexiLoop</strong><span>Vocabulary studio</span></div><button className="icon-button collapse-sidebar" title="Hide navigation" onClick={onToggleCollapsed}><PanelLeftClose size={18}/></button><button className="icon-button close-mobile" onClick={()=>setPage(page)}><X size={19}/></button></div>
    <nav className="main-nav">
      <Nav active={page==='home'} icon={<Gauge/>} label="Overview" onClick={()=>setPage('home')}/>
      <Nav active={page==='study'} icon={<BrainCircuit/>} label="Study" onClick={()=>setPage('study')} badge={pools.reduce((n,p)=>n+p.due_count,0)}/>
      <Nav active={page==='library'} icon={<Library/>} label="Library" onClick={()=>setPage('library')}/>
      <Nav active={page==='analytics'} icon={<CircleDollarSign/>} label="AI usage" onClick={()=>setPage('analytics')}/>
    </nav>
    <div className="sidebar-section-title"><span>YOUR POOLS</span><button onClick={()=>setCreating(true)} title="New pool"><Plus size={16}/></button></div>
    <div className="pool-list">
      {pools.map(p=><div className="pool-row" key={p.id} onContextMenu={e=>{e.preventDefault();showMenu(p,e.clientX,e.clientY)}}>
        <button className={`pool-link ${activePool===p.id?'active':''}`} onClick={()=>setActivePool(p.id)}>
          <span className={`pool-dot ${poolAccentClass(p.accent)}`}/><span>{p.name}</span><small>{p.card_count}</small>
        </button>
        <button className="pool-more" title={`Actions for ${p.name}`} onClick={e=>{e.stopPropagation();const r=e.currentTarget.getBoundingClientRect();showMenu(p,r.right-8,r.bottom+5)}}><MoreVertical size={15}/></button>
      </div>)}
      {!pools.length && <div className="sidebar-empty">Create a pool to begin.</div>}
    </div>
    <div className="sidebar-bottom">
      <ThemeButton theme={theme} onChange={onThemeChange}/>
      <Nav active={page==='settings'} icon={<SettingsIcon/>} label="Settings" onClick={()=>setPage('settings')}/>
      <div className="user-chip"><div className="mini-avatar">{username.slice(0,2).toUpperCase()}</div><span>{username}</span><button onClick={onSignOut} title="Sign out"><LogOut size={17}/></button></div>
    </div>
    {/* Portaled to body: below 1050px the sidebar carries a transform (which
        makes it the containing block for position:fixed) and scrolls its own
        overflow, so a menu rendered inside it gets mispositioned and clipped. */}
    {context&&createPortal(<div className="pool-context-menu" style={{left:context.x,top:context.y}} onPointerDown={e=>e.stopPropagation()}>
      <div><span className={`pool-dot ${poolAccentClass(context.pool.accent)}`}/><b>{context.pool.name}</b></div>
      <button onClick={()=>{setEditing(context.pool);setContext(null)}}><Edit3 size={16}/><span>Rename or change color</span></button>
      <button onClick={()=>{setTransfer({pool:context.pool,mode:'copy'});setContext(null)}}><Copy size={16}/><span>Copy into another pool</span></button>
      <button onClick={()=>{setTransfer({pool:context.pool,mode:'move'});setContext(null)}}><GitMerge size={16}/><span>Merge and remove source</span></button>
      <button className="danger" onClick={()=>{setDeleting(context.pool);setContext(null)}}><Trash2 size={16}/><span>Delete pool</span></button>
    </div>,document.body)}
    {creating && <PoolModal onClose={()=>setCreating(false)} onSaved={async()=>{setCreating(false);await onCreated()}}/>}
    {editing&&<PoolEditModal pool={editing} onClose={()=>setEditing(null)} onSaved={async()=>{setEditing(null);await onCreated();notify('Pool updated')}}/>}
    {transfer&&<PoolTransferModal source={transfer.pool} mode={transfer.mode} pools={pools} onClose={()=>setTransfer(null)} onSaved={async target=>{setTransfer(null);setActivePool(target);await onCreated();notify(transfer.mode==='copy'?'Cards copied without changing the source pool.':'Pools merged. Cards and AI usage now belong to the destination.')}}/>}
    {deleting&&<PoolDeleteModal pool={deleting} onClose={()=>setDeleting(null)} onDeleted={async()=>{setDeleting(null);await onCreated();notify(`Deleted “${deleting.name}”`)}}/>}
  </aside>
}
function Nav({active,icon,label,onClick,badge}:{active:boolean;icon:React.ReactNode;label:string;onClick:()=>void;badge?:number}){
  return <button className={`nav-link ${active?'active':''}`} onClick={onClick}>{icon}<span>{label}</span>{Boolean(badge)&&<b>{badge}</b>}</button>
}

function poolAccentClass(accent:string){return `pool-accent-${accent||'emerald'}`}
function PoolTransferModal({source,mode,pools,onClose,onSaved}:{source:Pool;mode:'copy'|'move';pools:Pool[];onClose:()=>void;onSaved:(target:number)=>void}){
  const targets=pools.filter(p=>p.id!==source.id);const [target,setTarget]=useState(targets[0]?.id??0);const [busy,setBusy]=useState(false);const [error,setError]=useState('')
  const submit=async(e:React.FormEvent)=>{e.preventDefault();if(!target)return;setBusy(true);setError('');try{await api(`/pools/${source.id}/transfer/`,{method:'POST',body:JSON.stringify({target_pool:target,mode})});onSaved(target)}catch(err){setError((err as Error).message)}finally{setBusy(false)}}
  return <Modal title={mode==='copy'?'Copy cards into another pool':'Merge pools'} subtitle={mode==='copy'?'The source pool remains unchanged. Cards and current progress are copied; AI usage and review history are not duplicated.':'The destination keeps its name. Cards, review history, and historical AI usage move there. The source pool is deleted.'} onClose={onClose}><form className="modal-form" onSubmit={submit}><div className="pool-operation-source"><span className={`pool-dot ${poolAccentClass(source.accent)}`}/><div><small>Source pool</small><b>{source.name}</b><span>{source.card_count} cards</span></div></div><label>Destination pool<select value={target} onChange={e=>setTarget(Number(e.target.value))} required>{targets.map(p=><option key={p.id} value={p.id}>{p.name} · {p.card_count} cards</option>)}</select></label>{mode==='move'&&<div className="operation-warning"><AlertTriangle size={17}/><span>Duplicate words are consolidated. The more mature schedule is retained and the earlier due date wins.</span></div>}{!targets.length&&<div className="form-error">Create another pool first.</div>}{error&&<div className="form-error">{error}</div>}<div className="modal-actions"><button type="button" className="ghost" onClick={onClose}>Cancel</button><button className="primary" disabled={busy||!targets.length}>{busy?'Working…':mode==='copy'?'Copy cards':'Merge pools'}</button></div></form></Modal>
}
function PoolDeleteModal({pool,onClose,onDeleted}:{pool:Pool;onClose:()=>void;onDeleted:()=>void}){
  const [busy,setBusy]=useState(false);const [error,setError]=useState('')
  const remove=async()=>{setBusy(true);setError('');try{await api(`/pools/${pool.id}/`,{method:'DELETE'});onDeleted()}catch(err){setError((err as Error).message)}finally{setBusy(false)}}
  return <Modal title={`Delete “${pool.name}”?`} subtitle="This permanently deletes every card and schedule in this pool. Historical AI spend remains in analytics under Deleted pools." onClose={onClose}><div className="modal-form"><div className="delete-pool-hero"><Trash2/><div><b>{pool.card_count} cards will be deleted</b><span>This action cannot be undone.</span></div></div>{error&&<div className="form-error">{error}</div>}<div className="modal-actions"><button className="ghost" onClick={onClose}>Cancel</button><button className="danger-button" onClick={remove} disabled={busy}>{busy?'Deleting…':'Delete pool'}</button></div></div></Modal>
}

function PoolModal({onClose,onSaved}:{onClose:()=>void;onSaved:()=>void}){
  const [name,setName]=useState('');const [description,setDescription]=useState('');const [busy,setBusy]=useState(false);const [error,setError]=useState('')
  const submit=async(e:React.FormEvent)=>{e.preventDefault();setBusy(true);try{await api('/pools/',{method:'POST',body:JSON.stringify({name,description})});onSaved()}catch(err){setError((err as Error).message)}finally{setBusy(false)}}
  return <Modal title="Create a new pool" onClose={onClose}><form className="modal-form" onSubmit={submit}>
    <label>Pool name<input autoFocus value={name} onChange={e=>setName(e.target.value)} placeholder="Business English" required/></label>
    <label>Description<AutoTextarea value={description} onChange={e=>setDescription(e.target.value)} placeholder="Optional learning goal"/></label>
    {error&&<div className="form-error">{error}</div>}<div className="modal-actions"><button type="button" className="ghost" onClick={onClose}>Cancel</button><button className="primary" disabled={busy}>Create pool</button></div>
  </form></Modal>
}

function PoolEditModal({pool,onClose,onSaved}:{pool:Pool;onClose:()=>void;onSaved:()=>void}){
  const [name,setName]=useState(pool.name)
  const [description,setDescription]=useState(pool.description||'')
  const [accent,setAccent]=useState<AccentColor>((ACCENTS.includes(pool.accent as AccentColor)?pool.accent:'emerald') as AccentColor)
  const [busy,setBusy]=useState(false)
  const [error,setError]=useState('')
  const submit=async(e:React.FormEvent)=>{e.preventDefault();setBusy(true);setError('');try{await api(`/pools/${pool.id}/`,{method:'PATCH',body:JSON.stringify({name:name.trim(),description,accent})});onSaved()}catch(err){setError((err as Error).message)}finally{setBusy(false)}}
  return <Modal title="Edit pool" subtitle="Rename this collection or give it a more recognizable color." onClose={onClose}><form className="modal-form pool-edit-form" onSubmit={submit}>
    <div className="pool-operation-source"><span className={`pool-dot ${poolAccentClass(accent)}`}/><div><small>Preview</small><b>{name||pool.name}</b><span>{pool.card_count} cards</span></div></div>
    <label>Pool name<input autoFocus value={name} onChange={e=>setName(e.target.value)} placeholder="Business English" required/></label>
    <label>Description<AutoTextarea value={description} onChange={e=>setDescription(e.target.value)} placeholder="Optional learning goal"/></label>
    <div className="pool-edit-accent"><span>Pool color</span><AccentPicker value={accent} set={setAccent}/></div>
    {error&&<div className="form-error">{error}</div>}
    <div className="modal-actions"><button type="button" className="ghost" onClick={onClose}>Cancel</button><button className="primary" disabled={busy||!name.trim()}>{busy?'Saving…':'Save pool'}</button></div>
  </form></Modal>
}

function Home({pools,activePool,setActivePool,go,refreshPools}:{pools:Pool[];activePool:number|null;setActivePool:(n:number)=>void;go:(p:Page)=>void;refreshPools:()=>Promise<void>}){
  const [data,setData]=useState<Overview|null>(null)
  useEffect(()=>{void Promise.all([api<Overview>('/overview/').then(setData),refreshPools()]).catch(()=>{})},[refreshPools])
  // Zeros flashing before the real numbers looked like a glitch; show the
  // same loader the AI usage page uses until the overview arrives.
  if(!data)return <Loader text="Loading your overview…"/>
  return <div className="stack-xl">
    <section className="hero-panel">
      <div><span className="badge"><Flame size={14}/>{data?.streak??0} day streak</span><h2>Build a vocabulary that<br/><em>stays with you.</em></h2><p>{data?.due_now?`${data.due_now} cards are ready for review.`:'You are caught up. Add a few words or explore your library.'}</p>
        <div className="hero-actions"><button className="primary big" onClick={()=>go('study')}><BrainCircuit size={18}/>Start studying</button><button className="secondary big" onClick={()=>go('library')}><Plus size={18}/>Add words</button></div>
      </div><div className="hero-visual"><div className="ring" style={{background:`conic-gradient(var(--primary) 0 ${Math.max(0,Math.min(100,data?.retention??0))}%, var(--surface3) ${Math.max(0,Math.min(100,data?.retention??0))}% 100%)`}}><strong>{Math.round(data?.retention??0)}%</strong><span>retention</span></div><div className="floating-card f1">ubiquitous <Check size={15}/></div><div className="floating-card f2">meticulous <Sparkles size={15}/></div></div>
    </section>
    <div className="stat-grid">
      <Stat icon={<BookOpen/>} value={data?.total_cards??0} label="Total cards" hint="across all pools"/>
      <Stat icon={<Clock3/>} value={data?.due_now??0} label="Due now" hint="ready to review" accent/>
      <Stat icon={<Zap/>} value={data?.reviews_today??0} label="Reviews today" hint="keep the loop moving"/>
      <Stat icon={<ShieldCheck/>} value={`${data?.retention??0}%`} label="Answer retention" hint="all-time accepted"/>
    </div>
    <section className="panel activity-panel"><div className="section-heading"><div><span className="eyebrow">STUDY ACTIVITY</span><h2>Your learning year</h2></div><span className="muted">{(data?.activity??[]).reduce((n,x)=>n+x.reviews,0).toLocaleString()} reviews in the last year</span></div><ActivityHeatmap rows={data?.activity??[]}/></section>
    <section><div className="section-heading"><div><span className="eyebrow">COLLECTIONS</span><h2>Your pools</h2></div><button className="text-button" onClick={()=>go('library')}>Open library <ArrowRight size={16}/></button></div>
      <div className="pool-card-grid">{pools.map(p=><button className="pool-card" key={p.id} onClick={()=>{setActivePool(p.id);go('library')}}><div className={`pool-icon ${poolAccentClass(p.accent)}`}><BookOpen/></div><div><h3>{p.name}</h3><p>{p.description||'Your vocabulary collection'}</p></div><div className="pool-meta"><span>{p.card_count} cards</span><span className={p.due_count?'due':''}>{p.due_count} due</span></div><ChevronRight className="pool-arrow"/></button>)}
        {!pools.length&&<Empty title="No pools yet" text="Create your first pool from the sidebar, then add a word and let AI fill in the rest." icon={<FolderPlus/>}/>}</div>
    </section>
  </div>
}
function dateKey(date:Date){return `${date.getFullYear()}-${String(date.getMonth()+1).padStart(2,'0')}-${String(date.getDate()).padStart(2,'0')}`}
const MONTH_NAMES=['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
function useMediaQuery(query:string){
  const [matches,setMatches]=useState(()=>matchMedia(query).matches)
  useEffect(()=>{const media=matchMedia(query);const listener=()=>setMatches(media.matches);media.addEventListener('change',listener);return()=>media.removeEventListener('change',listener)},[query])
  return matches
}
const VERTICAL_RECENT_WEEKS=13
function ActivityHeatmap({rows}:{rows:{day:string;reviews:number}[]}){
  // Narrow screens get a vertical grid (weeks as rows, most recent on top)
  // instead of a horizontally scrolling year.
  const vertical=useMediaQuery('(max-width:820px)')
  const [expanded,setExpanded]=useState(false)
  const scrollRef=useRef<HTMLDivElement>(null)
  useEffect(()=>{const el=scrollRef.current;if(el)el.scrollLeft=el.scrollWidth},[rows.length,vertical])
  const byDay=new Map(rows.map(row=>[row.day,row.reviews]))
  const today=new Date();today.setHours(0,0,0,0)
  const start=new Date(today);start.setDate(start.getDate()-364)
  start.setDate(start.getDate()-((start.getDay()+6)%7)) // back to Monday
  const weeks:{date:Date;key:string;count:number}[][]=[]
  for(let day=new Date(start);day<=today;day.setDate(day.getDate()+1)){
    const date=new Date(day)
    if(!weeks.length||weeks[weeks.length-1].length===7)weeks.push([])
    weeks[weeks.length-1].push({date,key:dateKey(date),count:byDay.get(dateKey(date))??0})
  }
  // Absolute thresholds: scaling against the user's own yearly maximum made a
  // 2-review day on a quiet account as bright as a 100-review day elsewhere.
  const LEVEL_THRESHOLDS=[1,10,50,120]
  const level=(count:number)=>LEVEL_THRESHOLDS.reduce((current,min,index)=>count>=min?index+1:current,0)
  const LEVEL_TITLES=['No reviews','1–9 reviews','10–49 reviews','50–119 reviews','120+ reviews']
  const cellTitle=(cell:{date:Date;count:number})=>`${cell.count} review${cell.count===1?'':'s'} on ${cell.date.toLocaleDateString('en-US',{month:'short',day:'numeric',year:'numeric'})}`
  const legend=<div className="activity-legend"><span>Less</span>{[0,1,2,3,4].map(value=><span key={value} className={`activity-cell level-${value}`} title={LEVEL_TITLES[value]}/>)}<span>More</span></div>
  if(vertical){
    const recentFirst=[...weeks].reverse()
    const shown=expanded?recentFirst:recentFirst.slice(0,VERTICAL_RECENT_WEEKS)
    let lastLabel=''
    return <div className="activity-vertical" role="img" aria-label="Daily study activity, most recent week first">
      <div className="activity-v-row activity-v-head"><span className="activity-v-month"/>{['M','T','W','T','F','S','S'].map((day,index)=><b key={index}>{day}</b>)}</div>
      {shown.map((week,index)=>{
        const monthStart=week.find(cell=>cell.date.getDate()===1)
        let label=monthStart?MONTH_NAMES[monthStart.date.getMonth()]:(index===0?MONTH_NAMES[week[week.length-1].date.getMonth()]:'')
        if(label&&label===lastLabel)label=''
        if(label)lastLabel=label
        return <div className="activity-v-row" key={week[0].key}>
          <span className="activity-v-month">{label}</span>
          {week.map(cell=><span key={cell.key} className={`activity-cell level-${level(cell.count)}`} title={cellTitle(cell)}/>)}
        </div>
      })}
      <div className="activity-v-foot"><button type="button" className="text-button" onClick={()=>setExpanded(!expanded)}>{expanded?'Show recent weeks':'Show the full year'}<ChevronDown size={14} style={expanded?{transform:'rotate(180deg)'}:undefined}/></button>{legend}</div>
    </div>
  }
  const monthLabel=(index:number)=>{
    const month=weeks[index][0].date.getMonth()
    if(index===0)return MONTH_NAMES[month]
    return month!==weeks[index-1][0].date.getMonth()?MONTH_NAMES[month]:''
  }
  return <div className="activity-scroll" ref={scrollRef}><div className="activity-grid-wrap">
    <div className="activity-months">{weeks.map((_,index)=><span key={index}>{monthLabel(index)}</span>)}</div>
    <div className="activity-body">
      <div className="activity-weekdays"><span>Mon</span><span>Wed</span><span>Fri</span></div>
      <div className="activity-grid" role="img" aria-label="Daily study activity for the last year">
        {weeks.map((week,index)=><div className="activity-week" key={index}>
          {week.map(cell=><span key={cell.key} className={`activity-cell level-${level(cell.count)}`} title={cellTitle(cell)}/>)}
        </div>)}
      </div>
    </div>
    {legend}
  </div></div>
}
function NotFound({onHome}:{onHome:()=>void}){return <div className="center-stage"><Empty icon={<AlertTriangle/>} title="Page not found" text="This address is not part of LexiLoop. Admin, API, and application pages now have separate routes."/><div className="empty-actions"><button className="primary" onClick={onHome}><ArrowRight size={16}/>Return to Overview</button></div></div>}
function Stat({icon,value,label,hint,accent=false}:{icon:React.ReactNode;value:string|number;label:string;hint:string;accent?:boolean}){return <div className={`stat-card ${accent?'accent':''}`}><div className="stat-icon">{icon}</div><div><strong>{value}</strong><span>{label}</span><small>{hint}</small></div></div>}
function wait(ms:number){return new Promise(resolve=>window.setTimeout(resolve,ms))}
// The review endpoint answers in milliseconds (DB statement timeout is 15 s),
// so anything slower is a stuck connection worth surfacing quickly.
const REVIEW_TIMEOUT_MS=20_000
// The judge has a 40 s server-side deadline; the extra slack covers the network.
const JUDGE_TIMEOUT_MS=50_000
async function reviewCurrentCard(cardId:number,payload:Record<string,unknown>){
  try{return await api(`/study/${cardId}/review/`,{method:'POST',body:JSON.stringify(payload)},REVIEW_TIMEOUT_MS)}
  catch(error){
    if(error instanceof ApiError && error.status===409){await wait(850);return await api(`/study/${cardId}/review/`,{method:'POST',body:JSON.stringify(payload)},REVIEW_TIMEOUT_MS)}
    throw error
  }
}

function Study({activePool,notify}:{activePool:number|null;notify:(m:string,k?:Toast['kind'])=>void}){
  type StudyMode = 'due'|'practice'
  type QueueBreakdown = {new:number;learning:number;review:number}
  type StudySession = {card:Card|null;direction:Direction;prompt?:string;message?:string;mode?:StudyMode;practice_complete?:boolean;queue_count?:number;round_total?:number;round_completed?:number;queue_breakdown?:QueueBreakdown;show_images?:boolean;image_animations?:string[];image_animation_durations?:Record<string,number>;upcoming_images?:{id:number;image_key:string}[]}
  const [session,setSession]=useState<StudySession|null>(null)
  const [mode,setMode]=useState<StudyMode>('due')
  const [practiceSeen,setPracticeSeen]=useState<number[]>([])
  const [roundCompleted,setRoundCompleted]=useState(0)
  const [roundTotal,setRoundTotal]=useState(0)
  const [answer,setAnswer]=useState('')
  const [judge,setJudge]=useState<JudgeResult|null>(null)
  const [revealed,setRevealed]=useState(false)
  const [busy,setBusy]=useState(false)
  const [started,setStarted]=useState(Date.now())
  const [responseMs,setResponseMs]=useState<number|null>(null)
  const [hintLetters,setHintLetters]=useState(0)
  const [reviewed,setReviewed]=useState(false)
  const [promptImage,setPromptImage]=useState<{thumb?:string;full?:string;loaded:boolean;bright?:boolean;portrait?:boolean}|null>(null)
  const [imageEditor,setImageEditor]=useState(false)
  const reviewedRef=useRef(false)
  const cardRef=useRef<HTMLElement>(null)
  const load=useCallback(async(requestedMode:StudyMode='due',excluded:number[]=[],completed=0,resetRound=false,forcedTotal?:number)=>{
    setBusy(true)
    try{
      const params=new URLSearchParams({mode:requestedMode})
      if(activePool)params.set('pool',String(activePool))
      if(requestedMode==='practice'&&excluded.length)params.set('exclude',excluded.join(','))
      const data=await api<StudySession>(`/study/next/?${params.toString()}`)
      reviewedRef.current=false
      setReviewed(false)
      setSession(data);setMode(requestedMode);setAnswer('');setJudge(null);setRevealed(false);setResponseMs(null);setHintLetters(0);setStarted(Date.now())
      if(requestedMode==='practice'){
        setRoundCompleted(data.round_completed??excluded.length)
        setRoundTotal(data.round_total??Math.max(excluded.length+(data.queue_count??0),0))
      }else{
        setRoundCompleted(completed)
        setRoundTotal(previous=>forcedTotal!==undefined?Math.max(forcedTotal,completed+(data.queue_count??0)):resetRound?(data.queue_count??0):Math.max(previous,completed+(data.queue_count??0)))
      }
    }catch(e){notify((e as Error).message,'error')}finally{setBusy(false)}
  },[activePool])
  useEffect(()=>{setPracticeSeen([]);void load('due',[],0,true)},[load])
  const card=session?.card
  useEffect(()=>{
    if(!card||!cardRef.current)return
    if(matchMedia('(min-width: 821px) and (max-height: 900px)').matches){
      requestAnimationFrame(()=>cardRef.current?.scrollIntoView({block:'start',behavior:'auto'}))
    }
  },[card?.id])
  const showImages=session?.show_images!==false
  const enabledAnimations=session?.image_animations??ANIMATION_CHOICES.map(choice=>choice.id)
  useEffect(()=>{
    let alive=true
    setPromptImage(null)
    if(!card?.has_image||!showImages)return
    // The tiny blurred thumb paints first; the full image starts its reveal
    // animation only after it is decoded, so the animation never stutters.
    void cardImageObjectUrl(card.id,card.image_key,'thumb').then(async url=>{
      const luminance=await measureLuminance(url)
      if(alive)setPromptImage(previous=>({loaded:false,...(previous||{}),thumb:url,bright:luminance>0.58}))
    }).catch(()=>{})
    void cardImageObjectUrl(card.id,card.image_key,'full').then(url=>{
      const probe=document.createElement('img')
      probe.src=url
      const ready=()=>{if(alive)setPromptImage(previous=>({...(previous||{}),full:url,loaded:true,portrait:probe.naturalHeight>probe.naturalWidth*1.15}))}
      if(probe.decode)probe.decode().then(ready,ready);else probe.onload=ready
    }).catch(()=>{})
    return()=>{alive=false}
  },[card?.id,card?.image_key,showImages])
  useEffect(()=>{
    // Warm the blob cache for the next cards so their reveal is instant.
    for(const upcoming of session?.upcoming_images||[]){
      void cardImageObjectUrl(upcoming.id,upcoming.image_key,'thumb').catch(()=>{})
      void cardImageObjectUrl(upcoming.id,upcoming.image_key,'full').catch(()=>{})
    }
  },[session?.upcoming_images])
  const elapsed=()=>Math.max(0,Date.now()-started)
  const markReviewed=useCallback((cardId:number)=>{
    reviewedRef.current=true
    setReviewed(true)
    if(mode==='practice'){
      setPracticeSeen(previous=>previous.includes(cardId)?previous:[...previous,cardId])
      setRoundCompleted(previous=>practiceSeen.includes(cardId)?previous:previous+1)
    }else{
      setRoundCompleted(previous=>previous+1)
    }
  },[mode,practiceSeen])
  const recordReview=useCallback(async(result?:JudgeResult|null,measuredOverride?:number)=>{
    if(!card)return false
    if(reviewedRef.current)return true
    const measured=measuredOverride??responseMs??elapsed()
    reviewedRef.current=true
    setBusy(true)
    try{
      await reviewCurrentCard(card.id,{
        answer,direction:session?.direction,judge_score:result?.score,judge_verdict:result?.verdict,
        feedback:result?.feedback,accepted:result?.accepted??false,response_ms:measured,practice:mode==='practice',hint_revealed_letters:hintLetters,hint_total_letters:recallLetterCount(card.term)
      })
      markReviewed(card.id)
      return true
    }catch(e){
      reviewedRef.current=false
      setReviewed(false)
      notify((e as Error).message,'error')
      return false
    }finally{setBusy(false)}
  },[card,answer,session?.direction,responseMs,started,mode,hintLetters,markReviewed,notify])
  const submit=async()=>{
    if(!card||!answer.trim()||busy)return
    const measured=responseMs??elapsed();setResponseMs(measured);setBusy(true)
    try{
      // The judge endpoint records the review server-side in the same request;
      // recordReview remains only as a fallback for a lost lock race.
      const result=await api<JudgeResult>(`/study/${card.id}/judge/`,{method:'POST',body:JSON.stringify({
        answer,direction:session?.direction,response_ms:measured,practice:mode==='practice',
        hint_revealed_letters:hintLetters,hint_total_letters:recallLetterCount(card.term)
      })},JUDGE_TIMEOUT_MS)
      setJudge(result)
      if(result.review_recorded)markReviewed(card.id)
      else await recordReview(result,measured)
    }catch(e){notify((e as Error).message,'error')}finally{setBusy(false)}
  }
  const reveal=()=>{
    if(!card||busy)return
    const measured=responseMs??elapsed()
    if(responseMs===null)setResponseMs(measured)
    setRevealed(true)
    void recordReview(judge,measured)
  }
  const next=async()=>{
    if(!card||busy||(!judge&&!revealed))return
    const wasReviewed=reviewedRef.current
    if(!wasReviewed){
      const saved=await recordReview(judge,responseMs??elapsed())
      if(!saved)return
    }
    setBusy(true)
    try{
      if(mode==='practice'){
        const nextSeen=practiceSeen.includes(card.id)?practiceSeen:[...practiceSeen,card.id]
        setPracticeSeen(nextSeen);await load('practice',nextSeen,nextSeen.length)
      }else{
        const completed=roundCompleted+(wasReviewed?0:1);await load('due',[],completed)
      }
    }catch(e){notify((e as Error).message,'error')}finally{setBusy(false)}
  }
  const suspendCurrent=async()=>{if(!card||busy)return;setBusy(true);try{await api(`/flashcards/${card.id}/suspend/`,{method:'POST'});notify(`Blocked “${card.term}” from future study`);if(mode==='practice'){const nextSeen=[...practiceSeen,card.id];setPracticeSeen(nextSeen);await load('practice',nextSeen,nextSeen.length)}else{const adjustedTotal=Math.max(roundCompleted,roundTotal-1);await load('due',[],roundCompleted,false,adjustedTotal)}}catch(e){notify((e as Error).message,'error')}finally{setBusy(false)}}
  const startPractice=()=>{setPracticeSeen([]);void load('practice',[],0,true)}
  const returnToDue=()=>{setPracticeSeen([]);void load('due',[],0,true)}
  useEffect(()=>{const fn=(e:KeyboardEvent)=>{
    if(!card||busy||e.repeat||imageEditor||document.visibilityState!=='visible'||!document.hasFocus())return
    const target=e.target as HTMLElement|null
    const typing=Boolean(target?.closest('input, textarea, select, [contenteditable="true"]'))
    const enter=e.key==='Enter'||e.code==='NumpadEnter'
    const revealShortcut=(e.ctrlKey||e.metaKey)&&(
      e.code==='Slash'||e.key==='?'||e.key==='/'
    )
    const suspendShortcut=(e.ctrlKey||e.metaKey)&&(e.code==='Minus'||e.code==='NumpadSubtract'||e.key==='-')
    if(suspendShortcut){e.preventDefault();e.stopPropagation();void suspendCurrent();return}
    if(judge||revealed){
      if(!e.altKey&&!e.shiftKey&&(e.key==='ArrowRight'||enter)){e.preventDefault();void next()}
      return
    }
    if(revealShortcut){e.preventDefault();e.stopPropagation();reveal();return}
    if((e.ctrlKey||e.metaKey)&&enter){e.preventDefault();void submit();return}
    if(typing)return
  };window.addEventListener('keydown',fn,{capture:true});return()=>window.removeEventListener('keydown',fn,{capture:true})},[card,judge,revealed,answer,busy,mode,practiceSeen,responseMs,started,roundCompleted,reviewed,imageEditor])
  if(busy&&!session)return <Loader text="Choosing the right card…"/>
  if(!card){
    const practiceComplete=mode==='practice'&&session?.practice_complete
    return <div className="center-stage"><Empty icon={practiceComplete?<RotateCcw/>:<Check/>} title={practiceComplete?'Practice round complete':'You are caught up'} text={session?.message||'No cards are due right now.'}/><div className="empty-actions">{mode==='due'?<><button className="primary" onClick={startPractice}><RotateCcw size={16}/>Practice all cards now</button><button className="secondary" onClick={()=>void load('due',[],0,true)}>Check due cards</button></>:<><button className="primary" onClick={startPractice}><RotateCcw size={16}/>Practice again</button><button className="secondary" onClick={returnToDue}>Return to due reviews</button></>}</div></div>
  }
  const defMode=session.direction==='term_to_definition'
  const sentenceMode=session.direction==='term_to_sentence'
  const showsTerm=defMode||sentenceMode
  const responseTime=responseMs===null?'':humanDuration(responseMs)
  // queue_count and queue_breakdown were counted with the on-screen card still
  // in the queue; once its review is saved they are one card stale.
  const remaining=Math.max(0,(session.queue_count??0)-(reviewed?1:0))
  const total=Math.max(roundTotal,roundCompleted+remaining)
  const progress=total?Math.min(100,100*roundCompleted/total):0
  const servedAs=card.schedule.state==='new'?'new':card.schedule.state==='review'?'review':'learning'
  const breakdown=session.queue_breakdown&&reviewed
    ?{...session.queue_breakdown,[servedAs]:Math.max(0,session.queue_breakdown[servedAs]-1)}
    :session.queue_breakdown
  return <div className="study-layout">
    <div className="study-progress"><div className="study-progress-copy"><span>{mode==='practice'?'Practice round':'Due review round'}</span><small>{roundCompleted} done · {remaining} left{mode==='practice'?' in this pool':''}</small></div><div className="study-progress-track"><div role="progressbar" aria-valuemin={0} aria-valuemax={total} aria-valuenow={roundCompleted}><i style={{width:`${progress}%`}}/></div>{mode==='due'&&breakdown&&remaining>0&&<div className="queue-chips" aria-label="Remaining queue composition">{breakdown.new>0&&<span className="qc-new" title={`${breakdown.new} brand-new card${breakdown.new===1?'':'s'} within today's limit`}>{breakdown.new} new</span>}{breakdown.learning>0&&<span className="qc-learning" title={`${breakdown.learning} card${breakdown.learning===1?' is':'s are'} in short learning steps — failed or recently added cards return here`}>{breakdown.learning} learning</span>}{breakdown.review>0&&<span className="qc-review" title={`${breakdown.review} graduated card${breakdown.review===1?'':'s'} scheduled for review today`}>{breakdown.review} review</span>}</div>}</div><button className="practice-switch" title={mode==='practice'?'Return to cards scheduled as due by spaced repetition':'Study every card once now without changing its due date'} onClick={()=>mode==='practice'?returnToDue():startPractice()}>{mode==='practice'?'Due reviews':'Practice all'}</button></div>
    <article ref={cardRef} className={`study-card ${judge?.accepted?'correct':judge&&!judge.accepted?'wrong':''}`}>
      <div className={`card-topline task-${session.direction}`}><span>{defMode?'Explain this word':sentenceMode?'Use this word in a sentence':'Recall the word'}</span><div className="topline-tools"><button className="topline-image-button" title={card.has_image?'Change this card’s image':'Add an image to this card'} onClick={()=>setImageEditor(true)}>{card.has_image?<ImageIcon size={15}/>:<ImagePlus size={15}/>}</button><span className="state-pill">{mode==='practice'?'practice':card.schedule.state}</span></div></div>
      <div className={`study-prompt ${promptImage?'has-image':''} ${promptImage?.loaded?'image-loaded':''} ${promptImage?.bright?'image-bright':''} ${promptImage?.portrait?'image-portrait':''}`}>
        {promptImage&&<div key={`${card.id}|${card.image_key}`} className={`prompt-visual anim-${enabledAnimations.length?enabledAnimations[card.id%enabledAnimations.length]:'fade'}`} style={Object.fromEntries(Object.entries(ANIMATION_DEFAULT_SECONDS).map(([name,fallback])=>[`--dur-${name}`,`${session.image_animation_durations?.[name]??fallback}s`])) as React.CSSProperties} aria-hidden="true">{promptImage.thumb&&<i className="prompt-visual-thumb" style={{backgroundImage:`url(${promptImage.thumb})`}}/>}{promptImage.full&&<span className="prompt-visual-frame"><i className="prompt-visual-full" style={{backgroundImage:`url(${promptImage.full})`}}/></span>}<i className="prompt-visual-scrim"/></div>}
        <div className="prompt-content">
        <h2>{session.prompt}</h2>{showsTerm&&card.ipa&&<div className="pronunciation">/{card.ipa}/ <button onClick={()=>void playPronunciation(card.term).catch(e=>notify((e as Error).message,'error'))}><Volume2 size={17}/></button></div>}
        {showsTerm&&card.part_of_speech&&<span className="pos">{card.part_of_speech}</span>}
        {!showsTerm&&<RecallHints card={card} revealed={hintLetters} onReveal={()=>setHintLetters(n=>Math.min(recallLetterCount(card.term),n+1))}/>}
        </div>
      </div>
      {!judge&&!revealed&&<div className="answer-area"><label>{defMode?'Write the meaning in your own words':sentenceMode?'Write one sentence using this word':'Type the English word or accepted phrase'}<AutoTextarea autoFocus value={answer} onChange={e=>setAnswer(e.target.value)} placeholder={defMode?'A clear paraphrase is enough…':sentenceMode?'Any natural sentence that shows the meaning…':'Your answer…'}/></label><div className="answer-actions"><button className="ghost" onClick={reveal}>Show answer</button><button className="primary" onClick={submit} disabled={busy||!answer.trim()}>{busy?'Checking…':'Check answer'}<Sparkles size={17}/></button></div><small className="shortcut">⌘/Ctrl Enter checks · ⌘/Ctrl ? shows the answer</small></div>}
      {(judge||revealed)&&<div className="result-area">
        {judge&&<div className={`judge-banner ${judge.accepted?'accepted':'rejected'}`}><div className={`score-orb ${judge.grading==='binary'?'binary':''}`}>{judge.grading==='binary'?(judge.accepted?<Check size={24}/>:<X size={24}/>):judge.score}</div><div><b>{judge.accepted?'Correct':judge.grading==='binary'?'Incorrect':humanVerdict(judge.verdict)}</b>{distinctJudgeFeedback(judge)&&<p>{distinctJudgeFeedback(judge)}</p>}</div></div>}
        <div className="answer-reveal"><div className="answer-title-row"><div><h3>{card.term}</h3>{card.ipa&&<small>/{card.ipa}/</small>}</div><button className="answer-audio" onClick={()=>void playPronunciation(card.term).catch(e=>notify((e as Error).message,'error'))}><Volume2 size={17}/>Pronounce</button></div><p>{card.definition}</p><div className="answer-examples">{card.examples?.slice(0,3).map((example,index)=><blockquote key={`${example.sentence}-${index}`}>“{example.sentence}”{example.note&&<small>{example.note}</small>}</blockquote>)}</div>
          {(card.synonyms.length>0||card.collocations.length>0)&&<div className="chip-row">{card.synonyms.slice(0,4).map(x=><span key={x}>{x}</span>)}{card.collocations.slice(0,3).map(x=><span key={x}>{x}</span>)}</div>}
        </div>
        <div className="next-block"><div className="review-meta"><Clock3 size={16}/><span>{judge?(responseTime||'Answer checked'):reviewed?'Saved':'Answer revealed'}{mode==='practice'?' · Practice':''}</span></div><button className="primary next-task" onClick={next} disabled={busy}>{busy?'Loading…':<>Next task <ArrowRight size={17}/></>}</button></div>
      </div>}
    </article>
    <div className="study-footer"><span><KeyRound size={14}/> {defMode?'Definitions use a fixed 1–7 semantic rubric.':sentenceMode?'Sentences are graded on a fixed 1–7 usage rubric.':'Infinitive “to” is optional for verb recall.'}</span><span>⌘/Ctrl − blocks this card · Enter or Right Arrow continues</span></div>
    {imageEditor&&<Modal title="Card image" subtitle={`Shown on the flashcard for “${card.term}”.`} onClose={()=>setImageEditor(false)}><div className="modal-form"><CardImageControls card={card} notify={notify} onUpdated={updated=>setSession(previous=>previous&&previous.card?{...previous,card:updated}:previous)}/></div></Modal>}
  </div>
}
function humanVerdict(s:string){return s.split('_').map(x=>x[0].toUpperCase()+x.slice(1)).join(' ')}
function distinctJudgeFeedback(judge:JudgeResult){
  const title=(judge.accepted?'correct':judge.grading==='binary'?'incorrect':humanVerdict(judge.verdict)).toLowerCase().replace(/[.!?]+$/,'').trim()
  const feedback=(judge.feedback||'').toLowerCase().replace(/[.!?]+$/,'').trim()
  const generic=new Set(['correct','right','exact','incorrect','wrong'])
  return !feedback||feedback===title||generic.has(feedback)?'':judge.feedback
}
function humanDuration(milliseconds:number){
  const seconds=Math.max(0,Math.round(milliseconds/1000))
  if(seconds<60)return `${seconds}s`
  const minutes=Math.floor(seconds/60),remainingSeconds=seconds%60
  if(minutes<60)return remainingSeconds?`${minutes}m ${remainingSeconds}s`:`${minutes}m`
  const hours=Math.floor(minutes/60),remainingMinutes=minutes%60
  return remainingMinutes?`${hours}h ${remainingMinutes}m`:`${hours}h`
}
function RecallHints({card,revealed,onReveal}:{card:Card;revealed:number;onReveal:()=>void}){
  const examples=card.examples.slice(0,3).map(x=>maskRecallAnswer(x.sentence,card)).filter(x=>x.includes('_____'))
  const collocations=card.collocations.slice(0,3).map(x=>maskRecallAnswer(x,card)).filter(x=>x.includes('_____'))
  const total=recallLetterCount(card.term)
  return <div className="recall-hints">
    <div className="recall-hints-head"><CircleHelp size={16}/><b>Context clues</b><span>{card.part_of_speech||'English term'}</span><button type="button" className="letter-hint" onClick={onReveal} disabled={revealed>=total} title="Reveal one more letter; using hints lowers the scheduling grade"><span>{maskedTerm(card.term,revealed)}</span><small>{revealed}/{total}</small></button></div>
    {examples.length>0&&<div className="recall-examples">{examples.map((sentence,i)=><p key={`${sentence}-${i}`}><span>{i+1}</span>{sentence}</p>)}</div>}
    {collocations.length>0&&<div className="recall-collocations"><small>Common use</small>{collocations.map(x=><span key={x}>{x}</span>)}</div>}
    {!examples.length&&!collocations.length&&<p className="recall-fallback">Think of the word that best matches this definition and its grammatical role.</p>}
    {revealed>0&&<p className="hint-impact">{revealed/Math.max(1,total)>.4?'More than 40% revealed: this review counts as Again.':revealed/Math.max(1,total)>.2?'More than 20% revealed: the rating is capped at Hard.':'A letter hint was used: the rating is capped at Good.'}</p>}
  </div>
}
function maskRecallAnswer(text:string,card:Card){
  const base=card.term.replace(/^to\s+/i,'').trim()
  const aliases=card.aliases.filter((x):x is string=>typeof x==='string')
  const forms=Object.values(card.forms).filter((x):x is string=>typeof x==='string')
  const candidates=new Set<string>([card.term,base,...aliases,...forms])
  if(base&&!base.includes(' ')){
    candidates.add(`${base}s`);candidates.add(`${base}es`);candidates.add(`${base}ed`);candidates.add(`${base}ing`)
    if(base.endsWith('e')){candidates.add(`${base}d`);candidates.add(`${base.slice(0,-1)}ing`)}
    if(base.endsWith('y')){candidates.add(`${base.slice(0,-1)}ies`);candidates.add(`${base.slice(0,-1)}ied`)}
  }
  let result=text
  ;[...candidates].filter(Boolean).sort((a,b)=>b.length-a.length).forEach(value=>{
    const escaped=value.replace(/[.*+?^${}()|[\]\\]/g,'\\$&')
    result=result.replace(new RegExp(`\\b${escaped}\\b`,'gi'),'_____')
  })
  return result
}
function recallBase(term:string){return term.replace(/^to\s+/i,'').trim()}
function recallLetterCount(term:string){return (recallBase(term).match(/[A-Za-z]/g)||[]).length}
function maskedTerm(term:string,revealed:number){let remaining=revealed;return recallBase(term).split('').map(ch=>{if(!/[A-Za-z]/.test(ch))return ch;if(remaining>0){remaining-=1;return ch}return '_'}).join(' ')}
const pronunciationCache=new Map<string,string>()
let activePronunciation:HTMLAudioElement|null=null
async function playPronunciation(text:string){
  const key=text.trim().toLocaleLowerCase()
  let url=pronunciationCache.get(key)
  if(!url){const blob=await apiBlob(`/pronunciation/?text=${encodeURIComponent(text)}`);url=URL.createObjectURL(blob);pronunciationCache.set(key,url)}
  activePronunciation?.pause()
  activePronunciation=new Audio(url)
  await activePronunciation.play()
}

// Card images are served by an authenticated endpoint, so they are fetched as
// blobs (like pronunciation audio) and cached as object URLs. The image_key
// changes with every stored file, which makes the cache safe to keep forever.
// Cinematic reveal styles for the flashcard image; a card keeps "its"
// animation between sessions (picked deterministically among the enabled ones).
const ANIMATION_CHOICES=[
  {id:'mist',label:'Morning mist',hint:'the memory sharpens out of a blur'},
  {id:'ripple',label:'Ripple',hint:'one drop lands and spreads from the middle'},
  {id:'drift',label:'Slow drift',hint:'a quiet cinematic pan settles into place'},
  {id:'droplets',label:'Watercolor droplets',hint:'soft drops slowly soak through the card and merge'},
]
const ANIMATION_DEFAULT_SECONDS:Record<string,number>={mist:2.5,ripple:2.5,drift:2.5,droplets:8}
// While focused the field holds free text, so deleting or retyping digits
// never fights a clamped controlled value; the state receives a valid number
// on every parsable keystroke and the display snaps back to it on blur.
function NumberField({value,set,min,max,step=1,round=false}:{value:number;set:(v:number)=>void;min?:number;max?:number;step?:number|string;round?:boolean}){
  const [draft,setDraft]=useState<string|null>(null)
  return <input type="number" min={min} max={max} step={step} value={draft??String(value)}
    onChange={e=>{
      setDraft(e.target.value)
      let parsed=Number(e.target.value)
      if(e.target.value.trim()===''||!Number.isFinite(parsed))return
      if(round)parsed=Math.round(parsed)
      if(min!==undefined)parsed=Math.max(min,parsed)
      if(max!==undefined)parsed=Math.min(max,parsed)
      set(parsed)
    }}
    onBlur={()=>setDraft(null)}/>
}
const cardImageCache=new Map<string,Promise<string>>()
function cardImageObjectUrl(cardId:number,imageKey:string,size:'full'|'thumb'='full'):Promise<string>{
  const key=`${imageKey}|${size}`
  let promise=cardImageCache.get(key)
  if(!promise){
    // The v parameter varies with the stored file: the endpoint URL itself is
    // stable and served with immutable caching, so without it a replaced image
    // would keep coming out of the browser's HTTP cache.
    promise=apiBlob(`/flashcards/${cardId}/image/?${size==='thumb'?'size=thumb&':''}v=${encodeURIComponent(imageKey)}`).then(blob=>URL.createObjectURL(blob))
    promise.catch(()=>{cardImageCache.delete(key)})
    cardImageCache.set(key,promise)
  }
  return promise
}
// Average luminance of the blur-up thumb decides how strong the text scrim
// must be: white prompt text over a bright image needs a darker veil.
function measureLuminance(url:string):Promise<number>{
  return new Promise(resolve=>{
    const probe=document.createElement('img')
    probe.onload=()=>{
      try{
        const canvas=document.createElement('canvas')
        canvas.width=canvas.height=8
        const context=canvas.getContext('2d')!
        context.drawImage(probe,0,0,8,8)
        const data=context.getImageData(0,0,8,8).data
        let sum=0
        for(let i=0;i<data.length;i+=4)sum+=(.2126*data[i]+.7152*data[i+1]+.0722*data[i+2])/255
        resolve(sum/64)
      }catch{resolve(0)}
    }
    probe.onerror=()=>resolve(0)
    probe.src=url
  })
}

function CardImageControls({card,notify,onUpdated}:{card:Card;notify:(m:string,k?:Toast['kind'])=>void;onUpdated:(card:Card)=>void}){
  const [busy,setBusy]=useState(false)
  const [link,setLink]=useState('')
  const [preview,setPreview]=useState('')
  const fileRef=useRef<HTMLInputElement>(null)
  useEffect(()=>{
    let alive=true
    setPreview('')
    if(card.has_image)void cardImageObjectUrl(card.id,card.image_key).then(url=>{if(alive)setPreview(url)}).catch(()=>{})
    return()=>{alive=false}
  },[card.id,card.image_key,card.has_image])
  const send=async(body:FormData|string)=>{
    setBusy(true)
    try{
      const data=await api<Card&{image_source?:string}>(`/flashcards/${card.id}/image/`,{method:'POST',body},90_000)
      setLink('')
      onUpdated(data)
      notify(data.image_source==='ai'?'The image assistant picked a picture from that page':'Image saved')
    }catch(e){notify((e as Error).message,'error')}finally{setBusy(false)}
  }
  const fromFile=(file?:File)=>{if(!file)return;const form=new FormData();form.append('file',file);void send(form)}
  const fromLink=()=>{const url=link.trim();if(url&&!busy)void send(JSON.stringify({url}))}
  const remove=async()=>{
    setBusy(true)
    try{onUpdated(await api<Card>(`/flashcards/${card.id}/image/`,{method:'DELETE'}));notify('Image removed')}
    catch(e){notify((e as Error).message,'error')}finally{setBusy(false)}
  }
  return <div className="card-image-block">
    {card.has_image&&<div className="card-image-preview">{preview?<img src={preview} alt={`Illustration for ${card.term}`}/>:<div className="card-image-loading"><RefreshCw className="spin-slow" size={17}/></div>}</div>}
    <div className="card-image-link"><input value={link} onChange={e=>setLink(e.target.value)} placeholder="Image link, or a Yandex/Google image page" onKeyDown={e=>{if(e.key==='Enter'){e.preventDefault();fromLink()}}}/><button type="button" className="secondary" onClick={fromLink} disabled={busy||!link.trim()}>{busy?'Working…':<><ImagePlus size={15}/>Fetch</>}</button></div>
    <div className="card-image-actions">
      <input ref={fileRef} type="file" accept="image/*" hidden onChange={e=>{fromFile(e.target.files?.[0]??undefined);e.target.value=''}}/>
      <button type="button" className="secondary" onClick={()=>fileRef.current?.click()} disabled={busy}><Upload size={15}/>{card.has_image?'Replace file':'Upload file'}</button>
      {card.has_image&&<button type="button" className="danger-text" onClick={()=>void remove()} disabled={busy}><Trash2 size={15}/>Remove</button>}
    </div>
    <small className="card-image-hint">Any page link works — even a copied Google or Yandex image-search page: the image assistant finds the best matching picture when the link isn’t a file.</small>
  </div>
}

function LibraryPage({activePool,pools,notify,refreshPools}:{activePool:number|null;pools:Pool[];notify:(m:string,k?:Toast['kind'])=>void;refreshPools:()=>Promise<void>}){
  const PAGE_SIZE=30
  const [cards,setCards]=useState<Card[]>([]);const [search,setSearch]=useState('');const [debouncedSearch,setDebouncedSearch]=useState('');const [term,setTerm]=useState('');const [busy,setBusy]=useState(false);const [loading,setLoading]=useState(true);const [edit,setEdit]=useState<Card|null>(null);const [manual,setManual]=useState(false);const [bulk,setBulk]=useState(false);const [expanded,setExpanded]=useState<number|null>(null);const [page,setPage]=useState(1);const [total,setTotal]=useState(0)
  const totalPages=Math.max(1,Math.ceil(total/PAGE_SIZE))
  useEffect(()=>{const timer=window.setTimeout(()=>{setDebouncedSearch(search.trim());setPage(1)},250);return()=>window.clearTimeout(timer)},[search])
  useEffect(()=>{setPage(1);setExpanded(null)},[activePool])
  const load=useCallback(async(targetPage=page,targetSearch=debouncedSearch)=>{if(!activePool){setCards([]);setTotal(0);setLoading(false);return}setLoading(true);try{const data=await apiPage<Card>(`/flashcards/?pool=${activePool}&search=${encodeURIComponent(targetSearch)}&page=${targetPage}&page_size=${PAGE_SIZE}`);if(!data.results.length&&data.count&&targetPage>1){setPage(Math.max(1,Math.ceil(data.count/PAGE_SIZE)));return}setCards(data.results);setTotal(data.count);setExpanded(null)}catch(e){notify((e as Error).message,'error')}finally{setLoading(false)}},[activePool,debouncedSearch,page])
  useEffect(()=>{void load()},[load])
  const generate=async()=>{if(!activePool||!term.trim())return;setBusy(true);try{const card=await api<Card>('/generate/',{method:'POST',body:JSON.stringify({pool:activePool,term:term.trim()})},180_000);setTerm('');setPage(1);setDebouncedSearch('');setSearch('');notify(`Generated “${card.term}”`);await Promise.all([load(1,''),refreshPools()])}catch(e){notify((e as Error).message,'error')}finally{setBusy(false)}}
  const selected=pools.find(p=>p.id===activePool)
  const first=total?((page-1)*PAGE_SIZE)+1:0
  const last=Math.min(total,page*PAGE_SIZE)
  const pages=paginationWindow(page,totalPages)
  if(!activePool)return <Empty icon={<Library/>} title="Choose or create a pool" text="Pools keep different vocabulary goals separate."/>
  return <div className="stack-lg">
    <section className="generator-panel"><div className="generator-copy"><span className="badge"><WandSparkles size={14}/> One-field creation</span><h2>Add a word. AI builds the card.</h2><p>Definition, IPA, forms, examples, synonyms, collocations, and usage notes are generated automatically.</p></div><div className="generator-input"><input value={term} onChange={e=>setTerm(e.target.value)} onKeyDown={e=>{if(e.key==='Enter'&&(e.metaKey||e.ctrlKey)){e.preventDefault();void generate()}}} placeholder="Type a word or collocation…"/><button className="primary" onClick={generate} disabled={busy||!term.trim()}>{busy?'Generating…':<><Sparkles size={17}/>Generate</>}</button><small>⌘ Enter / Ctrl Enter</small></div></section>
    <div className="library-toolbar"><div><h2>{selected?.name}</h2><span>{loading?'Loading cards…':total?`${first}–${last} of ${total} cards`:'0 visible cards'}</span></div><div className="toolbar-actions"><div className="search"><Search size={17}/><input value={search} onChange={e=>setSearch(e.target.value)} placeholder="Search cards"/></div><button className="secondary" onClick={()=>setBulk(true)}><ListPlus size={16}/>Bulk AI</button><button className="secondary" onClick={()=>setManual(true)}><Plus size={16}/>Manual card</button></div></div>
    <div className="card-list">{loading?<Loader text="Loading cards…"/>:<>{cards.map(card=><div className={`library-card ${expanded===card.id?'expanded':''}`} key={card.id}>
      <button className="card-summary" onClick={()=>setExpanded(expanded===card.id?null:card.id)}><div className="word-cell"><div className="word-title"><h3>{card.term}</h3>{card.part_of_speech&&<span>{card.part_of_speech}</span>}</div><small>{card.ipa?`/${card.ipa}/`:card.short_definition}</small></div><p>{card.short_definition}</p><span className={`schedule-tag ${card.suspended?'blocked':card.schedule.state}`}>{card.suspended?'blocked':card.schedule.state}</span>{expanded===card.id?<ChevronDown/>:<ChevronRight/>}</button>
      {expanded===card.id&&<div className="card-details"><div className="definition-block"><span>DEFINITION</span><p>{card.definition}</p></div>{card.examples.length>0&&<div><span className="detail-label">EXAMPLES</span>{card.examples.map((x,i)=><div className="example" key={i}>“{x.sentence}” {x.note&&<small>{x.note}</small>}</div>)}</div>}
        {Object.keys(card.forms).length>0&&<div><span className="detail-label">FORMS</span><div className="chip-row">{Object.entries(card.forms).map(([k,v])=><span key={k}><b>{k}</b> {v}</span>)}</div></div>}
        <div className="detail-columns"><DetailList title="Synonyms" items={card.synonyms}/><DetailList title="Collocations" items={card.collocations}/><DetailList title="Antonyms" items={card.antonyms}/></div>{card.usage_notes&&<div className="note"><CircleHelp size={16}/>{card.usage_notes}</div>}
        <div><span className="detail-label">IMAGE</span><CardImageControls card={card} notify={notify} onUpdated={updated=>setCards(previous=>previous.map(existing=>existing.id===updated.id?updated:existing))}/></div>
        <div className="card-actions">{card.suspended&&<button className="ghost unblock-button" onClick={async()=>{await api(`/flashcards/${card.id}/unsuspend/`,{method:'POST'});await load();await refreshPools();notify(`Unblocked “${card.term}”`)}}><Unlock size={16}/>Unblock</button>}<button className="ghost" onClick={()=>void playPronunciation(card.term).catch(e=>notify((e as Error).message,'error'))}><Volume2 size={16}/>Pronounce</button><button className="ghost" onClick={()=>setEdit(card)}><Edit3 size={16}/>Edit</button><button className="danger-text" onClick={async()=>{if(confirm(`Delete “${card.term}”?`)){await api(`/flashcards/${card.id}/`,{method:'DELETE'});await load();await refreshPools()}}}><Trash2 size={16}/>Delete</button></div>
      </div>}
    </div>)}{!cards.length&&<Empty icon={<BookOpen/>} title="No cards found" text="Add a term above and press Generate. Editing stays out of the way until you need it."/>}</>}</div>
    {!loading&&totalPages>1&&<nav className="pagination" aria-label="Library pages"><button className="pagination-arrow" disabled={page<=1} onClick={()=>setPage(p=>Math.max(1,p-1))}><ChevronLeft size={17}/><span>Previous</span></button><div className="pagination-pages">{pages.map((item,index)=>item===null?<span className="pagination-ellipsis" key={`ellipsis-${index}`}>…</span>:<button key={item} className={item===page?'active':''} aria-current={item===page?'page':undefined} onClick={()=>setPage(item)}>{item}</button>)}</div><span className="pagination-mobile-label">Page {page} of {totalPages}</span><button className="pagination-arrow" disabled={page>=totalPages} onClick={()=>setPage(p=>Math.min(totalPages,p+1))}><span>Next</span><ChevronRight size={17}/></button></nav>}
    {(edit||manual)&&<CardEditor card={edit} pool={activePool} onClose={()=>{setEdit(null);setManual(false)}} onSaved={async()=>{setEdit(null);setManual(false);await load();await refreshPools();notify(edit?'Card updated':'Card created')}}/>}
    {bulk&&<BulkModal pool={activePool} onClose={()=>setBulk(false)} onDone={async(n,e)=>{setBulk(false);setPage(1);await load(1,debouncedSearch);await refreshPools();notify(`${n} cards created${e?`, ${e} failed`:''}`,n?'success':'error')}}/>}
  </div>
}
function paginationWindow(current:number,total:number):(number|null)[]{
  if(total<=7)return Array.from({length:total},(_,i)=>i+1)
  const values=new Set([1,total,current-1,current,current+1].filter(x=>x>=1&&x<=total))
  const sorted=[...values].sort((a,b)=>a-b);const output:(number|null)[]=[]
  sorted.forEach((value,index)=>{if(index&&value-sorted[index-1]>1)output.push(null);output.push(value)})
  return output
}

function DetailList({title,items}:{title:string;items:string[]}){if(!items.length)return null;return <div><span className="detail-label">{title}</span><div className="chip-row">{items.map(x=><span key={x}>{x}</span>)}</div></div>}

function CardEditor({card,pool,onClose,onSaved}:{card:Card|null;pool:number;onClose:()=>void;onSaved:()=>void}){
  const [form,setForm]=useState({term:card?.term||'',part_of_speech:card?.part_of_speech||'',ipa:card?.ipa||'',short_definition:card?.short_definition||'',definition:card?.definition||'',examples:card?.examples.map(x=>x.sentence).join('\n')||'',forms:card?Object.entries(card.forms).map(([k,v])=>`${k}: ${v}`).join('\n'):'',synonyms:card?.synonyms.join(', ')||'',antonyms:card?.antonyms.join(', ')||'',collocations:card?.collocations.join(', ')||'',usage_notes:card?.usage_notes||'',aliases:card?.aliases.join(', ')||''})
  const [busy,setBusy]=useState(false);const [error,setError]=useState('')
  const set=(k:keyof typeof form,v:string)=>setForm(f=>({...f,[k]:v}))
  const payload=()=>({pool,term:form.term,part_of_speech:form.part_of_speech,ipa:form.ipa,short_definition:form.short_definition,definition:form.definition,
    examples:form.examples.split('\n').map(x=>x.trim()).filter(Boolean).map(sentence=>({sentence,note:''})),
    forms:Object.fromEntries(form.forms.split('\n').map(x=>x.split(':')).filter(x=>x.length>1).map(([k,...v])=>[k.trim(),v.join(':').trim()])),
    synonyms:csv(form.synonyms),antonyms:csv(form.antonyms),collocations:csv(form.collocations),aliases:csv(form.aliases),usage_notes:form.usage_notes})
  const submit=async(e:React.FormEvent)=>{e.preventDefault();setBusy(true);setError('');try{await api(card?`/flashcards/${card.id}/`:'/flashcards/',{method:card?'PATCH':'POST',body:JSON.stringify(payload())});onSaved()}catch(err){setError((err as Error).message)}finally{setBusy(false)}}
  return <Modal wide title={card?`Edit “${card.term}”`:'Create a card manually'} subtitle="Every generated field remains fully editable." onClose={onClose}><form className="editor-grid" onSubmit={submit}>
    <label>Word or collocation<input autoFocus value={form.term} onChange={e=>set('term',e.target.value)} required/></label><label>Part of speech<input value={form.part_of_speech} onChange={e=>set('part_of_speech',e.target.value)} placeholder="verb, noun, idiom…"/></label><label>IPA<input value={form.ipa} onChange={e=>set('ipa',e.target.value)} placeholder="without slashes"/></label><label className="span-2">Short definition<input value={form.short_definition} onChange={e=>set('short_definition',e.target.value)} required/></label><label className="span-2">Full definition<AutoTextarea value={form.definition} onChange={e=>set('definition',e.target.value)} required/></label><label className="span-2">Examples <small>one sentence per line</small><AutoTextarea value={form.examples} onChange={e=>set('examples',e.target.value)}/></label><label>Forms <small>key: value, one per line</small><AutoTextarea value={form.forms} onChange={e=>set('forms',e.target.value)}/></label><label>Synonyms <small>comma-separated</small><AutoTextarea value={form.synonyms} onChange={e=>set('synonyms',e.target.value)}/></label><label>Collocations<AutoTextarea value={form.collocations} onChange={e=>set('collocations',e.target.value)}/></label><label>Antonyms<AutoTextarea value={form.antonyms} onChange={e=>set('antonyms',e.target.value)}/></label><label>Accepted aliases<AutoTextarea value={form.aliases} onChange={e=>set('aliases',e.target.value)}/></label><label>Usage notes<AutoTextarea value={form.usage_notes} onChange={e=>set('usage_notes',e.target.value)}/></label>{error&&<div className="form-error span-2">{error}</div>}<div className="modal-actions span-2"><button type="button" className="ghost" onClick={onClose}>Cancel</button><button className="primary" disabled={busy}><Save size={16}/>{busy?'Saving…':'Save card'}</button></div>
  </form></Modal>
}
function csv(s:string){return s.split(',').map(x=>x.trim()).filter(Boolean)}

function BulkModal({pool,onClose,onDone}:{pool:number;onClose:()=>void;onDone:(n:number,e:number)=>void}){
  type Preview={normalized:string[];changes:{source:string;normalized:string;status:string}[];errors:{term:string;normalized?:string;error:string}[];input_count:number}
  const [terms,setTerms]=useState('')
  const [preview,setPreview]=useState<Preview|null>(null)
  const [batchSize,setBatchSize]=useState(20)
  const [busy,setBusy]=useState(false)
  const [error,setError]=useState('')
  const [job,setJob]=useState<BulkJob|null>(null)
  const rawCount=terms.split(/[\n;,]+/).filter(x=>x.trim()).length
  const seenKey=`lexiloop_bulk_report_seen_${pool}`
  const clampConcurrency=(value:number)=>setBatchSize(Math.max(1,Math.min(200,Number.isFinite(value)?Math.round(value):1)))
  // Window-level so the shortcut also works when nothing inside the form has
  // focus (stage 2 renders with focus on the document body).
  const formRef=useRef<HTMLFormElement>(null)
  useEffect(()=>{const fn=(e:KeyboardEvent)=>{
    if(!(e.metaKey||e.ctrlKey)||(e.key!=='Enter'&&e.code!=='NumpadEnter'))return
    if(!formRef.current||busy)return
    e.preventDefault();e.stopPropagation()
    formRef.current.requestSubmit()
  };window.addEventListener('keydown',fn,{capture:true});return()=>window.removeEventListener('keydown',fn,{capture:true})},[busy])
  useEffect(()=>{api<BulkJob[]>(`/generate/bulk/?pool=${pool}`).then(jobs=>{const active=jobs.find(candidate=>['queued','running'].includes(candidate.status));if(active){setJob(active);return}const latest=jobs[0];const seen=localStorage.getItem(seenKey);if(latest&&latest.id!==seen&&Date.now()-new Date(latest.updated_at).getTime()<24*60*60*1000)setJob(latest)}).catch(()=>{})},[pool])
  useEffect(()=>{if(!job||!['queued','running'].includes(job.status))return;const timer=window.setInterval(()=>{api<BulkJob>(`/generate/bulk/jobs/${job.id}/`).then(setJob).catch(err=>setError((err as Error).message))},800);return()=>window.clearInterval(timer)},[job?.id,job?.status])
  const normalize=async(e:React.FormEvent)=>{e.preventDefault();setBusy(true);setError('');try{const result=await api<Preview>('/generate/normalize/',{method:'POST',body:JSON.stringify({terms})});setPreview(result);if(result.normalized.length)setBatchSize(Math.min(200,Math.max(1,Math.min(20,result.normalized.length))))}catch(err){setError((err as Error).message)}finally{setBusy(false)}}
  const generate=async(e:React.FormEvent)=>{e.preventDefault();if(!preview?.normalized.length)return;setBusy(true);setError('');try{const created=await api<BulkJob>('/generate/bulk/',{method:'POST',body:JSON.stringify({pool,terms:preview.normalized,batch_size:batchSize})});setJob(created)}catch(err){if(err instanceof ApiError&&err.status===409&&err.data?.id)setJob(err.data as BulkJob);else setError((err as Error).message)}finally{setBusy(false)}}
  const cancel=async()=>{if(!job)return;setBusy(true);try{setJob(await api<BulkJob>(`/generate/bulk/jobs/${job.id}/cancel/`,{method:'POST'}))}catch(err){setError((err as Error).message)}finally{setBusy(false)}}
  const dismiss=()=>{if(job&&!['queued','running'].includes(job.status))localStorage.setItem(seenKey,job.id);onClose()}
  const finish=()=>{if(job){localStorage.setItem(seenKey,job.id);onDone(job.created_count,job.failed_count)}else onClose()}
  if(job){const active=['queued','running'].includes(job.status);const done=['completed','completed_with_errors','failed','cancelled'].includes(job.status);return <Modal title="Bulk AI generation" subtitle={active?`Round ${Math.max(1,job.current_round)} of ${job.max_rounds} · the job continues if this popup is closed`:'Generation report'} onClose={dismiss}><div className="modal-form bulk-job-view"><div className="bulk-progress-head"><div><strong>{job.created_count}</strong><span>created</span></div><div><strong>{job.skipped_count}</strong><span>already existed</span></div><div><strong>{job.failed_count}</strong><span>currently failed</span></div></div><div className="bulk-progress-track" role="progressbar" aria-valuenow={job.progress} aria-valuemin={0} aria-valuemax={100}><i style={{width:`${job.progress}%`}}/></div><div className="bulk-progress-copy"><b>{job.status==='queued'?'Waiting for the background worker…':job.status==='running'?`${job.processed_count} of ${job.total_count} resolved`:`${job.processed_count} of ${job.total_count} finished`}</b><span>{job.progress.toFixed(1)}%</span></div>{active&&<div className="bulk-live-note"><RefreshCw className="spin-slow" size={17}/><span>Each successful card is saved immediately. Failed items are retried in later rounds with three attempts per request.</span></div>}{job.error&&<div className="form-error">{job.error}</div>}{done&&job.failed_terms.length>0&&<details className="bulk-failures" open><summary>{job.failed_terms.length} terms could not be generated</summary><div>{job.failed_terms.map(item=><div key={item.term}><b>{item.term}</b><span>{item.error}</span><small>{item.attempts} round attempt{item.attempts===1?'':'s'}</small></div>)}</div></details>}<div className="modal-actions"><button className="ghost" onClick={active?onClose:dismiss}>{active?'Close and keep running':'Close'}</button>{active?<button className="danger-text" onClick={cancel} disabled={busy}>Cancel job</button>:<button className="primary" onClick={finish}>Done</button>}</div></div></Modal>}
  if(!preview)return <Modal title="Bulk AI generation" subtitle="Stage 1 of 2 · normalize and validate before spending tokens." onClose={onClose}><form ref={formRef} className="modal-form" onSubmit={normalize}><label>Paste your vocabulary list<AutoTextarea className="bulk-area" autoFocus value={terms} onChange={e=>{setTerms(e.target.value);setError('')}} placeholder={'to abolish (v)\nabuse (n) / to abuse (v)\nadolescent (n / adj)'} required/></label><div className="normalization-hint"><WandSparkles size={17}/><span>Infinitive to, part-of-speech labels, duplicate grammatical variants, and list separators will be cleaned first.</span></div>{error&&<div className="form-error">{error}</div>}<div className="modal-actions"><span className="modal-count">{rawCount} source line{rawCount===1?'':'s'}</span><button type="button" className="ghost" onClick={onClose}>Cancel</button><button className="primary" disabled={busy||!terms.trim()}>{busy?'Normalizing…':<>Normalize list <ArrowRight size={16}/></>}</button></div></form></Modal>
  return <Modal title="Review normalized terms" subtitle="Stage 2 of 2 · start a durable background job." onClose={onClose}><form ref={formRef} className="modal-form" onSubmit={generate}><div className="normalization-summary"><div><strong>{preview.normalized.length}</strong><span>cards ready</span></div><div><strong>{preview.errors.length}</strong><span>rejected</span></div><div><strong>{preview.changes.filter(x=>x.status==='duplicate').length}</strong><span>duplicates merged</span></div></div><div className="normalized-list">{preview.normalized.map(term=><span key={term}>{term}</span>)}</div>{preview.errors.length>0&&<details className="normalization-details errors"><summary>{preview.errors.length} rejected items</summary>{preview.errors.map((x,i)=><div key={`${x.term}-${i}`}><code>{x.term}</code><span>{x.error}</span></div>)}</details>}<section className="concurrency-control"><div className="concurrency-head"><div><b>Concurrent requests</b><small>The worker retries failures across up to five convergence rounds.</small></div><label><NumberField min={1} max={200} round value={batchSize} set={clampConcurrency}/><span>of 200</span></label></div><input type="range" min={1} max={200} value={batchSize} onChange={e=>clampConcurrency(Number(e.target.value))}/><div className="concurrency-presets">{[8,20,50,100,200].map(value=><button type="button" key={value} className={batchSize===value?'active':''} onClick={()=>setBatchSize(value)}>{value}</button>)}</div></section>{error&&<div className="form-error">{error}</div>}<div className="modal-actions"><button type="button" className="ghost" onClick={()=>setPreview(null)}>Back</button><button className="primary" disabled={busy||!preview.normalized.length}><Sparkles size={16}/>{busy?'Starting…':`Start ${preview.normalized.length}-card job`}</button></div></form></Modal>
}
function AnalyticsPage({pools}:{pools:Pool[]}){
  const [data,setData]=useState<Analytics|null>(null);const [loading,setLoading]=useState(true)
  useEffect(()=>{setLoading(true);api<Analytics>('/analytics/').then(setData).finally(()=>setLoading(false))},[pools.length])
  if(loading)return <Loader text="Loading cost ledger…"/>;if(!data)return null
  const accentFor=(poolId:number|null,accent?:string)=>accent||pools.find(pool=>pool.id===poolId)?.accent||'muted'
  return <div className="stack-lg"><div className="stat-grid"><Stat icon={<CircleDollarSign/>} value={`$${data.totals.cost.toFixed(4)}`} label="Recorded cost" hint="reported by router adapters" accent/><Stat icon={<Sparkles/>} value={data.totals.calls} label="LLM calls" hint="generation + judging"/><Stat icon={<Zap/>} value={data.totals.tokens.toLocaleString()} label="Total tokens" hint="when providers report usage"/><Stat icon={<Clock3/>} value={`${data.totals.average_latency}s`} label="Average latency" hint="latest 500 calls"/></div>
    <section className="panel"><div className="section-heading"><div><span className="eyebrow">COST OVER TIME</span><h2>Provider spend</h2></div><span className="muted">Exact adapter-reported totals.</span></div><CostChart rows={data.daily}/></section>
    <div className="two-column"><section className="panel"><div className="section-heading"><div><span className="eyebrow">BREAKDOWN</span><h2>By pool</h2></div></div><div className="usage-list">{data.by_pool.map(x=><div key={x.pool_id??'deleted'}><span className={`pool-dot ${poolAccentClass(accentFor(x.pool_id,x.accent))}`}/><div><b>{x.pool__name||'Deleted pool'}</b><small>{x.calls} calls · {x.tokens.toLocaleString()} tokens</small></div><strong>${x.cost.toFixed(4)}</strong></div>)}{!data.by_pool.length&&<p className="muted">No pools yet.</p>}</div></section>
      <section className="panel"><div className="section-heading"><div><span className="eyebrow">HEALTH</span><h2>Recent failures</h2></div></div><div className="failure-list">{data.failures.map(x=><div key={x.id}><span>!</span><div><b>{x.operation} · {x.model}</b><p>{x.error}</p><small>{new Date(x.created_at).toLocaleString()}</small></div></div>)}{!data.failures.length&&<div className="healthy"><ShieldCheck/><b>No recent failures</b><p className="healthy-copy">Your provider calls look healthy.</p></div>}</div></section></div>
  </div>
}

function CostChart({rows}:{rows:Analytics['daily']}){
  if(!rows.length)return <div className="chart-empty">The chart appears after your first LLM call.</div>
  const w=760,h=230,p=34,max=Math.max(...rows.map(x=>x.cost),.000001);const points=rows.map((x,i)=>({x:p+i*(w-2*p)/Math.max(1,rows.length-1),y:h-p-(x.cost/max)*(h-2*p),...x}))
  const line=points.map((x,i)=>`${i?'L':'M'} ${x.x} ${x.y}`).join(' ');const area=`${line} L ${points.at(-1)!.x} ${h-p} L ${points[0].x} ${h-p} Z`
  return <div className="chart-wrap"><svg viewBox={`0 0 ${w} ${h}`} role="img" aria-label="Daily AI cost chart"><defs><linearGradient id="costFill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="currentColor" stopOpacity=".28"/><stop offset="100%" stopColor="currentColor" stopOpacity="0"/></linearGradient></defs>{[0,.25,.5,.75,1].map(n=><line key={n} x1={p} x2={w-p} y1={p+n*(h-2*p)} y2={p+n*(h-2*p)} className="gridline"/>)}<path d={area} fill="url(#costFill)"/><path d={line} className="chart-line"/>{points.map(x=><g key={x.day}><circle cx={x.x} cy={x.y} r="4"/><title>{x.day}: ${x.cost.toFixed(6)}</title></g>)}</svg><div className="chart-labels"><span>{rows[0].day}</span><span>{rows.at(-1)!.day}</span></div></div>
}

function SettingsPage({value,onSaved,notify}:{value:Settings;onSaved:(s:Settings)=>void;notify:(m:string,k?:Toast['kind'])=>void}){
  const [form,setForm]=useState(value);const [providerTokens,setProviderTokens]=useState<Record<string,string>>({});const [models,setModels]=useState<ModelOption[]>([]);const [busy,setBusy]=useState(false);const [advanced,setAdvanced]=useState(false)
  useEffect(()=>setForm(value),[value]);useEffect(()=>{api<{models:ModelOption[]}>('/models/').then(x=>setModels(x.models)).catch(()=>{})},[])
  const patch=<K extends keyof Settings>(k:K,v:Settings[K])=>setForm(f=>({...f,[k]:v}))
  // Keys are stored once per provider, so switching between models of the same
  // provider never asks for the key again. providerTokens holds only staged
  // edits: a non-empty string replaces the key, an empty string removes it.
  const stageToken=(provider:string,token:string)=>setProviderTokens(prev=>({...prev,[provider]:token}))
  const unstageToken=(provider:string)=>setProviderTokens(prev=>{const next={...prev};delete next[provider];return next})
  const save=async()=>{setBusy(true);try{const payload:any={...form};if(Object.keys(providerTokens).length)payload.provider_tokens=providerTokens;delete payload.has_generation_token;delete payload.has_judge_token;delete payload.has_image_token;delete payload.has_sentence_token;delete payload.token_status;const result=await api<Settings>('/settings/',{method:'PATCH',body:JSON.stringify(payload)});setProviderTokens({});onSaved(result)}catch(e){notify((e as Error).message,'error')}finally{setBusy(false)}}
  const generationModel=models.find(model=>model.id===form.generation_model)
  const judgeModel=models.find(model=>model.id===form.judge_model)
  const tokenSaved=(model?:ModelOption)=>Boolean(model&&form.token_status?.[model.token_provider])
  const tokenValue=(model?:ModelOption)=>model?providerTokens[model.token_provider]??'':''
  const tokenPlaceholder=(model?:ModelOption)=>tokenSaved(model)?'••••••••  Leave blank to keep':`Paste ${model?.token_label||'API key'}`
  return <div className="settings-wrap"><section className="panel settings-section"><div className="settings-heading"><div className="settings-icon"><WandSparkles/></div><div><h2>Flashcard generation</h2><p>Choose a public model. LexiLoop handles the router identifier internally.</p></div><span className={`status ${form.has_generation_token?'ok':''}`}>{form.has_generation_token?'Key saved':'Key required'}</span></div><div className="settings-grid"><label>Generation model<ModelInput value={form.generation_model} set={v=>patch('generation_model',v)} models={models} role="generation"/></label><label>{generationModel?.token_label||'Provider API key'}<input type="text" name="lexiloop-generation-provider-token" autoComplete="off" autoCorrect="off" autoCapitalize="off" spellCheck={false} data-lpignore="true" data-1p-ignore="true" data-form-type="other" value={tokenValue(generationModel)} onChange={e=>generationModel&&stageToken(generationModel.token_provider,e.target.value)} placeholder={tokenPlaceholder(generationModel)}/><small>Encrypted at rest and never returned by the API. Saved once per provider.</small></label></div></section>
    <section className="panel settings-section"><div className="settings-heading"><div className="settings-icon"><BrainCircuit/></div><div><h2>Definition judge</h2><p>Use a fast, inexpensive model independently from generation.</p></div><span className={`status ${form.has_judge_token?'ok':''}`}>{form.has_judge_token?'Key saved':'Key required'}</span></div><div className="settings-grid"><label>Judge model<ModelInput value={form.judge_model} set={v=>patch('judge_model',v)} models={models} role="judge"/></label><label>{judgeModel?.token_label||'Provider API key'}<input type="text" name="lexiloop-judge-provider-token" autoComplete="off" autoCorrect="off" autoCapitalize="off" spellCheck={false} data-lpignore="true" data-1p-ignore="true" data-form-type="other" value={tokenValue(judgeModel)} onChange={e=>judgeModel&&stageToken(judgeModel.token_provider,e.target.value)} placeholder={tokenPlaceholder(judgeModel)}/><small>Use the key belonging to the selected provider.</small></label><label>Accept score <b>{form.judge_acceptance_score}</b><input type="range" min={1} max={7} value={form.judge_acceptance_score} onChange={e=>patch('judge_acceptance_score',Number(e.target.value))}/><small>Answers at or above this score count as understood.</small></label></div></section>
    <section className="panel settings-section"><div className="settings-heading"><div className="settings-icon"><PencilLine/></div><div><h2>Sentence judge</h2><p>Grades the Word → sentence task: does the sentence use the word correctly and naturally?</p></div><span className={`status ${form.has_sentence_token?'ok':''}`}>{form.has_sentence_token?'Key saved':'Key required'}</span></div><div className="settings-grid"><label>Sentence judge model<select value={form.sentence_judge_model} onChange={e=>patch('sentence_judge_model',e.target.value)}><option value="">Same as the definition judge</option>{models.map(model=><option key={model.id} value={model.id}>{model.label} · {model.provider.split(' · ')[0]}</option>)}</select><small>Sentences are graded on a fixed 1–7 usage rubric. Uses the provider key saved above.</small></label><label>Accept score <b>{form.sentence_acceptance_score}</b><input type="range" min={1} max={7} value={form.sentence_acceptance_score} onChange={e=>patch('sentence_acceptance_score',Number(e.target.value))}/><small>Sentences at or above this score count as correct usage.</small></label></div></section>
    <section className="panel settings-section"><div className="settings-heading"><div className="settings-icon"><ImageIcon/></div><div><h2>Card images</h2><p>An optional picture appears on the flashcard during study. AI helps fetch pictures from page links.</p></div><span className={`status ${form.has_image_token?'ok':''}`}>{form.has_image_token?'Key saved':'Key required'}</span></div><div className="settings-grid"><label>Image assistant model<select value={form.image_model} onChange={e=>patch('image_model',e.target.value)}><option value="">Same as the generation model</option>{models.map(model=><option key={model.id} value={model.id}>{model.label} · {model.provider.split(' · ')[0]}</option>)}</select><small>Reads a pasted page link and points at the right image file when a plain download fails. Uses the provider key saved above.</small></label><label>Study images<div className="toggle-row"><button type="button" role="switch" aria-checked={form.show_card_images} className={`switch ${form.show_card_images?'on':''}`} onClick={()=>patch('show_card_images',!form.show_card_images)}><i/></button><span>{form.show_card_images?'Images are shown on flashcards':'Images stay hidden during study'}</span></div><small>Turning this off hides pictures without deleting them.</small></label>
    <div className="settings-field">Where images appear<div className="check-list"><label className="check-row"><input type="checkbox" checked={form.show_images_term_to_definition} onChange={e=>patch('show_images_term_to_definition',e.target.checked)}/><span>Word → definition tasks</span></label><label className="check-row"><input type="checkbox" checked={form.show_images_definition_to_term} onChange={e=>patch('show_images_definition_to_term',e.target.checked)}/><span>Definition → word tasks<small>a picture can hint at the answer — turn off for stricter recall</small></span></label><label className="check-row"><input type="checkbox" checked={form.show_images_term_to_sentence} onChange={e=>patch('show_images_term_to_sentence',e.target.checked)}/><span>Word → sentence tasks</span></label></div><small>Applies while study images are on.</small></div>
    <div className="settings-field">Reveal animations<div className="check-list">{ANIMATION_CHOICES.map(choice=><div className="check-row anim-row" key={choice.id}><label className="check-row-main"><input type="checkbox" checked={form.image_animations.includes(choice.id)} onChange={e=>patch('image_animations',e.target.checked?ANIMATION_CHOICES.map(x=>x.id).filter(id=>id===choice.id||form.image_animations.includes(id)):form.image_animations.filter(id=>id!==choice.id))}/><span>{choice.label}<small>{choice.hint}</small></span></label><label className="anim-duration" title="Animation duration in seconds"><NumberField min={0.5} max={30} step={0.1} value={form.image_animation_durations[choice.id]??ANIMATION_DEFAULT_SECONDS[choice.id]} set={v=>patch('image_animation_durations',{...form.image_animation_durations,[choice.id]:v})}/><span>s</span></label></div>)}</div><small>Each card keeps one of the checked animations. Uncheck all for a plain fade.</small></div>
    <label>Prefetch upcoming images<NumberField min={0} max={10} round value={form.image_prefetch_count} set={v=>patch('image_prefetch_count',v)}/><small>How many of the next flashcards’ images load in advance during study. 0 disables prefetching.</small></label></div></section>
    <ProviderKeysSection models={models} status={form.token_status||{}} staged={providerTokens} onRemove={provider=>stageToken(provider,'')} onUndo={unstageToken}/>
    <section className="panel settings-section"><div className="settings-heading"><div className="settings-icon"><BookOpen/></div><div><h2>Study experience</h2><p>Control prompt direction, appearance, and new-card load.</p></div></div><div className="settings-grid three"><div className="settings-field">Task types<div className="check-list">{([['term_to_definition','Word → definition'],['definition_to_term','Definition → word'],['term_to_sentence','Word → sentence']] as [Direction,string][]).map(([id,label])=><label className="check-row" key={id}><input type="checkbox" checked={form.study_directions.includes(id)} onChange={e=>{const next=e.target.checked?(['term_to_definition','definition_to_term','term_to_sentence'] as Direction[]).filter(d=>d===id||form.study_directions.includes(d)):form.study_directions.filter(d=>d!==id);if(next.length)patch('study_directions',next)}}/><span>{label}</span></label>)}</div><small>Due cards rotate through the enabled task types. At least one stays on.</small></div><label>Appearance<select value={form.theme} onChange={e=>patch('theme',e.target.value as Theme)}><option value="dark">Dark</option><option value="light">Light</option><option value="system">System</option></select></label><label>Daily new cards<NumberField min={0} max={500} round value={form.daily_new_limit} set={v=>patch('daily_new_limit',v)}/></label></div><div className="accent-setting"><div><Palette size={18}/><span><b>Interface color</b><small>Choose the accent used for actions, charts, and highlights.</small></span></div><AccentPicker value={form.accent_color} set={v=>patch('accent_color',v)}/></div></section>
    <section className="panel settings-section"><div className="settings-heading"><div className="settings-icon"><Clock3/></div><div><h2>Automatic review timing</h2><p>Correctness is primary; response time chooses Easy, Good, or Hard automatically.</p></div></div><div className="timing-settings"><TimingBand title="Word → definition" description="Writing a free-form meaning takes longer." easy={form.term_to_definition_easy_seconds} good={form.term_to_definition_good_seconds} setEasy={v=>patch('term_to_definition_easy_seconds',v)} setGood={v=>patch('term_to_definition_good_seconds',v)}/><TimingBand title="Definition → word" description="Recalling and typing one term should be faster." easy={form.definition_to_term_easy_seconds} good={form.definition_to_term_good_seconds} setEasy={v=>patch('definition_to_term_easy_seconds',v)} setGood={v=>patch('definition_to_term_good_seconds',v)}/><TimingBand title="Word → sentence" description="Composing an original sentence takes the longest." easy={form.term_to_sentence_easy_seconds} good={form.term_to_sentence_good_seconds} setEasy={v=>patch('term_to_sentence_easy_seconds',v)} setGood={v=>patch('term_to_sentence_good_seconds',v)}/></div></section>
    <section className="panel settings-section"><button className="advanced-toggle" onClick={()=>setAdvanced(!advanced)}><div><Gauge/><span><b>Scheduler tuning</b><small>Anki-inspired learning and review parameters</small></span></div>{advanced?<ChevronDown/>:<ChevronRight/>}</button>{advanced&&<div className="settings-grid advanced"><label>Learning steps (minutes)<input value={form.learning_steps_minutes.join(', ')} onChange={e=>patch('learning_steps_minutes',numbers(e.target.value))}/></label><label>Relearning steps (minutes)<input value={form.relearning_steps_minutes.join(', ')} onChange={e=>patch('relearning_steps_minutes',numbers(e.target.value))}/></label><NumberSetting label="Graduating interval (days)" value={form.graduating_interval_days} set={v=>patch('graduating_interval_days',v)}/><NumberSetting label="Easy interval (days)" value={form.easy_interval_days} set={v=>patch('easy_interval_days',v)}/><NumberSetting label="Easy bonus" value={form.easy_bonus} set={v=>patch('easy_bonus',v)}/><NumberSetting label="Hard multiplier" value={form.hard_multiplier} set={v=>patch('hard_multiplier',v)}/><NumberSetting label="Lapse multiplier" value={form.lapse_multiplier} set={v=>patch('lapse_multiplier',v)}/><NumberSetting label="Minimum ease" value={form.minimum_ease} set={v=>patch('minimum_ease',v)}/></div>}</section>
    <div className="settings-save"><span>Changes apply to future reviews.</span><button className="primary big" onClick={save} disabled={busy}><Save size={17}/>{busy?'Saving…':'Save settings'}</button></div>
  </div>
}
function ProviderKeysSection({models,status,staged,onRemove,onUndo}:{models:ModelOption[];status:Record<string,boolean>;staged:Record<string,string>;onRemove:(provider:string)=>void;onUndo:(provider:string)=>void}){
  const providers=[...new Map(models.map(model=>[model.token_provider,{id:model.token_provider,name:model.provider.split(' · ')[0],token_label:model.token_label}])).values()]
  if(!providers.length)return null
  return <section className="panel settings-section"><div className="settings-heading"><div className="settings-icon"><KeyRound/></div><div><h2>Saved API keys</h2><p>One key per provider. Every model of that provider uses it automatically.</p></div></div>
    <div className="provider-key-list">{providers.map(provider=>{
      const stagedValue=staged[provider.id]
      const state=stagedValue===''?'removing':stagedValue?'staging':status[provider.id]?'saved':'missing'
      const labels={removing:'Removed on save',staging:'Updated on save',saved:'Key saved',missing:'No key'} as const
      return <div className="provider-key-row" key={provider.id}>
        <span className={`provider-key-dot ${state}`}/>
        <div><b>{provider.name}</b><small>{provider.token_label}</small></div>
        <span className={`status ${state==='saved'||state==='staging'?'ok':''} ${state==='missing'?'neutral':''}`}>{labels[state]}</span>
        {state==='saved'&&<button type="button" className="danger-text" onClick={()=>onRemove(provider.id)}>Remove</button>}
        {stagedValue!==undefined&&<button type="button" className="ghost" onClick={()=>onUndo(provider.id)}>Undo</button>}
      </div>
    })}</div>
  </section>
}
function AccentPicker({value,set}:{value:AccentColor;set:(v:AccentColor)=>void}){const choices:AccentColor[]=['emerald','blue','teal','indigo','violet','rose','orange'];return <div className="accent-picker">{choices.map(color=><button type="button" key={color} className={`accent-swatch ${color} ${value===color?'active':''}`} title={color[0].toUpperCase()+color.slice(1)} aria-label={`Use ${color} interface color`} onClick={()=>set(color)}><span/></button>)}</div>}
function ModelInput({value,set,models,role}:{value:string;set:(v:string)=>void;models:ModelOption[];role:'generation'|'judge'}){
  const suitable=models.filter(model=>model.recommended_for.includes(role))
  const available=suitable.some(model=>model.id===value)?suitable:models.filter(model=>model.id===value||model.recommended_for.includes(role))
  const selected=models.find(model=>model.id===value)
  const providers=[...new Set(available.map(model=>model.provider.split(' · ')[0]))]
  return <div className="model-picker"><select value={value} onChange={e=>set(e.target.value)} disabled={!available.length}><option value="" disabled>{available.length?'Choose a model':'Loading models…'}</option>{providers.map(provider=><optgroup key={provider} label={provider}>{available.filter(model=>model.provider.split(' · ')[0]===provider).map(model=><option key={model.id} value={model.id}>{model.label}</option>)}</optgroup>)}</select>{selected?<div className="model-card"><div><b>{selected.label}</b>{selected.badge&&<span>{selected.badge}</span>}</div><small>{selected.provider}</small><p>{selected.description}</p>{selected.key_url&&<a href={selected.key_url} target="_blank" rel="noreferrer">Get a {selected.token_label}</a>}</div>:<small>Loading the public model catalog…</small>}</div>
}
function TimingBand({title,description,easy,good,setEasy,setGood}:{title:string;description:string;easy:number;good:number;setEasy:(v:number)=>void;setGood:(v:number)=>void}){return <div className="timing-band"><div><b>{title}</b><small>{description}</small></div><div className="timing-thresholds"><label><span>Easy</span><div>&lt; <NumberField min={1} max={600} round value={easy} set={setEasy}/> sec</div></label><label><span>Good</span><div>&lt; <NumberField min={2} max={900} round value={good} set={setGood}/> sec</div></label><label className="hard-band"><span>Hard</span><div>≥ {good} sec</div></label></div></div>}
function NumberSetting({label,value,set}:{label:string;value:number;set:(v:number)=>void}){return <label>{label}<NumberField step={0.05} value={value} set={set}/></label>}
function numbers(s:string){return s.split(/[ ,]+/).map(Number).filter(x=>Number.isFinite(x)&&x>0)}

function AutoTextarea(props:React.TextareaHTMLAttributes<HTMLTextAreaElement>){
  const ref=useRef<HTMLTextAreaElement>(null)
  const resize=(element:HTMLTextAreaElement)=>{element.style.height='auto';element.style.height=`${Math.min(element.scrollHeight,420)}px`;element.style.overflowY=element.scrollHeight>420?'auto':'hidden'}
  useEffect(()=>{if(ref.current)resize(ref.current)},[props.value])
  return <textarea {...props} ref={ref} rows={props.rows??2} onInput={event=>{resize(event.currentTarget);props.onInput?.(event)}}/>
}

function Modal({title,subtitle,onClose,children,wide=false}:{title:string;subtitle?:string;onClose:()=>void;children:React.ReactNode;wide?:boolean}){return <div className="modal-backdrop" onMouseDown={e=>{if(e.target===e.currentTarget)onClose()}}><div className={`modal ${wide?'wide':''}`}><div className="modal-head"><div><h2>{title}</h2>{subtitle&&<p>{subtitle}</p>}</div><button className="icon-button" onClick={onClose}><X size={19}/></button></div>{children}</div></div>}
function Empty({icon,title,text}:{icon:React.ReactNode;title:string;text:string}){return <div className="empty"><div>{icon}</div><h3>{title}</h3><p>{text}</p></div>}
function Loader({text}:{text:string}){return <div className="loader"><div className="spinner"/><span>{text}</span></div>}
