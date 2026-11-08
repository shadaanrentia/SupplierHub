import React, { useCallback, useEffect, useRef, useState } from "react";
import axios from "../lib/axios";
import { toast } from "sonner";
import { ArrowUpRight, Ruler } from "lucide-react";
import SearchField from "../components/SearchField";
import {
  DialogFrame,
  EmptyState,
  RefreshButton,
  StatusPill,
} from "../components/workbenchUi";
const API =
  (process.env.REACT_APP_BACKEND_URL || "").replace(/\/+$/, "") + "/api";
const fields = [
  ["weight_lb", "Weight", "lb"],
  ["length_in", "Length", "in"],
  ["width_in", "Width", "in"],
  ["height_in", "Height", "in"],
];
const message = (e) =>
  typeof e.response?.data?.detail === "string"
    ? e.response.data.detail
    : "Category defaults could not be saved.";
function admin() {
  try {
    return JSON.parse(localStorage.getItem("user") || "{}").role === "admin";
  } catch {
    return false;
  }
}
export function shippingLabel(rule) {
  return rule?.measurements_configured
    ? "Complete"
    : fields.some(([key]) => rule?.[key] != null)
      ? "Partial"
      : "Not set";
}
export function CategoryPolicyEditor({ category, onClose, onSaved }) {
  const [mode, setMode] = useState("global"),
    [value, setValue] = useState(""),
    [shipping, setShipping] = useState({}),
    [saving, setSaving] = useState(false),
    [error, setError] = useState("");
  useEffect(() => {
    if (category) {
      setMode(category.mode || "global");
      setValue(category.value == null ? "" : String(category.value));
      setShipping(
        Object.fromEntries(
          fields.map(([key]) => [
            key,
            category[key] == null ? "" : String(category[key]),
          ]),
        ),
      );
      setError("");
    }
  }, [category]);
  async function save() {
    const amount = mode === "global" ? null : Number(value);
    if (
      mode !== "global" &&
      (!value.trim() ||
        !Number.isFinite(amount) ||
        amount < 0 ||
        (mode === "direct" && amount < 0.01))
    ) {
      setError("Enter a valid pricing value.");
      return;
    }
    const measurements = Object.fromEntries(
      fields.map(([key]) => [
        key,
        shipping[key]?.trim() ? Number(shipping[key]) : null,
      ]),
    );
    if (
      Object.values(measurements).some(
        (v) => v !== null && (!Number.isFinite(v) || v < 0.0001),
      )
    ) {
      setError("Measurements must be positive numbers.");
      return;
    }
    const dims = ["length_in", "width_in", "height_in"].map(
      (key) => measurements[key],
    );
    if (dims.some((v) => v !== null) && dims.some((v) => v === null)) {
      setError("Enter length, width and height together.");
      return;
    }
    setSaving(true);
    setError("");
    try {
      const r = await axios.put(`${API}/category-policy`, {
        supplier_id: category.supplier_id,
        category_id: category.category_id,
        mode,
        value: amount,
        ...measurements,
      });
      toast.success(`Defaults saved · ${r.data.affected_products} products`);
      await onSaved?.();
      onClose();
    } catch (e) {
      setError(message(e));
    } finally {
      setSaving(false);
    }
  }
  return (
    <DialogFrame
      open={!!category}
      onClose={() => {
        if (!saving) onClose();
      }}
      title="Category defaults"
      level={210}
      footer={
        <>
          <button className="wb-button" disabled={saving} onClick={onClose}>
            Cancel
          </button>
          <button
            className="wb-button wb-button--primary"
            disabled={saving || !admin()}
            onClick={save}
          >
            {saving ? "Saving…" : "Save defaults"}
          </button>
        </>
      }
    >
      <div className="wb-form">
        <div className="wb-category-context">
          <Ruler size={18} />
          <div>
            <strong>{category?.category_name}</strong>
            <span>
              {(category?.supplier_categories?.length
                ? category.supplier_categories
                : category?.supplier_paths || []
              ).join(" · ")}
            </span>
          </div>
        </div>
        {error && (
          <div role="alert" className="wb-alert wb-alert--danger">
            {error}
          </div>
        )}
        <fieldset>
          <legend>Shipping per item</legend>
          <div className="wb-measure-fields">
            {fields.map(([key, label, unit]) => (
              <label key={key}>
                {label}
                <span className="wb-unit-input">
                  <input
                    aria-label={`${label} (${unit})`}
                    disabled={saving}
                    type="number"
                    min="0.0001"
                    step="0.0001"
                    placeholder="—"
                    value={shipping[key] || ""}
                    onChange={(e) =>
                      setShipping((old) => ({ ...old, [key]: e.target.value }))
                    }
                  />
                  <span>{unit}</span>
                </span>
              </label>
            ))}
          </div>
        </fieldset>
        <fieldset>
          <legend>Pricing</legend>
          <label>
            Rule
            <select
              className="wb-control"
              aria-label="Category pricing rule"
              disabled={saving}
              value={mode}
              onChange={(e) => {
                setMode(e.target.value);
                setValue("");
              }}
            >
              <option value="global">Global markup</option>
              <option value="percentage">Category markup (%)</option>
              <option value="direct">Base retail price ($)</option>
            </select>
          </label>
          {mode !== "global" && (
            <label>
              {mode === "percentage" ? "Markup (%)" : "Base retail price ($)"}
              <input
                className="wb-control"
                aria-label="Category pricing value"
                disabled={saving}
                type="number"
                min={mode === "direct" ? ".01" : "0"}
                step=".01"
                value={value}
                onChange={(e) => setValue(e.target.value)}
              />
            </label>
          )}
        </fieldset>
      </div>
    </DialogFrame>
  );
}
export default function CategoryPolicyManager() {
  const [suppliers, setSuppliers] = useState([]),
    [supplier, setSupplier] = useState(""),
    [rows, setRows] = useState([]),
    [query, setQuery] = useState(""),
    [status, setStatus] = useState(""),
    [loading, setLoading] = useState(false),
    [error, setError] = useState(""),
    [selected, setSelected] = useState(null);
  const version = useRef(0);
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
  const refresh = useCallback(async () => {
    const request = ++version.current;
    if (!supplier) {
      setRows([]);
      setError("");
      setLoading(false);
      return;
    }
    setLoading(true);
    setError("");
    try {
      const r = await axios.get(API + "/category-policies", {
        params: { supplier_id: supplier },
      });
      if (request === version.current) setRows(r.data.categories || []);
    } catch {
      if (request === version.current)
        setError("Category defaults could not be loaded.");
    } finally {
      if (request === version.current) setLoading(false);
    }
  }, [supplier]);
  useEffect(() => {
    setSelected(null);
    setRows([]);
    refresh();
  }, [refresh]);
  const shown = rows.filter(
    (row) =>
      (!status ||
        (status === "complete"
          ? row.measurements_configured
          : !row.measurements_configured)) &&
      [
        row.category_name,
        ...(row.supplier_categories || []),
        ...(row.supplier_paths || []),
      ].some((value) =>
        String(value).toLowerCase().includes(query.toLowerCase()),
      ),
  );
  const complete = rows.filter((row) => row.measurements_configured).length;
  return (
    <section className="wb-page">
      <header className="wb-page-header">
        <div>
          <h1>Category defaults</h1>
          <p>Pricing &amp; shipping measurements</p>
        </div>
        <RefreshButton disabled={loading || !supplier} onClick={refresh} />
      </header>
      <div className="wb-filter-bar">
        <select
          className="wb-control"
          aria-label="Category defaults supplier"
          value={supplier}
          onChange={(e) => setSupplier(e.target.value)}
        >
          <option value="">Choose supplier</option>
          {suppliers.map((s) => (
            <option key={s.id} value={s.id}>
              {s.supplier_name}
            </option>
          ))}
        </select>
        <select
          className="wb-control"
          aria-label="Measurement status"
          value={status}
          onChange={(e) => setStatus(e.target.value)}
        >
          <option value="">All measurements</option>
          <option value="complete">Complete</option>
          <option value="missing">Missing / partial</option>
        </select>
        <SearchField
          aria-label="Search category defaults"
          placeholder="Search categories"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        {supplier && (
          <span className="wb-filter-total">
            {complete} / {rows.length} complete
          </span>
        )}
      </div>
      {error && (
        <div className="wb-alert wb-alert--danger" role="alert">
          {error}
        </div>
      )}
      {loading ? (
        <div className="wb-loading">Loading categories…</div>
      ) : !supplier ? (
        <EmptyState title="Choose a supplier to set category defaults" />
      ) : (
        <div className="wb-table-wrap">
          <table className="wb-table wb-category-table">
            <thead>
              <tr>
                <th>Lightspeed category</th>
                <th>Pricing</th>
                <th>Weight</th>
                <th>Dimensions</th>
                <th>Measurements</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {shown.map((row) => (
                <tr key={row.category_id}>
                  <td>
                    <strong>
                      {row.category_available === false
                        ? "Category needs mapping"
                        : row.category_name}
                    </strong>
                    <small>{row.product_count} products</small>
                    <div className="wb-category-tags">
                      {(row.supplier_categories?.length
                        ? row.supplier_categories
                        : row.supplier_paths || []
                      )
                        .slice(0, 3)
                        .map((name) => (
                          <span key={name}>{name}</span>
                        ))}
                      {Math.max(
                        (row.supplier_categories?.length ||
                          row.supplier_paths?.length ||
                          0) - 3,
                        0,
                      ) > 0 && (
                        <details>
                          <summary>More</summary>
                          {(row.supplier_categories?.length
                            ? row.supplier_categories
                            : row.supplier_paths
                          )
                            .slice(3)
                            .map((name) => (
                              <p key={name}>{name}</p>
                            ))}
                        </details>
                      )}
                    </div>
                  </td>
                  <td>{row.pricing_label}</td>
                  <td>{row.weight_lb != null ? `${row.weight_lb} lb` : "—"}</td>
                  <td className="wb-nowrap">
                    {[row.length_in, row.width_in, row.height_in].every(
                      (v) => v != null,
                    )
                      ? `${row.length_in} × ${row.width_in} × ${row.height_in} in`
                      : "—"}
                  </td>
                  <td>
                    <StatusPill
                      value={
                        row.measurements_configured ? "ready" : "needs_review"
                      }
                      label={shippingLabel(row)}
                    />
                  </td>
                  <td>
                    <div className="wb-row-actions">
                      <button
                        className="wb-button"
                        disabled={!admin() || row.category_available === false}
                        onClick={() => setSelected(row)}
                      >
                        Edit defaults
                      </button>
                      {row.category_available === false && <a className="wb-button" href={`/category-mapping?supplier_id=${encodeURIComponent(row.supplier_id)}&search=${encodeURIComponent(row.supplier_categories?.[0] || '')}`}>Map category</a>}
                      {row.category_available !== false && (
                        <a
                          className="wb-icon-button"
                          title="Open category in Pre-processing"
                          aria-label="Open category in Pre-processing"
                          href={`/preprocessing?supplier_id=${encodeURIComponent(row.supplier_id)}&category_id=${encodeURIComponent(row.category_id)}`}
                        >
                          <ArrowUpRight size={16} />
                        </a>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {!shown.length && <EmptyState title="No matching categories" />}
        </div>
      )}
      <CategoryPolicyEditor
        category={selected}
        onClose={() => setSelected(null)}
        onSaved={refresh}
      />
    </section>
  );
}
