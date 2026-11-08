import React,{createContext,useContext,useEffect,useRef,useState} from 'react';
import {createPortal} from 'react-dom';
import axios from '../lib/axios';
import {toast} from 'sonner';
const API=(process.env.REACT_APP_BACKEND_URL||'').replace(/\/+$/,'')+'/api/lightspeed-sync';
const Context=createContext(null);
const button='rounded border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm text-zinc-200 hover:bg-zinc-800 disabled:opacity-40';
const words=value=>String(value||'').replace(/_/g,' ');
const message=e=>typeof e.response?.data?.detail==='string'?e.response.data.detail:e.response?.data?.detail?.message||e.message||'Request failed';
export const useLightspeedSync=()=>useContext(Context);
export function LightspeedSyncProvider({children}){
 const [jobs,setJobs]=useState([]),[id,setId]=useState(''),[data,setData]=useState(null),[open,setOpen]=useState(false);
 const [historyMode,setHistoryMode]=useState(false),[product,setProduct]=useState(null),[history,setHistory]=useState(null);
 const [search,setSearch]=useState(''),[issues,setIssues]=useState(false),[page,setPage]=useState(1),[revision,setRevision]=useState(0);
 const [error,setError]=useState(''),[starting,setStarting]=useState(false);
 const lock=useRef(false),dialog=useRef(null),lastNotification=useRef('');
 const refresh=()=>setRevision(n=>n+1);
 const showBatch=value=>{setId(value);setHistoryMode(false);setSearch('');setIssues(false);setPage(1);setOpen(true);};
 const showHistory=(productId,name)=>{setProduct(productId?{id:productId,name}:null);setHistoryMode(true);setSearch('');setIssues(true);setPage(1);setOpen(true);};
 useEffect(()=>{
  let stopped=false,timer,controller;
  const poll=async()=>{
   controller=new AbortController();
   try{const r=await axios.get(`${API}/jobs`,{signal:controller.signal});if(!stopped){setJobs(r.data);if(!id&&r.data.length)setId(r.data[0].id);}}
   catch(e){if(!stopped&&open)setError(message(e));}
   finally{if(!stopped)timer=setTimeout(poll,4000);}
  };poll();return()=>{stopped=true;clearTimeout(timer);controller?.abort();};
 },[id,revision,open]);
 useEffect(()=>{
  if(!id||historyMode)return;
  let stopped=false,timer,controller;setData(null);
  const poll=async()=>{
   controller=new AbortController();
   try{const r=await axios.get(`${API}/jobs/${id}`,{params:{page,search,issues_only:issues},signal:controller.signal});if(!stopped){setData(r.data);setError('');const key=`${id}:${r.data.status}:${r.data.counts.details_processed}`;if(lastNotification.current!==key){lastNotification.current=key;window.dispatchEvent(new Event('lightspeed-sync-updated'));}}}
   catch(e){if(!stopped)setError(message(e));}
   finally{if(!stopped)timer=setTimeout(poll,4000);}
  };poll();return()=>{stopped=true;clearTimeout(timer);controller?.abort();};
 },[id,historyMode,page,search,issues,revision]);
 useEffect(()=>{
  if(!historyMode||!open)return;
  const controller=new AbortController();setHistory(null);setError('');
  axios.get(`${API}/history`,{params:{product_id:product?.id,page,search,issues_only:issues},signal:controller.signal})
   .then(r=>{if(!controller.signal.aborted)setHistory(r.data);}).catch(e=>{if(!controller.signal.aborted)setError(message(e));});
  return()=>controller.abort();
 },[historyMode,product,page,search,issues,revision,open]);
 useEffect(()=>{
  if(!open)return;
  const previous=document.activeElement,overflow=document.body.style.overflow;document.body.style.overflow='hidden';dialog.current?.focus();
  const key=e=>{if(e.key==='Escape'){setOpen(false);return;}if(e.key!=='Tab')return;
   const nodes=[...(dialog.current?.querySelectorAll('button:not(:disabled),input,select,a[href],summary')||[])].filter(n=>n.getClientRects().length),first=nodes[0],last=nodes[nodes.length-1];
   if(!first){e.preventDefault();return;}if(e.shiftKey&&(document.activeElement===first||document.activeElement===dialog.current)){e.preventDefault();last.focus();}else if(!e.shiftKey&&(document.activeElement===last||document.activeElement===dialog.current)){e.preventDefault();first.focus();}};
  document.addEventListener('keydown',key);return()=>{document.body.style.overflow=overflow;document.removeEventListener('keydown',key);previous?.focus?.();};
 },[open]);
 const start=async body=>{
  if(lock.current)return;lock.current=true;setStarting(true);
  const signature=JSON.stringify(body);let request;
  try{request=JSON.parse(localStorage.getItem('lightspeed-sync-request')||'null');}catch{request=null;}
  if(request?.signature!==signature)request={signature,key:crypto.randomUUID()};
  localStorage.setItem('lightspeed-sync-request',JSON.stringify(request));
  try{const r=await axios.post(`${API}/jobs`,{...body,request_id:request.key},{timeout:30000});localStorage.removeItem('lightspeed-sync-request');showBatch(r.data.id);refresh();toast.success('Sync queued. You can continue using SupplierHub.');return r.data;}
  catch(e){if(e.response?.data?.detail?.job_id){showBatch(e.response.data.detail.job_id);refresh();}toast.error(message(e));throw e;}
  finally{lock.current=false;setStarting(false);}
 };
 const count=data?.counts||{},total=data?.total||0;
 const progress=total?Math.min(100,Math.round(((count.details_processed||0)+(count.finished||0))*50/total)):0;
 const current=jobs.find(job=>job.id===id)||jobs[0];
 const pages=Math.max(1,Math.ceil((historyMode?history?.total:data?.filtered_total||0)/50));
 return <Context.Provider value={{start,starting,showHistory,showBatch}}>{children}
  {current&&<div className="fixed bottom-3 left-3 right-3 sm:left-auto sm:w-96 z-40 rounded-lg border border-zinc-700 bg-zinc-950 p-3 text-zinc-100 shadow-xl"><button className="w-full text-left" onClick={()=>showBatch(current.id)}><span className="block text-sm font-medium">Lightspeed sync · {words(data?.status||current.status)}</span><span className="block text-xs text-zinc-400">{data?`${words(data.stage)} · ${count.details_processed||0}/${total} details checked · ${count.images_completed||0} images complete`:'Open progress and history'}</span>{total>0&&<progress aria-label="Batch progress" value={progress} max="100" className="mt-2 w-full accent-blue-500"/>}</button></div>}
  {open&&createPortal(<div className="fixed inset-0 z-[120] flex items-center justify-center bg-black/80 p-3" onMouseDown={e=>{if(e.target===e.currentTarget)setOpen(false);}}><section ref={dialog} role="dialog" aria-modal="true" aria-labelledby="sync-title" tabIndex={-1} className="flex max-h-[90dvh] w-full max-w-5xl flex-col overflow-hidden rounded-xl border border-zinc-700 bg-zinc-950 text-zinc-100 outline-none">
   <header className="flex justify-between gap-3 border-b border-zinc-800 p-4"><div><h2 id="sync-title" className="font-semibold">{historyMode?`Lightspeed sync history${product?` · ${product.name}`:''}`:'Lightspeed sync progress'}</h2><p className="text-xs text-zinc-400">You can close this popup and browse other pages. Server jobs continue.</p></div><button className={button} onClick={()=>setOpen(false)}>Close</button></header>
   <div className="min-h-0 space-y-4 overflow-auto p-4">
    <div className="flex gap-2"><button className={button} onClick={refresh}>Refresh</button><button className={button} onClick={()=>showHistory(null)}>Earlier sync jobs</button></div>
    {error&&<p role="alert" className="text-red-300 break-words">{error}</p>}
    {!historyMode&&<><label className="block text-sm">Batch<select value={id} onChange={e=>showBatch(e.target.value)} className="mt-1 w-full rounded border border-zinc-700 bg-zinc-900 p-2">{jobs.map(job=><option key={job.id} value={job.id}>{new Date(job.created_at).toLocaleString()} · {job.total||'Planning'} products · {words(job.status)}</option>)}</select></label>
     {!data&&!error&&<p role="status">Loading progress…</p>}
     {data&&<div className="space-y-2 rounded border border-zinc-800 p-3 text-sm"><p>{words(data.status)} · {words(data.stage)}{total?` · ${progress}%`:''}</p>{total>0&&<progress aria-label="Sync progress" value={progress} max="100" className="w-full accent-blue-500"/>}<p>Details verified: {count.details_completed} · Details failed: {count.details_failed} · Images complete: {count.images_completed} · Images need review: {count.images_pending}</p>{data.current&&<p className="text-blue-300">Currently processing: {data.current.sku} · {data.current.product_name}</p>}{data.selection?.category_id&&<p className="text-xs text-zinc-400">Category filter: {data.selection.category_id}</p>}{data.message&&<p className="text-amber-300 break-words">{data.message}</p>}<p className="text-xs text-zinc-400">The entire batch completes its product-detail stage before images begin. Progress counts product stages, not individual image uploads.</p></div>}
    </>}
    <div className="flex flex-wrap items-center gap-3"><input aria-label="Search sync results" placeholder="Search product or SKU" value={search} onChange={e=>{setSearch(e.target.value);setPage(1);}} className="min-w-0 flex-1 rounded border border-zinc-700 bg-zinc-900 p-2"/><label className="text-sm"><input type="checkbox" checked={issues} onChange={e=>{setIssues(e.target.checked);setPage(1);}}/> Issues only</label></div>
    {historyMode?<>{!history&&!error&&<p role="status">Loading history…</p>}{history&&<>{history.batches.map(item=><div key={item.batch_id} className="rounded border border-zinc-800 p-3"><p className="text-sm">{new Date(item.updated_at).toLocaleString()} · Details: {words(item.details_status)} · Images: {words(item.images_status)}</p><button className={button} onClick={()=>showBatch(item.batch_id)}>Open batch</button><Result item={item}/></div>)}<h3 className="text-sm">Recorded sync and repair jobs</h3>{history.earlier_jobs.map(item=><details key={item.id} className="rounded border border-zinc-800 p-3 text-sm"><summary className="cursor-pointer"><a className="text-blue-400 mr-2" href={`/export-review?product=${encodeURIComponent(item.product_id)}`}>{item.sku}</a>{new Date(item.updated_at).toLocaleString()} · {words(item.kind)} · {words(item.status)}</summary><pre className="mt-2 whitespace-pre-wrap break-words text-xs text-zinc-400">{JSON.stringify(item.result,null,2)}</pre></details>)}{!history.earlier_jobs.length&&!history.batches.length&&<p className="text-sm text-zinc-400">No recorded results match this filter.</p>}</>}</>:data&&<div className="overflow-x-auto"><table className="w-full text-left text-sm"><thead><tr><th className="p-2">Product</th><th className="p-2">Details</th><th className="p-2">Images</th><th className="p-2">Result</th></tr></thead><tbody>{data.items.map(item=><tr key={item.product_id} className="border-t border-zinc-800"><td className="p-2 align-top"><a className="text-blue-400" href={`/export-review?product=${encodeURIComponent(item.product_id)}`}>{item.sku}</a><p className="text-xs text-zinc-400">{item.product_name}</p></td><td className="p-2 align-top">{words(item.details_status)}</td><td className="p-2 align-top">{words(item.images_status)}</td><td className="p-2 align-top"><Result item={item}/></td></tr>)}</tbody></table>{!data.items.length&&<p className="p-3 text-sm text-zinc-400">No products match this filter.</p>}</div>}
    <div className="flex justify-between items-center"><button className={button} disabled={page<=1} onClick={()=>setPage(n=>n-1)}>Previous</button><span className="text-xs">Page {page} of {pages}</span><button className={button} disabled={page>=pages} onClick={()=>setPage(n=>n+1)}>Next</button></div>
   </div>
  </section></div>,document.body)}
 </Context.Provider>;
}
function Result({item}){return <details><summary className="cursor-pointer text-xs text-blue-400">View messages</summary><pre className="mt-2 max-h-72 overflow-auto whitespace-pre-wrap break-words text-xs text-zinc-400">{JSON.stringify({details:item.details_result,images:item.images_result},null,2)}</pre></details>;}
