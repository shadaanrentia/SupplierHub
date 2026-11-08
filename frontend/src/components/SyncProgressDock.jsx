import React, { useEffect, useRef, useState } from "react";
import { X, ArrowUpRight, RefreshCw } from "lucide-react";
import { toast } from "sonner";
import {
  activeStatus,
  progressJob,
  progressPercent,
} from "./syncProgressState";
const key = "supplierhub:hidden-sync-progress";
export default function SyncProgressDock({ jobs, detail, onOpen }) {
  const [hidden, setHidden] = useState(() => {
    try {
      const value = JSON.parse(localStorage.getItem(key) || "[]");
      return Array.isArray(value) ? value : [];
    } catch {
      return [];
    }
  });
  const previous = useRef(new Map());
  useEffect(() => {
    const seen = new Map(jobs.map((job) => [job.id, job]));
    if (
      detail?.id &&
      (!seen.has(detail.id) || activeStatus(seen.get(detail.id).status))
    )
      seen.set(detail.id, { ...seen.get(detail.id), ...detail });
    for (const [id, job] of seen) {
      if (activeStatus(previous.current.get(id)) && !activeStatus(job.status))
        toast.message(
          `Lightspeed sync · ${String(job.status).replace(/_/g, " ")}`,
          { description: "Saved in Sync History", duration: 5000 },
        );
      previous.current.set(id, job.status);
    }
  }, [jobs, detail]);
  const job = progressJob(jobs, detail, hidden);
  if (!job) return null;
  const percent = progressPercent(job);
  const hide = () =>
    setHidden((old) => {
      const next = [...old, job.id].slice(-100);
      try {
        localStorage.setItem(key, JSON.stringify(next));
      } catch {}
      return next;
    });
  return (
    <aside className="wb-sync-dock" aria-label="Active Lightspeed sync">
      <div className="wb-dock-heading">
        <span className="wb-dock-icon">
          <RefreshCw size={16} />
        </span>
        <div>
          <strong>Syncing to Lightspeed</strong>
          <span>
            {job.stage === "images"
              ? "Uploading images"
              : job.stage === "planning"
                ? "Preparing products"
                : "Updating details"}{" "}
            · {job.total || "…"} products
          </span>
        </div>
        <button
          className="wb-icon-button"
          aria-label="Close sync progress"
          title="Hide progress"
          onClick={hide}
        >
          <X size={15} />
        </button>
      </div>
      <div className="wb-progress-line">
        <div
          className={`wb-progress-track ${percent === null ? "is-indeterminate" : ""}`}
        >
          <span style={{ width: percent === null ? "30%" : `${percent}%` }} />
        </div>
        <span>{percent === null ? "…" : `${percent}%`}</span>
      </div>
      <button className="wb-text-link" onClick={() => onOpen(job.id)}>
        View progress
        <ArrowUpRight size={13} />
      </button>
    </aside>
  );
}
