import React from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { X, Inbox, RefreshCw } from "lucide-react";
export const words = (value) => String(value ?? "").replace(/_/g, " ");
export function StatusPill({ value, label }) {
  const state = String(value || "unknown");
  const tone = [
    "completed",
    "synced",
    "succeeded",
    "success",
    "ready",
  ].includes(state)
    ? "success"
    : ["running", "queued", "pending", "planning", "stopping"].includes(state)
      ? "active"
      : ["failed", "error", "interrupted"].includes(state)
        ? "danger"
        : [
              "images_pending",
              "completed_with_issues",
              "needs_review",
              "skipped",
            ].includes(state)
          ? "warning"
          : "muted";
  return (
    <span className={`wb-status wb-status--${tone}`}>
      <i />
      {label || words(state) || "Not recorded"}
    </span>
  );
}
export function EmptyState({ title = "No results", action }) {
  return (
    <div className="wb-empty">
      <Inbox size={25} />
      <p>{title}</p>
      {action}
    </div>
  );
}
export function RefreshButton({ onClick, disabled = false }) {
  return (
    <button
      type="button"
      className="wb-icon-button"
      title="Refresh"
      aria-label="Refresh"
      disabled={disabled}
      onClick={onClick}
    >
      <RefreshCw size={16} />
    </button>
  );
}
export function DialogFrame({
  open,
  onClose,
  title,
  subtitle,
  children,
  footer,
  wide = false,
  level = 180,
}) {
  return (
    <Dialog.Root
      open={open}
      onOpenChange={(value) => {
        if (!value) onClose();
      }}
    >
      <Dialog.Portal>
        <Dialog.Overlay className="wb-overlay" style={{ zIndex: level }} />
        <Dialog.Content
          {...(!subtitle ? { "aria-describedby": undefined } : {})}
          className={`wb-dialog ${wide ? "wb-dialog--wide" : ""}`}
          style={{ zIndex: level + 1 }}
        >
          <header className="wb-dialog-header">
            <div>
              <Dialog.Title>{title}</Dialog.Title>
              {subtitle && <Dialog.Description>{subtitle}</Dialog.Description>}
            </div>
            <Dialog.Close className="wb-icon-button" aria-label="Close">
              <X size={18} />
            </Dialog.Close>
          </header>
          <div className="wb-dialog-body">{children}</div>
          {footer && <footer className="wb-dialog-footer">{footer}</footer>}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
