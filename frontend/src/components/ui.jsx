/** Small, consistent building blocks. Radii vary by role: inputs 4px, panels 6px, sheets 0. */
import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { Eye, EyeOff, X } from "lucide-react";

export function cx(...c) {
  return c.filter(Boolean).join(" ");
}

const BTN = {
  primary: "bg-ledger text-white hover:bg-ledger-dark disabled:bg-rule-strong",
  secondary: "bg-sheet text-ink border border-rule-strong hover:border-ink-soft disabled:text-muted",
  ghost: "text-ink-soft hover:bg-ledger-tint hover:text-ink disabled:text-muted",
  danger: "bg-brick text-white hover:brightness-95 disabled:opacity-60",
};

export function Button({ variant = "primary", size = "md", className, loading, children, ...props }) {
  return (
    <button
      className={cx(
        "inline-flex items-center justify-center gap-2 rounded-[4px] font-medium transition-colors disabled:cursor-not-allowed",
        size === "sm" ? "h-8 px-3 text-sm" : "h-10 px-4",
        BTN[variant],
        className,
      )}
      disabled={loading || props.disabled}
      {...props}
    >
      {loading && <Spinner small />}
      {children}
    </button>
  );
}

export function IconButton({ label, className, children, ...props }) {
  return (
    <button
      aria-label={label}
      title={label}
      className={cx("inline-flex h-8 w-8 items-center justify-center rounded-[4px] text-ink-soft hover:bg-ledger-tint hover:text-ink disabled:opacity-40", className)}
      {...props}
    >
      {children}
    </button>
  );
}

export function Field({ label, hint, error, children, htmlFor }) {
  return (
    <div className="space-y-1.5">
      {label && (
        <label htmlFor={htmlFor} className="block text-sm font-medium text-ink">
          {label}
        </label>
      )}
      {children}
      {error ? <p className="text-sm text-brick">{error}</p> : hint ? <p className="text-sm text-muted">{hint}</p> : null}
    </div>
  );
}

const INPUT = "rounded-[4px] border border-rule-strong bg-sheet px-3 py-2 text-ink placeholder:text-muted/70 focus:border-ledger focus:outline-none focus:ring-2 focus:ring-ledger/20";

// Callers can set a width (w-40, max-w-xs…); otherwise fields fill their container.
const width = (className) => (/(^|\s)w-/.test(className || "") ? "" : "w-full");

export function Input({ className, ...props }) {
  return <input className={cx(INPUT, width(className), "h-10", className)} {...props} />;
}
/** Password field with a show/hide button. It only reveals what the person is typing on their own screen. */
export function PasswordInput({ className, ...props }) {
  const [show, setShow] = useState(false);
  return (
    <div className="relative">
      <Input type={show ? "text" : "password"} className={cx("pr-10", className)} {...props} />
      <button
        type="button"
        onClick={() => setShow((v) => !v)}
        aria-label={show ? "Hide password" : "Show password"}
        aria-pressed={show}
        title={show ? "Hide password" : "Show password"}
        className="absolute inset-y-0 right-0 flex w-10 items-center justify-center rounded-r-[4px] text-muted hover:text-ink"
      >
        {show ? <EyeOff size={17} /> : <Eye size={17} />}
      </button>
    </div>
  );
}

export function Textarea({ className, ...props }) {
  return <textarea className={cx(INPUT, width(className), className)} {...props} />;
}
export function Select({ className, children, ...props }) {
  return (
    <select className={cx(INPUT, width(className), "h-10 pr-8", className)} {...props}>
      {children}
    </select>
  );
}

export function Spinner({ small }) {
  return (
    <span
      role="status"
      aria-label="Loading"
      className={cx("inline-block animate-spin rounded-full border-2 border-current border-r-transparent", small ? "h-3.5 w-3.5" : "h-5 w-5")}
    />
  );
}

export function Loading({ label = "Loading…" }) {
  return (
    <div className="flex items-center gap-3 p-6 text-muted">
      <Spinner /> {label}
    </div>
  );
}

export function ErrorNote({ error, className }) {
  if (!error) return null;
  const msg = typeof error === "string" ? error : error.message;
  return (
    <div role="alert" className={cx("rounded-[4px] border-l-4 border-brick bg-brick-tint px-3 py-2 text-sm text-ink", className)}>
      {msg}
      {error.errors?.length > 0 && (
        <ul className="mt-1 list-disc pl-5">
          {error.errors.map((e, i) => (
            <li key={i}>
              {e.field ? `${e.field}: ` : ""}
              {e.message}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function Empty({ title, children, action }) {
  return (
    <div className="max-w-md py-10">
      <p className="text-lg font-semibold">{title}</p>
      {children && <p className="mt-1 text-muted">{children}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

const TONES = {
  neutral: "bg-paper text-ink-soft border-rule",
  green: "bg-ledger-tint text-ledger-dark border-ledger/25",
  amber: "bg-amber-tint text-amber border-amber/25",
  red: "bg-brick-tint text-brick border-brick/25",
  ink: "bg-ink text-paper border-ink",
};
export function Badge({ tone = "neutral", children, className, title }) {
  return (
    <span title={title} className={cx("inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-medium", TONES[tone], className)}>
      {children}
    </span>
  );
}

export function PageHeader({ title, description, actions }) {
  return (
    <header className="mb-6 flex flex-wrap items-end justify-between gap-4 border-b border-rule pb-4">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        {description && <p className="mt-1 max-w-2xl text-muted">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </header>
  );
}

export function Modal({ open, onClose, title, children, footer, wide }) {
  const ref = useRef(null);
  useEffect(() => {
    if (!open) return;
    const prev = document.activeElement;
    ref.current?.querySelector("input,select,textarea,button")?.focus();
    const onKey = (e) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      prev?.focus?.();
    };
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-ink/40 p-4 pt-[10vh]" onMouseDown={onClose}>
      <div
        ref={ref}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className={cx("w-full rounded-md border border-rule bg-sheet shadow-xl", wide ? "max-w-2xl" : "max-w-md")}
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-rule px-5 py-3">
          <h2 className="font-semibold">{title}</h2>
          <IconButton label="Close" onClick={onClose}>
            <X size={18} />
          </IconButton>
        </div>
        <div className="px-5 py-4">{children}</div>
        {footer && <div className="flex justify-end gap-2 border-t border-rule bg-paper px-5 py-3">{footer}</div>}
      </div>
    </div>
  );
}

export function ConfirmDialog({ open, title, body, confirmLabel, onConfirm, onClose, loading, danger = true }) {
  return (
    <Modal
      open={open}
      onClose={onClose}
      title={title}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button variant={danger ? "danger" : "primary"} onClick={onConfirm} loading={loading}>
            {confirmLabel}
          </Button>
        </>
      }
    >
      <p className="text-ink-soft">{body}</p>
    </Modal>
  );
}

/* ---------- Toasts ---------- */
const ToastContext = createContext(() => {});
export function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([]);
  const push = useCallback((message, tone = "green") => {
    const id = Math.random().toString(36).slice(2);
    setToasts((t) => [...t, { id, message, tone }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 4000);
  }, []);
  return (
    <ToastContext.Provider value={push}>
      {children}
      <div aria-live="polite" className="fixed bottom-4 right-4 z-[60] space-y-2">
        {toasts.map((t) => (
          <div
            key={t.id}
            className={cx(
              "rounded-[4px] border-l-4 bg-sheet px-4 py-2.5 text-sm shadow-lg",
              t.tone === "red" ? "border-brick" : "border-ledger",
            )}
          >
            {t.message}
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}
export function useToast() {
  return useContext(ToastContext);
}

/* ---------- formatting ---------- */
export function formatDate(iso, withTime = false) {
  if (!iso) return "–";
  const d = new Date(iso);
  return d.toLocaleString(undefined, withTime ? { dateStyle: "medium", timeStyle: "short" } : { dateStyle: "medium" });
}
export function relativeTime(iso) {
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  if (s < 7 * 86400) return `${Math.floor(s / 86400)} d ago`;
  return formatDate(iso);
}
export function formatBytes(n) {
  if (!n && n !== 0) return "–";
  if (n < 1024) return `${n} B`;
  if (n < 1024 ** 2) return `${(n / 1024).toFixed(0)} KB`;
  return `${(n / 1024 ** 2).toFixed(1)} MB`;
}
export const ROLE_LABEL = { admin: "Admin", hr: "HR", employee: "Employee" };
