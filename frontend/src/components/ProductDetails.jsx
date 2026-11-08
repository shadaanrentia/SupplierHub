import React, { createContext, useContext, useEffect, useState } from "react";
import axios from "../lib/axios";
import {
  Package,
  Images,
  Ruler,
  History,
  Layers,
  ExternalLink,
  ChevronLeft,
  ChevronRight,
  Info,
} from "lucide-react";
import SearchField from "./SearchField";
import ProductHistory from "./ProductHistory";
import {
  DialogFrame,
  StatusPill,
  EmptyState,
  RefreshButton,
} from "./workbenchUi";
import {
  money,
  safeNumber,
  descriptionBlocks,
  groupImages,
  measurementGroups,
  availableOptions,
} from "../lib/productPresentation";
import { CategoryPolicyEditor } from "../pages/CategoryPolicyEditor";
const API =
  (process.env.REACT_APP_BACKEND_URL || "").replace(/\/+$/, "") + "/api";
const Context = createContext(null);
export const useProductDetails = () => useContext(Context);
export function ProductLink({ productId, children, className = "", ...props }) {
  const show = useProductDetails();
  if (!productId) return <span className={className}>{children}</span>;
  return (
    <a
      {...props}
      className={`wb-product-link ${className}`}
      href={`/products/${encodeURIComponent(productId)}`}
      onClick={(e) => {
        if (show && !e.ctrlKey && !e.metaKey && !e.shiftKey && e.button === 0) {
          e.preventDefault();
          e.stopPropagation();
          show(productId);
        }
      }}
    >
      {children}
    </a>
  );
}
export function ProductDetailsProvider({ children }) {
  const [id, setId] = useState("");
  return (
    <Context.Provider value={setId}>
      {children}
      <DialogFrame
        open={!!id}
        onClose={() => setId("")}
        title="Product details"
        wide
        level={200}
      >
        {id && <ProductDetails productId={id} />}
      </DialogFrame>
    </Context.Provider>
  );
}
function sourceUrl(item) {
  return item.local_url
    ? API.replace(/\/api$/, "") + item.local_url
    : item.url
      ? `${API}/media_proxy?url=${encodeURIComponent(item.url)}`
      : "";
}
function ProductImages({ media, variants }) {
  const groups = groupImages(media, variants),
    [colour, setColour] = useState(""),
    [selected, setSelected] = useState(null);
  const all = groups.flatMap((group) =>
    group.images.map((item) => ({ ...item, colour: group.colour })),
  );
  const shown = colour
    ? groups.filter((group) => group.colour === colour)
    : groups;
  const index = selected
    ? all.findIndex(
        (item) => (item.id || item.url) === (selected.id || selected.url),
      )
    : -1;
  return (
    <>
      <div className="wb-toolbar">
        <span className="wb-muted">
          {all.length} images · {groups.length} colours
        </span>
        {groups.length > 1 && (
          <select
            className="wb-control"
            aria-label="Image colour"
            value={colour}
            onChange={(e) => setColour(e.target.value)}
          >
            <option value="">All colours</option>
            {groups.map((group) => (
              <option key={group.colour}>{group.colour}</option>
            ))}
          </select>
        )}
      </div>
      {!all.length ? (
        <EmptyState title="No product images" />
      ) : (
        shown.map((group) => (
          <section className="wb-image-group" key={group.colour}>
            <h3>
              {group.colour}
              <span>{group.images.length}</span>
            </h3>
            <div className="wb-image-grid">
              {group.images.map((item, i) => (
                <button
                  key={item.id || item.url}
                  className="wb-image-card"
                  aria-label={`Open ${group.colour} image ${i + 1}`}
                  onClick={() => setSelected({ ...item, colour: group.colour })}
                >
                  <img
                    src={sourceUrl(item)}
                    alt={`${group.colour} · ${i + 1}`}
                    loading="lazy"
                    onError={(e) => {
                      e.currentTarget.style.opacity = ".2";
                      e.currentTarget.alt = "Image unavailable";
                    }}
                  />
                  <span>
                    {group.colour}
                    <small>
                      {i + 1} / {group.images.length}
                    </small>
                  </span>
                </button>
              ))}
            </div>
          </section>
        ))
      )}
      <DialogFrame
        open={!!selected}
        onClose={() => setSelected(null)}
        title={selected?.colour || "Product image"}
        level={220}
        footer={
          <div className="wb-lightbox-nav">
            <button
              className="wb-icon-button"
              aria-label="Previous image"
              disabled={index <= 0}
              onClick={() => setSelected(all[index - 1])}
            >
              <ChevronLeft size={18} />
            </button>
            <span>
              {index + 1} / {all.length}
            </span>
            <button
              className="wb-icon-button"
              aria-label="Next image"
              disabled={index >= all.length - 1}
              onClick={() => setSelected(all[index + 1])}
            >
              <ChevronRight size={18} />
            </button>
          </div>
        }
      >
        {selected && (
          <img
            className="wb-lightbox"
            src={sourceUrl(selected)}
            alt={selected.colour}
          />
        )}
      </DialogFrame>
    </>
  );
}
function Variants({ rows }) {
  const [search, setSearch] = useState(""),
    [colour, setColour] = useState(""),
    [page, setPage] = useState(1);
  const colours = [...new Set(rows.map((v) => v.color).filter(Boolean))];
  const filtered = rows.filter(
    (v) =>
      (!colour || v.color === colour) &&
      [v.variant_sku, v.color, v.size].some((value) =>
        String(value || "")
          .toLowerCase()
          .includes(search.toLowerCase()),
      ),
  );
  const shown = filtered.slice((page - 1) * 25, page * 25);
  return (
    <>
      <div className="wb-toolbar">
        <SearchField
          aria-label="Search variants"
          placeholder="Search SKU, colour or size"
          value={search}
          onChange={(e) => {
            setSearch(e.target.value);
            setPage(1);
          }}
        />
        <div className="wb-toolbar-right">
          <select
            className="wb-control"
            aria-label="Variant colour"
            value={colour}
            onChange={(e) => {
              setColour(e.target.value);
              setPage(1);
            }}
          >
            <option value="">All colours</option>
            {colours.map((value) => (
              <option key={value}>{value}</option>
            ))}
          </select>
          <span className="wb-muted">{filtered.length} variants</span>
        </div>
      </div>
      <div className="wb-table-wrap">
        <table className="wb-table">
          <thead>
            <tr>
              {[
                "SKU",
                "Colour",
                "Size",
                "Supplier price",
                "Retail price",
                "Stock · Mississauga",
              ].map((label) => (
                <th key={label}>{label}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {shown.map((v, i) => (
              <tr key={v.id || i}>
                <td className="wb-mono">{v.variant_sku}</td>
                <td>{v.color || "—"}</td>
                <td>{v.size || "—"}</td>
                <td>{money(v.price)}</td>
                <td className="wb-retail">{money(v.computed_retail)}</td>
                <td>{v.inventory ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {!filtered.length && <EmptyState title="No matching variants" />}
      </div>
      <div className="wb-pagination">
        <span>{filtered.length} variants</span>
        <div>
          <button
            className="wb-button"
            disabled={page <= 1}
            onClick={() => setPage((n) => n - 1)}
          >
            Previous
          </button>
          <span>
            {page} / {Math.max(1, Math.ceil(filtered.length / 25))}
          </span>
          <button
            className="wb-button"
            disabled={page * 25 >= filtered.length}
            onClick={() => setPage((n) => n + 1)}
          >
            Next
          </button>
        </div>
      </div>
    </>
  );
}
function Measurements({ product, onSaved }) {
  const [editing, setEditing] = useState(false);
  const groups = measurementGroups(product.variants);
  const defaults = product.category_shipping || {};
  let admin = false;
  try {
    admin = JSON.parse(localStorage.getItem("user") || "{}").role === "admin";
  } catch {}
  const category = {
    supplier_id: product.supplier_id,
    category_id: product.readiness?.mapped_lightspeed_category_id,
    category_name: product.lightspeed_category_name || product.category,
    mode: product.category_pricing_mode || "global",
    value: product.category_pricing_value,
    ...defaults,
  };
  return (
    <>
      <div className="wb-toolbar">
        <h3 className="wb-section-title">Shipping measurements</h3>
        {admin &&
          category.category_id &&
          product.readiness?.category_available !== false && (
            <button className="wb-button" onClick={() => setEditing(true)}>
              Edit category defaults
            </button>
          )}
      </div>
      <div className="wb-measure-summary">
        <div>
          <span>Category</span>
          <strong>
            {product.lightspeed_category_name ||
              product.category ||
              "Not mapped"}
          </strong>
        </div>
        <div>
          <span>Default weight</span>
          <strong>
            {defaults.weight_lb != null ? `${defaults.weight_lb} lb` : "—"}
          </strong>
        </div>
        <div>
          <span>Default dimensions</span>
          <strong>
            {[defaults.length_in, defaults.width_in, defaults.height_in].every(
              (v) => v != null,
            )
              ? `${defaults.length_in} × ${defaults.width_in} × ${defaults.height_in} in`
              : "—"}
          </strong>
        </div>
      </div>
      <div className="wb-table-wrap">
        <table className="wb-table">
          <thead>
            <tr>
              <th>Applies to</th>
              <th>Variants</th>
              <th>Weight (lb)</th>
              <th>Dimensions (in)</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {groups.map((g, i) => (
              <tr key={i}>
                <td>
                  {g.count === product.variants.length
                    ? "All variants"
                    : g.sizes.join(", ") || "Variants"}
                  <small>
                    {g.colours.length <= 3
                      ? g.colours.join(", ")
                      : `${g.colours.length} colours`}
                  </small>
                </td>
                <td>{g.count}</td>
                <td>{g.weight ?? "—"}</td>
                <td>
                  {g.dims.every((v) => v !== null) ? g.dims.join(" × ") : "—"}
                </td>
                <td>
                  <StatusPill
                    value={
                      g.error ||
                      g.weight === null ||
                      g.dims.some((v) => v === null)
                        ? "needs_review"
                        : "ready"
                    }
                    label={
                      g.error
                        ? "Needs review"
                        : g.weight === null || g.dims.some((v) => v === null)
                          ? "Missing values"
                          : "Complete"
                    }
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {!groups.length && <EmptyState title="No variants to measure" />}
      <CategoryPolicyEditor
        category={editing ? category : null}
        onClose={() => setEditing(false)}
        onSaved={onSaved}
      />
    </>
  );
}
export default function ProductDetails({ productId }) {
  const [product, setProduct] = useState(null),
    [error, setError] = useState(""),
    [tab, setTab] = useState("overview"),
    [revision, setRevision] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setProduct(null);
    setError("");
    axios
      .get(`${API}/products/${encodeURIComponent(productId)}/workbench`, {
        signal: controller.signal,
      })
      .then((r) => setProduct(r.data))
      .catch((e) => {
        if (!controller.signal.aborted)
          setError(
            typeof e.response?.data?.detail === "string"
              ? e.response.data.detail
              : "Product could not be loaded.",
          );
      });
    return () => controller.abort();
  }, [productId, revision]);
  useEffect(() => setTab("overview"), [productId]);
  const refresh = () => setRevision((n) => n + 1);
  if (error)
    return (
      <div className="wb-product">
        <div role="alert" className="wb-alert wb-alert--danger">
          {error}
          <button className="wb-button" onClick={refresh}>
            Retry
          </button>
        </div>
      </div>
    );
  if (!product) return <div className="wb-loading">Loading product…</div>;
  const variants = product.variants || [],
    stock =
      variants.length && variants.every((v) => safeNumber(v.inventory) !== null)
        ? variants.reduce((sum, v) => sum + Number(v.inventory), 0)
        : null;
  const images = groupImages(product.media, variants).flatMap((g) => g.images);
  const blocks = descriptionBlocks(product.description);
  const options=availableOptions(variants);
  const details = [
    ["Supplier", product.supplier_name],
    ["Brand", product.brand],
    ["Supplier category", product.category],
    [
      "Lightspeed category",
      product.lightspeed_category_name || "Needs mapping",
    ],
  ];
  const errors = product.readiness?.validation_errors || [];
  return (
    <div className="wb-product">
      <div className="wb-product-head">
        <div className="wb-product-title">
          <div>
            <h1>{product.product_name}</h1>
            <p>
              {product.supplier_sku}
              <span>·</span>
              {product.brand || product.supplier_name}
            </p>
          </div>
          <div className="wb-head-actions">
            <StatusPill
              value={
                product.lightspeed_sync_status || product.readiness?.status
              }
            />
            <RefreshButton onClick={refresh} />
          </div>
        </div>
        <nav className="wb-tabs" aria-label="Product sections">
          {[
            ["overview", "Overview", Package],
            ["variants", "Variants", Layers],
            ["images", "Images", Images],
            ["measurements", "Measurements", Ruler],
            ["history", "History", History],
          ].map(([value, label, Icon]) => (
            <button
              key={value}
              aria-selected={tab === value}
              onClick={() => setTab(value)}
              className={tab === value ? "is-active" : ""}
            >
              <Icon size={15} />
              {label}
              {value === "variants" && <span>{variants.length}</span>}
              {value === "images" && <span>{images.length}</span>}
            </button>
          ))}
        </nav>
      </div>
      <div className="wb-product-content">
        {tab === "overview" && (
          <>
            <div className="wb-product-overview">
              <div className="wb-cover">
                {images.length ? (
                  <img src={sourceUrl(images[0])} alt={product.product_name} />
                ) : (
                  <Package size={44} />
                )}
              </div>
              <div className="wb-overview-main">
                <div className="wb-price-strip">
                  <div>
                    <span>Supplier price</span>
                    <strong>{money(product.base_price)}</strong>
                  </div>
                  <div>
                    <span>Retail price</span>
                    <strong className="wb-retail">
                      {money(product.computed_base_retail)}
                    </strong>
                  </div>
                  <div>
                    <span>Mississauga stock</span>
                    <strong>{stock ?? "—"}</strong>
                  </div>
                </div>
                <dl className="wb-info-grid">
                  {details.map(([label, value]) => (
                    <div key={label}>
                      <dt>{label}</dt>
                      <dd>{value || "—"}</dd>
                    </div>
                  ))}
                </dl>
              </div>
            </div>
            <section className="product-options" aria-label="Available product options">
              {[['Available colours',options.colours],['Available sizes',options.sizes]].map(([label,values])=><div key={label}><h3>{label}<span>{values.length}</span></h3>{values.length?<div className="product-option-chips">{values.map(value=><span key={value}>{value}</span>)}</div>:<p className="wb-muted">Not provided</p>}</div>)}
            </section>
            <section className="wb-description">
              <h3>Product description</h3>
              {blocks.length ? (
                <>
                  {blocks.slice(0, 4).map((text, i) => (
                    <p key={i}>{text}</p>
                  ))}
                  {blocks.length > 4 && (
                    <details>
                      <summary>Read more</summary>
                      {blocks.slice(4).map((text, i) => (
                        <p key={i}>{text}</p>
                      ))}
                    </details>
                  )}
                </>
              ) : (
                <p className="wb-muted">No description available.</p>
              )}
            </section>
            {errors.length > 0 && (
              <details className="wb-alert">
                <summary>
                  <Info size={15} />
                  {errors.length === 1
                    ? "1 item needs attention"
                    : `${errors.length} items need attention`}
                </summary>
                <ul>
                  {errors.map((message, i) => (
                    <li key={i}>{message}</li>
                  ))}
                </ul>
                <a className="wb-text-link" href="/category-mapping">
                  Review category mapping <ExternalLink size={12} />
                </a>
              </details>
            )}
          </>
        )}
        {tab === "variants" && <Variants rows={variants} />}{" "}
        {tab === "images" && (
          <ProductImages media={product.media} variants={variants} />
        )}{" "}
        {tab === "measurements" && (
          <Measurements product={product} onSaved={refresh} />
        )}{" "}
        {tab === "history" && <ProductHistory productId={productId} />}
      </div>
    </div>
  );
}
