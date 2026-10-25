import { useState, useEffect } from "react";
import { useParams, useNavigate } from "react-router-dom";
import axios from "axios";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ArrowLeft, Package, Image, Tag, Layers } from "lucide-react";
import { toast } from "sonner";

const API = (process.env.REACT_APP_BACKEND_URL || "").replace(/\/+$/, "") + "/api";

export default function ProductDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [product, setProduct] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetch = async () => {
      try {
        const res = await axios.get(`${API}/products/${id}`);
        setProduct(res.data);
      } catch (e) {
        toast.error("Failed to load product");
        navigate("/products");
      } finally {
        setLoading(false);
      }
    };
    fetch();
  }, [id, navigate]);

  const toggleSelection = async () => {
    if (!product) return;
    try {
      await axios.post(`${API}/products/${product.id}/select-for-odoo`, {
        product_id: product.id,
        selected: !product.selected_for_odoo,
      });
      setProduct((p) => ({ ...p, selected_for_odoo: !p.selected_for_odoo }));
      toast.success(product.selected_for_odoo ? "Deselected from Odoo" : "Selected for Odoo");
    } catch (e) {
      toast.error("Failed to update");
    }
  };

  if (loading) {
    return (
      <div className="p-6 space-y-4">
        <div className="h-8 w-64 bg-zinc-800 animate-pulse rounded-sm" />
        <div className="h-64 bg-zinc-800/50 animate-pulse rounded-sm" />
      </div>
    );
  }

  if (!product) return null;

  const uniqueColors = [...new Set(product.variants?.map((v) => v.color).filter(Boolean))];
  const uniqueSizes = [...new Set(product.variants?.map((v) => v.size).filter(Boolean))];

  return (
    <div className="p-6 space-y-6" data-testid="product-detail-page">
      <div className="flex items-center gap-4">
        <Button
          variant="ghost"
          onClick={() => navigate("/products")}
          className="rounded-none text-zinc-400 hover:text-white"
          data-testid="back-to-products-btn"
        >
          <ArrowLeft className="w-4 h-4 mr-2" />
          Back
        </Button>
      </div>

      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="font-heading text-3xl font-bold tracking-tight">{product.product_name}</h1>
          <div className="flex items-center gap-3 mt-2">
            <span className="font-mono text-sm text-zinc-400">{product.supplier_sku}</span>
            <span className="text-zinc-700">|</span>
            <span className="text-sm text-zinc-400">{product.brand}</span>
            <span className="text-zinc-700">|</span>
            <span className="text-sm text-zinc-400">{product.supplier_name}</span>
          </div>
        </div>
        <div className="flex items-center gap-4">
          <div className="text-right">
            <p className="text-xs text-zinc-500">Select for Odoo</p>
            <Switch
              checked={product.selected_for_odoo}
              onCheckedChange={toggleSelection}
              className="data-[state=checked]:bg-blue-600 mt-1"
              data-testid="detail-odoo-toggle"
            />
          </div>
          <div className="text-right">
            <p className="text-xs text-zinc-500">Sync Status</p>
            <span className={`inline-flex px-2 py-0.5 text-xs font-mono border rounded-none mt-1 ${
              product.sync_status === "synced" ? "bg-emerald-950/50 text-emerald-400 border-emerald-800" :
              product.sync_status === "error" ? "bg-red-950/50 text-red-400 border-red-800" :
              "bg-zinc-800 text-zinc-400 border-zinc-700"
            }`}>
              {product.sync_status}
            </span>
          </div>
        </div>
      </div>

      <Tabs defaultValue="overview" className="space-y-4">
        <TabsList className="bg-zinc-900 border border-zinc-800 rounded-none p-0.5">
          <TabsTrigger value="overview" className="rounded-none text-sm data-[state=active]:bg-zinc-800 data-[state=active]:text-white" data-testid="tab-overview">
            <Package className="w-4 h-4 mr-2" strokeWidth={1.5} />Overview
          </TabsTrigger>
          <TabsTrigger value="variants" className="rounded-none text-sm data-[state=active]:bg-zinc-800 data-[state=active]:text-white" data-testid="tab-variants">
            <Layers className="w-4 h-4 mr-2" strokeWidth={1.5} />Variants ({product.variants?.length || 0})
          </TabsTrigger>
          <TabsTrigger value="media" className="rounded-none text-sm data-[state=active]:bg-zinc-800 data-[state=active]:text-white" data-testid="tab-media">
            <Image className="w-4 h-4 mr-2" strokeWidth={1.5} />Media ({product.media?.length || 0})
          </TabsTrigger>
        </TabsList>

        <TabsContent value="overview">
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <Card className="bg-zinc-900/50 border-zinc-800 rounded-sm">
              <CardHeader className="p-4 border-b border-zinc-800/50">
                <CardTitle className="font-heading text-sm font-bold uppercase text-zinc-400 tracking-wider">Product Info</CardTitle>
              </CardHeader>
              <CardContent className="p-4 space-y-3">
                <InfoRow label="Name" value={product.product_name} />
                <InfoRow label="SKU" value={product.supplier_sku} mono />
                <InfoRow label="Brand" value={product.brand} />
                <InfoRow label="Category" value={product.category} />
                <InfoRow label="Base Price" value={product.base_price ? `$${product.base_price.toFixed(2)}` : "$0.00"} mono />
                <InfoRow label="Odoo Status" value={product.odoo_sync_status} />
                <InfoRow label="Variants" value={product.variants?.length || 0} mono />
                <InfoRow label="Media" value={product.media?.length || 0} mono />
              </CardContent>
            </Card>
            <Card className="bg-zinc-900/50 border-zinc-800 rounded-sm">
              <CardHeader className="p-4 border-b border-zinc-800/50">
                <CardTitle className="font-heading text-sm font-bold uppercase text-zinc-400 tracking-wider">Description</CardTitle>
              </CardHeader>
              <CardContent className="p-4">
                <p className="text-sm text-zinc-300 leading-relaxed whitespace-pre-line"> {product.description || "No description available."}</p>
                {uniqueColors.length > 0 && (
                  <div className="mt-4">
                    <p className="text-xs text-zinc-500 mb-2">Available Colors</p>
                    <div className="flex flex-wrap gap-1.5">
                      {uniqueColors.map((c) => (
                        <span key={c} className="px-2 py-0.5 text-xs font-mono bg-zinc-800 text-zinc-300 border border-zinc-700">{c}</span>
                      ))}
                    </div>
                  </div>
                )}
                {uniqueSizes.length > 0 && (
                  <div className="mt-3">
                    <p className="text-xs text-zinc-500 mb-2">Available Sizes</p>
                    <div className="flex flex-wrap gap-1.5">
                      {uniqueSizes.map((s) => (
                        <span key={s} className="px-2 py-0.5 text-xs font-mono bg-zinc-800 text-zinc-300 border border-zinc-700">{s}</span>
                      ))}
                    </div>
                  </div>
                )}
              </CardContent>
            </Card>
          </div>
        </TabsContent>

        <TabsContent value="variants">
          <Card className="bg-zinc-900/50 border-zinc-800 rounded-sm">
            <CardContent className="p-0">
              {product.variants?.length > 0 ? (
                <div className="overflow-x-auto">
                  {product.preferred_warehouse && (
                    <div className="p-3 border-b border-zinc-800/50 bg-zinc-900/80">
                      <p className="text-xs text-zinc-400">
                        Showing inventory for: <span className="text-emerald-400 font-mono">{product.preferred_warehouse}</span>
                      </p>
                    </div>
                  )}
                  <table className="w-full" data-testid="variants-table">
                    <thead>
                      <tr className="border-b border-zinc-800 bg-zinc-900/80">
                        <th className="text-left p-3 text-xs font-mono text-zinc-500 uppercase tracking-wider">SKU</th>
                        <th className="text-left p-3 text-xs font-mono text-zinc-500 uppercase tracking-wider">Color</th>
                        <th className="text-left p-3 text-xs font-mono text-zinc-500 uppercase tracking-wider">Size</th>
                        <th className="text-left p-3 text-xs font-mono text-zinc-500 uppercase tracking-wider">Price</th>
                        <th className="text-left p-3 text-xs font-mono text-zinc-500 uppercase tracking-wider">
                          {product.preferred_warehouse ? `Inventory (${product.preferred_warehouse.split('/')[0]})` : 'Inventory'}
                        </th>
                        <th className="text-left p-3 text-xs font-mono text-zinc-500 uppercase tracking-wider">Lead Time</th>
                      </tr>
                    </thead>
                    <tbody>
                      {product.variants.map((v, i) => (
                        <tr key={v.id || i} className="border-b border-zinc-800/50 hover:bg-zinc-800/30 transition-colors">
                          <td className="p-3 text-sm font-mono text-zinc-300">{v.variant_sku}</td>
                          <td className="p-3 text-sm text-zinc-300">{v.color || "-"}</td>
                          <td className="p-3 text-sm font-mono">{v.size || "-"}</td>
                          <td className="p-3 text-sm font-mono tabular-nums">{v.price ? `$${v.price.toFixed(2)}` : "-"}</td>
                          <td className="p-3 text-sm font-mono tabular-nums">
                            <span className={v.inventory > 0 ? "text-emerald-400" : "text-red-400"}>{v.inventory ?? 0}</span>
                          </td>
                          <td className="p-3 text-sm text-zinc-400">{v.lead_time || "-"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <div className="p-12 text-center text-zinc-600 font-mono text-sm">NO VARIANTS</div>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="media">
          {product.media?.length > 0 ? (
            <>
              <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3">
                {product.media.map((m, i) => {
                  // Use media proxy to bypass CDN restrictions
                  const localUrl = m.local_url ? `${API.replace(/\/api$/, '')}${m.local_url}` : '';
                  const proxyUrl = localUrl || (m.url ? `${API}/media_proxy?url=${encodeURIComponent(m.url)}` : '');
                  return (
                    <Card key={m.id || i} className="bg-zinc-900/50 border-zinc-800 rounded-sm overflow-hidden group">
                      <div className="w-full h-48 bg-zinc-800 flex items-center justify-center relative">
                        <img 
                          src={proxyUrl} 
                          alt={m.description || "Product"} 
                          className="w-full h-full object-contain" 
                          onError={(e) => { 
                            e.target.style.display = 'none'; 
                            e.target.nextSibling.style.display = 'flex';
                          }} 
                        />
                        <div className="hidden absolute inset-0 flex-col items-center justify-center text-zinc-500 p-2 bg-zinc-800">
                          <Image className="w-8 h-8 mb-2" strokeWidth={1} />
                          <p className="text-xs text-center mb-2">Image unavailable</p>
                          <a 
                            href={proxyUrl || undefined} 
                            target="_blank" 
                            rel="noopener noreferrer"
                            className="text-xs text-blue-400 hover:text-blue-300 underline"
                          >
                            {localUrl ? 'Open saved image' : 'Open image'}
                          </a>
                        </div>
                      </div>
                      <CardContent className="p-2">
                        <a 
                          href={proxyUrl || undefined} 
                          target="_blank" 
                          rel="noopener noreferrer"
                          className="text-xs font-mono text-zinc-500 hover:text-zinc-300 truncate block" 
                          title={m.url}
                        >
                          {m.url?.split('/').pop() || m.media_type}
                        </a>
                      </CardContent>
                    </Card>
                  );
                })}
              </div>
              {product.media.some(m => m.media_type === 'image' && !m.stored_locally) &&
                <p className="mt-3 text-xs text-zinc-400">Some images are not saved yet. Run Media sync for this supplier to download them.</p>}
            </>
          ) : (
            <div className="flex flex-col items-center justify-center py-20 text-zinc-600">
              <Image className="w-12 h-12 mb-4 text-zinc-700" strokeWidth={1} />
              <p className="font-mono text-sm">NO MEDIA AVAILABLE</p>
              <p className="text-xs mt-1">Sync media from supplier to load product images</p>
            </div>
          )}
        </TabsContent>
      </Tabs>
    </div>
  );
}

function InfoRow({ label, value, mono }) {
  return (
    <div className="flex items-center justify-between py-1 border-b border-zinc-800/30 last:border-0">
      <span className="text-xs text-zinc-500">{label}</span>
      <span className={`text-sm text-zinc-200 ${mono ? "font-mono tabular-nums" : ""}`}>{value || "-"}</span>
    </div>
  );
}

