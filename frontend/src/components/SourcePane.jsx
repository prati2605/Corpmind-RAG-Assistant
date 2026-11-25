import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ExternalLink, FileStack, X } from "lucide-react";
import { downloadFile } from "../api/client";
import { documents } from "../api/endpoints";
import { locationLabel } from "./Answer";
import { Button, ErrorNote, IconButton, Loading, cx } from "./ui";

const STOP = new Set("a an the and or of to in on at for by with from as is are was were be been this that it its you your we our they their not no per each any all if than so into about".split(" "));
const words = (s) => (s.toLowerCase().match(/[a-z0-9][a-z0-9-]*/g) || []).filter((w) => !STOP.has(w));
const splitSentences = (line) => line.split(/(?<=[.!?])\s+/).filter((s) => s.trim());
// Short lines without closing punctuation read as headings ("3. Carry Forward and Encashment").
const isHeading = (line) => line.length < 70 && !/[.:;,]$/.test(line.trim()) && words(line).length <= 8;

/** The answer sentences that cite source `index`. */
function citingSentences(answer, index) {
  return answer
    .split(/(?<=[.!?])\s+|\n+/)
    .filter((s) => new RegExp(`\\[${index}\\]`).test(s))
    .map((s) => s.replace(/\[\d+\]/g, ""));
}

/**
 * Lay the source text out line by line (keeping headings), and mark the sentences that best support
 * the answer: those sharing most of their key words with the sentences that cite this source.
 * If nothing scores well, the whole passage is marked (the citation points at the whole chunk).
 */
/** PDFs break lines where the page wrapped them; re-join lines that don't end a sentence. */
function paragraphs(text) {
  const out = [];
  for (const raw of text.split(/\n+/)) {
    const line = raw.trim();
    if (!line) continue;
    const prev = out[out.length - 1];
    if (prev && !isHeading(prev) && !isHeading(line) && !/[.!?:;]$/.test(prev)) out[out.length - 1] = `${prev} ${line}`;
    else out.push(line);
  }
  return out;
}

function layout(text, answer, index) {
  const lines = paragraphs(text);
  const target = new Set(citingSentences(answer, index).flatMap(words));
  const sentences = lines.flatMap((l, li) => (isHeading(l) ? [] : splitSentences(l).map((s) => ({ li, s }))));
  const score = (s) => {
    const w = words(s);
    return w.length && target.size ? w.filter((x) => target.has(x)).length / Math.min(w.length, target.size) : 0;
  };
  const best = Math.max(0, ...sentences.map((x) => score(x.s)));
  const markAll = best < 0.25;
  const cut = Math.max(0.25, best * 0.6);
  return lines.map((l, li) =>
    isHeading(l)
      ? { heading: l }
      : { parts: sentences.filter((x) => x.li === li).map((x) => ({ s: x.s, on: markAll || score(x.s) >= cut })) },
  );
}

export default function SourcePane({ citation, answer, onClose }) {
  const [wholePage, setWholePage] = useState(false);
  const enabled = !!citation && citation.available !== false;
  const chunkQ = useQuery({
    queryKey: ["chunk", citation?.chunk_id],
    queryFn: () => documents.chunk(citation.chunk_id),
    enabled,
  });
  const pageQ = useQuery({
    queryKey: ["page", citation?.document_id, citation?.page],
    queryFn: () => documents.pageChunks(citation.document_id, citation.page),
    enabled: enabled && wholePage && !!citation.page,
  });
  const blocks = useMemo(
    () => (chunkQ.data ? layout(chunkQ.data.text, answer || "", citation.index) : []),
    [chunkQ.data, answer, citation?.index],
  );

  if (!citation) return null;
  return (
    <aside aria-label="Source" className="source-pane-enter flex h-full flex-col border-l border-rule bg-paper">
      <div className="flex items-start justify-between gap-3 border-b border-rule bg-sheet px-5 py-3">
        <div className="min-w-0">
          <p className="text-xs text-muted">Source {citation.index}</p>
          <h2 className="truncate font-semibold" title={citation.title}>
            {citation.title}
          </h2>
        </div>
        <IconButton label="Close source" onClick={onClose}>
          <X size={18} />
        </IconButton>
      </div>

      <div className="flex-1 overflow-y-auto p-5">
        {citation.available === false ? (
          <p className="text-muted">
            This source is no longer available to you. It may have been removed, or your access to its category changed.
          </p>
        ) : chunkQ.isLoading ? (
          <Loading label="Opening source…" />
        ) : chunkQ.error ? (
          <ErrorNote error={chunkQ.error} />
        ) : (
          <>
            {/* The sheet: a page of the document with the supporting sentences marked. */}
            <article className="relative bg-sheet px-6 pb-11 pt-6 shadow-[0_1px_0_#d6dcd8,0_8px_24px_-12px_rgba(27,42,58,.25)]">
              {chunkQ.data.section && !blocks.some((b) => b.heading === chunkQ.data.section) && (
                <p className="mb-2 text-sm font-semibold text-ink-soft">{chunkQ.data.section}</p>
              )}
              <div className="prose-doc text-[0.98rem]">
                {blocks.map((b, i) =>
                  b.heading ? (
                    <p key={i} className="mb-1.5 mt-3 font-sans text-[0.9rem] font-semibold text-ink first:mt-0">
                      {b.heading}
                    </p>
                  ) : (
                    <p key={i}>
                      {b.parts.map((p, j) => (
                        <span key={j}>
                          {p.on ? <span className="mark">{p.s}</span> : p.s}{" "}
                        </span>
                      ))}
                    </p>
                  ),
                )}
              </div>
              {locationLabel(citation) && (
                <span className="absolute bottom-3 right-5 font-serif text-sm italic text-muted">{locationLabel(citation)}</span>
              )}
            </article>

            {wholePage && pageQ.data && (
              <div className="mt-5">
                <p className="mb-2 text-sm font-medium text-ink-soft">All text on page {citation.page}</p>
                <div className="prose-doc space-y-3 bg-sheet px-6 py-5 text-[0.95rem] text-ink-soft">
                  {pageQ.data.map((c) => (
                    <p key={c.id} className={cx("whitespace-pre-line", c.id === citation.chunk_id && "text-ink")}>
                      {c.text}
                    </p>
                  ))}
                </div>
              </div>
            )}
          </>
        )}
      </div>

      {citation.available !== false && (
        <div className="flex flex-wrap gap-2 border-t border-rule bg-sheet px-5 py-3">
          {citation.page && !wholePage && (
            <Button size="sm" variant="secondary" onClick={() => setWholePage(true)}>
              <FileStack size={15} /> Show whole page
            </Button>
          )}
          <Button
            size="sm"
            variant="secondary"
            onClick={() => downloadFile(`/documents/${citation.document_id}/download`, citation.title)}
          >
            <ExternalLink size={15} /> Open original
          </Button>
        </div>
      )}
    </aside>
  );
}
