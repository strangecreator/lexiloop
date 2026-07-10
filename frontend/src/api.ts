const API = '/api'

export class ApiError extends Error {
  status:number; data:any
  constructor(status:number, data:any) {
    super(typeof data?.detail === 'string' ? data.detail : flattenErrors(data) || `Request failed (${status})`)
    this.status=status; this.data=data
  }
}
function flattenErrors(data:any):string {
  if (!data || typeof data !== 'object') return ''
  return Object.entries(data).map(([k,v]) => `${k}: ${Array.isArray(v) ? v.join(', ') : String(v)}`).join(' · ')
}
export function token() { return localStorage.getItem('lexiloop_token') || '' }
export function setToken(value:string) { value ? localStorage.setItem('lexiloop_token', value) : localStorage.removeItem('lexiloop_token') }
export async function api<T>(path:string, options:RequestInit={}, timeoutMs?:number):Promise<T> {
  const headers = new Headers(options.headers)
  if (!(options.body instanceof FormData)) headers.set('Content-Type','application/json')
  if (token()) headers.set('Authorization',`Token ${token()}`)
  // Browsers wait minutes on a stalled connection by default; time-critical
  // calls pass timeoutMs so the UI fails fast with a readable error instead.
  const controller = timeoutMs ? new AbortController() : null
  const timer = controller ? window.setTimeout(()=>controller.abort(), timeoutMs) : 0
  let response:Response
  try {
    response = await fetch(`${API}${path}`, {...options, headers, ...(controller ? {signal:controller.signal} : {})})
  } catch (error) {
    if (controller?.signal.aborted) throw new ApiError(0, {detail:`No response after ${Math.round((timeoutMs||0)/1000)} seconds. Check your connection and try again.`})
    throw error
  } finally {
    if (timer) window.clearTimeout(timer)
  }
  if (response.status === 204) return undefined as T
  const data = await response.json().catch(()=>({detail:response.statusText}))
  if (!response.ok) throw new ApiError(response.status,data)
  return data as T
}
export async function apiBlob(path:string, options:RequestInit={}):Promise<Blob> {
  const headers = new Headers(options.headers)
  if (token()) headers.set('Authorization',`Token ${token()}`)
  const response = await fetch(`${API}${path}`, {...options, headers})
  if (!response.ok) {
    const data = await response.json().catch(()=>({detail:response.statusText}))
    throw new ApiError(response.status,data)
  }
  return response.blob()
}
export function list<T>(data:T[]|{results:T[]}):T[] { return Array.isArray(data) ? data : data.results }

export interface Paginated<T> { count:number; next:string|null; previous:string|null; results:T[] }

export async function apiPage<T>(path:string):Promise<Paginated<T>> {
  const data=await api<T[]|Paginated<T>>(path)
  if(Array.isArray(data)) return {count:data.length,next:null,previous:null,results:data}
  return data
}

export async function apiListAll<T>(path:string, maxPages=100):Promise<T[]> {
  const output:T[]=[]
  let nextPath:string|null=path
  let pages=0
  while(nextPath!==null&&pages<maxPages){
    const requestPath:string=nextPath.startsWith('/api/')?nextPath.slice(4):nextPath
    const page:T[]|Paginated<T>=await api<T[]|Paginated<T>>(requestPath)
    if(Array.isArray(page)){output.push(...page);break}
    output.push(...page.results)
    if(!page.next){nextPath=null;break}
    const parsedUrl:URL=new URL(page.next,window.location.origin)
    nextPath=`${parsedUrl.pathname}${parsedUrl.search}`
    pages+=1
  }
  return output
}
