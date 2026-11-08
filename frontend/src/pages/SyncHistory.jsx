import React, { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import axios from "../lib/axios";
import { toast } from "sonner";
import { SlidersHorizontal, ArrowDownLeft, ArrowUpRight } from "lucide-react";
import SearchField from "../components/SearchField";
import { ProductLink } from "../components/ProductDetails";
import { useLightspeedSync } from "../components/LightspeedSync";
import {
  DialogFrame,
  StatusPill,
  EmptyState,
  RefreshButton,
  words,
} from "../components/workbenchUi";
import { dateLabel, resultMessages } from "../lib/productPresentation";
const API =
  (process.env.REACT_APP_BACKEND_URL || "").replace(/\/+$/, "") + "/api";
const active = (status) =>
  [
    "pending",
    "queued",
    "running",
    "planning",
    "stopping",
    "in_progress",
  ].includes(status);
const message = (e) =>
  typeof e.response?.data?.detail === "string"
    ? e.response.data.detail
    : "History could not be loaded.";
function Totals({ event }) {
  const values = [
    ["Total", event.total],
    ["Passed", event.succeeded],
    ["Failed", event.failed],
    ["Images pending", event.images_pending],
  ];
  return (
    <div className="wb-inline-counts">
      {values
        .filter(([, value]) => value != null)
        .map(([label, value]) => (
          <span
            key={label}
            className={label === "Failed" && value > 0 ? "is-danger" : ""}
          >
            {value}
            <small>{label}</small>
          </span>
        ))}
    </div>
  );
}
function HistoryRecord({ identity, onClose }) {
  const [data, setData] = useState(null),
    [error, setError] = useState(""),
    [search, setSearch] = useState(""),
    [state, setState] = useState(""),
    [page, setPage] = useState(1),
    [revision, setRevision] = useState(0),
    [busy, setBusy] = useState(false);
  const monitor = useLightspeedSync();
  useEffect(() => {
    setPage(1);
    setSearch("");
    setState("");
    setData(null);
    setError("");
  }, [identity]);
  useEffect(() => {
    if (!identity) return;
    let stopped = false,
      timer;
    const controller = new AbortController();
    const poll = async () => {
      try {
        const r = await axios.get(
          `${API}/sync-history/events/${encodeURIComponent(identity)}`,
          { params: { search, state, page }, signal: controller.signal },
        );
        if (!stopped) {
          setData(r.data);
          setError("");
          if (active(r.data.event.status)) timer = setTimeout(poll, 5000);
        }
      } catch (e) {
        if (!stopped) setError(message(e));
      }
    };
    poll();
    return () => {
      stopped = true;
      clearTimeout(timer);
      controller.abort();
    };
  }, [identity, search, state, page, revision]);
  const action = async (kind) => {
    setBusy(true);
    try {
      await axios.post(`${API}/sync/${kind}/${identity.split(":")[1]}`);
      toast.success(kind === "stop" ? "Stop requested" : "Retry queued");
      setRevision((n) => n + 1);
    } catch (e) {
      toast.error(message(e));
    } finally {
      setBusy(false);
    }
  };
  const event = data?.event;
  const summaryMessages = resultMessages(event?.result);
  return (
    <DialogFrame
      open={!!identity}
      onClose={onClose}
      title="Sync results"
      wide
      footer={
        <>
          <span className="wb-muted">{event?.supplier_names?.join(", ")}</span>
          <button className="wb-button" onClick={onClose}>
            Close
          </button>
        </>
      }
    >
      {error && (
        <div role="alert" className="wb-alert wb-alert--danger">
          {error}
        </div>
      )}
      {!data && !error && <div className="wb-loading">Loading results…</div>}
      {event && (
        <>
          <div className="wb-record-heading">
            <div>
              <h2>{words(event.operation)}</h2>
              <p>
                {dateLabel(event.started_at || event.recorded_at)} ·{" "}
                {event.platform}
              </p>
            </div>
            <StatusPill value={event.status} />
          </div>
          <Totals event={event} />
          <div className="wb-toolbar">
            <div className="wb-toolbar-left">
              <SearchField
                aria-label="Search history items"
                placeholder="Search SKU or message"
                value={search}
                onChange={(e) => {
                  setSearch(e.target.value);
                  setPage(1);
                }}
              />
              <select
                className="wb-control"
                aria-label="History item status"
                value={state}
                onChange={(e) => {
                  setState(e.target.value);
                  setPage(1);
                }}
              >
                <option value="">All statuses</option>
                {[
                  "pending",
                  "queued",
                  "running",
                  "completed",
                  "failed",
                  "interrupted",
                  "skipped",
                ].map((value) => (
                  <option key={value}>{value}</option>
                ))}
              </select>
            </div>
            <RefreshButton onClick={() => setRevision((n) => n + 1)} />
          </div>
          {data.items.length ? (
            <div className="wb-table-wrap">
              <table className="wb-table">
                <thead>
                  <tr>
                    <th>Product / SKU</th>
                    <th>Status</th>
                    <th>Result</th>
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((item, i) => {
                    const messages = resultMessages(
                      item.details_result || item.images_result
                        ? {
                            details: item.details_result,
                            images: item.images_result,
                          }
                        : item,
                    );
                    return (
                      <tr
                        key={`${item.product_id || item.sku}:${item.stage || i}`}
                      >
                        <td>
                          {item.product_id ? (
                            <ProductLink productId={item.product_id}>
                              {item.sku || item.product_name}
                            </ProductLink>
                          ) : (
                            item.sku
                          )}
                          <small>
                            {item.product_name || words(item.stage)}
                          </small>
                        </td>
                        <td>
                          {item.details_status ? (
                            <div className="wb-stage-pills">
                              <StatusPill
                                value={item.details_status}
                                label={`Details · ${words(item.details_status)}`}
                              />
                              <StatusPill
                                value={item.images_status}
                                label={`Images · ${words(item.images_status)}`}
                              />
                            </div>
                          ) : (
                            <StatusPill value={item.status} />
                          )}
                        </td>
                        <td>
                          {messages.length ? (
                            <details className="wb-result">
                              <summary>View messages</summary>
                              <ul>
                                {messages.map((text, index) => (
                                  <li key={index}>{text}</li>
                                ))}
                              </ul>
                            </details>
                          ) : (
                            <span className="wb-muted">—</span>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          ) : (
            <EmptyState title="No item-level results recorded" />
          )}
          <div className="wb-pagination">
            <span>{data.total} items</span>
            <div>
              <button
                className="wb-button"
                disabled={page <= 1}
                onClick={() => setPage((n) => n - 1)}
              >
                Previous
              </button>
              <span>
                {page} / {Math.max(1, Math.ceil(data.total / 50))}
              </span>
              <button
                className="wb-button"
                disabled={page * 50 >= data.total}
                onClick={() => setPage((n) => n + 1)}
              >
                Next
              </button>
            </div>
          </div>
          {(event.message || summaryMessages.length > 0) && (
            <details className="wb-result">
              <summary>Summary messages</summary>
              <ul>
                {[event.message, ...summaryMessages]
                  .filter(Boolean)
                  .map((text, i) => (
                    <li key={i}>{text}</li>
                  ))}
              </ul>
            </details>
          )}
          <div className="wb-row-actions">
            {identity.startsWith("batch:") && (
              <button
                className="wb-button wb-button--primary"
                onClick={() => {
                  onClose();
                  monitor.showBatch(event.id);
                }}
              >
                Open batch progress
              </button>
            )}
            {event.managed &&
              event.direction === "inbound" &&
              (active(event.status) ? (
                <button
                  className="wb-button wb-button--danger"
                  disabled={busy || event.status === "stopping"}
                  onClick={() => action("stop")}
                >
                  Stop job
                </button>
              ) : (
                event.status !== "completed" &&
                event.operation !== "bulk_data" && (
                  <button
                    className="wb-button"
                    disabled={busy}
                    onClick={() => action("retry")}
                  >
                    Retry unfinished
                  </button>
                )
              ))}
          </div>
        </>
      )}
    </DialogFrame>
  );
}
export default function SyncHistory() {
  const [params, setParams] = useSearchParams();
  const direction =
    params.get("direction") === "outbound" ? "outbound" : "inbound";
  const [suppliers, setSuppliers] = useState([]),
    [supplier, setSupplier] = useState(""),
    [platform, setPlatform] = useState(""),
    [state, setState] = useState(""),
    [operation, setOperation] = useState(""),
    [first, setFirst] = useState(""),
    [last, setLast] = useState(""),
    [search, setSearch] = useState(""),
    [page, setPage] = useState(1),
    [data, setData] = useState(null),
    [error, setError] = useState(""),
    [revision, setRevision] = useState(0),
    [selected, setSelected] = useState(""),
    [filters, setFilters] = useState(false);
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
    let stopped = false,
      timer;
    const controller = new AbortController();
    setData(null);
    setError("");
    const poll = async () => {
      try {
        const r = await axios.get(API + "/sync-history", {
          params: {
            direction,
            supplier_id: supplier,
            platform,
            state,
            operation,
            date_from: first,
            date_to: last,
            search,
            page,
          },
          signal: controller.signal,
        });
        if (!stopped) {
          setData(r.data);
          setError("");
        }
      } catch (e) {
        if (!stopped) setError(message(e));
      } finally {
        if (!stopped) timer = setTimeout(poll, 10000);
      }
    };
    poll();
    return () => {
      stopped = true;
      clearTimeout(timer);
      controller.abort();
    };
  }, [
    direction,
    supplier,
    platform,
    state,
    operation,
    first,
    last,
    search,
    page,
    revision,
  ]);
  const change = (setter) => (e) => {
    setter(e.target.value);
    setPage(1);
  };
  return (
    <div className="wb-page">
      <header className="wb-page-header">
        <div>
          <h1>Sync history</h1>
          <p>Supplier imports &amp; platform exports</p>
        </div>
        <RefreshButton onClick={() => setRevision((n) => n + 1)} />
      </header>
      <div className="wb-segment" role="tablist" aria-label="Sync direction">
        {[
          ["inbound", "To SupplierHub", ArrowDownLeft],
          ["outbound", "From SupplierHub", ArrowUpRight],
        ].map(([value, label, Icon]) => (
          <button
            key={value}
            role="tab"
            aria-selected={direction === value}
            className={direction === value ? "is-selected" : ""}
            onClick={() => {
              setParams({ direction: value });
              setPlatform("");
              setOperation("");
              setPage(1);
            }}
          >
            <Icon size={15} />
            {label}
          </button>
        ))}
      </div>
      <section className="wb-history-controls">
        <div className="wb-filter-bar">
          <select
            className="wb-control"
            aria-label="History supplier"
            value={supplier}
            onChange={change(setSupplier)}
          >
            <option value="">All suppliers</option>
            {suppliers.map((s) => (
              <option key={s.id} value={s.id}>
                {s.supplier_name}
              </option>
            ))}
          </select>
          {direction === "outbound" && (
            <select
              className="wb-control"
              aria-label="History destination"
              value={platform}
              onChange={change(setPlatform)}
            >
              <option value="">All destinations</option>
              <option value="lightspeed">Lightspeed</option>
              <option value="odoo">Odoo</option>
            </select>
          )}
          <select
            className="wb-control"
            aria-label="History status"
            value={state}
            onChange={change(setState)}
          >
            <option value="">All statuses</option>
            {[
              "queued",
              "running",
              "stopping",
              "completed",
              "completed_with_issues",
              "failed",
              "interrupted",
              "stopped",
            ].map((value) => (
              <option key={value} value={value}>
                {words(value)}
              </option>
            ))}
          </select>
          <SearchField
            aria-label="Search sync history"
            placeholder="Search supplier, SKU or message"
            value={search}
            onChange={change(setSearch)}
          />
          <button
            className={`wb-button ${filters ? "is-selected" : ""}`}
            aria-expanded={filters}
            onClick={() => setFilters((old) => !old)}
          >
            <SlidersHorizontal size={15} />
            Filters
            {(operation || first || last) && <i className="wb-filter-dot" />}
          </button>
        </div>
        {filters && (
          <div className="wb-extra-filters">
            <label>
              Operation
              <select
                className="wb-control"
                value={operation}
                onChange={change(setOperation)}
              >
                <option value="">All operations</option>
                {data?.operations.map((value) => (
                  <option key={value} value={value}>
                    {words(value)}
                  </option>
                ))}
              </select>
            </label>
            <label>
              From (UTC)
              <input
                className="wb-control"
                type="date"
                value={first}
                onChange={change(setFirst)}
              />
            </label>
            <label>
              To (UTC)
              <input
                className="wb-control"
                type="date"
                value={last}
                onChange={change(setLast)}
              />
            </label>
            <button
              className="wb-text-link"
              onClick={() => {
                setOperation("");
                setFirst("");
                setLast("");
                setPage(1);
              }}
            >
              Clear
            </button>
          </div>
        )}
      </section>
      {error && (
        <div role="alert" className="wb-alert wb-alert--danger">
          {error}
        </div>
      )}
      {!data && !error && <div className="wb-loading">Loading history…</div>}
      {data && (
        <>
          <div className="wb-stat-grid">
            {[
              ["total", "Records"],
              ["active", "Active"],
              ["completed", "Completed"],
              ["attention", "Needs attention"],
            ].map(([key, label]) => (
              <div className={`wb-stat wb-stat--${key}`} key={key}>
                <span>{label}</span>
                <strong>{data.summary[key]}</strong>
              </div>
            ))}
          </div>
          <div className="wb-table-wrap">
            <table className="wb-table wb-history-table">
              <thead>
                <tr>
                  <th>When</th>
                  <th>Supplier / destination</th>
                  <th>Operation</th>
                  <th>Status</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {data.items.map((item) => (
                  <tr key={item.key}>
                    <td className="wb-nowrap">
                      {dateLabel(item.started_at || item.recorded_at)}
                    </td>
                    <td>
                      {item.supplier_names?.join(", ") || "Not recorded"}
                      <small>
                        {item.direction === "inbound"
                          ? "Supplier import"
                          : item.platform}
                      </small>
                    </td>
                    <td>
                      {words(item.operation)}
                      {item.product_id && (
                        <small>
                          <ProductLink productId={item.product_id}>
                            {item.sku}
                          </ProductLink>
                        </small>
                      )}
                    </td>
                    <td>
                      <StatusPill value={item.status} />
                      <Totals event={item} />
                    </td>
                    <td>
                      <button
                        className="wb-button"
                        onClick={() => setSelected(item.key)}
                      >
                        View results
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {!data.items.length && <EmptyState title="No matching syncs" />}
          </div>
          <div className="wb-pagination">
            <span>{data.total} records</span>
            <div>
              <button
                className="wb-button"
                disabled={page <= 1}
                onClick={() => setPage((n) => n - 1)}
              >
                Previous
              </button>
              <span>
                {page} / {Math.max(1, Math.ceil(data.total / 50))}
              </span>
              <button
                className="wb-button"
                disabled={page * 50 >= data.total}
                onClick={() => setPage((n) => n + 1)}
              >
                Next
              </button>
            </div>
          </div>
        </>
      )}
      <HistoryRecord identity={selected} onClose={() => setSelected("")} />
    </div>
  );
}
