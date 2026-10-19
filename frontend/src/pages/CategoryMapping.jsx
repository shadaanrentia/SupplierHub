import React, { useState, useEffect, useCallback, useMemo } from "react";
import axios from "../lib/axios";
import SanMarCategoryMapping from "./SanMarCategoryMapping";
import CategoryPolicyManager from "./CategoryPolicyEditor";
import { toast } from "sonner";
import { Card, CardContent, CardHeader, CardTitle } from "../components/ui/card";
import { Button } from "../components/ui/button";
import { Checkbox } from "../components/ui/checkbox";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../components/ui/select";
import { RefreshCw, FolderTree, ArrowRight, Check, X, Zap, ChevronRight } from "lucide-react";

const API = process.env.REACT_APP_BACKEND_URL + "/api";

function LegacyCategoryMapping() {
  const [platform, setPlatform] = useState("lightspeed");
  const [odooCategories, setOdooCategories] = useState([]);
  const [lightspeedCategories, setLightspeedCategories] = useState([]);
  const [supplierCategories, setSupplierCategories] = useState([]);
  const [mappings, setMappings] = useState([]);
  const [syncing, setSyncing] = useState(false);
  const [savingMapping, setSavingMapping] = useState({});
  const [selectedCategories, setSelectedCategories] = useState(new Set());

  const fetchData = useCallback(async () => {
    try {
      const [odooRes, supplierRes, mappingsRes] = await Promise.all([
        axios.get(`${API}/odoo/categories`).catch(() => ({ data: { categories: [] } })),
        axios.get(`${API}/supplier-categories`),
        axios.get(`${API}/category-mappings`)
      ]);

      setOdooCategories(odooRes.data.categories || []);
      setSupplierCategories(supplierRes.data.categories || []);
      setMappings(mappingsRes.data.mappings || []);

      const selected = new Set(
        (odooRes.data.categories || [])
          .filter(c => c.is_selected)
          .map(c => c.id)
      );
      setSelectedCategories(selected);
    } catch (e) {
      console.error("Failed to fetch data:", e);
    }
  }, []);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  // Build hierarchical Lightspeed categories (Level 1 -> Level 2)
  const lsHierarchy = useMemo(() => {
    if (!lightspeedCategories.length) return [];
    const result = [];
    const visit = (parentId, level = 1) => {
      lightspeedCategories.filter(c => (c.parent_id || null) === parentId)
        .sort((a,b) => a.category_name.localeCompare(b.category_name))
        .forEach(c => { result.push({...c, level}); if(level < 3) visit(c.lightspeed_category_id, level + 1); });
    };
    visit(null);
    return result;
  }, [lightspeedCategories]);

  // Flat list of leaf categories for mapping dropdown
  const lsLeafCategories = useMemo(() => {
    return lightspeedCategories.filter(c => c.leaf_category);
  }, [lightspeedCategories]);

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
        const res = await axios.get(`${API}/categories/lightspeed`);
        if (res.data.success) {
          setLightspeedCategories(res.data.categories || []);
          toast.success(`Fetched ${(res.data.categories || []).length} categories from Lightspeed`);
        } else {
          toast.error(res.data.error || "Failed to fetch Lightspeed categories");
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
      const body = { supplier_category_name: supplierCategory };
      if (platform === "odoo") {
        body.odoo_category_id = value === "none" ? null : parseInt(value);
      } else {
        // Lightspeed IDs are UUID strings, not integers
        body.lightspeed_category_id = value === "none" ? null : value;
      }
      await axios.post(`${API}/category-mappings`, body);
      toast.success(`Mapped "${supplierCategory}"`);
      fetchData();
    } catch (e) {
      toast.error("Failed to save mapping");
    } finally {
      setSavingMapping(prev => ({ ...prev, [supplierCategory]: false }));
    }
  };

  const getMappingForSupplier = (supplierCategory) => {
    const mapping = mappings.find(m => m.supplier_category_name === supplierCategory);
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
              Sync Categories from {platformLabel}
            </Button>
          </div>
          <p className="text-sm text-zinc-500 mt-2">
            {platform === "odoo"
              ? "Fetch categories from Odoo and select which ones to use for product mapping."
              : "Fetch categories from Lightspeed Retail store to use for product mapping."}
          </p>
        </CardHeader>
        <CardContent>
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
                      {odooCategories.map((cat) => (
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
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-zinc-800 text-zinc-400">
                      <th className="text-left py-2 px-3">Category Name</th>
                      <th className="text-left py-2 px-3 w-24">Level</th>
                    </tr>
                  </thead>
                  <tbody>
                    {lsHierarchy.map((cat) => (
                      <tr
                        key={cat.lightspeed_category_id}
                        className={`border-b border-zinc-800/50 hover:bg-zinc-800/30 ${cat.level === 1 ? 'bg-zinc-800/20' : ''}`}
                        data-testid={`ls-category-row-${cat.lightspeed_category_id}`}
                      >
                        <td className="py-2 px-3">
                          {cat.level === 1 ? (
                            <span className="text-zinc-100 font-medium flex items-center gap-1.5">
                              <FolderTree className="w-3.5 h-3.5 text-emerald-400" />
                              {cat.category_name}
                            </span>
                          ) : (
                            <span className="text-zinc-300 flex items-center gap-1.5 pl-6">
                              <ChevronRight className="w-3 h-3 text-zinc-600" />
                              {cat.category_name}
                            </span>
                          )}
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
              </div>
            ) : (
              <div className="text-center py-10 text-zinc-500">
                <Zap className="w-12 h-12 mx-auto mb-4 opacity-50" />
                <p>No Lightspeed categories loaded yet.</p>
                <p className="text-sm mt-1">Click "Sync Categories from Lightspeed" to fetch them. Ensure credentials are set in Settings.</p>
              </div>
            )
          )}
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
          {supplierCategories.length > 0 ? (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-zinc-800 text-zinc-400">
                    <th className="text-left py-2 px-3">Supplier Category</th>
                    <th className="text-left py-2 px-3 w-1/3">{platformLabel} Category</th>
                    <th className="text-left py-2 px-3 w-20">Status</th>
                  </tr>
                </thead>
                <tbody>
                  {supplierCategories.map((supplierCat) => {
                    const currentMapping = getMappingForSupplier(supplierCat);
                    const isMapped = currentMapping !== "none";
                    return (
                      <tr key={supplierCat} className="border-b border-zinc-800/50 hover:bg-zinc-800/30" data-testid={`mapping-row-${supplierCat}`}>
                        <td className="py-2 px-3 text-zinc-100 font-medium">{supplierCat}</td>
                        <td className="py-2 px-3">
                          <Select
                            value={currentMapping}
                            onValueChange={(value) => updateMapping(supplierCat, value)}
                            disabled={savingMapping[supplierCat]}
                          >
                            <SelectTrigger className="w-full bg-zinc-800 border-zinc-700" data-testid={`mapping-select-${supplierCat}`}>
                              <SelectValue placeholder={`Select ${platformLabel} category`} />
                            </SelectTrigger>
                            <SelectContent className="bg-zinc-900 border-zinc-800 max-h-72">
                              <SelectItem value="none">— Not Mapped —</SelectItem>
                              {platform === "odoo" ? (
                                targetCategories.map((c) => (
                                  <SelectItem key={c.odoo_category_id} value={c.odoo_category_id.toString()}>
                                    {c.category_name}{c.parent_category && ` (${c.parent_category})`}
                                  </SelectItem>
                                ))
                              ) : (
                                targetCategories.map((c) => (
                                  <SelectItem key={c.lightspeed_category_id} value={c.lightspeed_category_id}>
                                    {(c.category_path && c.category_path.length > 1)
                                      ? c.category_path.map(p => p.name).join(" > ")
                                      : c.category_name}
                                  </SelectItem>
                                ))
                              )}
                            </SelectContent>
                          </Select>
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
              <p>No supplier categories found.</p>
              <p className="text-sm mt-1">Sync products from suppliers first to see their categories.</p>
            </div>
          )}
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
  const [mode, setMode] = useState('sanmar');
  return <><div className="px-6 pt-5 flex flex-wrap gap-2" aria-label="Mapping mode">
    <Button variant={mode==='sanmar'?'default':'outline'} onClick={() => setMode('sanmar')}>SanMar catalogue mapping</Button>
    <Button variant={mode==='legacy'?'default':'outline'} onClick={() => setMode('legacy')}>Legacy / other supplier mapping</Button>
    <Button variant={mode==='defaults'?'default':'outline'} onClick={() => setMode('defaults')}>Category pricing &amp; measurements</Button>
  </div>{mode==='sanmar'?<SanMarCategoryMapping />:mode==='defaults'?<CategoryPolicyManager />:<LegacyCategoryMapping />}</>;
}
