import React, { useEffect, useState } from "react";
import axios from "../lib/axios";
import SearchField from "./SearchField";
import { StatusPill, EmptyState, RefreshButton, words } from "./workbenchUi";
import { dateLabel, resultMessages } from "../lib/productPresentation";
const API =
  (process.env.REACT_APP_BACKEND_URL || "").replace(/\/+$/, "") + "/api";
export default function ProductHistory({ productId, initialDirection = "inbound" }) {
  const [direction, setDirection] = useState(initialDirection),
    [search, setSearch] = useState(""),
    [page, setPage] = useState(1),
    [data, setData] = useState(null),
    [error, setError] = useState(""),
    [revision, setRevision] = useState(0);
  useEffect(() => {
    let stopped = false,
      timer;
    const controller = new AbortController();
    setData(null);
    setError("");
    const poll = async () => {
      try {
        const r = await axios.get(
          `${API}/products/${encodeURIComponent(productId)}/history`,
          { params: { direction, search, page }, signal: controller.signal },
        );
        if (!stopped) {
          setData(r.data);
          setError("");
          if (
            r.data.items.some((i) =>
              ["running", "queued", "pending"].includes(i.status),
            )
          )
            timer = setTimeout(poll, 5000);
        }
      } catch (e) {
        if (!stopped)
          setError(
            typeof e.response?.data?.detail === "string"
              ? e.response.data.detail
              : "History could not be loaded.",
          );
      }
    };
    poll();
    return () => {
      stopped = true;
      clearTimeout(timer);
      controller.abort();
    };
  }, [productId, direction, search, page, revision]);
  return (
    <section className="wb-section">
      <div className="wb-toolbar">
        <div className="wb-segment">
          {[
            ["inbound", "From supplier"],
            ["outbound", "To Lightspeed"],
          ].map(([value, label]) => (
            <button
              type="button"
              key={value}
              className={direction === value ? "is-selected" : ""}
              onClick={() => {
                setDirection(value);
                setPage(1);
              }}
            >
              {label}
            </button>
          ))}
        </div>
        <div className="wb-toolbar-right">
          <SearchField
            aria-label="Search this product history"
            placeholder="Search SKU or operation"
            value={search}
            onChange={(e) => {
              setSearch(e.target.value);
              setPage(1);
            }}
          />
          <RefreshButton onClick={() => setRevision((n) => n + 1)} />
        </div>
      </div>
      {error && (
        <div role="alert" className="wb-alert wb-alert--danger">
          {error}
          <button
            className="wb-button"
            onClick={() => setRevision((n) => n + 1)}
          >
            Retry
          </button>
        </div>
      )}
      {!data && !error && <div className="wb-loading">Loading history…</div>}
      {data && (
        <>
          {data.items.length ? (
            <div className="wb-table-wrap">
              <table className="wb-table">
                <thead>
                  <tr>
                    <th>When</th>
                    <th>Operation</th>
                    <th>Status</th>
                    <th>Result</th>
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((item) => {
                    const messages = resultMessages(item.result);
                    return (
                      <tr key={item.key}>
                        <td className="wb-nowrap">
                          {dateLabel(item.recorded_at)}
                        </td>
                        <td>
                          {words(item.operation)}
                          <small>{item.sku}</small>
                        </td>
                        <td>
                          <StatusPill value={item.status} />
                        </td>
                        <td>
                          {messages.length ? (
                            <details className="wb-result">
                              <summary>
                                {messages.length === 1
                                  ? "View message"
                                  : `${messages.length} messages`}
                              </summary>
                              <ul>
                                {messages.map((message, i) => (
                                  <li key={i}>{message}</li>
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
            <EmptyState title="No recorded history for this product" />
          )}
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
                {page} / {Math.max(1, Math.ceil(data.total / 25))}
              </span>
              <button
                className="wb-button"
                disabled={page * 25 >= data.total}
                onClick={() => setPage((n) => n + 1)}
              >
                Next
              </button>
            </div>
          </div>
        </>
      )}
    </section>
  );
}
