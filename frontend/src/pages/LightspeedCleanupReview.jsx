import React, { useCallback, useState } from "react";
import axios from "../lib/axios";
import SearchField from "../components/SearchField";
import { ProductLink } from "../components/ProductDetails";

const API = (process.env.REACT_APP_BACKEND_URL || "").replace(/\/+$/, "") + "/api";

export default function LightspeedCleanupReview() {
  const [search,setSearch] = useState("");
  const [data,setData] = useState(null);
  const [loading,setLoading] = useState(false);
  const [error,setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true); setError("");
    try {
      const response = await axios.get(API + "/export-review/cleanup-preview", {params:{search,page:1}});
      setData(response.data);
    } catch (e) {
      setError(typeof e.response?.data?.detail === "string" ? e.response.data.detail : "Could not load the read-only cleanup preview.");
    } finally { setLoading(false); }
  },[search]);

  return (
    <main className="p-6 space-y-5">
      <header>
        <h1 className="text-2xl font-bold text-zinc-100">Lightspeed Variant Cleanup Review</h1>
        <p className="mt-1 text-sm text-zinc-400">Read-only report of variants already in Lightspeed that no longer meet supplier price and inventory eligibility.</p>
      </header>
      <div className="rounded-lg border border-amber-800/60 bg-amber-950/20 p-4 text-sm text-amber-200">
        Preview only. This page does not delete, disable, or modify any Lightspeed variant.
      </div>
      <div className="flex flex-wrap gap-3">
        <SearchField aria-label="Search cleanup candidates" placeholder="Search product name or supplier SKU" value={search} onChange={e=>setSearch(e.target.value)} />
        <button className="wb-button" disabled={loading} onClick={load}>{loading ? "Checking…" : "Generate preview"}</button>
      </div>
      {error && <div role="alert" className="wb-alert wb-alert--danger">{error}</div>}
      {data && (
        <section className="space-y-4">
          <div className="text-sm text-zinc-400">{data.matched_products} products with candidates or lookup errors · {data.total_products_checked} products checked</div>
          {!data.products.length && <p className="text-sm text-zinc-400">No ineligible remote variants found for this page.</p>}
          {data.products.map(product=>(
            <article key={product.product_id} className="rounded-lg border border-zinc-800 bg-zinc-900/40 p-4 space-y-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div><ProductLink productId={product.product_id}>{product.product_name || product.supplier_sku}</ProductLink><p className="text-xs text-zinc-500">{product.supplier_name} · {product.supplier_sku}</p></div>
                <span className="text-xs text-zinc-400">{product.candidates.length} candidates</span>
              </div>
              {product.candidates.length>0 && <div className="overflow-x-auto"><table className="wb-table"><thead><tr><th>Variant SKU</th><th>Lightspeed variant ID</th><th>Reason</th><th>Destination family</th></tr></thead><tbody>{product.candidates.map((item,i)=><tr key={item.lightspeed_variant_id || i}><td>{item.variant_sku}</td><td className="wb-mono">{item.lightspeed_variant_id}</td><td>{item.reason.replaceAll("_"," ")}</td><td className="wb-mono">{item.destination_id}</td></tr>)}</tbody></table></div>}
              {product.errors.map((item,i)=><p key={i} className="text-xs text-amber-300">Could not inspect {item.destination_id}: {item.message}</p>)}
            </article>
          ))}
        </section>
      )}
    </main>
  );
}
