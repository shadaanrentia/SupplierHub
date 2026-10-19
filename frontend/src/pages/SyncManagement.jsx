import { useEffect, useRef, useState } from 'react';
import axios from '@/lib/axios';
import { RefreshCw, Play, Square, Loader2, ChevronLeft, ChevronRight, X, Zap, Package, Tag, ShoppingBag } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { toast } from 'sonner';

const API = (process.env.REACT_APP_BACKEND_URL || '').replace(/\/+$/, '') + '/api';
const activeStatus = status => ['running', 'stopping'].includes(status);
const label = value => String(value || '').replaceAll('_', ' ');
const errorMessage = error => {
  const detail = error.response?.data?.detail;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) return detail.map(item => item.msg).join('; ');
  return error.code === 'ECONNABORTED' ? 'The request timed out. Refresh the job list before trying again; it may already have started.' : error.message || 'Request failed';
};
const button = 'inline-flex items-center justify-center gap-2 border border-zinc-700 bg-zinc-900 hover:bg-zinc-800 px-3 py-2 rounded-none text-sm disabled:opacity-40 disabled:cursor-not-allowed';
const input = 'bg-zinc-950 border border-zinc-700 rounded-none px-3 py-2 text-sm';
const styles = {
  completed: 'text-emerald-400 bg-emerald-950/40', completed_with_errors: 'text-amber-400 bg-amber-950/40',
  failed: 'text-red-400 bg-red-950/40', running: 'text-blue-400 bg-blue-950/40',
  stopping: 'text-orange-400 bg-orange-950/40', stopped: 'text-zinc-300 bg-zinc-800',
  interrupted: 'text-amber-400 bg-amber-950/40', cancelled: 'text-zinc-300 bg-zinc-800',
};
function Badge({status}) { return <span className={`inline-flex px-2 py-0.5 border border-zinc-700 rounded-none text-xs font-mono capitalize ${styles[status] || 'bg-zinc-800 text-zinc-300'}`}>{label(status)}</span>; }
function localTime(value) {
  if (!value) return '—';
  // Backend stores naive UTC timestamps. Explicitly interpret them as UTC.
  const normalized = /(?:Z|[+-]\d{2}:?\d{2})$/.test(value) ? value : value + 'Z';
  const date = new Date(normalized);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}
const operations = [
  {type:'products',title:'Products',description:'Import names, descriptions and variants.'},
  {type:'pricing',title:'Pricing',description:'Refresh supplier costs; retained prices stay protected.'},
  {type:'inventory',title:'Inventory',description:'Refresh stock for matching variant SKUs.'},
  {type:'media',title:'Media',description:'Fetch image URLs into Supplier Hub.'},
  {type:'refresh',title:'Refresh details',description:'Pricing, inventory and media in parallel for imported products.'},
  {type:'all',title:'Full sync',description:'Import products, then pricing, inventory and media in parallel.'},
  {type:'bulk-data',title:'Bulk Data',description:'Supplier-specific bulk import; may be account limited.'},
  {type:'enrich-categories',title:'Enrich categories',description:'Fetch categories for products missing them.'},
];

export default function SyncManagement() {
  const [suppliers,setSuppliers] = useState([]);
  const [logs,setLogs] = useState([]);
  const [activeJobs,setActiveJobs] = useState([]);
  const [supplierFilter,setSupplierFilter] = useState('all');
  const [typeFilter,setTypeFilter] = useState('all');
  const [page,setPage] = useState(1);
  const [loading,setLoading] = useState(true);
  const [fetchError,setFetchError] = useState('');
  const [supplierError,setSupplierError] = useState('');
  const [lastUpdated,setLastUpdated] = useState(null);
  const [refresh,setRefresh] = useState(0);
  const [busy,setBusy] = useState({});
  const [selected,setSelected] = useState('');
  const [detail,setDetail] = useState(null);
  const [detailError,setDetailError] = useState('');
  const [limit,setLimit] = useState(1500);
  const [skuText,setSkuText] = useState('');
  const [includeSkipped,setIncludeSkipped] = useState(false);
  const actionLocks = useRef(new Set());
  const mounted = useRef(true);
  useEffect(()=>{mounted.current=true;return()=>{mounted.current=false;};},[]);

  useEffect(()=>{
    const controller = new AbortController();
    axios.get(`${API}/suppliers`,{signal:controller.signal,timeout:15000}).then(response=>{
      setSuppliers(response.data.suppliers || []);setSupplierError('');
    }).catch(error=>{if(!axios.isCancel(error))setSupplierError(errorMessage(error));});
    return()=>controller.abort();
  },[refresh]);

  useEffect(()=>{
    let disposed=false,timer;
    const controller=new AbortController();
    const poll=async()=>{
      let delay=10000;
      try {
        const response=await axios.get(`${API}/sync/logs`,{signal:controller.signal,timeout:15000,params:{
          ...(supplierFilter!=='all' && {supplier_id:supplierFilter}),
          ...(typeFilter!=='all' && {sync_type:typeFilter}),limit:20,offset:(page-1)*20,
        }});
        if(disposed)return;
        setLogs(response.data.logs || []);setActiveJobs(response.data.active_jobs || []);
        setFetchError('');setLastUpdated(new Date());
        delay=response.data.active_jobs?.length ? 3000 : 10000;
      } catch(error) {
        if(!disposed && !axios.isCancel(error)){setFetchError(errorMessage(error));delay=15000;}
      } finally {
        if(!disposed){setLoading(false);timer=setTimeout(poll,delay);}
      }
    };
    setLoading(true);poll();
    return()=>{disposed=true;clearTimeout(timer);controller.abort();};
  },[supplierFilter,typeFilter,page,refresh]);

  useEffect(()=>{
    let disposed=false,timer;
    const controller=new AbortController();
    setDetail(null);setDetailError('');
    if(!selected)return()=>controller.abort();
    const poll=async()=>{
      let delay;
      try {
        const response=await axios.get(`${API}/sync/log/${selected}`,{signal:controller.signal,timeout:15000});
        if(disposed)return;
        setDetail(response.data);setDetailError('');
        if(activeStatus(response.data.status))delay=3000;
      } catch(error) {if(!disposed && !axios.isCancel(error)){setDetailError(errorMessage(error));delay=15000;}}
      if(!disposed && delay)timer=setTimeout(poll,delay);
    };
    poll();return()=>{disposed=true;clearTimeout(timer);controller.abort();};
  },[selected,refresh]);

  useEffect(()=>{
    if(!selected)return undefined;
    const previous=document.body.style.overflow;
    const focused=document.activeElement;
    document.body.style.overflow='hidden';
    const dialog=document.querySelector('[role="dialog"]');
    const controls=()=>dialog ? Array.from(dialog.querySelectorAll('button:not(:disabled),input:not(:disabled),a[href],select:not(:disabled),[tabindex="0"]')) : [];
    controls()[0]?.focus();
    const close=event=>{
      if(event.key==='Escape')setSelected('');
      if(event.key==='Tab'){
        const nodes=controls();if(!nodes.length)return;
        const first=nodes[0],last=nodes[nodes.length-1];
        if(event.shiftKey && document.activeElement===first){event.preventDefault();last.focus();}
        else if(!event.shiftKey && document.activeElement===last){event.preventDefault();first.focus();}
      }
    };
    window.addEventListener('keydown',close);
    return()=>{document.body.style.overflow=previous;window.removeEventListener('keydown',close);focused?.focus?.();};
  },[selected]);

  const act=async(key,callback)=>{
    if(actionLocks.current.has(key))return;
    actionLocks.current.add(key);setBusy(state=>({...state,[key]:true}));
    try {await callback();}
    catch(error){toast.error(errorMessage(error));if(mounted.current)setRefresh(v=>v+1);}
    finally {actionLocks.current.delete(key);if(mounted.current)setBusy(state=>({...state,[key]:false}));}
  };
  const start=(supplier,type)=>act(`supplier-${supplier.id}-${type}`,async()=>{
    const value=Number(limit);
    const supplierOperation=operations.some(operation=>operation.type===type) && type!=='bulk-data';
    if(supplierOperation && (!Number.isInteger(value) || value<1 || value>10000))throw new Error('Product limit must be between 1 and 10,000.');
    const skus=skuText.trim();
    if(supplierOperation && skus && skus.split(/[,\s]+/).filter(Boolean).length>200)throw new Error('Enter at most 200 supplier SKUs.');
    const response=await axios.post(`${API}/sync/${type}/${supplier.id}`,null,{timeout:20000,params:supplierOperation?{limit:value,...(skus && {skus})}:undefined});
    if(!mounted.current)return;
    if(response.data.status==='no_action')toast.info(response.data.message);
    else {toast.success('Job accepted. Watch progress below.');if(response.data.log_id){setSelected(response.data.log_id);setActiveJobs(jobs=>[...jobs,{id:response.data.log_id,supplier_id:supplier.id,supplier_name:supplier.supplier_name,sync_type:type==='all'?'full':type.replaceAll('-','_'),status:'running'}]);}}
    setRefresh(v=>v+1);
  });
  const stop=id=>act(`stop-${id}`,async()=>{
    const response=await axios.post(`${API}/sync/stop/${id}`,null,{timeout:15000});
    toast.info(response.data.status==='stopping'?'Stop requested. The current supplier request must finish first.':`Job is ${label(response.data.status)}.`);
    if(mounted.current)setRefresh(v=>v+1);
  });
  const retry=id=>act(`retry-${id}`,async()=>{
    const response=await axios.post(`${API}/sync/retry/${id}`,null,{timeout:15000,params:{include_skipped:includeSkipped}});
    toast.success(includeSkipped?'Retry job created, including skipped items.':'Retry job created for failed and unfinished items.');
    if(mounted.current){setSelected(response.data.log_id);setRefresh(v=>v+1);}
  });
  const stages=type=>type==='refresh'?['pricing','inventory','media']:['pricing','inventory','media'].includes(type)?[type]:['*'];
  const overlaps=(first,second)=>{const a=stages(first),b=stages(second);return a.includes('*') || b.includes('*') || a.some(stage=>b.includes(stage));};
  const blocked=(supplierId,type)=>Object.keys(busy).some(key=>busy[key] && key.startsWith(`supplier-${supplierId}-`) && overlaps(type,key.slice(`supplier-${supplierId}-`.length))) || activeJobs.some(job=>job.supplier_id===supplierId && overlaps(type,job.sync_type));
  const canRetry=job=>job?.managed && !activeStatus(job.status) && job.sync_type!=='bulk_data' && (Number(job.unfinished)>0 || ['failed','pending','running',...(includeSkipped?['skipped']:[])].some(status=>Number(job.item_counts?.[status])>0) || (includeSkipped && Number(job.skipped)>0));

  return <div className="p-6 space-y-6" data-testid="sync-page">
    <div className="flex items-center justify-between gap-3"><div><h1 className="font-heading text-3xl font-bold tracking-tight">Sync Management</h1><p className="text-zinc-500 text-sm mt-1">Manage data synchronization jobs</p></div><button className={button} onClick={()=>setRefresh(v=>v+1)} aria-label="Refresh sync jobs" data-testid="refresh-logs-btn"><RefreshCw className="w-4 h-4"/></button></div>
    {(fetchError || supplierError) && <div role="alert" className="border border-amber-800 bg-amber-950/30 p-4"><p>Unable to refresh: {fetchError || supplierError}</p><p className="text-xs mt-1">Loaded results may be stale. Refresh before starting another job.</p></div>}
    <Card className="bg-zinc-900/50 border-zinc-800 rounded-sm"><CardHeader className="p-4 border-b border-zinc-800/50"><CardTitle className="font-heading text-sm font-bold uppercase text-zinc-400 tracking-wider">Manual Sync Triggers</CardTitle></CardHeader><CardContent className="p-4 space-y-4">
      <div className="flex flex-wrap gap-4"><label className="text-xs text-zinc-400">Product limit<input className={`${input} block mt-1 w-32`} type="number" min="1" max="10000" value={limit} onChange={e=>setLimit(e.target.value)}/></label><label className="text-xs text-zinc-400 flex-1 min-w-[200px]">Specific supplier SKUs (optional)<input className={`${input} block mt-1 w-full`} value={skuText} onChange={e=>setSkuText(e.target.value)} placeholder="ATC1015, ATC1000L"/></label></div>
      <p className="text-xs text-zinc-500">Pricing, inventory and media can run together. Refresh details runs all three for imported products; Sync All imports products first. Bulk Data uses the complete supplier feed.</p>
      {!suppliers.length && <p className="text-zinc-500 text-sm font-mono">{supplierError?'Suppliers could not be loaded.':'No suppliers configured'}</p>}
      {suppliers.map(supplier=><div key={supplier.id} className="flex flex-wrap items-center justify-between gap-3 p-3 border border-zinc-800 bg-zinc-950/50"><div><p className="text-sm font-medium text-zinc-200">{supplier.supplier_name}</p><p className="text-xs font-mono text-zinc-500">{supplier.account_number}</p><div className="flex flex-wrap gap-2 mt-1">{activeJobs.filter(job=>job.supplier_id===supplier.id).map(job=><button key={job.id} className="text-xs text-blue-400 underline" onClick={()=>setSelected(job.id)}>{label(job.sync_type)} · {job.status}</button>)}</div></div><div className="flex gap-2 flex-wrap justify-end">{operations.map(operation=>{
        const Icon=operation.type==='all'?Zap:operation.type==='refresh'?RefreshCw:operation.type==='bulk-data'?Package:operation.type==='enrich-categories'?Tag:Play;
        const color=operation.type==='all'?'bg-emerald-700 hover:bg-emerald-600 text-white border-emerald-600':operation.type==='bulk-data'?'bg-purple-700 hover:bg-purple-600 text-white border-purple-600':operation.type==='enrich-categories'?'bg-amber-700 hover:bg-amber-600 text-white border-amber-600':'bg-zinc-800 hover:bg-zinc-700 text-zinc-300 border-zinc-700';
        return <button key={operation.type} className={`inline-flex items-center px-3 py-2 rounded-none text-xs border disabled:opacity-40 ${color}`} title={operation.description} disabled={blocked(supplier.id,operation.type) || !!fetchError || !lastUpdated} onClick={()=>start(supplier,operation.type)} data-testid={`sync-${operation.type}-${supplier.id}`}>{busy[`supplier-${supplier.id}-${operation.type}`]?<Loader2 className="w-3 h-3 animate-spin mr-1"/>:<Icon className="w-3 h-3 mr-1"/>}{operation.type==='all'?'Sync All':operation.title}</button>;
      })}<button className="inline-flex items-center px-3 py-2 bg-emerald-700 hover:bg-emerald-600 text-white rounded-none text-xs border border-emerald-600 disabled:opacity-40" disabled={blocked(supplier.id,'lightspeed') || !!fetchError || !lastUpdated} onClick={()=>start(supplier,'lightspeed')} title="Push selected products to Lightspeed"><ShoppingBag className="w-3 h-3 mr-1"/>Push to Lightspeed</button></div></div>)}
      <a href="/export-review" className="inline-block text-xs text-blue-400 underline">Review prices, split groups and images before exporting</a>
    </CardContent></Card>
    <div className="flex flex-wrap gap-3"><select className={`${input} w-44`} aria-label="Filter supplier" value={supplierFilter} onChange={e=>{setSupplierFilter(e.target.value);setPage(1);}}><option value="all">All Suppliers</option>{suppliers.map(s=><option key={s.id} value={s.id}>{s.supplier_name}</option>)}</select><select className={`${input} w-40`} aria-label="Filter operation" value={typeFilter} onChange={e=>{setTypeFilter(e.target.value);setPage(1);}}>{['all','products','full','refresh','inventory','pricing','media','bulk_data','enrich_categories','lightspeed_push','odoo_push'].map(type=><option key={type} value={type}>{type==='all'?'All Types':label(type)}</option>)}</select><span className="py-2 text-xs text-zinc-500">{activeJobs.length} active jobs</span></div>
    <Card className="bg-zinc-900/50 border-zinc-800 rounded-sm"><CardHeader className="p-4 border-b border-zinc-800/50"><CardTitle className="font-heading text-sm font-bold uppercase text-zinc-400 tracking-wider">Sync Logs {activeJobs.length>0 && <span className="ml-2 text-blue-400 text-xs font-normal animate-pulse">LIVE</span>}</CardTitle></CardHeader><CardContent className="p-0">
      {loading && !logs.length ? <div className="p-4 space-y-2">{Array(5).fill(0).map((_,i)=><div key={i} className="h-10 bg-zinc-800/30 animate-pulse rounded-sm"/>)}</div> : !logs.length ? <div className="p-12 text-center text-zinc-600 font-mono text-sm">NO SYNC LOGS</div> : <div className="overflow-x-auto"><table className="w-full" data-testid="sync-logs-table"><thead><tr className="border-b border-zinc-800 bg-zinc-900/80">{['Type','Supplier','Status','Progress','Message','Started','Actions'].map(title=><th key={title} className="text-left p-3 text-xs font-mono text-zinc-500 uppercase tracking-wider">{title}</th>)}</tr></thead><tbody>{logs.map(job=>{
        const pct=Math.max(0,Math.min(100,Number(job.progress)||0));
        return <tr key={job.id} className="border-b border-zinc-800/50 hover:bg-zinc-800/30 transition-colors"><td className="p-3 text-sm font-mono">{job.sync_type}{job.parent_log_id && <p className="text-xs text-zinc-500">retry</p>}</td><td className="p-3 text-sm">{job.supplier_name}</td><td className="p-3"><Badge status={job.status}/></td><td className="p-3 min-w-[180px]"><div className="h-1.5 bg-zinc-800 rounded-full overflow-hidden"><div className="h-full bg-blue-500 transition-all duration-500 rounded-full" style={{width:`${pct}%`}}/></div><p className="text-xs font-mono text-zinc-400 mt-1">{job.processed_items || 0}/{job.total_items || 0} ({pct}%)</p>{job.managed && <p className="text-xs mt-1"><span className="text-emerald-400">{job.succeeded || 0} successful</span> · <span className="text-red-400">{job.failed || 0} failed</span> · {job.skipped || 0} skipped</p>}</td><td className="p-3 text-xs text-zinc-400 max-w-xs truncate" title={job.message}>{job.message}</td><td className="p-3 text-xs font-mono text-zinc-500">{localTime(job.start_time)}</td><td className="p-3"><div className="flex flex-wrap gap-2"><button className={button} onClick={()=>setSelected(job.id)}>Details</button>{job.status==='running' && <button className={`${button} text-red-400`} disabled={busy[`stop-${job.id}`]} onClick={()=>stop(job.id)}><Square className="w-3 h-3"/>Stop</button>}{job.status==='stopping' && <span className="text-xs text-orange-400">Stopping…</span>}{canRetry(job) && <button className={button} disabled={busy[`retry-${job.id}`] || blocked(job.supplier_id,job.sync_type)} onClick={()=>retry(job.id)}>Retry unfinished</button>}</div></td></tr>;
      })}</tbody></table></div>}
      <div className="p-4 border-t border-zinc-800 flex flex-wrap justify-between gap-3 text-xs text-zinc-500"><span>{lastUpdated?`Last refreshed ${lastUpdated.toLocaleTimeString()}`:'Waiting for refresh'}</span><div className="flex items-center gap-3"><button className={button} disabled={page===1} onClick={()=>setPage(p=>p-1)} aria-label="Previous page"><ChevronLeft className="w-4 h-4"/></button><span>Page {page}</span><button className={button} disabled={logs.length<20} onClick={()=>setPage(p=>p+1)} aria-label="Next page"><ChevronRight className="w-4 h-4"/></button></div></div>
    </CardContent></Card>
    {selected && <div className="fixed inset-0 z-50 bg-black/70 flex items-center justify-center p-4" onClick={e=>{if(e.target===e.currentTarget)setSelected('');}}><section className="w-full max-w-5xl max-h-[90vh] overflow-y-auto bg-zinc-950 border border-zinc-700 rounded-sm p-4 space-y-4" role="dialog" aria-modal="true" aria-label="Job details"><div className="flex justify-between gap-3"><h2 className="font-semibold">Job details</h2><button className={button} aria-label="Close job details" onClick={()=>setSelected('')}><X className="w-4 h-4"/></button></div>{detailError && <p role="alert" className="text-amber-400">{detailError}</p>}{!detail && !detailError && <p>Loading details…</p>}{detail && <><div className="flex flex-wrap gap-3 items-center"><p>{detail.supplier_name} · {label(detail.sync_type)}</p><Badge status={detail.status}/><p className="text-xs text-zinc-500 break-all">Job ID: {selected}</p></div><p>{detail.message}</p><label className="flex items-center gap-2 text-sm text-zinc-400"><input type="checkbox" checked={includeSkipped} onChange={e=>setIncludeSkipped(e.target.checked)}/>Include skipped items when retrying</label><div className="flex flex-wrap gap-3 text-sm"><span className="text-emerald-400">{detail.succeeded || 0} successful</span><span className="text-red-400">{detail.failed || 0} failed</span><span className="text-zinc-400">{detail.skipped || 0} skipped</span><span className="text-blue-400">{detail.item_counts?.running || 0} in flight</span></div>{detail.running_items?.length>0 && <div className="border border-blue-900 bg-blue-950/20 p-3"><p className="text-xs text-blue-400 mb-2">Currently fetching</p>{detail.running_items.map(item=><p key={item.stage+item.sku} className="text-sm">{label(item.stage)} · {item.sku}</p>)}</div>}<p className="text-sm text-zinc-400">Stage: {detail.stage || 'Older/export job'} · Latest activity SKU: {detail.current_sku || '—'} · Automatic retries: {detail.retries || 0}</p>{detail.last_error?.message && <div role="alert" className="bg-red-950/20 border border-red-900 rounded p-3"><p>{detail.last_error.code} {detail.last_error.sku && `· ${detail.last_error.sku}`}</p><p className="text-sm mt-1">{detail.last_error.message}</p></div>}{detail.status==='running' && <button className={`${button} text-red-400`} disabled={busy[`stop-${selected}`]} onClick={()=>stop(selected)}>Stop this job</button>}{detail.status==='stopping' && <p className="text-sm text-orange-400">Stopping; waiting for in-flight supplier requests…</p>}{canRetry(detail) && <button className={button} disabled={busy[`retry-${selected}`] || blocked(detail.supplier_id,detail.sync_type)} onClick={()=>retry(selected)}>{includeSkipped?'Retry failed, skipped and unfinished items':'Retry failed and unfinished items'}</button>}<p className="text-xs text-zinc-500">Full-sync counts represent product-stage operations: one product can have four items. Failures and skips below show the latest 100 records.</p>{detail.items?.length>0 && <div className="overflow-x-auto"><table className="w-full text-sm text-left"><thead><tr>{['SKU','Stage','Result','Code','Explanation'].map(title=><th className="p-2" key={title}>{title}</th>)}</tr></thead><tbody>{detail.items.map(item=><tr key={item.stage+item.sku} className="border-t border-zinc-800"><td className="p-2">{item.sku}</td><td className="p-2">{label(item.stage)}</td><td className="p-2">{item.status}</td><td className="p-2">{item.error_code}</td><td className="p-2 text-xs text-zinc-400">{item.message}</td></tr>)}</tbody></table></div>}</>}</section></div>}
  </div>;
}
