import SearchField from '@/components/SearchField';
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import axios from '../lib/axios';
import { toast } from 'sonner';
import './SanMarCategoryMapping.css';
import {CategoryPolicyEditor,shippingLabel} from './CategoryPolicyEditor';

const API = (process.env.REACT_APP_BACKEND_URL || '').replace(/\/+$/, '') + '/api';
const PAGE_SIZE = 40;
const empty = { nodes: [], rows: [], labels: [], products: [], summary: {}, warnings: [] };
function userIsAdmin() {
  try { return JSON.parse(localStorage.getItem('user') || '{}').role === 'admin'; }
  catch { return false; }
}
const errorMessage = e => typeof e.response?.data?.detail === 'string' ? e.response.data.detail : e.message || 'Request failed';

export default function SanMarCategoryMapping() {
  const [suppliers, setSuppliers] = useState([]);
  const [supplier, setSupplier] = useState('');
  const [data, setData] = useState(empty);
  const [policies,setPolicies]=useState([]);
  const [editingPolicy,setEditingPolicy]=useState(null);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(false);
  const [tab, setTab] = useState('products');
  const [query, setQuery] = useState('');
  const [filter, setFilter] = useState('all');
  const [page, setPage] = useState(0);
  const [collapsed] = useState(new Set());
  const [importPreview, setImportPreview] = useState(null);
  const [upload, setUpload] = useState(null);
  const [job, setJob] = useState(null);
  const [history, setHistory] = useState([]);
  const [selectedSkus, setSelectedSkus] = useState(new Set());
  const [bulkPath, setBulkPath] = useState('');
  const [parentOptions, setParentOptions] = useState([]);
  const [parentId, setParentId] = useState('');
  const [savedParentId, setSavedParentId] = useState('');
  const [configurationLoaded, setConfigurationLoaded] = useState(false);
  const [configurationLoading, setConfigurationLoading] = useState(false);
  const [configurationError, setConfigurationError] = useState('');
  const [customName, setCustomName] = useState('');
  const [customParent, setCustomParent] = useState('');
  const activeSupplier = useRef(supplier);
  activeSupplier.current = supplier;
  const admin = userIsAdmin();
  const running = job?.status === 'running';
  const locked = busy || loading || running || configurationLoading || !!editingPolicy;
  const catalogueReady = data.summary.category_policy === 'product-only-two-level-audience-v3';
  const parentReady = configurationLoaded && !!parentId && parentId === savedParentId;

  useEffect(() => {
    let live = true;
    axios.get(`${API}/suppliers`).then(res => {
      if (!live) return;
      const candidates = (res.data.suppliers || []).filter(s => /san\s*mar/i.test(s.supplier_name));
      setSuppliers(candidates);
      if (candidates.length === 1) setSupplier(candidates[0].id);
    }).catch(e => toast.error(errorMessage(e)));
    return () => { live = false; };
  }, []);

  const refresh = useCallback(async () => {
    if (!supplier) return;
    setLoading(true);
    try {
      const [catalog, jobs, rules] = await Promise.all([
        axios.get(`${API}/taxonomy/${supplier}`), axios.get(`${API}/taxonomy/${supplier}/jobs`),axios.get(`${API}/category-policies`,{params:{supplier_id:supplier}})
      ]);
      if (activeSupplier.current !== supplier) return;
      setData(catalog.data); setHistory(jobs.data.jobs || []);setPolicies(rules.data.categories || []);
    } catch(e) { toast.error(errorMessage(e)); }
    finally { if (activeSupplier.current === supplier) setLoading(false); }
  }, [supplier]);
  useEffect(() => {
    setSelectedSkus(new Set()); setBulkPath('');setPolicies([]);setEditingPolicy(null);
    setData(empty); setJob(null); setImportPreview(null); setUpload(null); setHistory([]);
    refresh();
  }, [refresh]);
  const loadConfiguration = useCallback(async () => {
    if (!supplier) return;
    setConfigurationLoading(true);
    setConfigurationLoaded(false);
    setConfigurationError('');
    try {
      const { data: result } = await axios.get(`${API}/taxonomy/${supplier}/configuration`);
      if (activeSupplier.current !== supplier) return;
      const options = result.parents || [];
      const config = result.config;
      const saved = config?.store_domain === result.store_domain
        && options.some(parent => parent.id === config.parent_category_id)
        ? config.parent_category_id : '';
      setParentOptions(options);
      setParentId(saved);
      setSavedParentId(saved);
      setConfigurationLoaded(true);
    } catch (error) {
      if (activeSupplier.current === supplier) {
        setConfigurationError(errorMessage(error));
      }
    } finally {
      if (activeSupplier.current === supplier) setConfigurationLoading(false);
    }
  }, [supplier]);
  useEffect(() => {
    setParentOptions([]); setParentId(''); setSavedParentId('');
    setConfigurationLoaded(false); setConfigurationError('');
    setCustomName(''); setCustomParent('');
    loadConfiguration();
  }, [loadConfiguration]);
  useEffect(() => { setPage(0); }, [query, filter, tab, supplier]);
  useEffect(() => {
    if (!running || !job?.id || !supplier) return;
    let live = true;
    const timer = setInterval(async () => {
      try {
        const res = await axios.get(`${API}/taxonomy/${supplier}/jobs/${job.id}`);
        if (!live) return;
        setJob(res.data);
        if (res.data.status !== 'running') {
          refresh();
          toast[res.data.status === 'completed' ? 'success' : 'error'](`Category job: ${res.data.status.replaceAll('_',' ')}`);
        }
      } catch(e) { if (live) toast.error(errorMessage(e)); }
    }, 2000);
    return () => { live = false; clearInterval(timer); };
  }, [running, job?.id, supplier, refresh]);

  const perform = async fn => {
    setBusy(true);
    try { await fn(); } catch(e) { toast.error(errorMessage(e)); }
    finally { setBusy(false); }
  };
  const saveParent = () => perform(async () => {
    const selectedSupplier = supplier;
    const selectedParent = parentId;
    await axios.put(`${API}/taxonomy/${selectedSupplier}/configuration`, {
      parent_category_id: selectedParent,
    });
    if (activeSupplier.current !== selectedSupplier) return;
    setSavedParentId(selectedParent); setJob(null);
    await refresh();
    toast.success('Parent saved');
  });
  const createCustomCategory = () => perform(async () => {
    const selectedSupplier = supplier;
    await axios.post(`${API}/taxonomy/${selectedSupplier}/custom-categories`, {
      name: customName.trim(), parent_path: customParent || null,
    });
    if (activeSupplier.current !== selectedSupplier) return;
    setCustomName(''); setJob(null);
    await refresh();
    toast.success('Category saved');
  });
  const previewImport = file => perform(async () => {
    if (!supplier) return;
    let res;
    if (file) {
      const form = new FormData(); form.append('file', file); form.append('dry_run', 'true');
      res = await axios.post(`${API}/taxonomy/${supplier}/import`, form);
    } else {
      res = await axios.post(`${API}/taxonomy/${supplier}/import-bundled`, { dry_run: true });
    }
    if (activeSupplier.current !== supplier) return;
    setUpload(file || null); setImportPreview(res.data);
  });
  const commitImport = () => perform(async () => {
    if (upload) {
      const form = new FormData(); form.append('file',upload); form.append('dry_run','false'); form.append('expected_digest',importPreview.digest);
      await axios.post(`${API}/taxonomy/${supplier}/import`,form);
    } else {
      await axios.post(`${API}/taxonomy/${supplier}/import-bundled`, {dry_run:false, expected_digest:importPreview.digest});
    }
    setImportPreview(null); setJob(null); await refresh(); toast.success('SanMar category catalogue imported');
  });
  const setOverride = (sku,path,reset=false) => perform(async () => {
    await axios.put(`${API}/taxonomy/${supplier}/override`,{sku,path:path || null,reset});
    setJob(null); await refresh(); toast.success('Category saved');
  });
  const bulkAssign = reset => perform(async () => {
    await axios.put(`${API}/taxonomy/${supplier}/bulk-overrides`, {skus:[...selectedSkus],path:bulkPath || null,reset});
    setSelectedSkus(new Set()); setJob(null); await refresh(); toast.success('Bulk assignments saved');
  });
  const toggleSku = sku => setSelectedSkus(current => {const next=new Set(current);next.has(sku)?next.delete(sku):next.add(sku);return next;});
  const previewJob = kind => perform(async () => {
    if (!parentReady) { toast.error('Select and save a destination parent first'); return; }
    const res = await axios.post(`${API}/taxonomy/${supplier}/preview`,{kind});
    if (activeSupplier.current !== supplier) return;
    setJob(res.data); setTab('jobs'); setQuery(''); setFilter('all'); await refresh();
  });
  const executeJob = () => perform(async () => {
    await axios.post(`${API}/taxonomy/${supplier}/jobs/${job.id}/execute`);
    setJob(current => ({...current,status:'running'}));
  });
  const openJob = id => perform(async () => {
    const res = await axios.get(`${API}/taxonomy/${supplier}/jobs/${id}`);
    setJob(res.data); setTab('jobs'); setQuery(''); setFilter('all');
  });

  const leaves = useMemo(() => data.nodes.filter(n => n.leaf && n.verified && n.level <= 2), [data.nodes]);
  const currentRows = useMemo(() => {
    const q = query.trim().toLowerCase();
    let rows = tab === 'categories' ? (catalogueReady ? data.nodes : []) : tab === 'styles' ? data.rows : tab === 'products' ? data.products : tab === 'labels' ? data.labels : (job?.items || []);
    return rows.filter(r => {
      if (q && !JSON.stringify(r).toLowerCase().includes(q)) return false;
      if (tab === 'styles' && filter !== 'all' && (filter === 'manual' ? !r.manual : r.status !== filter)) return false;
      if (tab === 'products' && filter !== 'all' && (filter === 'unmatched' ? r.assignment?.source !== 'not_in_csv' : filter === 'review' ? r.assignment?.status === 'ready' : r.assignment?.status !== 'ready')) return false;
      if (tab === 'categories' && filter === 'leaf' && !r.leaf) return false;
      if (tab === 'jobs' && filter !== 'all' && r.status !== filter) return false;
      if (tab === 'categories' && !q && [...collapsed].some(p => r.path.startsWith(p + ' > '))) return false;
      return true;
    });
  }, [data, tab, query, filter, job, collapsed, catalogueReady]);
  const pageCount = Math.max(1, Math.ceil(currentRows.length / PAGE_SIZE));
  const visiblePage = Math.min(page, pageCount - 1);
  const shown = currentRows.slice(visiblePage * PAGE_SIZE,(visiblePage + 1)*PAGE_SIZE);
  const jobCounts = (job?.items || []).reduce((out, item) => ({...out,[item.status]:(out[item.status]||0)+1}),{});
  const assignmentSelect = row => <div className="sm-assignment">
    <select aria-label={`Primary category for ${row.sku}`} disabled={!admin || locked || !catalogueReady} value={row.primary_path || ''} onChange={e => setOverride(row.sku,e.target.value)}>
      <option value="">Select category</option>
      {catalogueReady && leaves.map(n => <option key={n.path} value={n.path}>{n.custom ? 'Custom: ' : ''}{n.path}</option>)}
    </select>
    {row.manual && <button type="button" className="sm-link" disabled={locked || !admin} onClick={() => setOverride(row.sku,null,true)}>Use supplier category</button>}
  </div>;
  const badge = status => <span className={`sm-badge sm-${status}`}>{status?.replaceAll('_',' ') || 'unmatched'}</span>;

  return <div className="sm-page" data-testid="sanmar-category-mapping">
    <header className="sm-header"><div><h1>Category Mapping</h1><p>SanMar Canada</p></div>
      <label className="sm-supplier">Supplier<select aria-label="SanMar supplier" value={supplier} disabled={locked} onChange={e => setSupplier(e.target.value)}><option value="">Select supplier</option>{suppliers.map(s => <option key={s.id} value={s.id}>{s.supplier_name}</option>)}</select></label></header>
    {!admin && <p className="sm-notice">Read-only access</p>}
    {!suppliers.length && <p className="sm-notice">Add SanMar Canada in Suppliers.</p>}
    {supplier && <>
      <div className="sm-main-actions">
        <button disabled={!admin || locked} onClick={() => previewImport(null)}>Refresh catalogue</button>
        <label className={`sm-upload ${!admin || locked ? 'sm-disabled' : ''}`}>Import CSV<input type="file" accept=".csv,text/csv" disabled={!admin || locked} onChange={e => { const file=e.target.files?.[0]; if(file) previewImport(file); e.target.value=''; }} /></label>
        <button className="sm-primary" disabled={!admin || locked || !catalogueReady || !parentReady} onClick={() => previewJob('categories')}>Publish categories</button>
        <button disabled={!admin || locked || !catalogueReady || !parentReady} onClick={() => previewJob('products')}>Update synced products</button>
      </div>
      {data.digest && !catalogueReady && <p className="sm-notice">Refresh catalogue to use two-level product categories.</p>}
      <details className="sm-panel sm-settings" open={!parentReady}>
        <summary>Category settings <span>{parentReady ? parentOptions.find(p=>p.id===parentId)?.path : 'Select destination'}</span></summary>
        {configurationError && <p role="alert">{configurationError}</p>}
        <div className="sm-config-controls"><label>Lightspeed parent<select aria-label="Lightspeed parent" value={parentId} disabled={!admin || locked || !configurationLoaded} onChange={e=>{setParentId(e.target.value);setJob(null);}}><option value="">Select parent</option>{parentOptions.map(p=><option key={p.id} value={p.id}>{p.path}</option>)}</select></label>
          <button disabled={!admin || locked || !parentId || parentId===savedParentId} onClick={saveParent}>Save parent</button><button disabled={locked} onClick={loadConfiguration}>Reload</button></div>
        <div className="sm-config-controls"><input aria-label="New category name" placeholder="New category name" value={customName} maxLength={100} disabled={!admin || locked || !catalogueReady} onChange={e=>setCustomName(e.target.value)} />
          <select aria-label="New category parent" value={customParent} disabled={!admin || locked || !catalogueReady} onChange={e=>setCustomParent(e.target.value)}><option value="">Main category</option>{data.nodes.filter(n=>n.level===1 && !n.leaf).map(n=><option key={n.path} value={n.path}>{n.name}</option>)}</select>
          <button disabled={!admin || locked || !catalogueReady || !customName.trim()} onClick={createCustomCategory}>Add category</button></div>
      </details>
      {importPreview && <section className="sm-panel sm-import"><h2>Import catalogue</h2><p>{importPreview.summary.styles} styles · {importPreview.summary.categories} categories · {importPreview.summary.review} need a category</p><div className="sm-actions"><button className="sm-primary" disabled={locked} onClick={commitImport}>Save catalogue</button><button disabled={locked} onClick={()=>setImportPreview(null)}>Cancel</button></div></section>}
      <div className="sm-stats">{[['Products',data.products.length],['Mapped',data.products.filter(p=>p.assignment?.status==='ready').length],['Needs category',data.products.filter(p=>p.assignment?.status!=='ready').length],['Categories',catalogueReady?data.nodes.length:'—']].map(([label,value])=><div key={label}><strong>{value}</strong><span>{label}</span></div>)}</div>
      <section className="sm-panel">
        <div className="sm-toolbar"><nav aria-label="Mapping views">{[['products','Products'],['categories','Categories'],['jobs','Publish history']].map(([id,label])=><button key={id} className={tab===id?'sm-active':''} onClick={()=>{setTab(id);setFilter('all');setQuery('');}}>{label}</button>)}</nav><button disabled={locked} onClick={refresh}>Refresh</button></div>
        <div className="sm-search"><SearchField aria-label="Search mapping" placeholder={tab==='products'?'Search product name or SKU…':'Search categories…'} value={query} onChange={e=>setQuery(e.target.value)} /><select aria-label="Filter mapping" value={filter} onChange={e=>setFilter(e.target.value)}><option value="all">All</option>{(tab==='products'?[['ready','Mapped'],['review','Needs category']]:tab==='jobs'?[['failed','Failed'],['blocked','Blocked'],['done','Done'],['create','New'],['update','Updates']]:[]).map(([id,label])=><option key={id} value={id}>{label}</option>)}</select></div>
        {tab==='products' && <div className="sm-bulk"><button disabled={!admin || locked || !catalogueReady} onClick={()=>setSelectedSkus(new Set(currentRows.map(r=>r.supplier_sku)))}>Select filtered</button><button disabled={!selectedSkus.size || locked} onClick={()=>setSelectedSkus(new Set())}>Clear</button><span>{selectedSkus.size} selected</span><select aria-label="Category for selected products" value={bulkPath} disabled={!admin || locked || !catalogueReady} onChange={e=>setBulkPath(e.target.value)}><option value="">Select category</option>{catalogueReady && leaves.map(n=><option key={n.path} value={n.path}>{n.path}</option>)}</select><button className="sm-primary" disabled={!admin || locked || !catalogueReady || !selectedSkus.size || !bulkPath} onClick={()=>bulkAssign(false)}>Apply</button></div>}
        {tab==='jobs' && <div className="sm-job"><div className="sm-actions">{history.map(h=><button key={h.id} disabled={busy} onClick={()=>openJob(h.id)}>{h.kind==='categories'?'Categories':'Products'} · {h.status.replaceAll('_',' ')}</button>)}</div>{job && <><h2>{job.kind==='categories'?'Category changes':'Product changes'} {badge(job.status)}</h2><p>{Object.entries(jobCounts).map(([k,v])=>`${v} ${k}`).join(' · ')}</p>{job.status==='preview' && <div className="sm-actions"><button className="sm-primary" disabled={!admin || locked || !catalogueReady || !(jobCounts.create || jobCounts.reuse || jobCounts.update)} onClick={executeJob}>{job.kind==='categories'?'Confirm publish':'Confirm update'}</button><button disabled={locked} onClick={()=>setJob(null)}>Cancel</button></div>}{['failed','completed_with_errors','interrupted'].includes(job.status) && <button disabled={locked || !catalogueReady} onClick={()=>previewJob(job.kind)}>Retry preview</button>}{running && <p role="status">Publishing…</p>}</>}</div>}
        {loading && <p role="status">Loading…</p>}
        <div className="sm-table-scroll"><table><thead><tr>{(tab==='products'?['Product','Category','Status']:tab==='categories'?['Category','Subcategory','Products','Pricing rule','Weight (lb)','Dimensions (in)','Defaults']:['Product / category','Destination','Status','Result']).map(h=><th key={h}>{h}</th>)}</tr></thead><tbody>{shown.filter(r=>tab!=='categories'||(catalogueReady && r.level<=2)).map((r,index)=><tr key={r.product_id||r.id||r.supplier_sku||r.path||index}>
          {tab==='products'?<><td><label className="sm-check"><input type="checkbox" aria-label={`Select ${r.supplier_sku}`} checked={selectedSkus.has(r.supplier_sku)} disabled={!admin || locked || !catalogueReady} onChange={()=>toggleSku(r.supplier_sku)} /><strong>{r.supplier_sku}</strong></label><small>{r.product_name}</small></td><td>{r.assignment?assignmentSelect(r.assignment):'Needs category'}</td><td>{badge(r.assignment?.status==='ready'?'ready':'review')}<small>{r.lightspeed_product_id?'In Lightspeed':'Not synced'}</small></td></>:
            tab==='categories'?<><td>{r.path.split(' > ')[0]}</td><td>{r.level===2?r.name:'—'}</td><td>{r.product_count||0}</td>{(()=>{const policy=policies.find(p=>p.path===r.path);return <><td>{policy?.pricing_label || '—'}</td><td>{policy?.weight_lb ?? '—'}</td><td>{policy?.length_in!=null?`${policy.length_in} × ${policy.width_in} × ${policy.height_in}`:'—'}</td><td>{r.leaf?<><small>{policy?shippingLabel(policy):'Publish first'}</small><button disabled={!admin || locked || !policy} onClick={()=>setEditingPolicy(policy)}>Edit defaults</button></>:'—'}</td></>;})()}</>:
            <><td>{r.sku||r.path}</td><td>{r.path}</td><td>{badge(r.status)}</td><td>{r.message||(r.status==='reuse'?'Existing category':'Pending')}</td></>}
        </tr>)}</tbody></table></div>
        {!currentRows.length && <div className="sm-empty">{tab==='jobs'?'No publish changes selected.':'No matching products or categories.'}</div>}
        <footer className="sm-pagination"><span>{currentRows.length} results · {visiblePage+1} / {pageCount}</span><div><button disabled={visiblePage===0} onClick={()=>setPage(visiblePage-1)}>Previous</button><button disabled={visiblePage+1>=pageCount} onClick={()=>setPage(visiblePage+1)}>Next</button></div></footer>
      </section>
    </>}
    <CategoryPolicyEditor category={editingPolicy} onClose={()=>setEditingPolicy(null)} onSaved={refresh} />
  </div>;
}

