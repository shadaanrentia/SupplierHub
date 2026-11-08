import {categoryOptions,sortingSelection,sortingValue} from '../lib/dashboardCharts';
import {
  advancedDefaults,
  catalogueParams,
  readCatalogueFilters,
} from "../lib/catalogueFilters";
import React, { useEffect, useRef, useState } from "react";
import axios from "../lib/axios";
import { toast } from "sonner";
import {
  Package,
  Grid3X3,
  List,
  Download,
  MoreVertical,
} from "lucide-react";
import SearchField from "../components/SearchField";
import { ProductLink } from "../components/ProductDetails";
import { EmptyState, RefreshButton } from "../components/workbenchUi";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "../components/ui/dropdown-menu";
const BASE = (process.env.REACT_APP_BACKEND_URL || "").replace(/\/+$/, "");
const API = BASE + "/api";
function price(value, currency = "CAD") {
  if (value == null || value === "" || !Number.isFinite(Number(value)))
    return "—";
  try {
    return new Intl.NumberFormat("en-CA", {
      style: "currency",
      currency,
    }).format(Number(value));
  } catch {
    return String(value);
  }
}
function imageUrl(product) {
  const value = String(product.thumbnail || product.image || "").trim();
  if (!value) return "";
  if (value.startsWith("data:image/")) return value;
  if (/^https?:\/\//.test(value))
    return API + "/media_proxy?url=" + encodeURIComponent(value);
  return BASE + (value.startsWith("/") ? value : "/" + value);
}
function ProductImage({ product }) {
  const [failed, setFailed] = useState(false);
  const url = imageUrl(product);
  useEffect(() => setFailed(false), [url]);
  return url && !failed ? (
    <img
      src={url}
      alt={product.product_name || "Product"}
      loading="lazy"
      onError={() => setFailed(true)}
    />
  ) : (
    <div className="catalog-image-empty">
      <Package size={28} />
      <span>No image</span>
    </div>
  );
}
export default function Products() {
  const initial = useRef(readCatalogueFilters(window.location.search)).current;
  const [products, setProducts] = useState([]),
    [total, setTotal] = useState(0),
    [pages, setPages] = useState(1),
    [page, setPage] = useState(1),
    [loading, setLoading] = useState(true),
    [error, setError] = useState("");
  const [search, setSearch] = useState(initial.search),
    [supplier, setSupplier] = useState(initial.supplier),
    [category, setCategory] = useState(initial.category),
    [brand, setBrand] = useState(initial.brand);
  const [suppliers, setSuppliers] = useState([]),
    [categories, setCategories] = useState([]),
    [brands, setBrands] = useState([]),
    [filterError, setFilterError] = useState("");
  const [view, setView] = useState("grid"),
    [revision, setRevision] = useState(0),
    [exporting, setExporting] = useState(false),
    [syncing, setSyncing] = useState("");
  const exportLock = useRef(false);
  const [advanced, setAdvanced] = useState(initial.advanced),
    [sort, setSort] = useState(initial.sort),
    [facets, setFacets] = useState({ colours: [], sizes: [] });
  const canExport = suppliers.some((item) => item.id === supplier);
  const advancedCount = Object.values(advanced).filter(
    (value) => value !== "",
  ).length;
  useEffect(() => {
    const controller = new AbortController();
    axios
      .get(API + "/products/filter-options", {
        params: {
          supplier_id: supplier || undefined,
          category: category || undefined,
          brand: brand || undefined,
        },
        signal: controller.signal,
      })
      .then((r) => {
        if (!controller.signal.aborted) setFacets(r.data);
      })
      .catch(() => {
        if (!controller.signal.aborted)
          setFilterError("Some smart filter choices could not be loaded.");
      });
    return () => controller.abort();
  }, [supplier, category, brand]);
  useEffect(() => {
    const params = catalogueParams({
      search,
      supplier,
      category,
      brand,
      sort,
      advanced,
    });
    delete params.page;
    delete params.limit;
    if (params.sort === "newest") delete params.sort;
    const query = new URLSearchParams(params).toString();
    window.history.replaceState(
      null,
      "",
      window.location.pathname +
        (query ? "?" + query : "") +
        window.location.hash,
    );
  }, [search, supplier, category, brand, sort, advanced]);
  useEffect(() => {
    const controller = new AbortController();
    axios
      .get(API + "/suppliers", { signal: controller.signal })
      .then((r) =>
        setSuppliers(Array.isArray(r.data) ? r.data : r.data.suppliers || []),
      )
      .catch(() => {});
    return () => controller.abort();
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    setFilterError("");
    setCategories([]);
    axios
      .get(API + "/products/categories", {
        params: { supplier_id: supplier || undefined },
        signal: controller.signal,
      })
      .then((r) => setCategories(r.data.categories || []))
      .catch(() => {
        if (!controller.signal.aborted)
          setFilterError("Category filters could not be loaded.");
      });
    return () => controller.abort();
  }, [supplier]);
  useEffect(() => {
    const controller = new AbortController();
    setBrands([]);
    axios
      .get(API + "/products/brands", {
        params: {
          supplier_id: supplier || undefined,
          category: category || undefined,
        },
        signal: controller.signal,
      })
      .then((r) => setBrands(r.data.brands || []))
      .catch(() => {
        if (!controller.signal.aborted)
          setFilterError("Brand filters could not be loaded.");
      });
    return () => controller.abort();
  }, [supplier, category]);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError("");
    axios
      .get(API + "/products", {
        params: catalogueParams({
          page,
          search,
          supplier,
          category,
          brand,
          sort,
          advanced,
        }),
        signal: controller.signal,
      })
      .then((r) => {
        if(controller.signal.aborted)return;
        setProducts(r.data.products || []);
        setTotal(r.data.total || 0);
        setPages(Math.max(1, r.data.pages || 1));
      })
      .catch((e) => {
        if (!controller.signal.aborted)
          setError(
            typeof e.response?.data?.detail === "string"
              ? e.response.data.detail
              : "Products could not be loaded.",
          );
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [page, supplier, category, brand, search, sort, advanced, revision]);
  const refresh = () => setRevision((n) => n + 1);
  const filters = !!(
    supplier ||
    category ||
    brand ||
    search ||
    advancedCount ||
    sort !== "newest"
  );
  const change = (setter) => (event) => {
    setter(event.target.value);
    setPage(1);
  };
  const clear = () => {
    setSearch("");
    setSupplier("");
    setCategory("");
    setBrand("");
    setAdvanced({ ...advancedDefaults });
    setSort("newest");
    setPage(1);
  };
  async function sync(id, kind) {
    if (syncing) return;
    setSyncing(id + kind);
    try {
      const r = await axios.post(
        `${API}/sync/product/${encodeURIComponent(id)}/${kind}`,
      );
      if (r.data.success === false)
        throw new Error(r.data.message || "Sync failed");
      toast.success(r.data.message || "Supplier data refreshed");
      refresh();
    } catch (e) {
      toast.error(
        typeof e.response?.data?.detail === "string"
          ? e.response.data.detail
          : e.message || "Supplier sync failed",
      );
    } finally {
      setSyncing("");
    }
  }
  async function download() {
    if (!canExport || exportLock.current) return;
    exportLock.current = true;
    setExporting(true);
    try {
      const r = await axios.get(API + "/products/export.xlsx", {
        params: { supplier_id: supplier },
        responseType: "blob",
        timeout: 300000,
      });
      const url = URL.createObjectURL(r.data),
        link = document.createElement("a");
      link.href = url;
      link.download =
        (
          suppliers.find((s) => s.id === supplier)?.supplier_name || "supplier"
        ).replace(/[^a-z0-9_-]+/gi, "_") + "-products.xlsx";
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 10000);
    } catch {
      toast.error("Supplier list could not be exported");
    } finally {
      exportLock.current = false;
      setExporting(false);
    }
  }
  function actions(product) {
    return (
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <button
            type="button"
            className="wb-icon-button"
            aria-label={`Actions for ${product.supplier_sku}`}
          >
            <MoreVertical size={16} />
          </button>
        </DropdownMenuTrigger>
        <DropdownMenuContent
          className="bg-zinc-900 border-zinc-700 text-zinc-100"
          align="end"
        >
          {["pricing", "inventory", "media"].map((kind) => (
            <DropdownMenuItem
              key={kind}
              disabled={!!syncing}
              onSelect={() => sync(product.id, kind)}
            >
              Refresh supplier {kind}
            </DropdownMenuItem>
          ))}
        </DropdownMenuContent>
      </DropdownMenu>
    );
  }
  return (
    <section className="wb-page catalog-page">
      <header className="wb-page-header">
        <div>
          <h1>Products</h1>
          <p>
            {loading
              ? "Loading catalogue…"
              : `${total.toLocaleString()} products${filters ? " · filtered" : " in database"}`}
          </p>
        </div>
        <div className="wb-row-actions">
          <RefreshButton onClick={refresh} disabled={loading} />
        </div>
      </header>
      <div className="catalog-filters">
        <SearchField
          aria-label="Search products"
          placeholder="Search product name or SKU"
          value={search}
          onChange={change(setSearch)}
        />
        <select
          className="wb-control"
          aria-label="Products supplier"
          value={supplier}
          onChange={(e) => {
            setSupplier(e.target.value);
            setCategory("");
            setBrand("");
            setPage(1);
          }}
        >
          <option value="">All suppliers</option>
          {facets.unassigned_supplier && (
            <option value="__unassigned__">Unassigned supplier</option>
          )}
          {suppliers.map((s) => (
            <option key={s.id} value={s.id}>
              {s.supplier_name}
            </option>
          ))}
        </select>
        <select
          className="wb-control"
          aria-label="Products category"
          value={category}
          onChange={(e) => {
            setCategory(e.target.value);
            setBrand("");
            setPage(1);
          }}
        >
          <option value="">All categories</option>
          {categoryOptions(categories).map(option=><option key={option.value} value={option.value}>{option.label}</option>)}
        </select>
        <select
          className="wb-control"
          aria-label="Products brand"
          value={brand}
          onChange={change(setBrand)}
        >
          <option value="">All brands</option>
          {[...new Set([...brands, "Unbranded"])].map((b) => (
            <option
              key={b}
              value={b.toLowerCase() === "unbranded" ? "__unbranded__" : b}
            >
              {b}
            </option>
          ))}
        </select>
        {filters && (
          <button className="wb-text-link" onClick={clear}>
            Clear filters
          </button>
        )}
      </div>
      {advancedCount > 0 && (
        <div className="catalog-filter-chips">
          {Object.entries(advanced)
            .filter(([key, value]) => value !== "" && key!=="colour")
            .map(([key, value]) => (
              <button
                key={key}
                onClick={() => {
                  setAdvanced((old) => ({ ...old, [key]: "" }));
                  setPage(1);
                }}
                aria-label={`Remove ${key.replace(/_/g, " ")} filter`}
              >
                {key.replace(/_/g, " ")}: {String(value).replace(/_/g, " ")} ×
              </button>
            ))}
        </div>
      )}
      {filterError && (
        <p className="wb-muted" role="status">
          {filterError}
        </p>
      )}
      <div className="wb-toolbar">
        <div className="wb-toolbar-left">
          <button
            className="wb-button"
            disabled={!canExport || exporting}
            title={
              !canExport
                ? "Choose a supplier to export its complete catalogue"
                : undefined
            }
            onClick={download}
          >
            <Download size={14} />
            {exporting ? "Exporting…" : "Export list"}
          </button>
        </div>
        <div className="wb-toolbar-right">
          <select className="wb-control catalog-colour-control" aria-label="Colour filter" value={advanced.colour} onChange={e=>{setAdvanced(old=>({...old,colour:e.target.value}));setPage(1);}}><option value="">All colours</option>{[...new Set([...(facets.colours||[]),advanced.colour].filter(Boolean))].map(colour=><option key={colour}>{colour}</option>)}</select>
          <div className="catalog-sort-controls"><label>Sort by<select className="wb-control" aria-label="Sort field" value={sortingSelection(sort).field} onChange={e=>{setSort(sortingValue(e.target.value,sortingSelection(sort).direction));setPage(1);}}>{[['product','Product'],['brand','Brand'],['inventory','Inventory'],['price','Price'],['added','Date added'],['updated','Last updated'],['variants','Variants']].map(([value,label])=><option key={value} value={value}>{label}</option>)}</select></label><label>Order<select className="wb-control" aria-label="Sort direction" value={sortingSelection(sort).direction} onChange={e=>{setSort(sortingValue(sortingSelection(sort).field,e.target.value));setPage(1);}}><option value="asc">Ascending ↑</option><option value="desc">Descending ↓</option></select></label></div>
          <div className="wb-segment" aria-label="Product view">
            <button
              aria-label="Grid view"
              aria-pressed={view === "grid"}
              className={view === "grid" ? "is-selected" : ""}
              onClick={() => setView("grid")}
            >
              <Grid3X3 size={16} />
            </button>
            <button
              aria-label="List view"
              aria-pressed={view === "list"}
              className={view === "list" ? "is-selected" : ""}
              onClick={() => setView("list")}
            >
              <List size={16} />
            </button>
          </div>
        </div>
      </div>
      {error ? (
        <div className="wb-alert wb-alert--danger" role="alert">
          {error}
          <button className="wb-button" onClick={refresh}>
            Retry
          </button>
        </div>
      ) : loading ? (
        <div className="wb-loading">Loading products…</div>
      ) : !products.length ? (
        <EmptyState
          title={filters ? "No matching products" : "No products saved yet"}
          action={
            filters ? (
              <button className="wb-button" onClick={clear}>
                Clear filters
              </button>
            ) : undefined
          }
        />
      ) : view === "grid" ? (
        <div className="catalog-grid">
          {products.map((product) => (
            <article className="catalog-card" key={product.id}>
              <div className="catalog-card-image">
                <ProductLink
                  productId={product.id}
                  aria-label={`View ${product.product_name}`}
                >
                  <ProductImage product={product} />
                </ProductLink>
              </div>
              <div className="catalog-card-content">
                <div className="catalog-card-title">
                  <ProductLink productId={product.id}>
                    {product.product_name || product.supplier_sku}
                  </ProductLink>
                  {actions(product)}
                </div>
                <p className="catalog-sku">{product.supplier_sku}</p>
                <dl>
                  <div>
                    <dt>Brand</dt>
                    <dd>{String(product.brand||" ").trim() || "—"}</dd>
                  </div>
                  <div>
                    <dt>Category</dt>
                    <dd>{String(product.category||" ").trim() || "Uncategorized"}</dd>
                  </div>
                  <div><dt>Inventory</dt><dd title="Saved variant inventory total">{product.inventory_total==null?'—':Number(product.inventory_total).toLocaleString()}</dd></div>
                  <div>
                    <dt>Supplier</dt>
                    <dd>{product.supplier_name || "—"}</dd>
                  </div>
                </dl>
                <footer>
                  <span>
                    {product.variant_count ?? 0} variants ·{" "}
                    {product.media_count ?? 0} images
                  </span>
                  <strong>
                    {price(product.base_price, product.currency || "CAD")}
                  </strong>
                </footer>
              </div>
            </article>
          ))}
        </div>
      ) : (
        <div className="wb-table-wrap">
          <table className="wb-table">
            <thead>
              <tr>
                <th>Product</th>
                <th>Brand</th>
                <th>Category</th>
                <th>Supplier</th>
                <th>Variants</th>
                <th>Inventory</th><th>Supplier price</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {products.map((product) => (
                <tr key={product.id}>
                  <td>
                    <ProductLink productId={product.id}>
                      {product.product_name}
                    </ProductLink>
                    <small>{product.supplier_sku}</small>
                  </td>
                  <td>{String(product.brand||" ").trim() || "—"}</td>
                  <td>{String(product.category||" ").trim() || "Uncategorized"}</td>
                  <td>{product.supplier_name || "—"}</td>
                  <td>{product.variant_count ?? 0}</td>
                  <td>{product.inventory_total==null?'—':Number(product.inventory_total).toLocaleString()}</td><td>
                    {price(product.base_price, product.currency || "CAD")}
                  </td>
                  <td>{actions(product)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <div className="wb-pagination">
        <span>{loading ? "" : `${total.toLocaleString()} products`}</span>
        <div>
          <button
            className="wb-button"
            disabled={loading || page <= 1}
            onClick={() => setPage((n) => n - 1)}
          >
            Previous
          </button>
          <span>
            {page} / {pages}
          </span>
          <button
            className="wb-button"
            disabled={loading || page >= pages}
            onClick={() => setPage((n) => n + 1)}
          >
            Next
          </button>
        </div>
      </div>
    </section>
  );
}
