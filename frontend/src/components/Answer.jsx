import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { cx } from "./ui";

/**
 * Renders an assistant answer. Citation markers like [2] are turned into footnote buttons.
 * The backend already strips links, images and HTML; react-markdown doesn't render raw HTML either.
 */
export function AnswerMarkdown({ text, citations, onCite, activeIndex }) {
  const valid = new Set((citations || []).map((c) => c.index));
  // Footnote typography: no space before a marker, and the marker after punctuation ("system.¹"),
  // which also stops a full stop from wrapping onto its own line.
  const tidy = text
    .replace(/[ \t]+(?=\[\d+\])/g, "")
    .replace(/((?:\[\d+\])+)([.,;:])/g, "$2$1");
  // [2] -> a link with a special href the renderer below turns into a button
  const md = tidy.replace(/\[(\d+)\]/g, (m, n) => (valid.has(Number(n)) ? `[${n}](#cite-${n})` : ""));
  return (
    <div className="prose-doc">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          a({ href, children }) {
            const m = /^#cite-(\d+)$/.exec(href || "");
            if (!m) return <span>{children}</span>;
            const idx = Number(m[1]);
            const c = citations.find((x) => x.index === idx);
            return (
              <CiteMarker index={idx} citation={c} active={activeIndex === idx} onClick={() => onCite(c)} />
            );
          },
          img: () => null,
        }}
      >
        {md}
      </ReactMarkdown>
    </div>
  );
}

export function locationLabel(c) {
  if (c.page) return `page ${c.page}`;
  if (c.section) return c.section;
  return null;
}

function CiteMarker({ index, citation, active, onClick }) {
  const where = citation ? [citation.title, locationLabel(citation)].filter(Boolean).join(", ") : "";
  return (
    <button
      type="button"
      onClick={onClick}
      title={where}
      aria-label={`Source ${index}: ${where}`}
      className={cx(
        "ml-[2px] inline-flex h-[1.1rem] min-w-[1.1rem] -translate-y-[0.4em] items-center justify-center rounded-[3px] px-1 align-baseline font-sans text-[0.68rem] font-semibold leading-none transition-colors",
        active ? "bg-mark text-ink" : "bg-ledger-tint text-ledger-dark hover:bg-mark hover:text-ink",
      )}
    >
      {index}
    </button>
  );
}

/** The numbered source list under an answer. */
export function SourceList({ citations, onCite, activeIndex }) {
  if (!citations?.length) return null;
  return (
    <div className="mt-4 border-t border-rule pt-3">
      <p className="mb-1.5 text-sm font-medium text-ink-soft">Sources</p>
      <ol className="space-y-1">
        {citations.map((c) => (
          <li key={c.index}>
            <button
              type="button"
              onClick={() => onCite(c)}
              className={cx(
                "group flex w-full items-baseline gap-2.5 rounded-[3px] px-1.5 py-1 text-left text-sm",
                activeIndex === c.index ? "bg-mark-soft" : "hover:bg-paper",
              )}
            >
              <span className="w-4 shrink-0 text-right font-semibold text-ledger-dark">{c.index}</span>
              <span className={cx("min-w-0", c.available === false && "text-muted line-through")}>
                <span className="font-medium group-hover:underline">{c.title}</span>
                {locationLabel(c) && <span className="text-muted">, {locationLabel(c)}</span>}
              </span>
            </button>
          </li>
        ))}
      </ol>
    </div>
  );
}

const CONF = {
  high: { label: "Strong match", cls: "text-ledger-dark", bars: 3 },
  medium: { label: "Partial match", cls: "text-amber", bars: 2 },
  low: { label: "Weak match", cls: "text-brick", bars: 1 },
};

/** How well the retrieved passages matched the question. Shown as three bars, like signal strength. */
export function Confidence({ label, score }) {
  const c = CONF[label];
  if (!c) return null;
  return (
    <span
      className={cx("inline-flex items-center gap-1.5 text-xs font-medium", c.cls)}
      title={`How closely the source passages match your question (${Math.round((score || 0) * 100)}%). Weak matches deserve a check against the source.`}
    >
      <span className="flex items-end gap-[2px]" aria-hidden="true">
        {[1, 2, 3].map((i) => (
          <span key={i} className={cx("w-[3px] rounded-[1px]", i <= c.bars ? "bg-current" : "bg-rule-strong")} style={{ height: 4 + i * 3 }} />
        ))}
      </span>
      {c.label}
    </span>
  );
}
