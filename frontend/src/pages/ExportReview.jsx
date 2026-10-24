import React, { useCallback, useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import axios from '../lib/axios';
import { toast } from 'sonner';
import { Search, RefreshCw, X, ArrowRight, AlertTriangle, CheckCircle2, Layers, Image, ChevronLeft, ChevronRight, Package, Clock, ExternalLink } from 'lucide-react';

const API = (process.env.REACT_APP_BACKEND_URL || '').replace(/\/+$/, '') + '/api/export-review';
const PAGE_SIZE = 50;
const btn = 'inline-flex items-center justify-center gap-2 rounded-md border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm font-medium text-zinc-200 hover:bg-zinc-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 disabled:opacity-40 disabled:cursor-not-allowed';
const primary = `${btn} border-blue-600 bg-blue-600 text-white hover:bg-blue-500`;
const message = error => typeof error.response?.data?.detail === 'string' ? error.response.data.detail : error.message || 'Request failed. Please try again.';
const list = value => Array.isArray(value) ? value : [];
const json = value => { if (typeof value !== 'string') return value; try { return JSON.parse(value); } catch { return value; } };
const count = value => Array.isArray(json(value)) ? json(value).length : 0;
const words = value => String(value || '').replace(/_/g, ' ');
function isAdmin() { try { return JSON.parse(localStorage.getItem('user') || '{}').role === 'admin'; } catch { return false; } }
function issues(row) { return list(row.validation_errors).filter(Boolean); }
function status(row) {
  if (issues(row).length) return {label:'Needs review', tone:'amber'};
  if (row.previous_export_failed) return {label:'Retry needed', tone:'red'};
  return {label:'Ready', tone:'green'};
}
function Badge({children, tone='neutral'}) {
  const tones = {neutral:'border-zinc-700 bg-zinc-800/50 text-zinc-300', amber:'border-amber-800/60 bg-amber-950/40 text-amber-300', red:'border-red-800/60 bg-red-950/40 text-red-300', green:'border-emerald-800/60 bg-emerald-950/40 text-emerald-300', blue:'border-blue-800/60 bg-blue-950/40 text-blue-300'};
  return <span className={`inline-flex items-center rounded-md border px-2 py-1 text-xs font-medium whitespace-nowrap ${tones[tone] || tones.neutral}`}>{children}</span>;
}
function Metric({icon:Icon, label, value}) { return <div className="rounded-lg border border-zinc-800 bg-zinc-900/50 p-3"><div className="flex items-center gap-2 text-xs text-zinc-500"><Icon size={14} />{label}</div><div className="mt-2 text-lg font-semibold text-zinc-100">{value ?? '—'}</div></div>; }
function FamilyCard({group, preview=false}) {
  const sizes = list(group.sizes);
  const state = preview ? 'Preview' : words(group.state || 'planned');
  const tone = group.state === 'done' ? 'green' : ['uncertain','images_pending'].includes(group.state) ? 'amber' : 'neutral';
  return <div className="rounded-lg border border-zinc-800 bg-zinc-900/30 p-4 space-y-3">
    <div className="flex flex-wrap items-center justify-between gap-2"><div className="min-w-0"><p className="font-medium text-zinc-100 break-words">{group.name || `Group ${group.group_number ?? group.number}`}</p><p className="text-xs text-zinc-500 mt-1">{preview ? group.count : count(group.variant_ids)} variants{sizes.length ? ` · ${sizes.join(', ')}` : ''}</p></div><Badge tone={tone}>{state}</Badge></div>
    {group.message && <details className="text-sm"><summary className="cursor-pointer text-amber-300">Export details</summary><p className="mt-2 whitespace-pre-wrap break-words text-zinc-400">{group.message}</p></details>}
    {(group.lightspeed_product_id || list(group.variant_skus).length > 0) && <details className="text-xs text-zinc-500"><summary className="cursor-pointer">{preview ? 'View variant SKUs' : 'Destination details'}</summary>{preview ? <p className="mt-2 break-all">{list(group.variant_skus).join(', ')}</p> : <p className="mt-2 break-all">{group.lightspeed_product_id}</p>}</details>}
  </div>;
}

export default function ExportReview() {
  const [search,setSearch] = useState('');
  const [oversized,setOversized] = useState(false);
  const [issuesOnly,setIssuesOnly] = useState(true);
  const [page,setPage] = useState(1);
  const [rows,setRows] = useState([]);
  const [total,setTotal] = useState(0);
  const [loading,setLoading] = useState(true);
  const [listError,setListError] = useState('');
  const [revision,setRevision] = useState(0);
  const [selected,setSelected] = useState(()=>new URLSearchParams(window.location.search).get('product') || '');
  const [detail,setDetail] = useState(null);
  const [detailError,setDetailError] = useState('');
  const [detailLoading,setDetailLoading] = useState(false);
  const [tab,setTab] = useState('overview');
  const [preview,setPreview] = useState(null);
  const [busy,setBusy] = useState('');
  const [confirmReset,setConfirmReset] = useState(false);
  const dialogRef = useRef(null);
  const selectedRef = useRef(selected);
  const mounted = useRef(false);
  const detailSequence = useRef(0);
  const actionRef = useRef(false);
  const busyRef = useRef('');
  selectedRef.current = selected;
  busyRef.current = busy;
  const admin = isAdmin();
  const groups = list(detail?.groups);
  const jobs = list(detail?.jobs);
  const running = jobs.some(job=>['running','pending','queued'].includes(job.status));
  const locked = !!busy || running;
  const product = detail?.product || {};
  const readiness = detail?.readiness || {};
  const errors = list(readiness.validation_errors);
  const canPlan = !!detail && Number(detail.variant_count)>200 && !product.lightspeed_product_id && !groups.some(g=>g.lightspeed_product_id || g.state!=='planned');
  const hasDestination = !!product.lightspeed_product_id || groups.some(g=>g.lightspeed_product_id);
  const preLink = `/preprocessing?search=${encodeURIComponent(product.supplier_sku || '')}`;
  const refresh = () => setRevision(n=>n+1);
  useEffect(()=>{mounted.current=true;return()=>{mounted.current=false;};},[]);

  useEffect(()=>{
    const controller = new AbortController();
    setLoading(true);setListError('');
    const timer = setTimeout(async()=>{
      try {
        const params={search,oversized,issues_only:issuesOnly,page};
        const res=await axios.get(`${API}/products`,{params,signal:controller.signal});
        if(controller.signal.aborted)return;
        const nextTotal=Number(res.data.total)||0;
        const last=Math.max(1,Math.ceil(nextTotal/PAGE_SIZE));
        if(page>last){setPage(last);return;}
        setRows(list(res.data.products));setTotal(nextTotal);
      } catch(error){if(!controller.signal.aborted)setListError(message(error));}
      finally{if(!controller.signal.aborted)setLoading(false);}
    },250);
    return()=>{clearTimeout(timer);controller.abort();};
  },[search,oversized,issuesOnly,page,revision]);

  const refreshDetail = useCallback(async(id=selectedRef.current)=>{
    if(!id)return;
    const seq=++detailSequence.current;
    const res=await axios.get(`${API}/products/${id}`);
    if(mounted.current && selectedRef.current===id && seq===detailSequence.current){setDetail(res.data);setDetailError('');}
  },[]);
  useEffect(()=>{
    const controller=new AbortController();
    const seq=++detailSequence.current;
    setDetail(null);setDetailError('');setPreview(null);setTab('overview');setConfirmReset(false);
    if(!selected){setDetailLoading(false);return;}
    setDetailLoading(true);
    axios.get(`${API}/products/${selected}`,{signal:controller.signal}).then(res=>{
      if(!controller.signal.aborted && seq===detailSequence.current)setDetail(res.data);
    }).catch(error=>{if(!controller.signal.aborted && seq===detailSequence.current)setDetailError(message(error));})
      .finally(()=>{if(!controller.signal.aborted && seq===detailSequence.current)setDetailLoading(false);});
    return()=>controller.abort();
  },[selected]);
  useEffect(()=>{
    if(!running || !selected)return;
    let stopped=false,timer;
    const poll=async()=>{
      try{await refreshDetail(selected);}catch(error){if(!stopped)setDetailError(message(error));}
      finally{if(!stopped){refresh();timer=setTimeout(poll,4000);}}
    };
    timer=setTimeout(poll,4000);
    return()=>{stopped=true;clearTimeout(timer);};
  },[running,selected,refreshDetail]);

  // A portal keeps the dialog above layout containers with transforms or overflow.
  useEffect(()=>{
    if(!selected)return;
    const previousFocus=document.activeElement,overflow=document.body.style.overflow;
    document.body.style.overflow='hidden';
    dialogRef.current?.focus();
    const onKey=event=>{
      if(event.key==='Escape'){if(!busyRef.current)setSelected('');event.preventDefault();return;}
      if(event.key!=='Tab')return;
      const elements=[...(dialogRef.current?.querySelectorAll('button:not(:disabled), input:not(:disabled), a[href], summary, [tabindex="0"]')||[])].filter(el=>el.getClientRects().length);
      if(!elements.length){event.preventDefault();dialogRef.current?.focus();return;}
      const first=elements[0],last=elements[elements.length-1];
      if(!dialogRef.current?.contains(document.activeElement)||document.activeElement===dialogRef.current){event.preventDefault();(event.shiftKey?last:first).focus();}
      else if(event.shiftKey&&document.activeElement===first){event.preventDefault();last.focus();}
      else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first.focus();}
    };
    document.addEventListener('keydown',onKey);
    return()=>{document.body.style.overflow=overflow;document.removeEventListener('keydown',onKey);previousFocus?.focus?.();};
  },[selected]);

  const perform=async(label,action)=>{
    if(actionRef.current)return;
    actionRef.current=true;
    const id=selectedRef.current;
    setBusy(label);
    try{await action(id);}catch(error){if(mounted.current)toast.error(message(error));}
    finally{actionRef.current=false;if(mounted.current)setBusy('');}
  };
  const request=async(url,body)=>{
    const res=await axios.post(url,body);
    if(res.data?.success===false)throw new Error(res.data.error || res.data.message || 'The request could not be completed.');
    return res;
  };
  const makePreview=()=>perform('preview',async id=>{
    const res=await request(`${API}/products/${id}/split-preview`);
    if(selectedRef.current===id){setPreview(res.data);setTab('groups');}
  });
  const savePlan=()=>perform('save',async id=>{
    if(!preview?.digest)throw new Error('Create a fresh preview first.');
    await request(`${API}/products/${id}/split-plan`,{digest:preview.digest,store_domain:preview.store_domain});
    if(selectedRef.current===id)setPreview(null);
    await refreshDetail(id);refresh();toast.success('Size groups saved');
  });
  const refreshPricing=()=>perform('pricing',async id=>{
    await request(`${API.replace('/export-review','')}/sync/product/${id}/pricing`);
    await refreshDetail(id);refresh();toast.success('Pricing refresh requested');
  });
  const repair=()=>perform('images',async id=>{
    await request(`${API}/products/${id}/repair-images`);await refreshDetail(id);refresh();toast.success('Image repair requested');
  });
  const reset=()=>perform('reset',async id=>{
    await request(`${API}/products/${id}/reset-deleted-plan`);
    if(selectedRef.current===id){setPreview(null);setConfirmReset(false);}
    await refreshDetail(id);refresh();toast.success('Destination verification finished');
  });
  const headerStatus=errors.length ? {label:'Needs review',tone:'amber'} : readiness.previous_export_failed ? {label:'Retry needed',tone:'red'} : readiness.is_valid ? {label:'Ready',tone:'green'} : {label:'Review',tone:'neutral'};

  return <div className="p-4 md:p-6 space-y-5 min-w-0 text-zinc-100">
    <div className="flex flex-wrap items-center justify-between gap-3"><div><h1 className="text-2xl font-semibold tracking-tight">Export Review</h1><p className="text-sm text-zinc-500 mt-1">Resolve issues and prepare size groups.</p></div><a href="/preprocessing" className={btn}>Pre-processing<ArrowRight size={15}/></a></div>
    <div className="flex flex-wrap items-center gap-3 rounded-lg border border-zinc-800 bg-zinc-900/30 p-3">
      <div className="relative flex-1 min-w-[200px]"><Search className="absolute left-3 top-3 text-zinc-500" size={16}/><input aria-label="Search products" value={search} onChange={e=>{setSearch(e.target.value);setPage(1);}} placeholder="Search product name or SKU" className="w-full rounded-md border border-zinc-700 bg-zinc-950 py-2 pl-9 pr-3 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" /></div>
      <div className="flex rounded-md border border-zinc-700 p-1 gap-1" aria-label="Review filter">{[{label:'Needs review',value:true},{label:'All products',value:false}].map(item=><button key={item.label} aria-pressed={issuesOnly===item.value} className={`rounded px-3 py-1.5 text-sm ${issuesOnly===item.value?'bg-blue-600 text-white':'text-zinc-400 hover:text-white'}`} onClick={()=>{setIssuesOnly(item.value);setPage(1);}}>{item.label}</button>)}</div>
      <label className="inline-flex items-center gap-2 text-sm text-zinc-300 whitespace-nowrap"><input type="checkbox" className="accent-blue-500" checked={oversized} onChange={e=>{setOversized(e.target.checked);setPage(1);}}/>200+ variants</label>
      <button className={btn} disabled={loading} onClick={refresh} aria-label="Refresh products"><RefreshCw size={15} className={loading?'animate-spin':''}/><span className="hidden sm:inline">Refresh</span></button>
    </div>
    <div className="flex items-center justify-between text-xs text-zinc-500"><span>{loading?'Loading products…':`${total.toLocaleString()} products`}</span><span>Review → Prepare → Sync</span></div>
    <div className="overflow-x-auto rounded-lg border border-zinc-800" aria-busy={loading}>
      <table className="w-full text-sm min-w-[760px]"><thead className="bg-zinc-900/70 text-xs text-zinc-400"><tr className="text-left"><th className="px-4 py-3 w-1/3 font-medium">Product</th><th className="px-4 py-3 font-medium">Supplier cost</th><th className="px-4 py-3 font-medium">Variants</th><th className="px-4 py-3 font-medium">Status / issue</th><th className="px-4 py-3 text-right font-medium">Action</th></tr></thead>
      <tbody>{!listError&&!loading&&rows.map(row=>{const state=status(row),problems=issues(row);return <tr key={row.id} className="border-t border-zinc-800 hover:bg-zinc-900/40"><td className="px-4 py-4"><p className="font-medium text-zinc-100 break-words">{row.product_name || row.supplier_sku}</p><p className="mt-1 text-xs text-zinc-500">{row.supplier_sku} · {row.supplier_name || 'Supplier unavailable'}</p><div className="mt-2 flex gap-3 text-xs text-zinc-500"><span className="inline-flex items-center gap-1"><Image size={12}/>{row.image_count ?? 0} images</span>{Number(row.group_count)>0&&<span className="inline-flex items-center gap-1"><Layers size={12}/>{row.group_count} groups</span>}</div></td><td className="px-4 py-4 whitespace-nowrap">{row.price_needs_review || !Number.isFinite(Number(row.base_price)) || Number(row.base_price)<=0 ? <span className="text-amber-300 text-xs">Check price</span> : `$${Number(row.base_price).toFixed(2)}`}</td><td className="px-4 py-4"><span className="font-medium">{row.variant_count ?? 0}</span></td><td className="px-4 py-4 max-w-xs"><Badge tone={state.tone}>{state.label}</Badge>{problems.length>0&&<p className="mt-2 text-xs text-zinc-400 line-clamp-2 break-words" title={problems.join('; ')}>{problems[0]}{problems.length>1?` · +${problems.length-1} more`:''}</p>}{!problems.length&&row.previous_export_failed&&<p className="mt-2 text-xs text-zinc-400">Review the last export result</p>}</td><td className="px-4 py-4 text-right"><button className={btn} onClick={()=>setSelected(row.id)}>Review<ChevronRight size={14}/></button></td></tr>;})}</tbody></table>
      {loading&&<div role="status" className="flex items-center justify-center gap-2 p-12 text-zinc-500"><RefreshCw size={18} className="animate-spin"/>Loading products…</div>}
      {!loading&&listError&&<div role="alert" className="p-10 text-center"><p className="text-red-300 mb-3">{listError}</p><button className={btn} onClick={refresh}>Try again</button></div>}
      {!loading&&!listError&&!rows.length&&<div className="p-12 text-center"><CheckCircle2 className="mx-auto text-zinc-600 mb-3" size={28}/><p className="font-medium">No products found</p><p className="text-sm text-zinc-500 mt-1">Try a different search or filter.</p></div>}
    </div>
    <div className="flex flex-wrap items-center justify-between gap-3 text-xs text-zinc-500"><span>{total?`${(page-1)*PAGE_SIZE+1}–${Math.min(page*PAGE_SIZE,total)} of ${total}`:'0 products'}</span><div className="flex items-center gap-3"><button className={btn} disabled={loading||page===1} onClick={()=>setPage(p=>p-1)}><ChevronLeft size={14}/>Previous</button><span>Page {page} of {Math.max(1,Math.ceil(total/PAGE_SIZE))}</span><button className={btn} disabled={loading||page*PAGE_SIZE>=total} onClick={()=>setPage(p=>p+1)}>Next<ChevronRight size={14}/></button></div></div>

    {selected&&createPortal(<div className="fixed inset-0 z-[100] bg-black/80 flex items-center justify-center p-2 sm:p-6" onMouseDown={event=>{if(event.target===event.currentTarget&&!busy)setSelected('');}}>
      <section ref={dialogRef} tabIndex={-1} role="dialog" aria-modal="true" aria-labelledby="export-review-heading" className="flex flex-col w-full max-w-4xl overflow-hidden rounded-xl border border-zinc-700 bg-zinc-950 shadow-2xl outline-none" style={{height:'min(88dvh, 820px)',maxHeight:'calc(100dvh - 16px)'}}>
        <header className="shrink-0 border-b border-zinc-800 px-4 sm:px-6 py-4"><div className="flex items-start justify-between gap-3"><div className="min-w-0"><p className="text-xs text-zinc-500 uppercase tracking-wider mb-1">Product review</p><h2 id="export-review-heading" className="text-lg font-semibold text-zinc-100 break-words">{product.product_name || 'Export Review'}</h2>{product.supplier_sku&&<p className="text-xs text-zinc-500 mt-1">{product.supplier_sku}{product.supplier_name?` · ${product.supplier_name}`:''}</p>}</div><button className={`${btn} p-2 shrink-0`} disabled={!!busy} aria-label="Close review" onClick={()=>setSelected('')}><X size={18}/></button></div>
          {detail&&<div className="flex flex-wrap items-center justify-between gap-2 mt-3"><Badge tone={headerStatus.tone}>{headerStatus.label}</Badge><button className="text-xs text-zinc-400 hover:text-white inline-flex gap-1.5 items-center disabled:opacity-40" disabled={locked} onClick={()=>perform('refresh',id=>refreshDetail(id))}><RefreshCw size={12} className={busy==='refresh'?'animate-spin':''}/>Refresh</button></div>}
        </header>
        {detail&&<nav className="shrink-0 flex gap-1 px-4 sm:px-6 border-b border-zinc-800" aria-label="Review sections">{[{key:'overview',label:'Overview'},{key:'groups',label:`Size groups${preview?` (${list(preview.groups).length})`:groups.length?` (${groups.length})`:''}`},{key:'activity',label:'Activity'}].map(item=><button key={item.key} aria-pressed={tab===item.key} onClick={()=>setTab(item.key)} className={`px-3 py-3 text-sm border-b-2 ${tab===item.key?'border-blue-500 text-blue-400':'border-transparent text-zinc-500 hover:text-zinc-200'}`}>{item.label}</button>)}</nav>}
        <div className="flex-1 min-h-0 overflow-y-auto overscroll-contain px-4 sm:px-6 py-5 space-y-5">
          {detailLoading&&<div role="status" className="p-10 flex justify-center gap-2 text-zinc-500"><RefreshCw size={18} className="animate-spin"/>Loading review…</div>}
          {detailError&&<div role="alert" className="rounded-lg border border-red-900 bg-red-950/20 p-4 text-sm text-red-300 break-words">{detailError}{!detail&&<button className={`${btn} mt-3 block`} onClick={()=>perform('refresh',id=>refreshDetail(id))}>Try again</button>}</div>}
          {detail&&running&&<div role="status" className="rounded-lg border border-blue-900 bg-blue-950/20 p-3 flex items-center gap-2 text-sm text-blue-300"><RefreshCw size={15} className="animate-spin"/>Job running. Results update automatically.</div>}
          {detail&&tab==='overview'&&<>
            <div className="grid grid-cols-3 gap-2 sm:gap-3"><Metric icon={Package} label="Variants" value={detail.variant_count}/><Metric icon={Image} label="Source images" value={detail.images}/><Metric icon={Layers} label="Size groups" value={groups.length}/></div>
            {errors.length ? <div className="rounded-lg border border-amber-900/60 bg-amber-950/10"><div className="px-4 py-3 border-b border-amber-900/40 flex items-center gap-2 text-sm font-medium text-amber-300"><AlertTriangle size={16}/>Needs attention<Badge tone="amber">{errors.length}</Badge></div><ul className="divide-y divide-zinc-800">{errors.map((error,i)=><li key={`${i}-${error}`} className="px-4 py-3 text-sm text-zinc-300 break-words">{error}</li>)}</ul></div> : <div className={`rounded-lg border p-4 flex items-start gap-3 ${readiness.previous_export_failed?'border-amber-900 bg-amber-950/10':'border-emerald-900 bg-emerald-950/10'}`}>{readiness.previous_export_failed?<AlertTriangle size={18} className="text-amber-400 shrink-0"/>:<CheckCircle2 size={18} className="text-emerald-400 shrink-0"/>}<div><p className="text-sm font-medium">{readiness.previous_export_failed?'Source checks passed. Previous export needs a retry.':readiness.is_valid?'Ready for Pre-processing':'Check the latest review results'}</p><p className="text-xs text-zinc-500 mt-1">{readiness.previous_export_failed?'Check Activity, then retry in Pre-processing.':'Sync products from Pre-processing.'}</p></div></div>}
            <div><h3 className="text-sm font-medium mb-3">Quick actions</h3><div className="flex flex-wrap gap-2"><a href="/category-mapping" className={btn}>Category mapping<ExternalLink size={13}/></a><a href="/sync" className={btn}>Supplier sync<ExternalLink size={13}/></a><button className={btn} disabled={!admin||locked} onClick={refreshPricing}>{busy==='pricing'&&<RefreshCw size={14} className="animate-spin"/>}Refresh pricing</button><button className={btn} disabled={!admin||locked||!detail.images||!hasDestination} onClick={repair}>{busy==='images'&&<RefreshCw size={14} className="animate-spin"/>}Repair images</button></div></div>
            {Number(detail.variant_count)>200&&<button className="w-full rounded-lg border border-zinc-800 bg-zinc-900/40 p-4 flex items-center justify-between gap-3 text-left hover:border-zinc-600" onClick={()=>setTab('groups')}><span className="flex items-center gap-3"><Layers size={19} className="text-blue-400"/><span><span className="block text-sm font-medium">Size groups</span><span className="block text-xs text-zinc-500 mt-1">{groups.length?`${groups.length} saved groups`:'Prepare groups of up to 200 variants'}</span></span></span><ChevronRight size={17}/></button>}
          </>}
          {detail&&tab==='groups'&&<>
            <div className="flex flex-wrap items-center justify-between gap-3"><div><h3 className="text-sm font-medium">{preview?'Preview size groups':'Saved size groups'}</h3><p className="text-xs text-zinc-500 mt-1">Up to 200 variants per Lightspeed product family.</p></div>{canPlan&&<button className={btn} disabled={!admin||locked} onClick={makePreview}>{busy==='preview'?<RefreshCw size={14} className="animate-spin"/>:<Layers size={14}/>} {groups.length||preview?'Rebuild preview':'Create preview'}</button>}</div>
            {preview&&<div className="rounded-lg border border-blue-900 bg-blue-950/20 px-4 py-3 flex flex-wrap items-center justify-between gap-2 text-sm"><span className="text-blue-300">Preview · not saved{preview.replaces_unexported_plan?' · replaces the unexported plan':''}</span><button className="text-xs text-zinc-400 hover:text-white" disabled={!!busy} onClick={()=>setPreview(null)}>Discard preview</button></div>}
            {(preview?list(preview.groups):groups).map(group=><FamilyCard key={preview?group.number:group.id} group={group} preview={!!preview}/>)}
            {!preview&&!groups.length&&<div className="text-center py-10 text-zinc-500"><Layers size={28} className="mx-auto mb-3"/><p className="text-sm">{Number(detail.variant_count)>200?'No size groups yet':'Size groups are not required'}</p></div>}
            <details className="rounded-lg border border-zinc-800 p-4"><summary className="cursor-pointer text-sm text-zinc-400">Advanced recovery</summary><div className="mt-4 space-y-3"><p className="text-xs text-zinc-500">Use only when Lightspeed destinations were deleted or the saved plan is obsolete.</p>{!confirmReset?<button className={btn} disabled={!admin||locked} onClick={()=>setConfirmReset(true)}>Verify destinations / reset plan</button>:<div className="rounded border border-amber-900 p-3 space-y-3"><p className="text-sm text-amber-300">Verify deleted destinations and reset the saved plan?</p><div className="flex flex-wrap gap-2"><button className={btn} disabled={!admin||locked} onClick={reset}>{busy==='reset'?'Verifying…':'Verify and reset'}</button><button className={btn} disabled={!!busy} onClick={()=>setConfirmReset(false)}>Cancel</button></div></div>}</div></details>
          </>}
          {detail&&tab==='activity'&&<><h3 className="text-sm font-medium">Recent jobs</h3>{!jobs.length&&<div className="py-10 text-center text-zinc-500"><Clock size={26} className="mx-auto mb-3"/><p className="text-sm">No jobs recorded</p></div>}{jobs.map(job=><details key={job.id} className="rounded-lg border border-zinc-800 bg-zinc-900/30"><summary className="cursor-pointer p-4 text-sm"><span className="font-medium">{words(job.kind)}</span><span className="ml-3 text-zinc-500">{words(job.status)}</span></summary><pre className="border-t border-zinc-800 p-4 text-xs text-zinc-400 whitespace-pre-wrap break-words overflow-x-auto">{JSON.stringify(json(job.result),null,2) || 'No result recorded'}</pre></details>)}</>}
          {detail&&!admin&&<p className="text-xs text-zinc-500">An administrator can refresh pricing, repair images, and save groups.</p>}
        </div>
        <footer className="shrink-0 border-t border-zinc-800 px-4 sm:px-6 py-4 flex flex-wrap items-center justify-between gap-3 bg-zinc-950"><button className={btn} disabled={!!busy} onClick={()=>setSelected('')}>Close</button><div className="flex flex-wrap items-center gap-2">{preview&&tab==='groups'&&<button className={primary} disabled={!admin||locked||!list(preview.groups).length} onClick={savePlan}>{busy==='save'&&<RefreshCw size={14} className="animate-spin"/>}Save size groups</button>}{detail&&<a href={preLink} className={preview&&tab==='groups'?btn:primary}>Pre-processing<ArrowRight size={15}/></a>}</div></footer>
      </section>
    </div>,document.body)}
  </div>;
}
