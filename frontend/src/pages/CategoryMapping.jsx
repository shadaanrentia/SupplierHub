import React, { useState, useEffect, useCallback, useMemo, useRef } from "react";
import axios from "../lib/axios";
import CategoryPolicyManager from "./CategoryPolicyEditor";
import { toast } from "sonner";
import { Card, CardContent, CardHeader, CardTitle } from "../components/ui/card";
import { Button } from "../components/ui/button";
import { Checkbox } from "../components/ui/checkbox";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../components/ui/select";
import { RefreshCw, FolderTree, ArrowRight, Check, X, Zap, ChevronRight, ChevronDown } from "lucide-react";

const API = process.env.REACT_APP_BACKEND_URL + "/api";

function SearchableCategoryPicker({value, options, disabled, open, onToggle, onChange, label}) {
  const [query, setQuery] = useState("");
  const [limit, setLimit] = useState(100);
  const container = useRef(null);
  const input = useRef(null);
  const selected = options.find(option => option.value === value);
  const matches = useMemo(() => options.filter(option => option.label.toLowerCase().includes(query.trim().toLowerCase())), [options,query]);
  useEffect(() => {
    if (!open) return;
    setQuery(""); setLimit(100);
    input.current?.focus();
    const outside = event => { if (!container.current?.contains(event.target)) onToggle(false); };
    document.addEventListener("pointerdown", outside);
    return () => document.removeEventListener("pointerdown", outside);
  }, [open,onToggle]);
  return <div ref={container} className="relative min-w-[220px]" onKeyDown={event => {
    if (event.key === "Escape") { event.stopPropagation(); onToggle(false); container.current?.querySelector("[aria-haspopup]")?.focus(); }
  }}>
    <button type="button" disabled={disabled} aria-label={label} aria-haspopup="listbox" aria-expanded={open}
      onClick={() => onToggle(!open)} className="w-full flex items-center justify-between gap-2 text-left bg-zinc-800 border border-zinc-700 rounded px-3 py-2 text-zinc-100 text-sm disabled:opacity-50">
      <span className="truncate">{selected?.label || (value !== "none" ? "Saved destination unavailable" : "— Not Mapped —")}</span><ChevronRight className="w-3 h-3 shrink-0" />
    </button>
    {open && <div className="absolute z-50 left-0 right-0 mt-1 bg-zinc-900 border border-zinc-700 rounded shadow-xl p-2">
      <input ref={input} type="search" value={query} onChange={event => {setQuery(event.target.value);setLimit(100);}}
        aria-label="Search destination categories" placeholder="Search categories or full path…"
        onKeyDown={event => { if (event.key === "ArrowDown") {event.preventDefault();container.current?.querySelector('[role="option"]')?.focus();} }}
        className="w-full bg-zinc-800 border border-zinc-700 rounded px-2 py-2 text-sm text-zinc-100 mb-2" />
      <div role="listbox" aria-label={label} className="max-h-64 overflow-y-auto" onKeyDown={event => {
        if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
        const items = [...event.currentTarget.querySelectorAll('[role="option"]')];
        const i = items.indexOf(document.activeElement);
        event.preventDefault();items[Math.max(0,Math.min(items.length-1,i+(event.key === "ArrowDown" ? 1 : -1)))]?.focus();
      }}>
        <button type="button" role="option" aria-selected={value === "none"} onClick={() => {onChange("none");onToggle(false);}}
          className="block w-full text-left text-sm px-2 py-2 text-zinc-400 hover:bg-zinc-800 focus:bg-zinc-800">— Not Mapped —</button>
        {matches.slice(0,limit).map(option => <button key={option.value} type="button" role="option" aria-selected={value === option.value}
          onClick={() => {onChange(option.value);onToggle(false);}}
          className={`block w-full text-left text-sm px-2 py-2 whitespace-normal hover:bg-zinc-800 focus:bg-zinc-800 ${value === option.value ? "text-emerald-400" : "text-zinc-100"}`}>{option.label}</button>)}
        {!matches.length && <p className="text-xs text-zinc-500 p-2">No matching categories</p>}
      </div>
      {matches.length > limit && <button type="button" onClick={() => setLimit(n=>n+100)} className="text-xs text-blue-400 p-2">Show more ({matches.length} matches)</button>}
    </div>}
  </div>;
}

function LegacyCategoryMapping() {
  const [suppliers, setSuppliers] = useState([]);
  const [supplierId, setSupplierId] = useState("");
  const [supplierLoading, setSupplierLoading] = useState(false);
  const [supplierError, setSupplierError] = useState("");
  const [openPicker, setOpenPicker] = useState(null);
  const supplierRef = useRef("");
  const supplierRequest = useRef(0);
  const [platform, setPlatform] = useState("lightspeed");
  const [odooCategories, setOdooCategories] = useState([]);
  const [lightspeedCategories, setLightspeedCategories] = useState([]);
  const [supplierCategories, setSupplierCategories] = useState([]);
  const [mappings, setMappings] = useState([]);
  const [syncing, setSyncing] = useState(false);
  const [savingMapping, setSavingMapping] = useState({});
  const [selectedCategories, setSelectedCategories] = useState(new Set());

  const [categorySearch, setCategorySearch] = useState("");
  const [mappingPage, setMappingPage] = useState(1);
  const [platformPage, setPlatformPage] = useState(1);
  const [expandedCategories,setExpandedCategories]=useState(new Set());
  const [treeSearch,setTreeSearch]=useState('');
  const [categoryStatus, setCategoryStatus] = useState({});
  const alive = useRef(false);
  const categoryFingerprint = useRef(null);
  const PAGE_SIZE = 25;
  const acceptCategories = useCallback((data) => {
    if (!alive.current) return;
    const rows = Array.isArray(data.categories) ? data.categories : [];
    const fingerprint = JSON.stringify(rows);
    if (categoryFingerprint.current !== fingerprint) {
      categoryFingerprint.current = fingerprint;
      setLightspeedCategories(rows);
    }
    setCategoryStatus(prev => prev.synced_at === data.synced_at && prev.last_error === data.last_error
      ? prev : {synced_at: data.synced_at, last_error: data.last_error});
  }, []);
  const filteredCategories = useMemo(() => supplierCategories.filter(category =>
    String(category).toLowerCase().includes(categorySearch.trim().toLowerCase())
  ), [supplierCategories, categorySearch]);
  const mappingPages = Math.max(1, Math.ceil(filteredCategories.length / PAGE_SIZE));
  const safePage = Math.min(mappingPage, mappingPages);
  const visibleSupplierCategories = filteredCategories.slice((safePage - 1) * PAGE_SIZE, safePage * PAGE_SIZE);
  useEffect(() => { setMappingPage(1); }, [categorySearch, platform, supplierId]);
  useEffect(() => { setPlatformPage(1); }, [platform]);

  const fetchData = useCallback(async () => {
    try {
      const [odooRes, suppliersRes, lightspeedRes] = await Promise.all([
        axios.get(`${API}/odoo/categories`).catch(() => ({data:{categories:[]}})),
        axios.get(`${API}/suppliers`),
        axios.get(`${API}/categories/lightspeed`)
      ]);
      if (!alive.current) return;
      setOdooCategories(odooRes.data.categories || []);
      setSelectedCategories(new Set((odooRes.data.categories || []).filter(c=>c.is_selected).map(c=>c.id)));
      const list = Array.isArray(suppliersRes.data) ? suppliersRes.data : suppliersRes.data.suppliers || [];
      setSuppliers(list);
      setSupplierId(current => list.some(s=>s.id === current) ? current : list[0]?.id || "");
      acceptCategories(lightspeedRes.data);
    } catch (error) {
      if (alive.current) toast.error("Unable to load categories or suppliers. Check your connection.");
    }
  }, [acceptCategories]);

  useEffect(() => {
    supplierRef.current = supplierId;
    const request = ++supplierRequest.current;
    setSupplierCategories([]);setMappings([]);setOpenPicker(null);setSupplierError("");
    if (!supplierId) {setSupplierLoading(false);return;}
    setSupplierLoading(true);
    const controller = new AbortController();
    Promise.all([
      axios.get(`${API}/supplier-categories`, {params:{supplier_id:supplierId},signal:controller.signal}),
      axios.get(`${API}/category-mappings`, {params:{supplier_id:supplierId},signal:controller.signal})
    ]).then(([categoriesRes,mappingsRes]) => {
      if (controller.signal.aborted || request !== supplierRequest.current) return;
      setSupplierCategories(categoriesRes.data.categories || []);
      setMappings(mappingsRes.data.mappings || []);
    }).catch(error => {
      if (!controller.signal.aborted && request === supplierRequest.current) setSupplierError("Could not load this supplier's categories. Refresh the page to retry.");
    }).finally(() => {
      if (!controller.signal.aborted && request === supplierRequest.current) setSupplierLoading(false);
    });
    return () => controller.abort();
  }, [supplierId]);

  useEffect(() => {
    alive.current = true;
    fetchData();
    let timer;
    const poll = async () => {
      try {
        if (!document.hidden) {
          const res = await axios.get(`${API}/categories/lightspeed`, {timeout: 15000});
          acceptCategories(res.data);
        }
      } catch (error) {
        if (alive.current) console.error("Cannot load saved categories:", error);
      } finally {
        if (alive.current) timer = setTimeout(poll, 15000);
      }
    };
    timer = setTimeout(poll, 15000);
    return () => { alive.current = false; clearTimeout(timer); };
  }, [fetchData, acceptCategories]);

  // Build hierarchical Lightspeed categories (Level 1 -> Level 2)
  const lsHierarchy = useMemo(() => {
    const byId = new Map();
    lightspeedCategories.forEach(category => {
      if (category.lightspeed_category_id) byId.set(String(category.lightspeed_category_id), category);
    });
    const children = new Map();
    byId.forEach(category => {
      const parent = category.parent_id ? String(category.parent_id) : null;
      const key = byId.has(parent) ? parent : null;
      if (!children.has(key)) children.set(key, []);
      children.get(key).push(category);
    });
    const result = [];
    const seen = new Set();
    const roots = children.get(null) || [];
    const stack = roots.slice().reverse().map(category => ({category, level: 1}));
    const drain = () => {
      while (stack.length) {
        const {category, level} = stack.pop();
        const id = String(category.lightspeed_category_id);
        if (seen.has(id)) continue;
        seen.add(id);
        result.push({...category, level});
        (children.get(id) || []).slice().reverse().forEach(child => stack.push({category: child, level: level + 1}));
      }
    };
    drain();
    byId.forEach(category => {
      if (!seen.has(String(category.lightspeed_category_id))) {
        stack.push({category, level: 1}); drain();
      }
    });
    return result;
  }, [lightspeedCategories]);

  const lsLeafCategories = useMemo(() => {
    const parents = new Set(lightspeedCategories.map(c => c.parent_id).filter(Boolean).map(String));
    return lightspeedCategories.filter(c => !parents.has(String(c.lightspeed_category_id)));
  }, [lightspeedCategories]);
  const treeRows = useMemo(() => {
    const ancestors=[];
    return lsHierarchy.map((category,index)=>{
      ancestors.length=category.level-1;
      const id=String(category.lightspeed_category_id);
      const row={...category,id,ancestors:[...ancestors],hasChildren:(lsHierarchy[index+1]?.level || 0)>category.level};
      ancestors.push(id);
      return row;
    });
  },[lsHierarchy]);
  const visibleTreeRows = useMemo(() => {
    const query=treeSearch.trim().toLocaleLowerCase();
    if(query){
      const included=new Set();
      treeRows.forEach(row=>{if(String(row.category_name || '').toLocaleLowerCase().includes(query)){
        included.add(row.id);row.ancestors.forEach(id=>included.add(id));
      }});
      return treeRows.filter(row=>included.has(row.id));
    }
    return treeRows.filter(row=>row.ancestors.every(id=>expandedCategories.has(id)));
  },[treeRows,treeSearch,expandedCategories]);
  const toggleCategory=id=>setExpandedCategories(current=>{const next=new Set(current);next.has(id)?next.delete(id):next.add(id);return next;});
  const platformRows = platform === 'odoo' ? odooCategories : visibleTreeRows;
  const platformPages = Math.max(1, Math.ceil(platformRows.length / 50));
  const safePlatformPage = Math.min(platformPage, platformPages);
  const visiblePlatformRows = platform === 'odoo' ? platformRows.slice((safePlatformPage - 1) * 50, safePlatformPage * 50) : platformRows;
  const mappingByName = useMemo(() => new Map(mappings.map(m => [m.supplier_category_name, m])), [mappings]);

  const syncCategories = async () => {
    setSyncing(true);
    try {
      if (platform === "odoo") {
        const res = await axios.post(`${API}/odoo/sync-categories`);
        if (res.data.success) {
          toast.success(`Synced ${res.data.synced} categories from Odoo`);
          fetchData();
        } else {
          toast.error(res.data.error || "Failed to sync categories");
        }
        } else {
        const res = await axios.post(
          `${API}/categories/lightspeed/refresh`
        );

        if (res.data.success) {
          acceptCategories(res.data);

          if (res.data.last_error) {
            toast.error(res.data.last_error);
          } else {
            toast.success(
              `Updated ${(res.data.categories || []).length} categories`
            );
          }
        } else {
          toast.error(
            res.data.error || "Failed to refresh Lightspeed categories"
          );
        }
      }
    } catch (e) {
      const msg = e.response?.data?.detail || e.response?.data?.error || e.message || "Failed to sync categories";
      toast.error(msg);
    } finally {
      setSyncing(false);
    }
  };

  const toggleCategorySelection = async (categoryId, isSelected) => {
    if (platform === "odoo") {
      try {
        await axios.put(`${API}/odoo/categories/${categoryId}/select`, { is_selected: isSelected });
        setSelectedCategories(prev => {
          const newSet = new Set(prev);
          isSelected ? newSet.add(categoryId) : newSet.delete(categoryId);
          return newSet;
        });
      } catch (e) {
        toast.error("Failed to update selection");
      }
    }
  };

  const selectAll = async () => {
    if (platform === "odoo") {
      const allIds = odooCategories.map(c => c.id);
      try {
        await axios.put(`${API}/odoo/categories/bulk-select`, { category_ids: allIds, is_selected: true });
        setSelectedCategories(new Set(allIds));
        toast.success("All categories selected");
      } catch (e) { toast.error("Failed to select all"); }
    }
  };

  const deselectAll = async () => {
    if (platform === "odoo") {
      const allIds = odooCategories.map(c => c.id);
      try {
        await axios.put(`${API}/odoo/categories/bulk-select`, { category_ids: allIds, is_selected: false });
        setSelectedCategories(new Set());
        toast.success("All categories deselected");
      } catch (e) { toast.error("Failed to deselect all"); }
    }
  };

  const updateMapping = async (supplierCategory, value) => {
    setSavingMapping(prev => ({ ...prev, [supplierCategory]: true }));
    try {
      const savingSupplier = supplierId;
      if (!savingSupplier || supplierLoading) return;
      const body = {supplier_id: savingSupplier, supplier_category_name: supplierCategory};
      if (platform === "odoo") {
        body.odoo_category_id = value === "none" ? null : parseInt(value);
      } else {
        // Lightspeed IDs are UUID strings, not integers
        body.lightspeed_category_id = value === "none" ? null : value;
      }
      await axios.post(`${API}/category-mappings`, body);
      toast.success(`Mapped "${supplierCategory}"`);
      if (supplierRef.current !== savingSupplier) return;
      setMappings(prev => {
        const existing = prev.find(item => item.supplier_category_name === supplierCategory);
        return existing
          ? prev.map(item => item.supplier_category_name === supplierCategory ? {...item, ...body} : item)
          : [...prev, body];
      });
    } catch (e) {
      toast.error("Failed to save mapping");
    } finally {
      setSavingMapping(prev => ({ ...prev, [supplierCategory]: false }));
    }
  };

  const getMappingForSupplier = (supplierCategory) => {
    const mapping = mappingByName.get(supplierCategory);
    if (platform === "odoo") {
      return mapping?.odoo_category_id?.toString() || "none";
    } else {
      return mapping?.lightspeed_category_id || "none";
    }
  };

  const platformLabel = platform === "odoo" ? "Odoo" : "Lightspeed";

  // Categories for the mapping dropdown
  const targetCategories = platform === "odoo"
    ? odooCategories.filter(c => selectedCategories.has(c.id))
    : lsLeafCategories;

  const targetOptions = useMemo(() => targetCategories.map(c => ({
    value: String(platform === "odoo" ? c.odoo_category_id : c.lightspeed_category_id),
    label: platform === "odoo" ? `${c.category_name}${c.parent_category ? ` (${c.parent_category})` : ""}`
      : Array.isArray(c.category_path) && c.category_path.length ? c.category_path.map(p=>p.name).join(" > ") : c.category_name
  })).sort((a,b)=>String(a.label).localeCompare(String(b.label))), [targetCategories,platform]);

  const mappedCount = mappings.filter(m =>
    platform === "odoo" ? m.odoo_category_id : m.lightspeed_category_id
  ).length;

  return (
    <div className="p-6 space-y-6" data-testid="category-mapping-page">
      {/* Header with Platform Selector */}
      <div className="flex items-center justify-between flex-wrap gap-4">
        <div>
          <h1 className="text-2xl font-bold text-zinc-100">Category Mapping</h1>
          <p className="text-sm text-zinc-500 mt-1">
            Sync categories from a platform and map them to supplier categories
          </p>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-xs text-zinc-500 uppercase tracking-wider">Target Platform</span>
          <Select value={platform} onValueChange={setPlatform}>
            <SelectTrigger className="w-[200px] bg-zinc-900 border-zinc-700 rounded-none" data-testid="platform-selector">
              <SelectValue />
            </SelectTrigger>
            <SelectContent className="bg-zinc-900 border-zinc-800">
              <SelectItem value="odoo">Odoo ERP</SelectItem>
              <SelectItem value="lightspeed">Lightspeed Retail (X-Series)</SelectItem>
            </SelectContent>
          </Select>
        </div>
      </div>

      {/* Step 1: Platform Categories */}
      <Card className="bg-zinc-900/50 border-zinc-800">
        <CardHeader className="pb-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              {platform === "odoo" ? (
                <FolderTree className="w-5 h-5 text-blue-400" />
              ) : (
                <Zap className="w-5 h-5 text-emerald-400" />
              )}
              <CardTitle className="text-lg">Step 1: {platformLabel} Categories</CardTitle>
            </div>
            <Button
              onClick={syncCategories}
              disabled={syncing}
              className={`${platform === "odoo" ? "bg-blue-600 hover:bg-blue-700" : "bg-emerald-600 hover:bg-emerald-700"}`}
              data-testid="sync-categories-btn"
            >
              {syncing ? <RefreshCw className="w-4 h-4 animate-spin mr-2" /> : <RefreshCw className="w-4 h-4 mr-2" />}
              {platform === "lightspeed" ? "Refresh now" : `Sync Categories from ${platformLabel}`}
            </Button>
          </div>
          {platform === "odoo" && <p className="text-sm text-zinc-500 mt-2">
            Fetch categories from Odoo and select which ones to use for product mapping.
          </p>}
        </CardHeader>
        <CardContent>
          {platform === "lightspeed" && <div className="text-xs text-zinc-500 mb-3" role="status">
            {categoryStatus.synced_at ? `Last updated: ${new Date(categoryStatus.synced_at).toLocaleString()}` : "Waiting for saved categories…"}
            {categoryStatus.last_error && <p className="text-amber-400 mt-1">{categoryStatus.last_error}</p>}
          </div>}

          {platform === "odoo" ? (
            odooCategories.length > 0 ? (
              <>
                <div className="flex gap-2 mb-4">
                  <Button variant="outline" size="sm" onClick={selectAll} className="text-xs">
                    <Check className="w-3 h-3 mr-1" /> Select All
                  </Button>
                  <Button variant="outline" size="sm" onClick={deselectAll} className="text-xs">
                    <X className="w-3 h-3 mr-1" /> Deselect All
                  </Button>
                  <span className="text-sm text-zinc-500 ml-4 self-center">
                    {selectedCategories.size} of {odooCategories.length} selected
                  </span>
                </div>
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-zinc-800 text-zinc-400">
                        <th className="text-left py-2 px-3 w-12">Select</th>
                        <th className="text-left py-2 px-3">Category Name</th>
                        <th className="text-left py-2 px-3">Parent</th>
                      </tr>
                    </thead>
                    <tbody>
                      {visiblePlatformRows.map((cat) => (
                        <tr key={cat.id} className="border-b border-zinc-800/50 hover:bg-zinc-800/30" data-testid={`odoo-category-row-${cat.odoo_category_id}`}>
                          <td className="py-2 px-3">
                            <Checkbox
                              checked={selectedCategories.has(cat.id)}
                              onCheckedChange={(checked) => toggleCategorySelection(cat.id, checked)}
                              data-testid={`category-checkbox-${cat.odoo_category_id}`}
                            />
                          </td>
                          <td className="py-2 px-3 text-zinc-100">{cat.category_name}</td>
                          <td className="py-2 px-3 text-zinc-500">{cat.parent_category || "—"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </>
            ) : (
              <div className="text-center py-10 text-zinc-500">
                <FolderTree className="w-12 h-12 mx-auto mb-4 opacity-50" />
                <p>No categories synced yet.</p>
                <p className="text-sm mt-1">Click "Sync Categories from Odoo" to fetch them.</p>
              </div>
            )
          ) : (
            // Lightspeed categories — hierarchical (Level 1 / Level 2)
            lsHierarchy.length > 0 ? (
              <div>
              <div className="flex flex-wrap items-center gap-2 mb-3">
                <input aria-label="Search Lightspeed categories" value={treeSearch} onChange={e=>setTreeSearch(e.target.value)}
                  placeholder="Search categories" className="bg-zinc-950 border border-zinc-700 rounded px-3 py-2 text-sm min-w-0 flex-1"/>
                <Button variant="outline" size="sm" disabled={!!treeSearch.trim()} onClick={()=>setExpandedCategories(new Set(treeRows.filter(row=>row.hasChildren).map(row=>row.id)))}>Expand all</Button>
                <Button variant="outline" size="sm" onClick={()=>{setTreeSearch('');setExpandedCategories(new Set());}}>Collapse all</Button>
                <span className="text-xs text-zinc-500">{lightspeedCategories.length} categories</span>
              </div>
              <div className="overflow-auto max-h-[560px] border border-zinc-800 rounded-sm">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-zinc-800 text-zinc-400">
                      <th className="text-left py-2 px-3">Category Name</th>
                      <th className="text-left py-2 px-3 w-24">Level</th>
                    </tr>
                  </thead>
                  <tbody>
                    {visiblePlatformRows.map((cat) => (
                      <tr
                        key={cat.lightspeed_category_id}
                        className={`border-b border-zinc-800/50 hover:bg-zinc-800/30 ${cat.level === 1 ? 'bg-zinc-800/20' : ''}`}
                        data-testid={`ls-category-row-${cat.lightspeed_category_id}`}
                      >
                        <td className="py-2 px-3">
                          <div className="flex items-center gap-2" style={{paddingLeft:(cat.level-1)*24}}>
                            {cat.hasChildren ? <button type="button" aria-expanded={treeSearch.trim()?true:expandedCategories.has(cat.id)}
                              aria-label={`${expandedCategories.has(cat.id)?'Collapse':'Expand'} ${cat.category_name}`}
                              onClick={()=>toggleCategory(cat.id)} disabled={!!treeSearch.trim()}
                              className="flex items-center gap-2 text-left text-zinc-100 font-medium hover:text-emerald-300 py-1 min-w-0">
                              {treeSearch.trim() || expandedCategories.has(cat.id)?<ChevronDown className="w-4 h-4 shrink-0 text-emerald-400"/>:<ChevronRight className="w-4 h-4 shrink-0 text-zinc-400"/>}
                              <FolderTree className="w-4 h-4 shrink-0 text-emerald-400"/>
                              <span>{cat.category_name}</span>
                            </button> : <span className="flex items-center gap-2 text-zinc-300 py-1"><span className="w-4 shrink-0"/><span className="w-4 shrink-0 text-center text-zinc-600">·</span>{cat.category_name}</span>}
                          </div>
                        </td>
                        <td className="py-2 px-3">
                          <span className={`text-xs px-2 py-0.5 rounded-none font-mono ${cat.level === 1 ? 'bg-emerald-950/50 text-emerald-400 border border-emerald-800' : 'bg-zinc-800 text-zinc-400 border border-zinc-700'}`}>
                            L{cat.level}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {!visibleTreeRows.length && <p className="p-4 text-sm text-zinc-500">No matching categories.</p>}
              </div>
              </div>
            ) : (
              <div className="text-center py-10 text-zinc-500">
                <Zap className="w-12 h-12 mx-auto mb-4 opacity-50" />
                <p>No Lightspeed categories loaded yet.</p>
                <p className="text-sm mt-1">Connect Lightspeed in Settings, then wait for the automatic refresh or click Refresh now.</p>
              </div>
            )
          )}
          {platform === "odoo" && platformRows.length > 50 && <div className="flex flex-wrap items-center justify-end gap-3 mt-4 pt-4 border-t border-zinc-800">
            <Button variant="outline" size="sm" disabled={safePlatformPage <= 1} onClick={() => setPlatformPage(safePlatformPage - 1)}>Previous</Button>
            <span className="text-xs text-zinc-400">{safePlatformPage} / {platformPages} · {platformRows.length} categories</span>
            <Button variant="outline" size="sm" disabled={safePlatformPage >= platformPages} onClick={() => setPlatformPage(safePlatformPage + 1)}>Next</Button>
          </div>}
        </CardContent>
      </Card>

      {/* Step 2: Supplier Category Mapping */}
      <Card className="bg-zinc-900/50 border-zinc-800">
        <CardHeader className="pb-3">
          <div className="flex items-center gap-3">
            <ArrowRight className="w-5 h-5 text-green-400" />
            <CardTitle className="text-lg">Step 2: Map Supplier Categories to {platformLabel}</CardTitle>
          </div>
          <p className="text-sm text-zinc-500 mt-2">
            Map each supplier category to a {platformLabel} category for product sync.
          </p>
        </CardHeader>
        <CardContent>
          <div className="flex flex-wrap items-center gap-3 mb-4">
            <select value={supplierId} aria-label="Supplier" onChange={event => {
              supplierRef.current=event.target.value;setSupplierLoading(true);setSupplierId(event.target.value);
            }} className="w-full sm:w-64 bg-zinc-800 border border-zinc-700 rounded px-3 py-2 text-sm text-zinc-100">
              {!suppliers.length && <option value="">No suppliers available</option>}
              {suppliers.map(supplier => <option key={supplier.id} value={supplier.id}>{supplier.supplier_name}</option>)}
            </select>
            <input type="search" value={categorySearch} onChange={event => setCategorySearch(event.target.value)}
              placeholder="Search supplier categories…" aria-label="Search supplier categories"
              className="w-full sm:w-80 bg-zinc-800 border border-zinc-700 rounded px-3 py-2 text-sm text-zinc-100" />

          </div>
          {supplierLoading ? <p role="status" className="py-8 text-zinc-400">Loading supplier categories…</p> : supplierError ?
            <p role="alert" className="py-8 text-red-400">{supplierError}</p> : filteredCategories.length > 0 ? (
            <div className="overflow-visible">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-zinc-800 text-zinc-400">
                    <th className="text-left py-2 px-3">Supplier Category</th>
                    <th className="text-left py-2 px-3 w-1/3">{platformLabel} Category</th>
                    <th className="text-left py-2 px-3 w-20">Status</th>
                  </tr>
                </thead>
                <tbody>
                  {visibleSupplierCategories.map((supplierCat) => {
                    const currentMapping = getMappingForSupplier(supplierCat);
                    const isMapped = currentMapping !== "none";
                    return (
                      <tr key={supplierCat} className="border-b border-zinc-800/50 hover:bg-zinc-800/30" data-testid={`mapping-row-${supplierCat}`}>
                        <td className="py-2 px-3 text-zinc-100 font-medium">{supplierCat}</td>
                        <td className="py-2 px-3">
                          <SearchableCategoryPicker
                            value={currentMapping} options={targetOptions} disabled={savingMapping[supplierCat] || supplierLoading}
                            open={openPicker === supplierCat} onToggle={show => setOpenPicker(show ? supplierCat : null)}
                            onChange={value => updateMapping(supplierCat,value)} label={`${platformLabel} category for ${supplierCat}`} />
                        </td>
                        <td className="py-2 px-3">
                          {savingMapping[supplierCat] ? (
                            <RefreshCw className="w-4 h-4 animate-spin text-blue-400" />
                          ) : isMapped ? (
                            <Check className="w-4 h-4 text-green-400" />
                          ) : (
                            <span className="text-zinc-500 text-xs">Not mapped</span>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="text-center py-10 text-zinc-500">
              <ArrowRight className="w-12 h-12 mx-auto mb-4 opacity-50" />
              <p>No matching supplier categories found.</p>
              <p className="text-sm mt-1">Sync products from suppliers first to see their categories.</p>
            </div>
          )}
          <div className="flex flex-wrap items-center justify-end gap-3 mt-4 pt-4 border-t border-zinc-800">
              <Button variant="outline" size="sm" disabled={safePage <= 1} onClick={() => setMappingPage(safePage - 1)}>Previous</Button>
              <span className="text-xs text-zinc-400">{safePage} / {mappingPages} · {filteredCategories.length} categories</span>
              <Button variant="outline" size="sm" disabled={safePage >= mappingPages} onClick={() => setMappingPage(safePage + 1)}>Next</Button>
            </div>
        </CardContent>
      </Card>

      {/* Summary */}
      {mappings.length > 0 && (
        <Card className="bg-zinc-900/50 border-zinc-800">
          <CardHeader className="pb-3">
            <CardTitle className="text-lg">Mapping Summary</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <div className="bg-zinc-800/50 rounded-lg p-4 text-center">
                <p className={`text-2xl font-bold ${platform === "odoo" ? "text-blue-400" : "text-emerald-400"}`}>
                  {platform === "odoo" ? odooCategories.length : lightspeedCategories.length}
                </p>
                <p className="text-sm text-zinc-500">{platformLabel} Categories</p>
              </div>
              <div className="bg-zinc-800/50 rounded-lg p-4 text-center">
                <p className="text-2xl font-bold text-green-400">
                  {platform === "odoo" ? selectedCategories.size : lsLeafCategories.length}
                </p>
                <p className="text-sm text-zinc-500">Available for Mapping</p>
              </div>
              <div className="bg-zinc-800/50 rounded-lg p-4 text-center">
                <p className="text-2xl font-bold text-amber-400">
                  {mappedCount} / {supplierCategories.length}
                </p>
                <p className="text-sm text-zinc-500">Categories Mapped</p>
              </div>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

export default function CategoryMapping() {
  const [mode, setMode] = useState('mapping');
  return <><div className="px-6 pt-5 flex flex-wrap gap-2" aria-label="Mapping mode">
    <Button variant={mode==='mapping'?'default':'outline'} onClick={() => setMode('mapping')}>Category mapping</Button>
    <Button variant={mode==='defaults'?'default':'outline'} onClick={() => setMode('defaults')}>Category pricing &amp; measurements</Button>
  </div>{mode==='defaults'?<CategoryPolicyManager />:<LegacyCategoryMapping />}</>;
}

