import React, {useCallback,useEffect,useRef,useState} from 'react';
import axios from '../lib/axios';
import {toast} from 'sonner';
import {Dialog,DialogContent,DialogHeader,DialogTitle} from '../components/ui/dialog';
import {Button} from '../components/ui/button';
const API=(process.env.REACT_APP_BACKEND_URL || '').replace(/\/+$/,'')+'/api';
const fields=[['weight_lb','Weight (lb)'],['length_in','Length (in)'],['width_in','Width (in)'],['height_in','Height (in)']];
const message=e=>typeof e.response?.data?.detail==='string'?e.response.data.detail:e.message;
function admin(){try{return JSON.parse(localStorage.getItem('user') || '{}').role==='admin';}catch{return false;}}
export function shippingLabel(rule){return rule?.measurements_configured?'Defaults added':fields.some(([k])=>rule?.[k]!=null)?'Partial defaults':'No defaults';}
export function CategoryPolicyEditor({category,onClose,onSaved}){
 const [mode,setMode]=useState('global'),[value,setValue]=useState(''),[shipping,setShipping]=useState({}),[saving,setSaving]=useState(false);
 useEffect(()=>{if(category){setMode(category.mode || 'global');setValue(category.value==null?'':String(category.value));setShipping(Object.fromEntries(fields.map(([k])=>[k,category[k]==null?'':String(category[k])])));}},[category]);
 async function save(){
  const amount=mode==='global'?null:Number(value);
  if(mode!=='global' && (!value.trim() || !Number.isFinite(amount) || amount<0 || (mode==='direct' && amount<.01))){toast.error('Enter a valid pricing value');return;}
  const measurements=Object.fromEntries(fields.map(([k])=>[k,shipping[k]?.trim()?Number(shipping[k]):null]));
  if(Object.values(measurements).some(v=>v!==null && (!Number.isFinite(v) || v<.0001))){toast.error('Shipping values must be at least 0.0001');return;}
  const dims=['length_in','width_in','height_in'].map(k=>measurements[k]);
  if(dims.some(v=>v!==null) && dims.some(v=>v===null)){toast.error('Enter all three dimensions or leave them all blank');return;}
  setSaving(true);
  try{const res=await axios.put(`${API}/category-policy`,{supplier_id:category.supplier_id,category_id:category.category_id,mode,value:amount,...measurements});toast.success(`Category defaults saved · ${res.data.affected_products} products pending sync`);await onSaved?.();onClose();}
  catch(e){toast.error(message(e));}finally{setSaving(false);}
 }
 return <Dialog open={!!category} onOpenChange={open=>{if(!open && !saving)onClose();}}><DialogContent className="bg-zinc-900 border-zinc-700 text-white max-w-md max-h-[90vh] overflow-y-auto">
  <DialogHeader><DialogTitle>Category pricing &amp; measurements</DialogTitle></DialogHeader><p className="text-sm text-zinc-200">{category?.category_name}</p><p className="text-xs text-zinc-500">Mapped supplier categories: {(category?.supplier_categories?.length?category.supplier_categories:category?.supplier_paths||[]).join(', ') || 'No current products'}</p>
  <label className="text-sm">Pricing rule<select aria-label="Category pricing rule" disabled={saving} value={mode} onChange={e=>{setMode(e.target.value);setValue('');}} className="w-full mt-1 p-2 bg-zinc-800 border border-zinc-700 rounded"><option value="global">Use global markup</option><option value="percentage">Category markup (%)</option><option value="direct">Direct base selling price</option></select></label>
  {mode!=='global' && <label className="text-sm">{mode==='percentage'?'Markup (%)':'Base selling price ($)'}<input aria-label="Category pricing value" disabled={saving} type="number" min={mode==='direct'?'.01':'0'} step={mode==='direct'?'.01':'.1'} value={value} onChange={e=>setValue(e.target.value)} className="w-full mt-1 p-2 bg-zinc-800 border border-zinc-700 rounded" /></label>}
  {mode==='direct' && <p className="text-xs text-zinc-400">Higher-cost sizes retain their supplier-cost difference.</p>}
  <div className="border-t border-zinc-700 pt-3"><p className="text-sm font-medium mb-2">Shipping defaults per piece</p><div className="grid grid-cols-2 gap-3">{fields.map(([key,label])=><label key={key} className="text-xs text-zinc-400">{label}<input aria-label={label} disabled={saving} type="number" min=".0001" step=".0001" placeholder="Optional" value={shipping[key] || ''} onChange={e=>setShipping(s=>({...s,[key]:e.target.value}))} className="w-full mt-1 p-2 bg-zinc-800 border border-zinc-700 rounded text-white" /></label>)}</div></div>
  <p className="text-xs text-zinc-500">Applies to this supplier’s products in this category. Verified supplier measurements take precedence.</p>
  <div className="flex justify-end gap-2"><Button variant="outline" disabled={saving} onClick={onClose}>Cancel</Button><Button disabled={saving || !admin()} onClick={save}>{saving?'Saving…':'Save category defaults'}</Button></div>
 </DialogContent></Dialog>;
}
export default function CategoryPolicyManager(){
 const [suppliers,setSuppliers]=useState([]),[supplier,setSupplier]=useState(''),[rows,setRows]=useState([]),[query,setQuery]=useState(''),[loading,setLoading]=useState(false),[error,setError]=useState(''),[selected,setSelected]=useState(null);const version=useRef(0);
 useEffect(()=>{let live=true;axios.get(`${API}/suppliers`).then(r=>{if(live){const rows=Array.isArray(r.data)?r.data:r.data.suppliers || [];setSuppliers(rows);setSupplier(rows[0]?.id || '');}}).catch(e=>{if(live)setError(message(e));});return()=>{live=false;};},[]);
 const refresh=useCallback(async()=>{const request=++version.current;if(!supplier){setRows([]);return;}setLoading(true);setError('');try{const r=await axios.get(`${API}/category-policies`,{params:{supplier_id:supplier}});if(request===version.current)setRows(r.data.categories || []);}catch(e){if(request===version.current)setError(message(e));}finally{if(request===version.current)setLoading(false);}},[supplier]);
 useEffect(()=>{setSelected(null);setRows([]);refresh();},[refresh]);
 const shown=rows.filter(r=>[r.category_name,...(r.supplier_categories||[]),...(r.supplier_paths||[])].some(value=>String(value).toLowerCase().includes(query.toLowerCase())));
 return <div className="p-6 space-y-4"><div className="flex flex-wrap items-center gap-3"><h2 className="text-xl font-semibold">Category defaults</h2><select aria-label="Category defaults supplier" disabled={!!selected} value={supplier} onChange={e=>setSupplier(e.target.value)} className="bg-zinc-800 border border-zinc-700 p-2 rounded"><option value="">Select supplier</option>{suppliers.map(s=><option key={s.id} value={s.id}>{s.supplier_name}</option>)}</select><input aria-label="Search category defaults" placeholder="Search categories" value={query} onChange={e=>setQuery(e.target.value)} className="bg-zinc-800 border border-zinc-700 p-2 rounded" /><Button variant="outline" disabled={loading} onClick={refresh}>Refresh</Button></div>
 {error && <p role="alert" className="text-red-400">{error}</p>}{loading && <p role="status" className="text-zinc-400">Loading…</p>}
 <div className="overflow-auto border border-zinc-800 rounded"><table className="w-full text-sm text-left"><thead className="bg-zinc-900 text-zinc-400"><tr>{['Lightspeed category / mapped supplier categories','Pricing rule','Weight (lb)','Dimensions (in)','Measurements',''].map((h,i)=><th key={i} className="p-3">{h}</th>)}</tr></thead><tbody>{shown.map(r=><tr key={r.category_id} className="border-t border-zinc-800"><td className="p-3"><span className="font-medium">{r.category_name}</span><small className="block text-zinc-500">{r.product_count} products</small><div className="mt-2 text-xs text-zinc-400"><span className="text-zinc-500">Mapped supplier categories:</span><ul className="mt-1 space-y-1">{(r.supplier_categories?.length?r.supplier_categories:r.supplier_paths||[]).map(name=><li key={name}>{name}</li>)}</ul></div></td><td className="p-3">{r.pricing_label}</td><td className="p-3">{r.weight_lb ?? '—'}</td><td className="p-3 whitespace-nowrap">{r.length_in!=null?`${r.length_in} × ${r.width_in} × ${r.height_in}`:'—'}</td><td className={`p-3 ${r.measurements_configured?'text-emerald-400':'text-amber-400'}`}>{shippingLabel(r)}</td><td className="p-3"><Button size="sm" variant="outline" disabled={!admin() || loading || !!error} onClick={()=>setSelected(r)}>Edit defaults</Button><a className="mt-2 block text-xs text-blue-400 hover:underline" href={`/preprocessing?supplier_id=${encodeURIComponent(r.supplier_id)}&category_id=${encodeURIComponent(r.category_id)}`}>Sync this category</a></td></tr>)}</tbody></table></div>
 {!loading && !error && !shown.length && <p className="text-zinc-500">No published categories found.</p>}
 <CategoryPolicyEditor category={selected} onClose={()=>setSelected(null)} onSaved={refresh} />
 </div>;
}

