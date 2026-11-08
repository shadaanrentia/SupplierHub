import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import axios from "axios";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Search, Package, Grid3X3, List, DollarSign, Warehouse, Image, Loader2, MoreVertical, RefreshCw, Download, Database, Globe, CheckCircle2 } from "lucide-react";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { toast } from "sonner";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

export default function ProductSearch() {
  const navigate = useNavigate();
  const [suppliers, setSuppliers] = useState([]);
  const [selectedSupplier, setSelectedSupplier] = useState("");
  const [searchQuery, setSearchQuery] = useState("");
  const [results, setResults] = useState([]);
  const [loading, setLoading] = useState(false);
  const [searched, setSearched] = useState(false);
  const [viewMode, setViewMode] = useState("grid");
  const [searchMode, setSearchMode] = useState("catalog"); // "catalog" or "database"
  const [syncing, setSyncing] = useState({});
  const [bulkSyncing, setBulkSyncing] = useState({});
  const [importing, setImporting] = useState({});
  const [catalogStats, setCatalogStats] = useState(null);

  // Fetch suppliers on mount
  useEffect(() => {
    axios.get(`${API}/suppliers`).then(res => {
      setSuppliers(res.data.suppliers || []);
    }).catch(() => {});
  }, []);

  const handleSearch = async (e) => {
    e.preventDefault();
    if (!selectedSupplier) {
      toast.error("Please select a supplier");
      return;
    }

    setLoading(true);
    setSearched(true);
    setCatalogStats(null);

    try {
      if (searchMode === "catalog") {
        // Search supplier's catalog via PromoStandards API (fast mode - SKUs only)
        const res = await axios.get(`${API}/suppliers/${selectedSupplier}/catalog`, {
          params: {
            search: searchQuery.trim() || undefined,
            limit: 100,
            get_details: false  // Fast mode - just SKUs
          }
        });
        setResults(res.data.products || []);
        setCatalogStats({
          total: res.data.total_in_catalog,
          showing: res.data.showing,
          supplier: res.data.supplier_name
        });
        if (res.data.products?.length === 0) {
          toast.info("No products found in supplier catalog");
        } else {
          toast.success(`Found ${res.data.showing} products from ${res.data.supplier_name} (${res.data.total_in_catalog.toLocaleString()} total in catalog)`);
        }
      } else {
        // Search local database
        if (!searchQuery.trim()) {
          toast.error("Please enter a search term for database search");
          setLoading(false);
          return;
        }
        const res = await axios.get(`${API}/products`, {
          params: {
            supplier_id: selectedSupplier,
            search: searchQuery.trim(),
            limit: 100
          }
        });
        setResults(res.data.products || []);
        if (res.data.products?.length === 0) {
          toast.info("No products found in database");
        }
      }
    } catch (e) {
      const msg = e.response?.data?.detail || "Search failed";
      toast.error(msg);
      setResults([]);
    } finally {
      setLoading(false);
    }
  };

  const importProduct = async (supplierSku) => {
    setImporting(prev => ({ ...prev, [supplierSku]: true }));
    try {
      const res = await axios.post(`${API}/suppliers/${selectedSupplier}/import-product/${encodeURIComponent(supplierSku)}`);
      if (res.data.success) {
        toast.success(`Imported "${res.data.product_name}" with ${res.data.variants_added} variants`);
        // Update the result to show as imported
        setResults(prev => prev.map(p => 
          p.supplier_sku === supplierSku ? { ...p, is_imported: true, id: res.data.product_id } : p
        ));
      } else {
        toast.info(res.data.message);
      }
    } catch (e) {
      toast.error(e.response?.data?.detail || "Import failed");
    } finally {
      setImporting(prev => ({ ...prev, [supplierSku]: false }));
    }
  };

  const syncProduct = async (productId, type) => {
    const key = `${productId}-${type}`;
    setSyncing(prev => ({ ...prev, [key]: true }));
    try {
      const res = await axios.post(`${API}/sync/product/${productId}/${type}`);
      if (res.data.success) {
        toast.success(res.data.message);
      } else {
        toast.error(res.data.message || "Sync failed");
      }
    } catch (e) {
      toast.error("Sync failed");
    } finally {
      setSyncing(prev => ({ ...prev, [key]: false }));
    }
  };

  const bulkSync = async (type) => {
    const productIds = results.filter(p => p.id).map(p => p.id);
    if (productIds.length === 0) {
      toast.error("No imported products to sync");
      return;
    }
    setBulkSyncing(prev => ({ ...prev, [type]: true }));
    try {
      const res = await axios.post(`${API}/sync/products/bulk?sync_type=${type}`, productIds);
      toast.success(`Synced ${res.data.success} products`);
    } catch (e) {
      toast.error("Bulk sync failed");
    } finally {
      setBulkSyncing(prev => ({ ...prev, [type]: false }));
    }
  };

  const importAll = async () => {
    const toImport = results.filter(p => !p.is_imported);
    if (toImport.length === 0) {
      toast.info("All products already imported");
      return;
    }
    
    toast.info(`Importing ${toImport.length} products...`);
    let imported = 0;
    
    for (const product of toImport) {
      try {
        await axios.post(`${API}/suppliers/${selectedSupplier}/import-product/${encodeURIComponent(product.supplier_sku)}`);
        imported++;
        setResults(prev => prev.map(p => 
          p.supplier_sku === product.supplier_sku ? { ...p, is_imported: true } : p
        ));
      } catch (e) {
        // Continue on error
      }
    }
    
    toast.success(`Imported ${imported} products`);
  };

  return (
    <div className="p-6 space-y-6" data-testid="product-search-page">
      <div>
        <h1 className="font-heading text-3xl font-bold tracking-tight">Product Search</h1>
        <p className="text-zinc-500 text-sm mt-1">Search products from supplier catalog or your database</p>
      </div>

      {/* Search Mode Tabs */}
      <Tabs value={searchMode} onValueChange={(v) => { setSearchMode(v); setResults([]); setSearched(false); setCatalogStats(null); }}>
        <TabsList className="bg-zinc-900 border border-zinc-800">
          <TabsTrigger value="catalog" className="data-[state=active]:bg-blue-600" data-testid="tab-catalog">
            <Globe className="w-4 h-4 mr-2" />
            Supplier Catalog
          </TabsTrigger>
          <TabsTrigger value="database" className="data-[state=active]:bg-blue-600" data-testid="tab-database">
            <Database className="w-4 h-4 mr-2" />
            Local Database
          </TabsTrigger>
        </TabsList>

        <TabsContent value="catalog" className="mt-4">
          <Card className="bg-zinc-900/50 border-zinc-800 rounded-sm">
            <CardHeader className="pb-2">
              <CardTitle className="text-lg font-heading flex items-center gap-2">
                <Globe className="w-5 h-5 text-blue-400" />
                Search Supplier Catalog (Live API)
              </CardTitle>
              <p className="text-xs text-zinc-500">Searches the supplier's PromoStandards API directly. Leave search empty to browse all products.</p>
            </CardHeader>
            <CardContent>
              <form onSubmit={handleSearch} className="flex flex-wrap gap-3 items-end">
                <div className="w-64">
                  <label className="text-xs text-zinc-500 mb-1 block">Supplier *</label>
                  <Select value={selectedSupplier} onValueChange={setSelectedSupplier}>
                    <SelectTrigger className="bg-zinc-950 border-zinc-800 rounded-none" data-testid="search-supplier">
                      <SelectValue placeholder="Select supplier..." />
                    </SelectTrigger>
                    <SelectContent className="bg-zinc-900 border-zinc-800">
                      {suppliers.map((s) => (
                        <SelectItem key={s.id} value={s.id}>{s.supplier_name}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="flex-1 min-w-[200px]">
                  <label className="text-xs text-zinc-500 mb-1 block">Search by SKU (optional)</label>
                  <div className="relative">
                    <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-zinc-500" />
                    <Input
                      value={searchQuery}
                      onChange={(e) => setSearchQuery(e.target.value)}
                      placeholder="Enter SKU to filter..."
                      className="pl-10 bg-zinc-950 border-zinc-800 rounded-none"
                      data-testid="search-input"
                    />
                  </div>
                </div>
                <Button type="submit" disabled={loading} className="bg-blue-600 hover:bg-blue-500 rounded-none" data-testid="search-btn">
                  {loading ? <Loader2 className="w-4 h-4 animate-spin mr-2" /> : <Search className="w-4 h-4 mr-2" />}
                  {loading ? "Searching..." : "Search Catalog"}
                </Button>
              </form>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="database" className="mt-4">
          <Card className="bg-zinc-900/50 border-zinc-800 rounded-sm">
            <CardHeader className="pb-2">
              <CardTitle className="text-lg font-heading flex items-center gap-2">
                <Database className="w-5 h-5 text-emerald-400" />
                Search Local Database
              </CardTitle>
              <p className="text-xs text-zinc-500">Searches products already imported into your database.</p>
            </CardHeader>
            <CardContent>
              <form onSubmit={handleSearch} className="flex flex-wrap gap-3 items-end">
                <div className="w-64">
                  <label className="text-xs text-zinc-500 mb-1 block">Supplier *</label>
                  <Select value={selectedSupplier} onValueChange={setSelectedSupplier}>
                    <SelectTrigger className="bg-zinc-950 border-zinc-800 rounded-none" data-testid="db-search-supplier">
                      <SelectValue placeholder="Select supplier..." />
                    </SelectTrigger>
                    <SelectContent className="bg-zinc-900 border-zinc-800">
                      {suppliers.map((s) => (
                        <SelectItem key={s.id} value={s.id}>{s.supplier_name}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="flex-1 min-w-[200px]">
                  <label className="text-xs text-zinc-500 mb-1 block">Search *</label>
                  <div className="relative">
                    <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-zinc-500" />
                    <Input
                      value={searchQuery}
                      onChange={(e) => setSearchQuery(e.target.value)}
                      placeholder="Search by name or SKU..."
                      className="pl-10 bg-zinc-950 border-zinc-800 rounded-none"
                      data-testid="db-search-input"
                    />
                  </div>
                </div>
                <Button type="submit" disabled={loading} className="bg-emerald-600 hover:bg-emerald-500 rounded-none" data-testid="db-search-btn">
                  {loading ? <Loader2 className="w-4 h-4 animate-spin mr-2" /> : <Search className="w-4 h-4 mr-2" />}
                  Search Database
                </Button>
              </form>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>

      {/* Catalog Stats */}
      {catalogStats && (
        <div className="bg-zinc-900/50 border border-zinc-800 p-3 rounded-sm">
          <p className="text-sm text-zinc-400">
            <span className="text-blue-400 font-mono">{catalogStats.showing}</span> products shown from 
            <span className="text-white font-semibold"> {catalogStats.supplier}</span> 
            <span className="text-zinc-500"> (Total in catalog: {catalogStats.total.toLocaleString()})</span>
          </p>
        </div>
      )}

      {/* Results */}
      {searched && (
        <Card className="bg-zinc-900/50 border-zinc-800 rounded-sm">
          <CardHeader className="pb-2 border-b border-zinc-800/50">
            <div className="flex items-center justify-between">
              <CardTitle className="text-lg font-heading">
                {searchMode === "catalog" ? "Catalog Results" : "Database Results"} ({results.length})
              </CardTitle>
              <div className="flex items-center gap-2">
                {searchMode === "catalog" && results.length > 0 && (
                  <Button onClick={importAll} variant="outline" size="sm" className="border-emerald-600 text-emerald-400 hover:bg-emerald-600/20 rounded-none">
                    <Download className="w-4 h-4 mr-1" />
                    Import All
                  </Button>
                )}
                {searchMode === "database" && results.length > 0 && (
                  <>
                    <Button onClick={() => bulkSync('pricing')} disabled={bulkSyncing.pricing} variant="outline" size="sm" className="border-zinc-700 rounded-none">
                      {bulkSyncing.pricing ? <Loader2 className="w-4 h-4 animate-spin mr-1" /> : <DollarSign className="w-4 h-4 mr-1" />}
                      Sync All Pricing
                    </Button>
                    <Button onClick={() => bulkSync('inventory')} disabled={bulkSyncing.inventory} variant="outline" size="sm" className="border-zinc-700 rounded-none">
                      {bulkSyncing.inventory ? <Loader2 className="w-4 h-4 animate-spin mr-1" /> : <Warehouse className="w-4 h-4 mr-1" />}
                      Sync All Inventory
                    </Button>
                  </>
                )}
                <div className="flex border border-zinc-800 rounded-sm overflow-hidden">
                  <Button variant="ghost" size="sm" onClick={() => setViewMode("grid")} className={`rounded-none ${viewMode === "grid" ? "bg-zinc-800" : ""}`} data-testid="view-grid">
                    <Grid3X3 className="w-4 h-4" />
                  </Button>
                  <Button variant="ghost" size="sm" onClick={() => setViewMode("list")} className={`rounded-none ${viewMode === "list" ? "bg-zinc-800" : ""}`} data-testid="view-list">
                    <List className="w-4 h-4" />
                  </Button>
                </div>
              </div>
            </div>
          </CardHeader>
          <CardContent className="p-4">
            {results.length === 0 ? (
              <div className="text-center py-12 text-zinc-500">
                <Package className="w-12 h-12 mx-auto mb-3 opacity-50" />
                <p>No products found</p>
              </div>
            ) : viewMode === "grid" ? (
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
                {results.map((product) => (
                  <div key={product.supplier_sku} className="bg-zinc-950 border border-zinc-800 p-4 hover:border-zinc-700 transition-colors" data-testid={`catalog-product-${product.supplier_sku}`}>
                    <div className="flex items-start justify-between mb-2">
                      <div className="flex-1 min-w-0">
                        <h3 className="font-medium text-sm truncate">{product.product_name || product.supplier_sku}</h3>
                        <p className="text-xs text-zinc-500 font-mono">{product.supplier_sku}</p>
                      </div>
                      {searchMode === "catalog" ? (
                        product.is_imported ? (
                          <span className="text-emerald-400 text-xs flex items-center gap-1">
                            <CheckCircle2 className="w-4 h-4" />
                            Imported
                          </span>
                        ) : (
                          <Button 
                            onClick={() => importProduct(product.supplier_sku)} 
                            disabled={importing[product.supplier_sku]}
                            size="sm"
                            className="bg-emerald-600 hover:bg-emerald-500 rounded-none text-xs"
                          >
                            {importing[product.supplier_sku] ? <Loader2 className="w-3 h-3 animate-spin" /> : <Download className="w-3 h-3 mr-1" />}
                            Import
                          </Button>
                        )
                      ) : (
                        <DropdownMenu>
                          <DropdownMenuTrigger asChild>
                            <Button variant="ghost" size="sm" className="h-8 w-8 p-0">
                              <MoreVertical className="w-4 h-4" />
                            </Button>
                          </DropdownMenuTrigger>
                          <DropdownMenuContent align="end" className="bg-zinc-900 border-zinc-800">
                            <DropdownMenuItem onClick={() => syncProduct(product.id, 'pricing')} disabled={syncing[`${product.id}-pricing`]}>
                              {syncing[`${product.id}-pricing`] ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <DollarSign className="w-4 h-4 mr-2" />}
                              Sync Pricing
                            </DropdownMenuItem>
                            <DropdownMenuItem onClick={() => syncProduct(product.id, 'inventory')} disabled={syncing[`${product.id}-inventory`]}>
                              {syncing[`${product.id}-inventory`] ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <Warehouse className="w-4 h-4 mr-2" />}
                              Sync Inventory
                            </DropdownMenuItem>
                            <DropdownMenuItem onClick={() => syncProduct(product.id, 'media')} disabled={syncing[`${product.id}-media`]}>
                              {syncing[`${product.id}-media`] ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <Image className="w-4 h-4 mr-2" />}
                              Sync Media
                            </DropdownMenuItem>
                          </DropdownMenuContent>
                        </DropdownMenu>
                      )}
                    </div>
                    <div className="text-xs text-zinc-500 space-y-1">
                      {product.brand && <p>Brand: <span className="text-zinc-400">{product.brand}</span></p>}
                      {product.category && <p>Category: <span className="text-zinc-400">{product.category}</span></p>}
                      <p>Variants: <span className="text-zinc-400">{product.variant_count || 0}</span></p>
                    </div>
                    {product.id && (
                      <Button 
                        onClick={() => navigate(`/products/${product.id}`)} 
                        variant="ghost" 
                        size="sm" 
                        className="w-full mt-3 text-xs border border-zinc-800 hover:bg-zinc-800 rounded-none"
                      >
                        View Details
                      </Button>
                    )}
                  </div>
                ))}
              </div>
            ) : (
              <div className="space-y-2">
                {results.map((product) => (
                  <div key={product.supplier_sku} className="bg-zinc-950 border border-zinc-800 p-3 flex items-center justify-between hover:border-zinc-700 transition-colors">
                    <div className="flex items-center gap-4">
                      <div>
                        <h3 className="font-medium text-sm">{product.product_name || product.supplier_sku}</h3>
                        <p className="text-xs text-zinc-500">
                          <span className="font-mono">{product.supplier_sku}</span>
                          {product.brand && <span className="ml-2">• {product.brand}</span>}
                          {product.category && <span className="ml-2">• {product.category}</span>}
                          <span className="ml-2">• {product.variant_count || 0} variants</span>
                        </p>
                      </div>
                    </div>
                    <div className="flex items-center gap-2">
                      {searchMode === "catalog" ? (
                        product.is_imported ? (
                          <span className="text-emerald-400 text-xs flex items-center gap-1 px-2">
                            <CheckCircle2 className="w-4 h-4" />
                            Imported
                          </span>
                        ) : (
                          <Button 
                            onClick={() => importProduct(product.supplier_sku)} 
                            disabled={importing[product.supplier_sku]}
                            size="sm"
                            className="bg-emerald-600 hover:bg-emerald-500 rounded-none"
                          >
                            {importing[product.supplier_sku] ? <Loader2 className="w-4 h-4 animate-spin" /> : <Download className="w-4 h-4 mr-1" />}
                            Import
                          </Button>
                        )
                      ) : (
                        <>
                          <Button onClick={() => syncProduct(product.id, 'pricing')} disabled={syncing[`${product.id}-pricing`]} variant="outline" size="sm" className="rounded-none">
                            {syncing[`${product.id}-pricing`] ? <Loader2 className="w-4 h-4 animate-spin" /> : <DollarSign className="w-4 h-4" />}
                          </Button>
                          <Button onClick={() => syncProduct(product.id, 'inventory')} disabled={syncing[`${product.id}-inventory`]} variant="outline" size="sm" className="rounded-none">
                            {syncing[`${product.id}-inventory`] ? <Loader2 className="w-4 h-4 animate-spin" /> : <Warehouse className="w-4 h-4" />}
                          </Button>
                          <Button onClick={() => navigate(`/products/${product.id}`)} variant="ghost" size="sm" className="rounded-none">
                            View
                          </Button>
                        </>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  );
}
