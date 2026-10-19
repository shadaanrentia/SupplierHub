import React, { useCallback, useEffect, useRef, useState } from 'react';
import axios from '../lib/axios';
import { toast } from 'sonner';

const API = (process.env.REACT_APP_BACKEND_URL || '').replace(/\/+$/, '') + '/api/export-review';
const message = error => typeof error.response?.data?.detail === 'string' ? error.response.data.detail : error.message;
function isAdmin() { try { return JSON.parse(localStorage.getItem('user') || '{}').role === 'admin'; } catch { return false; } }
const buttonClass = 'border border-zinc-700 rounded px-3 py-2 text-sm disabled:opacity-40';

export default function ExportReview() {
  const [search, setSearch] = useState('');
  const [oversized, setOversized] = useState(false);
  const [issuesOnly, setIssuesOnly] = useState(true);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [rows, setRows] = useState([]);
  const [selected, setSelected] = useState(()=>new URLSearchParams(window.location.search).get('product') || '');
  const [detail, setDetail] = useState(null);
  const [preview, setPreview] = useState(null);
  const [detailError, setDetailError] = useState('');
  const dialogRef = useRef(null);
  const selectedRef = useRef(selected);
  selectedRef.current = selected;
  const [busy, setBusy] = useState(false);
  const [groupIds, setGroupIds] = useState({});
  const admin = isAdmin();
  const running = detail?.jobs?.some(job => job.status === 'running');
  const locked = busy || running;

  const refresh = useCallback(async () => {
    const params = new URLSearchParams({ search, oversized: String(oversized), issues_only: String(issuesOnly), page: String(page) });
    const response = await axios.get(`${API}/products?${params}`);
    setRows(response.data.products || []); setTotal(response.data.total || 0);
  }, [search, oversized, issuesOnly, page]);
  useEffect(() => {
    let live = true;
    const timer = setTimeout(() => {
      const params = new URLSearchParams({ search, oversized: String(oversized), issues_only: String(issuesOnly), page: String(page) });
      axios.get(`${API}/products?${params}`).then(response => { if(live) {setRows(response.data.products || []);setTotal(response.data.total || 0);} }).catch(error => { if(live) toast.error(message(error)); });
    }, 250);
    return () => { live = false; clearTimeout(timer); };
  }, [search, oversized, issuesOnly, page]);
  const refreshDetail = useCallback(async () => {
    if (!selected) return;
    const result = await axios.get(`${API}/products/${selected}`);
    if (selectedRef.current === selected) setDetail(result.data);
  }, [selected]);
  useEffect(() => {
    let live = true;
    setDetail(null); setPreview(null); setDetailError(''); setGroupIds({});
    if(selected) axios.get(`${API}/products/${selected}`).then(response => { if(live) setDetail(response.data); }).catch(error => { if(live) { setDetailError(message(error)); toast.error(message(error)); } });
    return () => { live = false; };
  }, [selected]);
  useEffect(() => {
    if (!running) return;
    const timer = setInterval(() => refreshDetail().catch(error => toast.error(message(error))), 3000);
    return () => clearInterval(timer);
  }, [running, refreshDetail]);
  useEffect(() => {
    if (!selected) return;
    const previousFocus = document.activeElement;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    dialogRef.current?.querySelector('button')?.focus();
    const onKey = event => {
      if (event.key === 'Escape') { setSelected(''); return; }
      if (event.key !== 'Tab') return;
      const elements = [...(dialogRef.current?.querySelectorAll('button:not(:disabled), input:not(:disabled), a[href], summary, [tabindex="0"]') || [])];
      if (!elements.length) { event.preventDefault(); return; }
      const first = elements[0], last = elements[elements.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    };
    document.addEventListener('keydown', onKey);
    return () => { document.body.style.overflow = previousOverflow; document.removeEventListener('keydown', onKey); previousFocus?.focus?.(); };
  }, [selected]);
  const perform = async action => {
    setBusy(true);
    try { await action(); } catch(error) { toast.error(message(error)); }
    finally { setBusy(false); }
  };
  const makePreview = () => perform(async () => {
    const result = await axios.post(`${API}/products/${selected}/split-preview`);
    setPreview(result.data);
  });
  const savePlan = () => perform(async () => {
    await axios.post(`${API}/products/${selected}/split-plan`, {digest:preview.digest,store_domain:preview.store_domain});
    setPreview(null); await refreshDetail(); await refresh(); toast.success('Split plan saved. Check readiness, then sync from Pre-processing.');
  });
  const start = action => perform(async () => {
    await axios.post(`${API}/products/${selected}/${action}`);
    await refreshDetail(); toast.success(action === 'sync' ? 'Export job started' : 'Image-only repair started');
  });
  return <div className="p-4 md:p-6 space-y-5 min-w-0">
    <h1 className="text-2xl font-bold">Export Review</h1>
    <p className="text-zinc-400">Fix the issues listed here, or save size families for products with more than 200 variants. Ready products and automatic image retries are handled in Pre-processing. Each reviewed group creates a separate Lightspeed family with at most 200 variants.</p>
    <div className="flex flex-wrap gap-3">
      <input aria-label="Search exports" className="bg-zinc-900 border border-zinc-700 rounded px-3 py-2" placeholder="Search name or style SKU" value={search} onChange={e=>{setSearch(e.target.value);setPage(1);}} />
      <label className="flex items-center gap-2"><input type="checkbox" checked={issuesOnly} onChange={e=>{setIssuesOnly(e.target.checked);setPage(1);}} />Only products needing review</label>
      <label className="flex items-center gap-2"><input type="checkbox" checked={oversized} onChange={e=>{setOversized(e.target.checked);setPage(1);}} />Only products with more than 200 variants</label>
      <button className={buttonClass} disabled={busy} onClick={()=>perform(refresh)}>Refresh</button>
    </div>
    <div className="overflow-x-auto border border-zinc-800 rounded">
      <table className="w-full text-sm"><thead><tr className="text-left"><th className="p-3">Product / supplier</th><th>Cost</th><th>Variants</th><th>Source images</th><th>Families</th><th>Issues</th><th className="p-3">Action</th></tr></thead>
      <tbody>{rows.map(row=><tr key={row.id} className="border-t border-zinc-800"><td className="p-3">{row.product_name}<p className="text-xs text-zinc-500">{row.supplier_sku} · {row.supplier_name || 'No matching supplier'}<br />{row.id}</p></td><td>{row.price_needs_review || Number(row.base_price)<=0 ? 'Needs review' : row.base_price}</td><td>{row.variant_count}</td><td>{row.image_count}</td><td>{row.group_count}</td><td className="max-w-sm text-amber-300">{row.validation_errors?.join("; ") || (row.previous_export_failed ? "Previous export failed; retry in Pre-processing" : "Ready")}</td><td className="p-3"><button className={buttonClass} disabled={locked} onClick={()=>setSelected(row.id)}>Review</button></td></tr>)}</tbody></table>
      {!rows.length && <p className="p-4">No products match this filter.</p>}
    </div>
    <div className="flex gap-3"><button className={buttonClass} disabled={page===1} onClick={()=>setPage(p=>p-1)}>Previous</button><span className="py-2">Page {page}</span><button className={buttonClass} disabled={page*50>=total} onClick={()=>setPage(p=>p+1)}>Next</button></div>
    {selected && <div className="fixed inset-0 z-50 bg-black/75 flex items-center justify-center p-4" onClick={event=>{if(event.target===event.currentTarget)setSelected('');}}>
      <section ref={dialogRef} role="dialog" aria-modal="true" aria-labelledby="export-review-heading" className="w-full max-w-6xl max-h-[90vh] overflow-y-auto bg-zinc-950 border border-zinc-700 rounded p-4 space-y-4">
        <div className="flex items-center justify-between gap-3"><h2 id="export-review-heading" className="text-xl font-semibold">Export review</h2><button className={buttonClass} aria-label="Close export review" onClick={()=>setSelected('')}>Close ×</button></div>
        {detailError && <p role="alert" className="text-red-400">{detailError}</p>}
        {!detail && !detailError && <p role="status">Loading product review…</p>}
        {detail && <>
      <h2 className="text-xl font-semibold">{detail.product.product_name}</h2>
      <p>{detail.variant_count} active variants · {detail.images} source image records</p>
      {detail.readiness?.validation_errors?.length ? <ul role="alert" className="text-amber-400 list-disc pl-5">{detail.readiness.validation_errors.map(error=><li key={error}>{error}</li>)}</ul> : <p className="text-green-400">{detail.readiness?.previous_export_failed ? "Source details are complete. The previous export failed; check the error and retry from Pre-processing." : "All checks passed. This product is ready in Pre-processing."}</p>}
      <p className="text-sm text-zinc-400">For missing source details, refresh pricing, inventory or media on the Sync page. For a category issue, choose the category in Category Mapping and publish it.</p>
      <a href="/category-mapping" className="text-blue-400 underline mr-4">Open Category Mapping</a><a href="/sync" className="text-blue-400 underline">Open Supplier Sync</a>
      <p className="text-zinc-400">Supplier Hub keeps the original product. Each size group uses its own Lightspeed family. Complete sizes stay together wherever the 200-variant limit permits. Original variant SKUs are preserved.</p>
      <div className="flex flex-wrap gap-3">
        <button className={buttonClass} disabled={!admin || locked} onClick={()=>perform(async()=>{await axios.post(`${API.replace('/export-review','')}/sync/product/${selected}/pricing`);await refreshDetail();await refresh();toast.success('Supplier pricing request finished; check review status');})}>Refresh supplier pricing only</button>
        <button className={buttonClass} disabled={!admin || locked || !!detail.product.lightspeed_product_id || detail.groups.some(g=>g.lightspeed_product_id || g.state!=='planned') || detail.variant_count<=200} onClick={makePreview}>{detail.groups.length ? "Rebuild unexported families" : "Preview size families"}</button>
        <button className={buttonClass} disabled={!admin || locked} onClick={()=>perform(async()=>{await axios.post(`${API}/products/${selected}/reset-deleted-plan`);setPreview(null);await refreshDetail();await refresh();toast.success('Deleted destinations verified. Preview and save a new family plan.');})}>Verify deleted destinations / reset old plan</button>
        <a href={`/preprocessing?search=${encodeURIComponent(detail.product.supplier_sku || "")}`} className={`${buttonClass} text-blue-300`}>{detail.readiness?.is_valid ? "Ready — open Pre-processing" : "Back to Pre-processing"}</a>
        <button className={buttonClass} disabled={!admin || locked || !detail.images || (!detail.product.lightspeed_product_id && !detail.groups.some(g=>g.lightspeed_product_id))} onClick={()=>start('repair-images')}>Repair missing images only</button>
        <button className={buttonClass} disabled={busy} onClick={()=>perform(refreshDetail)}>Refresh results</button>
      </div>
      <p className="text-xs text-zinc-400">Image synchronization uses existing destination IDs. Failed reads retry automatically; uncertain uploads are reconciled before any repeat upload.</p>
      {preview && <div className="space-y-3"><h3 className="font-semibold">Size-family preview — not saved yet</h3>{preview.replaces_unexported_plan && <p className="text-amber-400">Saving replaces the unexported plan with families for the currently eligible SKUs.</p>}{preview.groups.map(group=><div key={group.number} className="border border-zinc-800 p-3"><p>{group.name} · {group.count} variants</p><details><summary>Sizes and variant SKUs</summary><p>{(group.sizes || []).join(', ')}</p><p className="break-words text-xs">{group.variant_skus.join(', ')}</p></details></div>)}<button className={buttonClass} disabled={!admin || locked} onClick={savePlan}>Save reviewed family plan</button></div>}
      {detail.groups.map(group=><div key={group.id} className="border border-zinc-800 p-3"><p>Family {group.group_number} · {group.variant_ids.length} variants · {group.state}</p><p className="text-xs break-all">Family destination: {group.lightspeed_product_id || 'Recovered or created during export'}</p><p className="text-sm">{group.message && `Last export result: ${group.message}`}</p>{group.state==='uncertain' && <p className="text-amber-300">Resume from Pre-processing. Existing variants are read before any additional creation request.</p>}</div>)}
      {running && <p role="status">Job running; results refresh automatically.</p>}
      <h3 className="font-semibold">Job history</h3>
      {detail.jobs.map(job=><details key={job.id}><summary>{job.kind} · {job.status}</summary><pre className="whitespace-pre-wrap break-words text-xs">{JSON.stringify(typeof job.result==='string' ? JSON.parse(job.result) : job.result,null,2)}</pre></details>)}
      <p className="text-zinc-400 text-sm">Images upload automatically during sync. Retry pending images from Pre-processing; no image approval is required here.</p>
    </>}
      </section>
    </div>}
  </div>;
}
