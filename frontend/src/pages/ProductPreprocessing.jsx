import React, { useState, useEffect, useCallback, useRef } from "react";
import axios from "../lib/axios";
import { toast } from "sonner";
import { Card, CardContent, CardHeader, CardTitle } from "../components/ui/card";
import { Button } from "../components/ui/button";
import { Checkbox } from "../components/ui/checkbox";
import { Badge } from "../components/ui/badge";
import { 
  RefreshCw, Package, DollarSign, CheckCircle, XCircle, 
  AlertTriangle, Eye, Upload, Calculator, Layers, Image,
  ArrowRight, Filter, Zap
} from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "../components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "../components/ui/select";

const API = (process.env.REACT_APP_BACKEND_URL || "").replace(/\/+$/, "") + "/api";

export default function ProductPreprocessing() {
  const [products, setProducts] = useState([]);
  const [summary, setSummary] = useState(null);
  const [suppliers,setSuppliers]=useState([]);
  const [supplierId,setSupplierId]=useState('all');
  useEffect(()=>{axios.get(`${API}/suppliers`).then(r=>setSuppliers(Array.isArray(r.data)?r.data:r.data.suppliers || [])).catch(()=>toast.error('Could not load suppliers'));},[]);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState('');
  const [syncing, setSyncing] = useState(false);
  const [selectedProducts, setSelectedProducts] = useState(new Set());
  const [readyIds, setReadyIds] = useState([]);
  const [readyLoading, setReadyLoading] = useState(true);
  const [readyError, setReadyError] = useState('');
  const [previewProduct, setPreviewProduct] = useState(null);
  const [showPreview, setShowPreview] = useState(false);
  const [statusFilter, setStatusFilter] = useState("all");
  const [search, setSearch] = useState(()=>new URLSearchParams(window.location.search).get("search") || "");
  const [searchQuery, setSearchQuery] = useState(()=>new URLSearchParams(window.location.search).get("search") || "");
  const requestVersion = useRef(0);
  const summaryVersion = useRef(0);
  useEffect(() => { const timer=setTimeout(() => {setSearchQuery(search);setPage(1);},250); return () => clearTimeout(timer); }, [search]);
  useEffect(() => {setSelectedProducts(new Set());},[searchQuery,statusFilter,supplierId]);
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [previewLoading, setPreviewLoading] = useState(false);
  const previewRequest = useRef(0);
  const syncPlatform = "lightspeed";
  const limit = 25;

  const fetchProducts = useCallback(async () => {
    const version=++requestVersion.current;
    setLoading(true);
    setLoadError('');
    setReadyLoading(true);setReadyError('');setReadyIds([]);
    try {
      const params = new URLSearchParams({ page, limit, search: searchQuery });
      if(supplierId!=='all') params.append('supplier_id',supplierId);
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
  }, [page, statusFilter, searchQuery,supplierId]);

  const readySelectedCount=readyIds.filter(id=>selectedProducts.has(id)).length;
  const allReadySelected=readyIds.length>0 && readySelectedCount===readyIds.length;
  const toggleAllReady=checked=>setSelectedProducts(checked ? new Set(readyIds) : new Set());

  const fetchSummary = useCallback(async () => {
    const version=++summaryVersion.current;
    try {
      const res = await axios.get(`${API}/preprocessing/summary`,{params:supplierId==='all'?{}:{supplier_id:supplierId}});
      if(version===summaryVersion.current) setSummary(res.data);
    } catch (e) {
      console.error("Failed to load summary");
    }
  }, [supplierId]);

  useEffect(() => {fetchProducts();}, [fetchProducts]);
  useEffect(() => {fetchSummary();}, [fetchSummary]);

  const recalculatePrices = async () => {
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

  const syncEndpoint = "sync-to-lightspeed";
  const platformLabel = "Lightspeed";

  const syncSelected = async () => {
    if (selectedProducts.size === 0) {
      toast.error("No products selected");
      return;
    }
    setSyncing(true);
    try {
      const res = await axios.post(`${API}/preprocessing/${syncEndpoint}`, {
        product_ids: Array.from(selectedProducts), supplier_id:supplierId==='all'?null:supplierId
      });
      if (res.data.synced > 0) {
        toast.success(`Synced ${res.data.synced} products to ${platformLabel}`);
      }
      if (res.data.failed > 0) {
        toast.error(`Failed to sync ${res.data.failed} products`);
      }
      if(res.data.images_pending || res.data.needs_review) toast.warning(`${res.data.images_pending || res.data.needs_review} products have images pending; inspect Export Review`);
      if(res.data.skipped) toast.info(`${res.data.skipped} products skipped: not eligible for this operation`);
      if(res.data.errors?.length) toast.error(res.data.errors[0].error);
      setSelectedProducts(new Set());
      fetchProducts();
      fetchSummary();
    } catch (e) {
      toast.error(e.response?.data?.detail || `Sync to ${platformLabel} failed`);
    } finally {
      setSyncing(false);
    }
  };

  const syncAll = async () => {
    setSyncing(true);
    try {
      const res = await axios.post(`${API}/preprocessing/${syncEndpoint}`, { sync_all: true, supplier_id:supplierId==='all'?null:supplierId });
      if (res.data.synced > 0) {
        toast.success(`Synced ${res.data.synced} products to ${platformLabel}`);
      }
      if (res.data.failed > 0) {
        toast.error(`Failed to sync ${res.data.failed} products`);
      }
      if(res.data.images_pending || res.data.needs_review) toast.warning(`${res.data.images_pending || res.data.needs_review} products have images pending; inspect Export Review`);
      if(res.data.errors?.length) toast.error(res.data.errors[0].error);
      fetchProducts();
      fetchSummary();
    } catch (e) {
      toast.error(e.response?.data?.detail || `Sync to ${platformLabel} failed`);
    } finally {
      setSyncing(false);
    }
  };

  const previewProductData = async (productId) => {
    const version=++previewRequest.current;
    setPreviewProduct(null); setPreviewLoading(true); setShowPreview(true);
    try {
      const res = await axios.get(`${API}/preprocessing/product/${productId}/preview`);
      if(version!==previewRequest.current) return;
      setPreviewProduct(res.data);
    } catch (e) {
      if(version===previewRequest.current) toast.error("Failed to load preview");
    } finally {
      if(version===previewRequest.current) setPreviewLoading(false);
    }
  };

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
              <Select disabled={syncing} value={supplierId} onValueChange={value=>{setSupplierId(value);setPage(1);setSelectedProducts(new Set());}}>
                <SelectTrigger aria-label="Supplier filter" className="w-48 bg-zinc-800 border-zinc-700"><SelectValue placeholder="All suppliers" /></SelectTrigger>
                <SelectContent className="bg-zinc-900 border-zinc-800"><SelectItem value="all">All suppliers</SelectItem>{suppliers.map(s=><SelectItem key={s.id} value={s.id}>{s.supplier_name}</SelectItem>)}</SelectContent>
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
              <input aria-label="Search preprocessing products" placeholder="Search product name or SKU" value={search} disabled={syncing} onChange={event=>setSearch(event.target.value)} className="pp-search bg-zinc-800 border border-zinc-700 rounded px-3 py-2 text-sm" />
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
                            <p title={product.product_name || product.supplier_sku} className="pp-product-name text-zinc-100 font-medium">
                              {product.product_name || product.supplier_sku}
                            </p>
                            <p className="pp-product-meta"><span>{product.supplier_sku}</span><span>{product.supplier_name || 'Unknown supplier'}</span></p>
                          </div>
                        </td>
                        <td className="py-2 px-3">
                          {product.mapped_lightspeed_category_id ? (
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
              <p className="text-sm mt-1">{search || statusFilter!=='all'?'Try a different search or status.':'Import products from your supplier to get started.'}</p>
              {(search || statusFilter!=='all') && <button className="pp-edit-pricing" onClick={()=>{setSearch('');setStatusFilter('all');setPage(1);}}>Clear filters</button>}
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
                disabled={syncing || loading || !!loadError || selectedProducts.size === 0}
                className="bg-blue-600 hover:bg-blue-700"
                data-testid="sync-selected-btn"
              >
                {syncing ? <RefreshCw className="w-4 h-4 animate-spin mr-2" /> : <Upload className="w-4 h-4 mr-2" />}
                Sync / Update Selected ({selectedProducts.size})
              </Button>
              <Button 
                onClick={syncAll}
                disabled={syncing || loading || !!loadError}
                variant="outline"
                data-testid="sync-all-btn"
              >
                {syncing ? <RefreshCw className="w-4 h-4 animate-spin mr-2" /> : <ArrowRight className="w-4 h-4 mr-2" />}
                {supplierId==='all'?'Sync All Ready':`Sync ${suppliers.find(s=>s.id===supplierId)?.supplier_name || 'Supplier'} Ready`} to {platformLabel}
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Preview Dialog */}
      <Dialog open={showPreview} onOpenChange={open=>{setShowPreview(open);if(!open){previewRequest.current++;setPreviewLoading(false);}}}>
        <DialogContent className="bg-zinc-900 border-zinc-800 max-w-3xl max-h-[80vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>Product Preview</DialogTitle>
          </DialogHeader>
          {previewLoading && <p role="status" className="text-zinc-400 py-6">Loading product…</p>}
          {!previewLoading && !previewProduct && <p role="alert" className="text-zinc-400 py-6">Preview could not be loaded. Close and try again.</p>}
          {previewProduct && (
            <div className="space-y-6 py-4">
              {/* Product Template */}
              <div>
                <h3 className="text-sm font-semibold text-zinc-400 mb-2">Product Details</h3>
                <div className="bg-zinc-800/50 rounded-lg p-4 space-y-2">
                  <div className="flex justify-between">
                    <span className="text-zinc-500">Name:</span>
                    <span className="text-zinc-100">{previewProduct.product_template.name}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-zinc-500">SKU:</span>
                    <span className="font-mono text-zinc-100">{previewProduct.product_template.default_code}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-zinc-500">Category:</span>
                    <span className={previewProduct.product_template.categ_id ? "text-green-400" : "text-red-400"}>
                      {previewProduct.product_template.category_name}
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-zinc-500">Supplier Price (before markup):</span>
                    <span className="font-mono text-zinc-400">{formatPrice(previewProduct.product_template.standard_price)}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-zinc-500">Retail Price (after markup):</span>
                    <span className="font-mono text-green-400 font-bold">{formatPrice(previewProduct.product_template.list_price)}</span>
                  </div>
                </div>
              </div>

              {/* Attributes */}
              <div>
                <h3 className="text-sm font-semibold text-zinc-400 mb-2">Attributes</h3>
                <div className="bg-zinc-800/50 rounded-lg p-4 grid grid-cols-2 gap-4">
                  <div>
                    <p className="text-xs text-zinc-500 mb-1">Colors ({previewProduct.attributes.colors.length})</p>
                    <div className="flex flex-wrap gap-1">
                      {previewProduct.attributes.colors.slice(0, 10).map((c, i) => (
                        <Badge key={i} variant="outline" className="text-xs">{c}</Badge>
                      ))}
                      {previewProduct.attributes.colors.length > 10 && (
                        <Badge variant="outline" className="text-xs">+{previewProduct.attributes.colors.length - 10} more</Badge>
                      )}
                    </div>
                  </div>
                  <div>
                    <p className="text-xs text-zinc-500 mb-1">Sizes ({previewProduct.attributes.sizes.length})</p>
                    <div className="flex flex-wrap gap-1">
                      {previewProduct.attributes.sizes.map((s, i) => (
                        <Badge key={i} variant="outline" className="text-xs">{s}</Badge>
                      ))}
                    </div>
                  </div>
                </div>
              </div>

              {/* Variants */}
              <div>
                <h3 className="text-sm font-semibold text-zinc-400 mb-2">Variants ({previewProduct.variants.length})</h3>
                <div className="bg-zinc-800/50 rounded-lg p-4 max-h-40 overflow-y-auto">
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="text-zinc-500">
                        <th className="text-left py-1">SKU</th>
                        <th className="text-left py-1">Color</th>
                        <th className="text-left py-1">Size</th>
                        <th className="text-right py-1">Supplier price</th>
                        <th className="text-right py-1">Retail price</th>
                        <th className="text-right py-1">Stock</th>
                      </tr>
                    </thead>
                    <tbody>
                      {previewProduct.variants.slice(0, 20).map((v, i) => (
                        <tr key={i} className="text-zinc-300">
                          <td className="py-1 font-mono">{v.sku}</td>
                          <td className="py-1">{v.color || '--'}</td>
                          <td className="py-1">{v.size || '--'}</td>
                          <td className="py-1 text-right">{formatPrice(v.price)}</td>
                          <td className="py-1 text-right">{formatPrice(v.retail_price)}</td>
                          <td className="py-1 text-right">{v.inventory}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {previewProduct.variants.length > 20 && (
                    <p className="text-xs text-zinc-500 mt-2">... and {previewProduct.variants.length - 20} more variants</p>
                  )}
                </div>
              </div>

              {/* Validation */}
              <div>
                <h3 className="text-sm font-semibold text-zinc-400 mb-2">Validation</h3>
                <div className={`rounded-lg p-4 ${previewProduct.validation.is_valid ? 'bg-green-900/20' : 'bg-red-900/20'}`}>
                  {previewProduct.validation.is_valid ? (
                    <div className="flex items-center gap-2 text-green-400">
                      <CheckCircle className="w-5 h-5" />
                      <span>Product is valid and ready for sync</span>
                    </div>
                  ) : (
                    <div>
                      <div className="flex items-center gap-2 text-red-400 mb-2">
                        <XCircle className="w-5 h-5" />
                        <span>Product has validation errors</span>
                      </div>
                      <ul className="list-disc list-inside text-sm text-red-300">
                        {previewProduct.validation.errors.map((err, i) => (
                          <li key={i}>{err}</li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}



