import SearchField from '@/components/SearchField';
import {ProductLink,useProductDetails} from "@/components/ProductDetails";
import { useLightspeedSync } from '@/components/LightspeedSync';
import React, { useState, useEffect, useCallback, useRef } from "react";
import axios from "../lib/axios";
import { toast } from "sonner";
import { Card, CardContent, CardHeader, CardTitle } from "../components/ui/card";
import { Button } from "../components/ui/button";
import { Checkbox } from "../components/ui/checkbox";
import { Badge } from "../components/ui/badge";
import { RefreshCw, Package, CheckCircle, AlertTriangle, Eye, Upload, Calculator, Layers, Image, ArrowRight, Filter } from "lucide-react";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "../components/ui/select";

const API = (process.env.REACT_APP_BACKEND_URL || "").replace(/\/+$/, "") + "/api";

export default function ProductPreprocessing() {
  const previewProductData=useProductDetails();
  const [products, setProducts] = useState([]);
  const [summary, setSummary] = useState(null);
  const [suppliers,setSuppliers]=useState([]);
  const [supplierId,setSupplierId]=useState(()=>new URLSearchParams(window.location.search).get('supplier_id') || '');
  const [categoryId,setCategoryId]=useState(()=>new URLSearchParams(window.location.search).get('category_id') || 'all');
  const [categories,setCategories]=useState([]),[categoryError,setCategoryError]=useState('');
  useEffect(()=>{
    const controller=new AbortController();setCategories([]);setCategoryError('');
    if(!supplierId)return()=>controller.abort();
    axios.get(`${API}/preprocessing/categories`,{params:supplierId==='all'?{}:{supplier_id:supplierId},signal:controller.signal}).then(({data})=>{
      if(controller.signal.aborted)return;
      const grouped=new Map();
      for(const row of data.categories||[]){const previous=grouped.get(row.category_id);grouped.set(row.category_id,{...row,product_count:(previous?.product_count||0)+row.product_count});}
      const choices=[...grouped.values()].sort((a,b)=>a.category_name.localeCompare(b.category_name));
      setCategories(choices);
      setCategoryId(current=>current==='all'||choices.some(c=>c.category_id===current)?current:choices.some(c=>c.category_id==='__unmapped__')?'__unmapped__':'all');
    }).catch(e=>{if(!controller.signal.aborted)setCategoryError('Could not load Lightspeed categories. Refresh this page to retry.');});
    return()=>controller.abort();
  },[supplierId]);
  useEffect(()=>{axios.get(`${API}/suppliers`).then(r=>setSuppliers(Array.isArray(r.data)?r.data:r.data.suppliers || [])).catch(()=>toast.error('Could not load suppliers'));},[]);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState('');
  const {start:startLightspeedSync,starting:syncing} = useLightspeedSync();
  const [selectedProducts, setSelectedProducts] = useState(new Set());
  const [readyIds, setReadyIds] = useState([]);
  const [readyLoading, setReadyLoading] = useState(true);
  const [readyError, setReadyError] = useState('');
  const [statusFilter, setStatusFilter] = useState("all");
  const [oversizedOnly, setOversizedOnly] = useState(false);
  const [search, setSearch] = useState(()=>new URLSearchParams(window.location.search).get("search") || "");
  const [searchQuery, setSearchQuery] = useState(()=>new URLSearchParams(window.location.search).get("search") || "");
  const requestVersion = useRef(0);
  const summaryVersion = useRef(0);
  useEffect(() => {setSelectedProducts(new Set());},[searchQuery,statusFilter,supplierId,categoryId,oversizedOnly]);
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const syncPlatform = "lightspeed";
  const limit = 25;

  const fetchProducts = useCallback(async () => {
    const version=++requestVersion.current;
    if(!supplierId){setProducts([]);setTotal(0);setReadyIds([]);setLoading(false);setReadyLoading(false);return;}
    setLoading(true);
    setLoadError('');
    setReadyLoading(true);setReadyError('');setReadyIds([]);
    try {
      const params = new URLSearchParams({ page, limit, search: searchQuery });
      if(supplierId!=='all') params.append('supplier_id',supplierId);
      if(categoryId!=='all') params.append('category_id',categoryId);
      if (statusFilter !== "all") {
        params.append("status", statusFilter);
      }
      const res = await axios.get(`${API}/preprocessing/products?${params}`);
      if(version!==requestVersion.current) return;
      setProducts(res.data.products || []);
      const eligibleIds=res.data.selectable_ids || [];
      setReadyIds(eligibleIds);
      const eligibleSet=new Set(eligibleIds);
      setSelectedProducts(current=>new Set([...current].filter(id=>eligibleSet.has(id))));
      setSelectedProducts(current=>new Set([...current].filter(id=>!(res.data.products || []).some(p=>p.id===id && !p.can_sync && !p.can_update))));
      setTotal(res.data.total || 0);
    } catch (e) {
      if(version===requestVersion.current) {setLoadError(typeof e.response?.data?.detail==='string'?e.response.data.detail:'Could not load products. Try again.');setReadyError('Could not load eligible products. Refresh to retry.');}
    } finally {
      if(version===requestVersion.current) {setLoading(false);setReadyLoading(false);}
    }
  }, [page, statusFilter, searchQuery,supplierId,categoryId,oversizedOnly]);

  const readySelectedCount=readyIds.filter(id=>selectedProducts.has(id)).length;
  const allReadySelected=readyIds.length>0 && readySelectedCount===readyIds.length;
  const toggleAllReady=checked=>setSelectedProducts(checked ? new Set(readyIds) : new Set());

  const fetchSummary = useCallback(async () => {
    const version=++summaryVersion.current;
    if(!supplierId){setSummary(null);return;}
    try {
      const res = await axios.get(`${API}/preprocessing/summary`,{params:{supplier_id:supplierId==='all'?undefined:supplierId,category_id:categoryId==='all'?undefined:categoryId}});
      if(version===summaryVersion.current) setSummary(res.data);
    } catch (e) {
      console.error("Failed to load summary");
    }
  }, [supplierId,categoryId]);

  useEffect(() => {fetchProducts();}, [fetchProducts]);
  useEffect(() => {fetchSummary();}, [fetchSummary]);

  const recalculatePrices = async () => {
    if(!supplierId){toast.error('Choose a supplier first');return;}
    setLoading(true);
    try {
      const res = await axios.post(`${API}/preprocessing/recalculate-prices`);
      toast.success(`Recalculated ${res.data.updated} products using category defaults`);
      fetchProducts();
    } catch (e) {
      toast.error("Failed to recalculate prices");
    } finally {
      setLoading(false);
    }
  };

  const validateProducts = async () => {
    if(!supplierId){toast.error('Choose a supplier first');return;}
    setLoading(true);
    try {
      const productIds = selectedProducts.size > 0 ? Array.from(selectedProducts) : [];
      const res = await axios.post(`${API}/preprocessing/validate-products`, { product_ids: productIds, supplier_id:supplierId==='all'?null:supplierId });
      toast.success(`${res.data.validated} complete products, ${res.data.invalid} need review`);
      fetchProducts();
      fetchSummary();
    } catch (e) {
      toast.error("Failed to validate products");
    } finally {
      setLoading(false);
    }
  };

  const platformLabel = 'Lightspeed';
  const scope = {supplier_id:supplierId==='all'?null:supplierId,category_id:categoryId==='all'?null:categoryId};
  const syncSelected = async () => {
    if(!supplierId){toast.error('Choose a supplier first');return;}
    if(!selectedProducts.size)return;
    try {await startLightspeedSync({...scope,product_ids:Array.from(selectedProducts)});setSelectedProducts(new Set());}
    catch (_) { /* The global monitor reports request errors. */ }
  };
  const syncAll = async () => {
    if(!supplierId){toast.error('Choose a supplier first');return;}
    try {await startLightspeedSync({...scope,sync_all:true,search:searchQuery,status:statusFilter});}
    catch (_) { /* The global monitor reports request errors. */ }
  };
  useEffect(()=>{const refresh=()=>{fetchProducts();fetchSummary();};window.addEventListener('lightspeed-sync-updated',refresh);return()=>window.removeEventListener('lightspeed-sync-updated',refresh);},[fetchProducts,fetchSummary]);

  const toggleProductSelection = (productId) => {
    setSelectedProducts(prev => {
      const newSet = new Set(prev);
      if (newSet.has(productId)) {
        newSet.delete(productId);
      } else {
        newSet.add(productId);
      }
      return newSet;
    });
  };

  const selectAllVisible = () => toggleAllReady(true);

  const deselectAll = () => {
    setSelectedProducts(new Set());
  };

  const formatPrice = (price) => {
    return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(price || 0);
  };


  return (
    <div className="pp-page p-6 space-y-6" data-testid="product-preprocessing-page">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-4">
        <div>
          <h1 className="text-2xl font-bold text-zinc-100">Pre-processing</h1>
          <p className="text-sm text-zinc-500 mt-1">
            Check pricing, choose products and sync to {platformLabel}.
          </p>
        </div>
        <div className="pp-header-actions flex gap-2">
          <a href="/export-review" className="pp-review-link">Export Review</a>
          <a href="/lightspeed-cleanup-review" className="pp-review-link">Lightspeed Cleanup Review</a>
          <Button 
            variant="outline" 
            onClick={recalculatePrices}
            disabled={loading || syncing}
          >
            <Calculator className="w-4 h-4 mr-2" />
            Recalculate Prices
          </Button>
          <Button 
            variant="outline" 
            onClick={validateProducts}
            disabled={loading || syncing}
          >
            <CheckCircle className="w-4 h-4 mr-2" />
            Refresh Readiness
          </Button>
        </div>
      </div>

      {/* Summary Cards */}
      {summary && (
        <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-4">
          <Card className="bg-zinc-900/50 border-zinc-800">
            <CardContent className="p-4">
              <div className="flex items-center gap-3">
                <Package className="w-8 h-8 text-blue-400" />
                <div>
                  <p className="text-2xl font-bold text-zinc-100">{summary.total_products}</p>
                  <p className="text-xs text-zinc-500">Total Products</p>
                </div>
              </div>
            </CardContent>
          </Card>
          
          <Card className="bg-zinc-900/50 border-zinc-800">
            <CardContent className="p-4">
              <div className="flex items-center gap-3">
                <Layers className="w-8 h-8 text-purple-400" />
                <div>
                  <p className="text-2xl font-bold text-zinc-100">{summary.total_variants}</p>
                  <p className="text-xs text-zinc-500">Total Variants</p>
                </div>
              </div>
            </CardContent>
          </Card>
          
          <Card className="bg-zinc-900/50 border-zinc-800">
            <CardContent className="p-4">
              <div className="flex items-center gap-3">
                <CheckCircle className="w-8 h-8 text-green-400" />
                <div>
                  <p className="text-2xl font-bold text-zinc-100">{summary.sync_status?.ready || 0}</p>
                  <p className="text-xs text-zinc-500">Ready for Sync</p>
                </div>
              </div>
            </CardContent>
          </Card>
          
          <Card className="bg-zinc-900/50 border-zinc-800">
            <CardContent className="p-4">
              <div className="flex items-center gap-3">
                <Upload className="w-8 h-8 text-emerald-400" />
                <div>
                  <p className="text-2xl font-bold text-zinc-100">{summary.sync_status?.synced || 0}</p>
                  <p className="text-xs text-zinc-500">Synced</p>
                </div>
              </div>
            </CardContent>
          </Card>
          
          <Card className="bg-zinc-900/50 border-zinc-800">
            <CardContent className="p-4">
              <div className="flex items-center gap-3">
                <AlertTriangle className="w-8 h-8 text-amber-400" />
                <div>
                  <p className="text-2xl font-bold text-zinc-100">{summary.category_mapping?.unmapped || 0}</p>
                  <p className="text-xs text-zinc-500">Missing Mapping</p>
                </div>
              </div>
            </CardContent>
          </Card>
          
          <Card className="bg-zinc-900/50 border-zinc-800">
            <CardContent className="p-4">
              <div className="flex items-center gap-3">
                <Image className="w-8 h-8 text-rose-400" />
                <div>
                  <p className="text-2xl font-bold text-zinc-100">{summary.images?.without_images || 0}</p>
                  <p className="text-xs text-zinc-500">Missing Images</p>
                </div>
              </div>
            </CardContent>
          </Card>
        </div>
      )}

      {/* Products Table */}
      <Card className="bg-zinc-900/50 border-zinc-800">
        <CardHeader className="pb-3">
          <div className="flex flex-wrap gap-3 items-center justify-between">
            <CardTitle className="text-lg flex items-center gap-2">
              <Package className="w-5 h-5 text-blue-400" />
              Products
            </CardTitle>
            <div className="pp-filters flex flex-wrap items-center gap-3">
              <Select disabled={syncing} value={supplierId} onValueChange={value=>{setSupplierId(value);setCategoryId('all');setPage(1);setSelectedProducts(new Set());}}>
                <SelectTrigger aria-label="Supplier filter" className="w-48 bg-zinc-800 border-zinc-700"><SelectValue placeholder="Choose a supplier" /></SelectTrigger>
                <SelectContent className="bg-zinc-900 border-zinc-800">{suppliers.map(s=><SelectItem key={s.id} value={s.id}>{s.supplier_name}</SelectItem>)}</SelectContent>
              </Select>
              <Select disabled={syncing} value={statusFilter} onValueChange={value=>{setStatusFilter(value);setPage(1);}}>
                <SelectTrigger className="w-40 bg-zinc-800 border-zinc-700">
                  <Filter className="w-4 h-4 mr-2" />
                  <SelectValue />
                </SelectTrigger>
                <SelectContent className="bg-zinc-900 border-zinc-800">
                  <SelectItem value="all">All Products</SelectItem>
                  <SelectItem value="ready">Ready</SelectItem>
                  <SelectItem value="invalid">Needs Review</SelectItem>
                  <SelectItem value="images_pending">Images pending</SelectItem>
                  <SelectItem value="synced">Synced</SelectItem>
                </SelectContent>
              </Select>
              <select aria-label="Variant count filter" disabled={syncing} value={oversizedOnly ? "200plus" : "all"} onChange={e=>{setOversizedOnly(e.target.value==="200plus");setPage(1);setSelectedProducts(new Set());}} className="rounded border border-zinc-700 bg-zinc-800 px-3 py-2 text-sm"><option value="all">All variant counts</option><option value="200plus">200+ eligible variants</option></select>\n              <select aria-label="Lightspeed category" disabled={syncing} value={categoryId} onChange={e=>{setCategoryId(e.target.value);setPage(1);setSelectedProducts(new Set());}} className="max-w-full rounded border border-zinc-700 bg-zinc-800 px-3 py-2 text-sm"><option value="all">All Lightspeed categories</option>{categories.map(category=><option key={category.category_id} value={category.category_id}>{category.category_name} ({category.product_count})</option>)}</select>
              {categoryError&&<p role="alert" className="text-xs text-red-300">{categoryError}</p>}
              {categories.some(c=>!c.category_available)&&<p className="category-remap-note">Some products need a current category. <a className="text-blue-400" href={`/category-mapping?supplier_id=${encodeURIComponent(supplierId)}`}>Review mappings</a></p>}
              <SearchField aria-label="Search preprocessing products" placeholder="Search product name or SKU" value={search} disabled={syncing} onChange={event=>{setSearch(event.target.value);setSearchQuery(event.target.value);setPage(1);}} className="pp-search bg-zinc-800 border border-zinc-700 rounded px-3 py-2 text-sm" />
              <Button disabled={loading || syncing || readyLoading || !!readyError || !readyIds.length} aria-label="Select eligible products matching these filters" variant="outline" size="sm" onClick={selectAllVisible}>
                {statusFilter==='synced'?'Select synced':'Select all eligible'}
              </Button>
              <Button disabled={syncing || !selectedProducts.size} variant="outline" size="sm" onClick={deselectAll}>
                Clear selection
              </Button>
            </div>
          </div>
        </CardHeader>
        <CardContent aria-busy={loading}>
          {loadError && <div className="pp-load-error" role="alert"><span>{loadError}</span><button disabled={loading} onClick={fetchProducts}>Retry</button></div>}
          <div className="pp-result-line" role="status">{loading?'Updating products…':`${total} products`} {selectedProducts.size>0 && <span>· {selectedProducts.size} selected</span>} {readyError && <span className="text-amber-400">{readyError}</span>}</div>
          {loading && !products.length ? (
            <div className="flex items-center justify-center py-10">
              <RefreshCw className="w-6 h-6 animate-spin text-zinc-500" />
            </div>
          ) : products.length > 0 ? (
            <>
              <div className="pp-table-wrap overflow-x-auto">
                <table className="pp-table w-full text-sm">
                  <thead>
                    <tr className="border-b border-zinc-800 text-zinc-400">
                      <th className="text-left py-2 px-3 w-10">
                        <Checkbox checked={allReadySelected ? true : readySelectedCount>0 ? 'indeterminate' : false}
                          onCheckedChange={checked=>toggleAllReady(checked===true)}
                          disabled={syncing || loading || readyLoading || !!readyError || !readyIds.length}
                          aria-label="Select all eligible products matching these filters, across all pages"
                          title={`Select all ${readyIds.length} ${statusFilter==='synced'?'synced':'ready'} products across all pages`}/>
                      </th>
                      <th className="text-left py-2 px-3">Product</th>
                      <th className="text-left py-2 px-3">Category</th>
                      <th className="text-right py-2 px-3">Supplier Price</th>
                      <th className="text-right py-2 px-3">Retail Price</th>
                      <th className="text-left py-2 px-3">Details</th>
                      <th className="text-center py-2 px-3">Status</th>
                      <th className="text-center py-2 px-3">Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {products.map((product) => (
                      <tr 
                        key={product.id} 
                        className={`border-b border-zinc-800/50 hover:bg-zinc-800/30 ${selectedProducts.has(product.id)?'pp-selected':''}`}
                      >
                        <td className="py-2 px-3">
                          <Checkbox
                            checked={selectedProducts.has(product.id)}
                            aria-label={`Select ${product.supplier_sku}`}
                            onCheckedChange={() => toggleProductSelection(product.id)}
                            disabled={(!product.can_sync && !product.can_update) || syncing || loading || !!loadError}
                          />
                        </td>
                        <td className="py-2 px-3">
                          <div>
                            <ProductLink productId={product.id} title={product.product_name || product.supplier_sku} className="pp-product-name font-medium">
                              {product.product_name || product.supplier_sku}
                            </ProductLink>
                            <p className="pp-product-meta"><span>{product.supplier_sku}</span><span>{product.supplier_name || 'Unknown supplier'}</span></p>
                          </div>
                        </td>
                        <td className="py-2 px-3">
                          {product.mapped_lightspeed_category_id && product.category_available!==false ? (
                            <Badge variant="outline" className="pp-category bg-emerald-950/40 text-emerald-400 border-emerald-800">
                              {product.lightspeed_category_name || "Mapped · name unavailable"}
                            </Badge>
                          ) : (
                            <Badge variant="outline" className="bg-red-900/20 text-red-400 border-red-800">
                              Not Mapped
                            </Badge>
                          )}
                          <p className="pp-source-category">Supplier: {product.category || 'No supplier category'}</p>
                        </td>
                        <td className="pp-cost py-2 px-3 text-right font-mono text-zinc-400">
                          {formatPrice(product.cost_price)}
                        </td>
                        <td className="pp-retail py-2 px-3 text-right font-mono text-green-400 font-medium">
                          <div>{product.calculated_sale_price == null ? 'Price needs review' : (product.retail_price_max>product.retail_price_min ? `${formatPrice(product.retail_price_min)} – ${formatPrice(product.retail_price_max)}` : formatPrice(product.calculated_sale_price))}</div>
                          <div className="pp-pricing-rule text-xs text-zinc-400 font-sans mt-1">{product.pricing_label}</div>
                        </td>
                        <td className="pp-details py-2 px-3">
                          <span>{product.variants_count || 0} variants</span>
                          <small className={product.images_count ? '' : 'pp-missing'}>{product.images_count || 0} source images</small>
                          <small className={product.measurement_summary?.complete?'text-emerald-400':'pp-missing'} title={`${product.measurement_summary?.variants_with_weight || 0}/${product.measurement_summary?.total_variants || 0} variants with weight; ${product.measurement_summary?.variants_with_dimensions || 0}/${product.measurement_summary?.total_variants || 0} with dimensions`}>{product.measurement_summary?.label || 'Measurements not checked'}</small>
                          {product.group_count>0 && <small>{product.group_count} families</small>}
                        </td>
                        <td className="py-2 px-3 text-center">
                          {product.is_valid ? (
                            <Badge className={product.status==='images_pending'?'pp-status pp-pending':product.status==='synced'?'pp-status pp-synced':'pp-status pp-ready'}>{product.status === "images_pending" ? "Images pending" : product.status === "synced" ? "Synced" : "Ready"}</Badge>
                          ) : (
                            <Badge className="pp-status pp-review">Needs review</Badge>
                          )}
                        </td>
                        <td className="py-2 px-3 text-center">
                          {(!product.is_valid || product.status==='images_pending') && <a className="pp-row-review" href={`/export-review?product=${encodeURIComponent(product.id)}`}>Review</a>}
                          <Button 
                            variant="ghost" 
                            size="sm"
                            onClick={() => previewProductData(product.id)}
                            aria-label={`Preview ${product.supplier_sku}`}
                          >
                            <Eye className="w-4 h-4 mr-1" /> Preview
                          </Button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              
              {/* Pagination */}
              <div className="flex items-center justify-between mt-4 pt-4 border-t border-zinc-800">
                <p className="text-sm text-zinc-500">
                  Showing {(page - 1) * limit + 1} - {Math.min(page * limit, total)} of {total} products
                </p>
                <div className="flex gap-2">
                  <Button 
                    variant="outline" 
                    size="sm" 
                    onClick={() => setPage(p => Math.max(1, p - 1))}
                    disabled={page === 1 || loading || syncing}
                  >
                    Previous
                  </Button>
                  <Button 
                    variant="outline" 
                    size="sm" 
                    onClick={() => setPage(p => p + 1)}
                    disabled={page * limit >= total || loading || syncing}
                  >
                    Next
                  </Button>
                </div>
              </div>
            </>
          ) : (
            <div className="text-center py-10 text-zinc-500">
              <Package className="w-12 h-12 mx-auto mb-4 opacity-50" />
              <p>No products found</p>
              <p className="text-sm mt-1">{!supplierId?'Choose a supplier above to load its products.':search || statusFilter!=='all'?'Try a different search or status.':'Import products from your supplier to get started.'}</p>
              {(search || statusFilter!=='all') && <button className="pp-edit-pricing" onClick={()=>{setSearch('');setSearchQuery('');setStatusFilter('all');setPage(1);}}>Clear filters</button>}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Sync Actions */}
      <Card className="pp-sync-bar bg-zinc-900/50 border-zinc-800">
        <CardContent className="p-4">
          <div className="flex items-center justify-between flex-wrap gap-4">
            <div className="flex items-center gap-4">
              <p className="text-sm text-zinc-400">
                <span className="font-bold text-zinc-100">{selectedProducts.size}</span> products selected
              </p>
              {summary && (
                <p className="text-sm text-zinc-400">
                  <span className="font-bold text-green-400">{summary.sync_status?.ready || 0}</span> ready for sync
                </p>
              )}
            </div>
            <div className="flex items-center gap-3">
              <span className="text-sm text-zinc-400">Lightspeed</span>
              <Button 
                onClick={syncSelected}
                disabled={!supplierId || syncing || loading || !!loadError || selectedProducts.size === 0}
                className="bg-blue-600 hover:bg-blue-700"
                data-testid="sync-selected-btn"
              >
                {syncing ? <RefreshCw className="w-4 h-4 animate-spin mr-2" /> : <Upload className="w-4 h-4 mr-2" />}
                Sync / Update Selected ({selectedProducts.size})
              </Button>
              <Button 
                onClick={syncAll}
                disabled={!supplierId || syncing || loading || !!loadError}
                variant="outline"
                data-testid="sync-all-btn"
              >
                {syncing ? <RefreshCw className="w-4 h-4 animate-spin mr-2" /> : <ArrowRight className="w-4 h-4 mr-2" />}
                {categoryId!=='all'?'Sync Category Ready':supplierId==='all'?'Sync All Ready':`Sync ${suppliers.find(s=>s.id===supplierId)?.supplier_name || 'Supplier'} Ready`} to {platformLabel}
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>


    </div>
  );
}





