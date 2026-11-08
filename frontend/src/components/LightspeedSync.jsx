import React, {
  createContext,
  useContext,
  useEffect,
  useRef,
  useState,
} from "react";
import axios from "../lib/axios";
import { toast } from "sonner";
import { Clock, Check } from "lucide-react";
import { ProductLink } from "./ProductDetails";
import ProductHistory from "./ProductHistory";
import SyncProgressDock from "./SyncProgressDock";
import SearchField from "./SearchField";
import {
  DialogFrame,
  StatusPill,
  EmptyState,
  RefreshButton,
  words,
} from "./workbenchUi";
import { dateLabel, resultMessages } from "../lib/productPresentation";
import { activeStatus, progressPercent } from "./syncProgressState";
const BASE =
  (process.env.REACT_APP_BACKEND_URL || "").replace(/\/+$/, "") + "/api";
const API = BASE + "/lightspeed-sync";
const Context = createContext(null);
const errorMessage = (e) =>
  typeof e.response?.data?.detail === "string"
    ? e.response.data.detail
    : e.response?.data?.detail?.message || "Request could not be completed.";
export const useLightspeedSync = () => useContext(Context);
function Result({ item }) {
  const messages = resultMessages({
    details: item.details_result,
    images: item.images_result,
  });
  if (!messages.length) return <span className="wb-muted">—</span>;
  return (
    <details className="wb-result">
      <summary>
        View {messages.length > 1 ? `${messages.length} messages` : "message"}
      </summary>
      <ul>
        {messages.map((text, i) => (
          <li key={i}>{text}</li>
        ))}
      </ul>
    </details>
  );
}
export function LightspeedSyncProvider({ children }) {
  const [jobs, setJobs] = useState([]),
    [id, setId] = useState(""),
    [data, setData] = useState(null),
    [activeData, setActiveData] = useState(null),
    [open, setOpen] = useState(false),
    [view, setView] = useState("batch"),
    [product, setProduct] = useState(null),
    [suppliers, setSuppliers] = useState([]);
  const [search, setSearch] = useState(""),
    [issues, setIssues] = useState(false),
    [page, setPage] = useState(1),
    [revision, setRevision] = useState(0),
    [error, setError] = useState(""),
    [starting, setStarting] = useState(false);
  const lock = useRef(false),
    lastNotification = useRef("");
  const refresh = () => setRevision((n) => n + 1);
  const showBatch = (value) => {
    setId(value);
    setView("batch");
    setSearch("");
    setIssues(false);
    setPage(1);
    setError("");
    setOpen(true);
  };
  const showHistory = (productId, name) => {
    setProduct(productId ? { id: productId, name } : null);
    setView(productId ? "product" : "history");
    setError("");
    setOpen(true);
  };
  useEffect(() => {
    const controller = new AbortController();
    axios
      .get(BASE + "/suppliers", { signal: controller.signal })
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
    const poll = async () => {
      try {
        const r = await axios.get(API + "/jobs", { signal: controller.signal });
        if (!stopped) {
          setJobs(r.data);
          setId((current) => current || r.data[0]?.id || "");
        }
      } catch (e) {
        if (!stopped && open) setError(errorMessage(e));
      } finally {
        if (!stopped) timer = setTimeout(poll, 5000);
      }
    };
    poll();
    return () => {
      stopped = true;
      clearTimeout(timer);
      controller.abort();
    };
  }, [revision, open]);
  useEffect(() => {
    if (!id || view !== "batch") return;
    let stopped = false,
      timer;
    const controller = new AbortController();
    setData(null);
    setError("");
    const poll = async () => {
      try {
        const r = await axios.get(`${API}/jobs/${encodeURIComponent(id)}`, {
          params: { page, search, issues_only: issues },
          signal: controller.signal,
        });
        if (!stopped) {
          setData(r.data);
          setError("");
          const key = `${id}:${r.data.status}:${r.data.counts?.details_processed}:${r.data.counts?.images_completed}`;
          if (lastNotification.current !== key) {
            lastNotification.current = key;
            window.dispatchEvent(new Event("lightspeed-sync-updated"));
          }
          if (open || activeStatus(r.data.status))
            timer = setTimeout(poll, 4000);
        }
      } catch (e) {
        if (!stopped) {
          setError(errorMessage(e));
          timer = setTimeout(poll, 8000);
        }
      }
    };
    poll();
    return () => {
      stopped = true;
      clearTimeout(timer);
      controller.abort();
    };
  }, [id, view, page, search, issues, revision, open]);
  const activeId = jobs.find((job) => activeStatus(job.status))?.id || "";
  useEffect(() => {
    if (!activeId || (view === "batch" && id === activeId)) {
      setActiveData(null);
      return;
    }
    let stopped = false,
      timer;
    const controller = new AbortController();
    const poll = async () => {
      try {
        const r = await axios.get(
          `${API}/jobs/${encodeURIComponent(activeId)}`,
          { signal: controller.signal },
        );
        if (!stopped) setActiveData(r.data);
      } catch {
      } finally {
        if (!stopped) timer = setTimeout(poll, 5000);
      }
    };
    poll();
    return () => {
      stopped = true;
      clearTimeout(timer);
      controller.abort();
    };
  }, [activeId, id, view]);
  const start = async (body) => {
    if (lock.current) return;
    lock.current = true;
    setStarting(true);
    try {
      const signature = JSON.stringify(body);
      let request;
      try {
        request = JSON.parse(
          localStorage.getItem("lightspeed-sync-request") || "null",
        );
      } catch {}
      if (request?.signature !== signature)
        request = { signature, key: crypto.randomUUID() };
      localStorage.setItem("lightspeed-sync-request", JSON.stringify(request));
      try {
        const r = await axios.post(
          API + "/jobs",
          { ...body, request_id: request.key },
          { timeout: 30000 },
        );
        localStorage.removeItem("lightspeed-sync-request");
        showBatch(r.data.id);
        refresh();
        toast.success("Sync queued");
        return r.data;
      } catch (e) {
        if (e.response?.data?.detail?.job_id) {
          showBatch(e.response.data.detail.job_id);
          refresh();
        }
        toast.error(errorMessage(e));
        throw e;
      }
    } finally {
      lock.current = false;
      setStarting(false);
    }
  };
  const current = jobs.find((job) => job.id === id);
  const detail = data?.id === id ? data : null;
  const batch =
    detail &&
    current &&
    new Date(current.updated_at) > new Date(detail.updated_at)
      ? { ...detail, ...current }
      : detail || current;
  const counts = detail?.counts || {},
    total = batch?.total || 0,
    detailsDone = total > 0 && Number(counts.details_processed) >= total,
    imagesDone = total > 0 && Number(counts.images_completed) >= total,
    percent = progressPercent(data?.id === id ? data : null),
    pages = Math.max(1, Math.ceil((data?.filtered_total || 0) / 50));
  const supplier =
    suppliers.find((s) => s.id === batch?.selection?.supplier_id)
      ?.supplier_name || "Lightspeed";
  return (
    <Context.Provider value={{ start, starting, showBatch, showHistory }}>
      {children}
      <SyncProgressDock
        jobs={jobs}
        detail={activeData || data}
        onOpen={showBatch}
      />
      <DialogFrame
        open={open}
        onClose={() => setOpen(false)}
        title={
          view === "product"
            ? "Product sync history"
            : view === "history"
              ? "Recent syncs"
              : "Lightspeed sync"
        }
        subtitle={view === "product" ? product?.name : undefined}
        wide
        level={180}
        footer={
          <>
            <span className="wb-muted">
              {view === "batch" && activeStatus(batch?.status)
                ? "Runs in background"
                : ""}
            </span>
            <button className="wb-button" onClick={() => setOpen(false)}>
              Close
            </button>
          </>
        }
      >
        {error && (
          <div className="wb-alert wb-alert--danger" role="alert">
            {error}
            <button className="wb-button" onClick={refresh}>
              Retry
            </button>
          </div>
        )}
        {view === "product" && product && (
          <ProductHistory key={product.id} productId={product.id} initialDirection="outbound" />
        )}
        {view === "history" && (
          <>
            {jobs.length ? (
              <div className="wb-table-wrap">
                <table className="wb-table">
                  <thead>
                    <tr>
                      <th>Started</th>
                      <th>Products</th>
                      <th>Status</th>
                      <th />
                    </tr>
                  </thead>
                  <tbody>
                    {jobs.map((job) => (
                      <tr key={job.id}>
                        <td>{dateLabel(job.created_at)}</td>
                        <td>{job.total || "Planning"}</td>
                        <td>
                          <StatusPill value={job.status} />
                        </td>
                        <td>
                          <button
                            className="wb-button"
                            onClick={() => showBatch(job.id)}
                          >
                            View
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <EmptyState title="No recorded syncs" />
            )}
          </>
        )}
        {view === "batch" && (
          <div className="wb-sync">
            <div className="wb-toolbar">
              <div className="wb-sync-batch">
                <label htmlFor="wb-batch">Batch</label>
                <select
                  id="wb-batch"
                  className="wb-control"
                  value={id}
                  onChange={(e) => showBatch(e.target.value)}
                >
                  {jobs.map((job) => (
                    <option key={job.id} value={job.id}>
                      {dateLabel(job.created_at)} · {job.total || "Planning"}{" "}
                      products
                    </option>
                  ))}
                </select>
              </div>
              <div className="wb-toolbar-right">
                <button
                  className="wb-icon-button"
                  title="Recent syncs"
                  aria-label="Recent syncs"
                  onClick={() => setView("history")}
                >
                  <Clock size={16} />
                </button>
                <RefreshButton onClick={refresh} />
              </div>
            </div>
            {!batch && !error && (
              <div className="wb-loading">Loading progress…</div>
            )}
            {batch && (
              <section className="wb-sync-summary">
                <div className="wb-toolbar">
                  <div>
                    <strong>{supplier}</strong>
                    <span className="wb-muted">
                      {" "}
                      ·{" "}
                      {total
                        ? `${total} ${total === 1 ? "product" : "products"}`
                        : "Preparing"}
                    </span>
                  </div>
                  <StatusPill value={batch.status} />
                </div>
                <div className="wb-progress-line">
                  <div
                    className={`wb-progress-track ${percent === null ? "is-indeterminate" : ""}`}
                  >
                    <span
                      style={{
                        width: percent === null ? "30%" : `${percent}%`,
                      }}
                    />
                  </div>
                  <strong>{percent === null ? "…" : `${percent}%`}</strong>
                </div>
                <ol className="wb-steps">
                  <li
                    className={
                      detailsDone
                        ? "is-done"
                        : batch.stage === "details" &&
                            activeStatus(batch.status)
                          ? "is-current"
                          : ""
                    }
                  >
                    <span>{detailsDone ? <Check size={12} /> : 1}</span>Product
                    details
                  </li>
                  <li
                    className={
                      imagesDone
                        ? "is-done"
                        : batch.stage === "images" && activeStatus(batch.status)
                          ? "is-current"
                          : ""
                    }
                  >
                    <span>{imagesDone ? <Check size={12} /> : 2}</span>Images
                  </li>
                </ol>
                <div className="wb-sync-counts">
                  <div>
                    <strong>{counts.details_processed ?? "—"}</strong>
                    <span>Details checked</span>
                  </div>
                  <div>
                    <strong>{counts.images_completed ?? "—"}</strong>
                    <span>Images complete</span>
                  </div>
                  <div
                    className={
                      Number(counts.details_failed || 0) +
                        Number(counts.images_pending || 0) >
                      0
                        ? "has-issues"
                        : ""
                    }
                  >
                    <strong>
                      {detail
                        ? Number(counts.details_failed || 0) +
                          Number(counts.images_pending || 0)
                        : "—"}
                    </strong>
                    <span>Issues</span>
                  </div>
                </div>
                {data?.current && (
                  <p className="wb-current-product">
                    <i />
                    <strong>{data.current.sku}</strong>
                    <span title={data.current.product_name}>
                      {data.current.product_name}
                    </span>
                  </p>
                )}
                {batch.message && (
                  <details className="wb-result">
                    <summary>Batch message</summary>
                    <p>{batch.message}</p>
                  </details>
                )}
              </section>
            )}
            <div className="wb-toolbar">
              <SearchField
                aria-label="Search sync results"
                placeholder="Search product or SKU"
                value={search}
                onChange={(e) => {
                  setSearch(e.target.value);
                  setPage(1);
                }}
              />
              <label className="wb-checkbox">
                <input
                  type="checkbox"
                  checked={issues}
                  onChange={(e) => {
                    setIssues(e.target.checked);
                    setPage(1);
                  }}
                />
                Issues only
              </label>
            </div>
            {data && (
              <>
                <div className="wb-table-wrap">
                  <table className="wb-table">
                    <thead>
                      <tr>
                        <th>Product</th>
                        <th>Details</th>
                        <th>Images</th>
                        <th>Result</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.items.map((item) => (
                        <tr key={item.product_id}>
                          <td>
                            <ProductLink productId={item.product_id}>
                              {item.sku}
                            </ProductLink>
                            <small
                              className="wb-truncate"
                              title={item.product_name}
                            >
                              {item.product_name}
                            </small>
                          </td>
                          <td>
                            <StatusPill value={item.details_status} />
                          </td>
                          <td>
                            <StatusPill value={item.images_status} />
                          </td>
                          <td>
                            <Result item={item} />
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {!data.items.length && (
                    <EmptyState
                      title={
                        batch?.stage === "planning"
                          ? "Preparing product list…"
                          : "No matching products"
                      }
                    />
                  )}
                </div>
                <div className="wb-pagination">
                  <span>{data.filtered_total} products</span>
                  <div>
                    <button
                      className="wb-button"
                      disabled={page <= 1}
                      onClick={() => setPage((n) => n - 1)}
                    >
                      Previous
                    </button>
                    <span>
                      {page} / {pages}
                    </span>
                    <button
                      className="wb-button"
                      disabled={page >= pages}
                      onClick={() => setPage((n) => n + 1)}
                    >
                      Next
                    </button>
                  </div>
                </div>
              </>
            )}
          </div>
        )}
      </DialogFrame>
    </Context.Provider>
  );
}
