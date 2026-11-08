import DashboardCharts from '../components/DashboardCharts';
import React, { useEffect, useState } from "react";
import axios from "../lib/axios";
import {
  Package,
  Layers,
  Truck,
  Tags,
  FolderTree,
  ArrowUpRight,
  History,
  RefreshCw,
} from "lucide-react";
import { ProductLink } from "../components/ProductDetails";
import { EmptyState, RefreshButton } from "../components/workbenchUi";
import { dateLabel } from "../lib/productPresentation";
const API =
  (process.env.REACT_APP_BACKEND_URL || "").replace(/\/+$/, "") + "/api";
const url = (params) => "/products?" + new URLSearchParams(params);
const fmt = (value) => Number(value || 0).toLocaleString();
export default function Dashboard() {
  const [data, setData] = useState(null),
    [error, setError] = useState(""),
    [loading, setLoading] = useState(true),
    [revision, setRevision] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError("");
    axios
      .get(API + "/dashboard/stats", { signal: controller.signal })
      .then((r) => {
        if (!controller.signal.aborted) setData(r.data);
      })
      .catch(() => {
        if (!controller.signal.aborted)
          setError("The catalogue overview could not be loaded.");
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [revision]);
  const cards = [
    ["total_products", "Products", Package, "/products"],
    ["total_variants", "Variants", Layers, "/products"],
    ["total_suppliers", "Suppliers", Truck, "/suppliers"],
    ["total_categories", "Categories", FolderTree, "/products"],
    ["total_brands", "Brands", Tags, "/products"],
  ];
  const coverage = [
    ["categorized", "Category assigned", { category: "__uncategorized__" }],
    ["branded", "Brand recorded", { brand: "__unbranded__" }],
    ["with_images", "Source images", { images: "without" }],
    ["priced", "Supplier price", { pricing: "missing" }],
  ];
  return (
    <div className="wb-page overview-page overview-page--graphs">
      <header className="wb-page-header">
        <div>
          <h1>Dashboard</h1>
          <p>
            Catalogue overview
            {data?.as_of ? ` · Updated ${dateLabel(data.as_of)}` : ""}
          </p>
        </div>
        <RefreshButton
          disabled={loading}
          onClick={() => setRevision((n) => n + 1)}
        />
      </header>
      {error && (
        <div className="wb-alert wb-alert--danger" role="alert">
          {error}
          <button
            className="wb-button"
            onClick={() => setRevision((n) => n + 1)}
          >
            Retry
          </button>
        </div>
      )}
      {!data && loading ? (
        <div className="wb-loading">Loading catalogue overview…</div>
      ) : (
        data && (
          <>
            <div className="overview-kpis">
              {cards.map(([key, label, Icon, link]) => (
                <a key={key} href={link}>
                  <Icon size={18} />
                  <strong>{fmt(data[key])}</strong>
                  <span>{label}</span>
                </a>
              ))}
            </div>
            <div className="overview-actions">
              <a className="wb-button wb-button--primary" href="/products">
                <Package size={15} />
                Browse catalogue
              </a>
              <a className="wb-button" href="/sync">
                <RefreshCw size={15} />
                Import supplier data
              </a>
              <a className="wb-button" href="/suppliers">
                <Truck size={15} />
                Manage suppliers
              </a>
              <a className="wb-button" href="/sync-history">
                <History size={15} />
                Sync history
              </a>
            </div>
            <DashboardCharts data={data}/>
<section className="overview-panel">
              <header>
                <h2>Supplier catalogues</h2>
                <a href="/suppliers" className="wb-text-link">
                  Manage
                  <ArrowUpRight size={13} />
                </a>
              </header>
              {data.supplier_catalogues?.length ? (
                <div className="wb-table-wrap">
                  <table className="wb-table">
                    <thead>
                      <tr>
                        <th>Supplier</th>
                        <th>Products</th>
                        <th>Variants</th>
                        <th>Last supplier sync</th>
                        <th />
                      </tr>
                    </thead>
                    <tbody>
                      {data.supplier_catalogues.map((row) => (
                        <tr key={row.supplier_id}>
                          <td>
                            <strong>{row.supplier_name}</strong>
                          </td>
                          <td>{fmt(row.products)}</td>
                          <td>{fmt(row.variants)}</td>
                          <td>{dateLabel(row.last_sync)}</td>
                          <td>
                            <a
                              className="wb-button"
                              href={url({ supplier_id: row.supplier_id })}
                            >
                              View catalogue
                              <ArrowUpRight size={13} />
                            </a>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <EmptyState
                  title="Connect a supplier to start importing"
                  action={
                    <a className="wb-button" href="/suppliers">
                      Add supplier
                    </a>
                  }
                />
              )}
            </section>
            <div className="overview-middle">
              <section className="overview-panel">
                <header>
                  <h2>Catalogue coverage</h2>
                  <span>Saved product data</span>
                </header>
                <div className="overview-coverage">
                  {coverage.map(([key, label, params]) => {
                    const count = Number(data[key] || 0),
                      total = Number(data.total_products || 0);
                    return (
                      <div key={key}>
                        <div>
                          <span>{label}</span>
                          <strong>
                            {total
                              ? Math.round((count / total) * 100) + "%"
                              : "—"}
                          </strong>
                        </div>
                        <div className="overview-track">
                          <span
                            style={{
                              width: `${total ? (count / total) * 100 : 0}%`,
                            }}
                          />
                        </div>
                        <footer>
                          <span>
                            {fmt(count)} / {fmt(total)} products
                          </span>
                          {total > count && (
                            <a className="wb-text-link" href={url(params)}>
                              Browse missing
                              <ArrowUpRight size={11} />
                            </a>
                          )}
                        </footer>
                      </div>
                    );
                  })}
                </div>
              </section>
              <section className="overview-panel">
                <header>
                  <h2>Recently added</h2>
                  <a className="wb-text-link" href={url({ sort: "newest" })}>
                    View all
                    <ArrowUpRight size={13} />
                  </a>
                </header>
                {data.recent_products?.length ? (
                  <div className="overview-recent">
                    {data.recent_products.map((row) => (
                      <article key={row.id}>
                        <Package size={17} />
                        <div>
                          <ProductLink productId={row.id}>
                            {row.product_name || row.supplier_sku}
                          </ProductLink>
                          <p>
                            {row.supplier_sku} ·{" "}
                            {row.supplier_name || "Unassigned supplier"}
                          </p>
                        </div>
                        <time>{dateLabel(row.created_at)}</time>
                      </article>
                    ))}
                  </div>
                ) : (
                  <EmptyState title="Imported products will appear here" />
                )}
              </section>
            </div>
            </>
        )
      )}
    </div>
  );
}
