import { useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Download, RotateCcw, Search, Trash2, Upload, UploadCloud, X } from "lucide-react";
import { downloadFile } from "../api/client";
import { documents, me } from "../api/endpoints";
import { useAuth } from "../auth/AuthContext";
import {
  Badge, Button, ConfirmDialog, Empty, ErrorNote, Field, IconButton, Input, Loading, Modal, PageHeader, Select, Textarea,
  cx, formatBytes, formatDate, useToast,
} from "../components/ui";

const STATUS = {
  ready: { tone: "green", label: "Ready" },
  processing: { tone: "amber", label: "Processing" },
  pending: { tone: "amber", label: "Queued" },
  failed: { tone: "red", label: "Failed" },
};
const ACCEPT = ".pdf,.docx,.txt,.csv";

export default function DocumentsPage() {
  const { canManageDocuments } = useAuth();
  const [params, setParams] = useSearchParams();
  const [filters, setFilters] = useState({ q: "", category_id: "", status: params.get("status") || "", date_from: "", date_to: "" });
  const [uploadOpen, setUploadOpen] = useState(false);
  const openId = params.get("open");
  const catsQ = useQuery({ queryKey: ["my-categories"], queryFn: me.categories });

  const listQ = useQuery({
    queryKey: ["documents", filters],
    queryFn: () => documents.list({ ...filters, limit: 200 }),
    // keep polling while anything is still being processed
    refetchInterval: (q) => (q.state.data?.some((d) => d.status === "pending" || d.status === "processing") ? 2000 : false),
  });
  const setF = (k) => (e) => setFilters({ ...filters, [k]: e.target.value });
  const open = (id) => setParams(id ? { open: id } : {});

  return (
    <div className="mx-auto max-w-6xl">
      <PageHeader
        title="Documents"
        description={canManageDocuments ? "Upload, version and remove the documents CorpMind answers from." : "Documents you can ask about."}
        actions={
          canManageDocuments && (
            <Button onClick={() => setUploadOpen(true)}>
              <Upload size={16} /> Upload documents
            </Button>
          )
        }
      />

      <div className="mb-4 flex flex-wrap items-end gap-3">
        <div className="relative w-full max-w-xs">
          <Search size={16} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted" />
          <Input className="pl-9" placeholder="Search titles" value={filters.q} onChange={setF("q")} aria-label="Search titles" />
        </div>
        <Select className="w-48" value={filters.category_id} onChange={setF("category_id")} aria-label="Category">
          <option value="">All categories</option>
          {catsQ.data?.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </Select>
        {canManageDocuments && (
          <Select className="w-36" value={filters.status} onChange={setF("status")} aria-label="Status">
            <option value="">Any status</option>
            <option value="ready">Ready</option>
            <option value="processing">Processing</option>
            <option value="failed">Failed</option>
          </Select>
        )}
        <label className="text-sm">
          <span className="mb-1 block text-muted">Dated from</span>
          <Input type="date" className="w-40" value={filters.date_from} onChange={setF("date_from")} />
        </label>
        <label className="text-sm">
          <span className="mb-1 block text-muted">Until</span>
          <Input type="date" className="w-40" value={filters.date_to} onChange={setF("date_to")} />
        </label>
      </div>

      {listQ.isLoading ? (
        <Loading />
      ) : listQ.error ? (
        <ErrorNote error={listQ.error} />
      ) : listQ.data.length === 0 ? (
        <Empty
          title="No documents found"
          action={canManageDocuments && <Button onClick={() => setUploadOpen(true)}>Upload documents</Button>}
        >
          {Object.values(filters).some(Boolean) ? "Try clearing the filters." : "Nothing has been uploaded to your categories yet."}
        </Empty>
      ) : (
        <div className="overflow-x-auto border border-rule bg-sheet">
          <table className="w-full text-left text-[0.93rem]">
            <thead className="border-b border-rule bg-paper text-sm text-ink-soft">
              <tr>
                <th className="px-4 py-2.5 font-medium">Title</th>
                <th className="px-4 py-2.5 font-medium">Category</th>
                <th className="px-4 py-2.5 font-medium">Version</th>
                <th className="px-4 py-2.5 font-medium">Status</th>
                <th className="px-4 py-2.5 font-medium" title="Effective date if set, otherwise upload date">Dated</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-rule">
              {listQ.data.map((d) => {
                const st = STATUS[d.status] || STATUS.ready;
                return (
                  <tr key={d.id} className={cx("cursor-pointer hover:bg-paper", openId === d.id && "bg-ledger-tint")} onClick={() => open(d.id)}>
                    <td className="px-4 py-2.5">
                      <button className="text-left font-medium hover:underline" onClick={(e) => (e.stopPropagation(), open(d.id))}>
                        {d.title}
                      </button>
                      {d.injection_flagged && canManageDocuments && (
                        <AlertTriangle size={14} className="ml-1.5 inline text-amber" aria-label="Contains suspicious instructions" />
                      )}
                    </td>
                    <td className="px-4 py-2.5 text-ink-soft">{d.category_name}</td>
                    <td className="px-4 py-2.5 text-ink-soft">
                      v{d.current_version || "–"}
                      {d.version_count > 1 && <span className="text-muted"> of {d.version_count}</span>}
                    </td>
                    <td className="px-4 py-2.5">
                      <Badge tone={st.tone}>{st.label}</Badge>
                    </td>
                    <td className="px-4 py-2.5 text-ink-soft">{formatDate(d.active_version?.effective_date || d.created_at)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {openId && <DocumentDrawer id={openId} onClose={() => open(null)} />}
      {uploadOpen && <UploadModal categories={catsQ.data || []} onClose={() => setUploadOpen(false)} />}
    </div>
  );
}

function DocumentDrawer({ id, onClose }) {
  const { canManageDocuments } = useAuth();
  const qc = useQueryClient();
  const toast = useToast();
  const [confirm, setConfirm] = useState(null);
  const fileRef = useRef(null);
  const docQ = useQuery({
    queryKey: ["document", id],
    queryFn: () => documents.get(id),
    refetchInterval: (q) => (q.state.data?.versions?.some((v) => v.status === "pending" || v.status === "processing") ? 2000 : false),
  });
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["document", id] });
    qc.invalidateQueries({ queryKey: ["documents"] });
  };
  const act = useMutation({
    mutationFn: ({ kind, versionId, file }) =>
      kind === "activate" ? documents.activate(id, versionId)
      : kind === "reprocess" ? documents.reprocess(id, versionId)
      : kind === "removeVersion" ? documents.removeVersion(id, versionId)
      : kind === "uploadVersion" ? documents.uploadVersion(id, file)
      : documents.remove(id),
    onSuccess: (_, { kind }) => {
      setConfirm(null);
      toast(
        { activate: "Version activated", reprocess: "Reprocessing started", removeVersion: "Version deleted", uploadVersion: "New version uploaded", remove: "Document deleted" }[kind],
      );
      if (kind === "remove") {
        qc.invalidateQueries({ queryKey: ["documents"] });
        onClose();
      } else refresh();
    },
    onError: (e) => toast(e.message, "red"),
  });

  const d = docQ.data;
  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-ink/30" onClick={onClose}>
      <aside aria-label="Document details" className="source-pane-enter flex h-full w-full max-w-lg flex-col bg-sheet shadow-2xl" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-start justify-between gap-3 border-b border-rule px-5 py-4">
          <div className="min-w-0">
            <h2 className="text-lg font-semibold">{d?.title || "Document"}</h2>
            {d && <p className="text-sm text-muted">{d.category_name}</p>}
          </div>
          <IconButton label="Close" onClick={onClose}>
            <X size={18} />
          </IconButton>
        </div>
        <div className="flex-1 overflow-y-auto px-5 py-4">
          {docQ.isLoading ? (
            <Loading />
          ) : docQ.error ? (
            <ErrorNote error={docQ.error} />
          ) : (
            <>
              {d.description && <p className="mb-4 text-ink-soft">{d.description}</p>}
              <div className="mb-3 flex items-center justify-between">
                <h3 className="font-semibold">Versions</h3>
                {canManageDocuments && (
                  <>
                    <input
                      ref={fileRef}
                      type="file"
                      accept={ACCEPT}
                      hidden
                      onChange={(e) => {
                        const f = e.target.files?.[0];
                        if (f) act.mutate({ kind: "uploadVersion", file: f });
                        e.target.value = "";
                      }}
                    />
                    <Button size="sm" variant="secondary" onClick={() => fileRef.current?.click()} loading={act.isPending && act.variables?.kind === "uploadVersion"}>
                      <Upload size={14} /> Upload new version
                    </Button>
                  </>
                )}
              </div>
              <ol className="space-y-3">
                {[...d.versions].reverse().map((v) => {
                  const st = STATUS[v.status];
                  return (
                    <li key={v.id} className={cx("rounded-md border p-3", v.is_active ? "border-ledger bg-ledger-tint/50" : "border-rule")}>
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="font-semibold">Version {v.version_number}</span>
                        {v.is_active && <Badge tone="ink">In use</Badge>}
                        <Badge tone={st.tone}>{st.label}</Badge>
                      </div>
                      <p className="mt-1 text-sm text-ink-soft">
                        {v.original_filename}, {formatBytes(v.file_size)}
                        {v.page_count ? `, ${v.page_count} ${v.page_count === 1 ? "page" : "pages"}` : ""}
                        {v.chunk_count ? `, ${v.chunk_count} ${v.chunk_count === 1 ? "passage" : "passages"}` : ""}
                      </p>
                      <p className="text-sm text-muted">
                        Uploaded {formatDate(v.created_at, true)}
                        {v.effective_date && `, effective ${formatDate(v.effective_date)}`}
                      </p>
                      {v.error_message && <p className="mt-2 text-sm text-brick">{v.error_message}</p>}
                      {v.injection_flagged && canManageDocuments && (
                        <div className="mt-2 border-l-2 border-amber bg-amber-tint/60 px-3 py-2 text-sm">
                          <p className="font-medium text-amber">Contains text that looks like instructions to an AI</p>
                          <p className="text-ink-soft">CorpMind treats it as plain content and won't follow it. Review the file if this wasn't expected.</p>
                          {v.injection_findings?.slice(0, 3).map((f, i) => (
                            <p key={i} className="mt-1 font-serif italic text-ink-soft">
                              "{f.excerpt}"{f.page ? `, page ${f.page}` : ""}
                            </p>
                          ))}
                        </div>
                      )}
                      <div className="mt-2 flex flex-wrap gap-1.5">
                        {(v.is_active || canManageDocuments) && v.status === "ready" && (
                          <Button size="sm" variant="ghost" onClick={() => downloadFile(`/documents/${id}/download?version=${v.version_number}`, v.original_filename)}>
                            <Download size={14} /> Open
                          </Button>
                        )}
                        {canManageDocuments && !v.is_active && v.status === "ready" && (
                          <Button size="sm" variant="ghost" onClick={() => act.mutate({ kind: "activate", versionId: v.id })}>
                            <RotateCcw size={14} /> Use this version
                          </Button>
                        )}
                        {canManageDocuments && v.status === "failed" && (
                          <Button size="sm" variant="ghost" onClick={() => act.mutate({ kind: "reprocess", versionId: v.id })}>
                            <RotateCcw size={14} /> Reprocess
                          </Button>
                        )}
                        {canManageDocuments && v.status !== "processing" && d.versions.length > 1 && (
                          <Button size="sm" variant="ghost" className="hover:!bg-brick-tint hover:!text-brick" onClick={() => setConfirm({ kind: "removeVersion", versionId: v.id, n: v.version_number })}>
                            <Trash2 size={14} /> Delete version
                          </Button>
                        )}
                      </div>
                    </li>
                  );
                })}
              </ol>
            </>
          )}
        </div>
        {canManageDocuments && d && (
          <div className="border-t border-rule px-5 py-3">
            <Button variant="danger" size="sm" onClick={() => setConfirm({ kind: "remove" })}>
              <Trash2 size={14} /> Delete document
            </Button>
          </div>
        )}
      </aside>
      <ConfirmDialog
        open={!!confirm}
        title={confirm?.kind === "remove" ? "Delete this document?" : `Delete version ${confirm?.n}?`}
        body={
          confirm?.kind === "remove"
            ? `"${d?.title}", all its versions and its search index entries will be permanently deleted. Answers will no longer use it.`
            : "This version's file and search index entries will be permanently deleted. If it's in use, the newest other ready version takes over."
        }
        confirmLabel={confirm?.kind === "remove" ? "Delete document" : "Delete version"}
        loading={act.isPending}
        onConfirm={() => act.mutate(confirm)}
        onClose={() => setConfirm(null)}
      />
    </div>
  );
}

function UploadModal({ categories, onClose }) {
  const qc = useQueryClient();
  const [files, setFiles] = useState([]);
  const [categoryId, setCategoryId] = useState("");
  const [effectiveDate, setEffectiveDate] = useState("");
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [drag, setDrag] = useState(false);
  const inputRef = useRef(null);
  const tooBig = useMemo(() => files.filter((f) => f.size > 20 * 1024 * 1024), [files]);

  const upload = useMutation({
    mutationFn: () => documents.upload(files, categoryId, { title: files.length === 1 ? title : undefined, description, effectiveDate }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["documents"] }),
  });

  const add = (list) => {
    const incoming = [...list].filter((f) => /\.(pdf|docx|txt|csv)$/i.test(f.name));
    setFiles((prev) => [...prev, ...incoming.filter((f) => !prev.some((p) => p.name === f.name && p.size === f.size))].slice(0, 20));
  };
  const done = upload.data;

  return (
    <Modal
      open
      wide
      onClose={onClose}
      title="Upload documents"
      footer={
        done ? (
          <Button onClick={onClose}>Done</Button>
        ) : (
          <>
            <Button variant="secondary" onClick={onClose}>
              Cancel
            </Button>
            <Button onClick={() => upload.mutate()} loading={upload.isPending} disabled={!files.length || !categoryId || tooBig.length > 0}>
              Upload {files.length > 0 ? files.length : ""} {files.length === 1 ? "file" : "files"}
            </Button>
          </>
        )
      }
    >
      {done ? (
        <div>
          <p className="mb-3 text-ink-soft">Accepted files are being processed. They become searchable when their status shows Ready.</p>
          <ul className="divide-y divide-rule border-y border-rule">
            {done.map((r, i) => (
              <li key={i} className="flex items-start justify-between gap-3 py-2">
                <div className="min-w-0">
                  <p className="truncate font-medium">{r.filename}</p>
                  {r.message && <p className="text-sm text-muted">{r.message}</p>}
                </div>
                <Badge tone={r.status === "accepted" ? "green" : r.status === "duplicate" ? "amber" : "red"}>
                  {{ accepted: "Accepted", duplicate: "Already uploaded", rejected: "Rejected" }[r.status]}
                </Badge>
              </li>
            ))}
          </ul>
        </div>
      ) : (
        <div className="space-y-4">
          <div
            onDragOver={(e) => (e.preventDefault(), setDrag(true))}
            onDragLeave={() => setDrag(false)}
            onDrop={(e) => {
              e.preventDefault();
              setDrag(false);
              add(e.dataTransfer.files);
            }}
            className={cx("rounded-md border-2 border-dashed px-4 py-7 text-center", drag ? "border-ledger bg-ledger-tint" : "border-rule-strong")}
          >
            <UploadCloud className="mx-auto mb-2 text-muted" />
            <p>
              Drag files here, or{" "}
              <button type="button" className="font-medium text-ledger underline-offset-2 hover:underline" onClick={() => inputRef.current?.click()}>
                choose files
              </button>
            </p>
            <p className="mt-1 text-sm text-muted">PDF, Word (.docx), text or CSV. Up to 20 files, 20 MB each.</p>
            <input ref={inputRef} type="file" multiple accept={ACCEPT} hidden onChange={(e) => (add(e.target.files), (e.target.value = ""))} />
          </div>
          {files.length > 0 && (
            <ul className="max-h-40 divide-y divide-rule overflow-y-auto border-y border-rule text-sm">
              {files.map((f) => (
                <li key={f.name + f.size} className="flex items-center justify-between gap-2 py-1.5">
                  <span className="truncate">{f.name}</span>
                  <span className={cx("shrink-0", f.size > 20 * 1024 * 1024 ? "text-brick" : "text-muted")}>{formatBytes(f.size)}</span>
                  <IconButton label={`Remove ${f.name}`} onClick={() => setFiles(files.filter((x) => x !== f))}>
                    <X size={14} />
                  </IconButton>
                </li>
              ))}
            </ul>
          )}
          {tooBig.length > 0 && <ErrorNote error={`${tooBig.length} file(s) are over 20 MB. Remove them to continue.`} />}
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Category" hint="Controls who can see these documents." htmlFor="cat">
              <Select id="cat" value={categoryId} onChange={(e) => setCategoryId(e.target.value)}>
                <option value="">Choose a category</option>
                {categories.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="Effective date" hint="Optional. Used for date filters." htmlFor="eff">
              <Input id="eff" type="date" value={effectiveDate} onChange={(e) => setEffectiveDate(e.target.value)} />
            </Field>
          </div>
          {files.length === 1 && (
            <Field label="Title" hint="Optional. Defaults to the file name. Uploading with an existing title adds a new version." htmlFor="title">
              <Input id="title" value={title} maxLength={255} onChange={(e) => setTitle(e.target.value)} />
            </Field>
          )}
          <Field label="Description" hint="Optional." htmlFor="desc">
            <Textarea id="desc" rows={2} maxLength={2000} value={description} onChange={(e) => setDescription(e.target.value)} />
          </Field>
          <ErrorNote error={upload.error} />
        </div>
      )}
    </Modal>
  );
}
