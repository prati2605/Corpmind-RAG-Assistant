import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Search, ThumbsDown, ThumbsUp, Trash2 } from "lucide-react";
import { admin } from "../api/endpoints";
import { useAuth } from "../auth/AuthContext";
import {
  Badge, Button, ConfirmDialog, ErrorNote, Field, IconButton, Input, PasswordInput, Loading, Modal, PageHeader, ROLE_LABEL, Select, cx,
  formatBytes, formatDate, useToast,
} from "../components/ui";

const TABS = [
  { id: "users", label: "Users" },
  { id: "access", label: "Access by category" },
  { id: "analytics", label: "Usage and quality" },
  { id: "feedback", label: "Answer feedback" },
  { id: "audit", label: "Audit log" },
];

export default function AdminPage() {
  const [params, setParams] = useSearchParams();
  const tab = params.get("tab") || "users";
  return (
    <div className="mx-auto max-w-6xl">
      <PageHeader title="Admin" description="Manage people, who can read what, and how well answers are working." />
      <div role="tablist" aria-label="Admin sections" className="mb-6 flex flex-wrap gap-1 border-b border-rule">
        {TABS.map((t) => (
          <button
            key={t.id}
            role="tab"
            aria-selected={tab === t.id}
            onClick={() => setParams({ tab: t.id })}
            className={cx(
              "-mb-px border-b-2 px-3.5 py-2 text-[0.95rem]",
              tab === t.id ? "border-ledger font-medium text-ink" : "border-transparent text-muted hover:text-ink",
            )}
          >
            {t.label}
          </button>
        ))}
      </div>
      {tab === "users" && <Users />}
      {tab === "access" && <Access />}
      {tab === "analytics" && <Analytics />}
      {tab === "feedback" && <FeedbackReview />}
      {tab === "audit" && <Audit />}
    </div>
  );
}

/* ---------------- Users ---------------- */
function Users() {
  const { user: me } = useAuth();
  const qc = useQueryClient();
  const toast = useToast();
  const [q, setQ] = useState("");
  const [role, setRole] = useState("");
  const [creating, setCreating] = useState(false);
  const usersQ = useQuery({ queryKey: ["admin-users", q, role], queryFn: () => admin.users({ q: q || undefined, role: role || undefined }) });
  const update = useMutation({
    mutationFn: ({ id, data }) => admin.updateUser(id, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin-users"] });
      toast("User updated");
    },
    onError: (e) => toast(e.message, "red"),
  });

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <div className="relative w-full max-w-xs">
          <Search size={16} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted" />
          <Input className="pl-9" placeholder="Search name or email" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search users" />
        </div>
        <Select className="w-40" value={role} onChange={(e) => setRole(e.target.value)} aria-label="Role">
          <option value="">All roles</option>
          <option value="admin">Admin</option>
          <option value="hr">HR</option>
          <option value="employee">Employee</option>
        </Select>
        <Button className="ml-auto" onClick={() => setCreating(true)}>
          <Plus size={16} /> Add user
        </Button>
      </div>
      {usersQ.isLoading ? (
        <Loading />
      ) : usersQ.error ? (
        <ErrorNote error={usersQ.error} />
      ) : (
        <div className="overflow-x-auto border border-rule bg-sheet">
          <table className="w-full text-left text-[0.93rem]">
            <thead className="border-b border-rule bg-paper text-sm text-ink-soft">
              <tr>
                <th className="px-4 py-2.5 font-medium">Name</th>
                <th className="px-4 py-2.5 font-medium">Role</th>
                <th className="px-4 py-2.5 font-medium">Last sign-in</th>
                <th className="px-4 py-2.5 font-medium">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-rule">
              {usersQ.data.map((u) => {
                const self = u.id === me.id;
                return (
                  <tr key={u.id} className={cx(!u.is_active && "text-muted")}>
                    <td className="px-4 py-2.5">
                      <p className="font-medium">{u.full_name}</p>
                      <p className="text-sm text-muted">
                        {u.email}
                        {u.department ? `, ${u.department}` : ""}
                      </p>
                    </td>
                    <td className="px-4 py-2.5">
                      <Select
                        className="h-8 w-32 py-0 text-sm"
                        value={u.role}
                        disabled={self}
                        title={self ? "You can't change your own role" : undefined}
                        aria-label={`Role for ${u.full_name}`}
                        onChange={(e) => update.mutate({ id: u.id, data: { role: e.target.value } })}
                      >
                        <option value="employee">Employee</option>
                        <option value="hr">HR</option>
                        <option value="admin">Admin</option>
                      </Select>
                    </td>
                    <td className="px-4 py-2.5 text-ink-soft">{u.last_login_at ? formatDate(u.last_login_at, true) : "Never"}</td>
                    <td className="px-4 py-2.5">
                      {self ? (
                        <Badge tone="green">You</Badge>
                      ) : (
                        <label className="flex items-center gap-2 text-sm">
                          <input
                            type="checkbox"
                            className="accent-ledger"
                            checked={u.is_active}
                            onChange={(e) => update.mutate({ id: u.id, data: { is_active: e.target.checked } })}
                          />
                          {u.is_active ? "Active" : "Deactivated"}
                        </label>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      {creating && <CreateUser onClose={() => setCreating(false)} />}
    </div>
  );
}

function CreateUser({ onClose }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [f, setF] = useState({ full_name: "", email: "", department: "", role: "employee", password: "" });
  const create = useMutation({
    mutationFn: () => admin.createUser({ ...f, department: f.department || null }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin-users"] });
      toast("User added");
      onClose();
    },
  });
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });
  return (
    <Modal
      open
      onClose={onClose}
      title="Add user"
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button onClick={() => create.mutate()} loading={create.isPending} disabled={!f.full_name || !f.email || f.password.length < 10}>
            Add user
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <Field label="Full name" htmlFor="nu-name">
          <Input id="nu-name" value={f.full_name} onChange={set("full_name")} />
        </Field>
        <Field label="Work email" htmlFor="nu-email">
          <Input id="nu-email" type="email" value={f.email} onChange={set("email")} />
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Role" htmlFor="nu-role">
            <Select id="nu-role" value={f.role} onChange={set("role")}>
              <option value="employee">Employee</option>
              <option value="hr">HR</option>
              <option value="admin">Admin</option>
            </Select>
          </Field>
          <Field label="Department" htmlFor="nu-dep">
            <Input id="nu-dep" value={f.department} onChange={set("department")} />
          </Field>
        </div>
        <Field label="Temporary password" hint="At least 10 characters, with letters and numbers. Share it securely; they can change it in Settings." htmlFor="nu-pw">
          <PasswordInput id="nu-pw" autoComplete="new-password" value={f.password} onChange={set("password")} />
        </Field>
        <ErrorNote error={create.error} />
      </div>
    </Modal>
  );
}

/* ---------------- Access matrix ---------------- */
function Access() {
  const qc = useQueryClient();
  const toast = useToast();
  const [adding, setAdding] = useState(false);
  const [deleting, setDeleting] = useState(null);
  const catsQ = useQuery({ queryKey: ["admin-categories"], queryFn: admin.categories });
  const setRoles = useMutation({
    mutationFn: ({ id, roles }) => admin.setCategoryRoles(id, roles),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin-categories"] });
      qc.invalidateQueries({ queryKey: ["my-categories"] });
      toast("Access updated. It applies to the next question anyone asks.");
    },
    onError: (e) => toast(e.message, "red"),
  });
  const remove = useMutation({
    mutationFn: (id) => admin.deleteCategory(id),
    onSuccess: () => {
      setDeleting(null);
      qc.invalidateQueries({ queryKey: ["admin-categories"] });
      toast("Category deleted");
    },
    onError: (e) => {
      setDeleting(null);
      toast(e.message, "red");
    },
  });

  if (catsQ.isLoading) return <Loading />;
  if (catsQ.error) return <ErrorNote error={catsQ.error} />;
  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <p className="max-w-2xl text-ink-soft">
          Tick who can read each category. CorpMind only searches categories the person's role can read, so a cleared box
          means those documents never appear in their answers. Admins can always read everything.
        </p>
        <Button onClick={() => setAdding(true)}>
          <Plus size={16} /> Add category
        </Button>
      </div>
      <div className="overflow-x-auto border border-rule bg-sheet">
        <table className="w-full text-left text-[0.93rem]">
          <thead className="border-b border-rule bg-paper text-sm text-ink-soft">
            <tr>
              <th className="px-4 py-2.5 font-medium">Category</th>
              <th className="w-28 px-4 py-2.5 text-center font-medium">Employee</th>
              <th className="w-28 px-4 py-2.5 text-center font-medium">HR</th>
              <th className="w-28 px-4 py-2.5 text-center font-medium">Admin</th>
              <th className="w-12" />
            </tr>
          </thead>
          <tbody className="divide-y divide-rule">
            {catsQ.data.map((c) => (
              <tr key={c.id}>
                <td className="px-4 py-2.5">
                  <p className="font-medium">{c.name}</p>
                  {c.description && <p className="text-sm text-muted">{c.description}</p>}
                </td>
                {["employee", "hr"].map((r) => (
                  <td key={r} className="px-4 py-2.5 text-center">
                    <input
                      type="checkbox"
                      className="h-4 w-4 accent-ledger"
                      aria-label={`${ROLE_LABEL[r]} can read ${c.name}`}
                      checked={c.roles.includes(r)}
                      onChange={(e) =>
                        setRoles.mutate({ id: c.id, roles: e.target.checked ? [...c.roles, r] : c.roles.filter((x) => x !== r) })
                      }
                    />
                  </td>
                ))}
                <td className="px-4 py-2.5 text-center">
                  <input type="checkbox" className="h-4 w-4 accent-ledger" checked disabled aria-label="Admins can always read" />
                </td>
                <td className="px-2">
                  <IconButton label={`Delete ${c.name}`} onClick={() => setDeleting(c)} className="hover:bg-brick-tint hover:text-brick">
                    <Trash2 size={15} />
                  </IconButton>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {adding && <AddCategory onClose={() => setAdding(false)} />}
      <ConfirmDialog
        open={!!deleting}
        title={`Delete "${deleting?.name}"?`}
        body="Only empty categories can be deleted. Move or delete its documents first."
        confirmLabel="Delete category"
        loading={remove.isPending}
        onConfirm={() => remove.mutate(deleting.id)}
        onClose={() => setDeleting(null)}
      />
    </div>
  );
}

function AddCategory({ onClose }) {
  const qc = useQueryClient();
  const [f, setF] = useState({ name: "", description: "", roles: ["employee", "hr"] });
  const create = useMutation({
    mutationFn: () => admin.createCategory({ ...f, description: f.description || null }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin-categories"] });
      onClose();
    },
  });
  const toggle = (r) => setF({ ...f, roles: f.roles.includes(r) ? f.roles.filter((x) => x !== r) : [...f.roles, r] });
  return (
    <Modal
      open
      onClose={onClose}
      title="Add category"
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button onClick={() => create.mutate()} loading={create.isPending} disabled={f.name.trim().length < 2}>
            Add category
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <Field label="Name" htmlFor="cat-name">
          <Input id="cat-name" value={f.name} maxLength={80} onChange={(e) => setF({ ...f, name: e.target.value })} />
        </Field>
        <Field label="Description" hint="Optional." htmlFor="cat-desc">
          <Input id="cat-desc" value={f.description} maxLength={255} onChange={(e) => setF({ ...f, description: e.target.value })} />
        </Field>
        <fieldset>
          <legend className="mb-1.5 text-sm font-medium">Who can read it</legend>
          {["employee", "hr"].map((r) => (
            <label key={r} className="mr-5 inline-flex items-center gap-2">
              <input type="checkbox" className="accent-ledger" checked={f.roles.includes(r)} onChange={() => toggle(r)} />
              {ROLE_LABEL[r]}
            </label>
          ))}
          <p className="mt-1 text-sm text-muted">Admins can always read every category.</p>
        </fieldset>
        <ErrorNote error={create.error} />
      </div>
    </Modal>
  );
}

/* ---------------- Analytics ---------------- */
const pct = (v) => (v === null || v === undefined ? "–" : `${Math.round(v * 100)}%`);
const duration = (ms) => (!ms && ms !== 0 ? "–" : ms < 1000 ? `${Math.round(ms)} ms` : `${(ms / 1000).toFixed(1)} s`);

/** One slot per day of the period, so missing days show as gaps rather than stretching the bars. */
function fillDays(perDay, days) {
  const counts = Object.fromEntries(perDay.map((d) => [d.date, d.count]));
  const out = [];
  for (let i = days - 1; i >= 0; i--) {
    const d = new Date(Date.now() - i * 86400000).toISOString().slice(0, 10);
    out.push({ date: d, count: counts[d] || 0 });
  }
  return out;
}

function Analytics() {
  const [days, setDays] = useState(30);
  const { data: a, isLoading, error } = useQuery({ queryKey: ["analytics", days], queryFn: () => admin.analytics(days) });
  if (isLoading) return <Loading />;
  if (error) return <ErrorNote error={error} />;
  const groups = [
    {
      title: "Usage",
      rows: [
        ["Questions answered", a.questions.answered],
        ["People who asked something", a.users.active_in_period],
        ["Active accounts", `${a.users.total_active} (${a.users.by_role.admin} admin, ${a.users.by_role.hr} HR, ${a.users.by_role.employee} employee)`],
      ],
    },
    {
      title: "Answer quality",
      rows: [
        ["Answered with sources", a.questions.not_found_rate === null ? "–" : pct(1 - a.questions.not_found_rate)],
        ["No answer found in documents", pct(a.questions.not_found_rate)],
        ["Average source match", pct(a.questions.avg_confidence)],
        ["Rated helpful", a.feedback.satisfaction === null ? "No ratings yet" : `${pct(a.feedback.satisfaction)} of ${a.feedback.positive + a.feedback.negative} ratings`],
      ],
    },
    {
      title: "Speed",
      rows: [
        ["Typical answer time", duration(a.latency_ms.avg)],
        ["Slowest 5% take longer than", duration(a.latency_ms.p95)],
      ],
    },
    {
      title: "Documents",
      rows: [
        ["Documents", a.documents.total],
        ["Searchable passages", a.documents.active_chunks],
        ["Versions failed to process", a.documents.versions_by_status.failed],
        ["Flagged for embedded instructions", a.documents.injection_flagged],
        ["Storage used", formatBytes(a.documents.storage_bytes)],
      ],
    },
  ];
  const series = fillDays(a.questions.per_day, days);
  const max = Math.max(1, ...series.map((d) => d.count));
  return (
    <div>
      <div className="mb-5 flex items-center gap-2">
        <span className="text-sm text-muted">Period</span>
        <Select className="h-8 w-40 py-0 text-sm" value={days} onChange={(e) => setDays(Number(e.target.value))} aria-label="Period">
          <option value={7}>Last 7 days</option>
          <option value={30}>Last 30 days</option>
          <option value={90}>Last 90 days</option>
        </Select>
      </div>
      <div className="grid gap-x-12 gap-y-8 lg:grid-cols-2">
        {groups.map((g) => (
          <section key={g.title}>
            <h2 className="mb-2 font-semibold">{g.title}</h2>
            <dl className="text-[0.95rem]">
              {g.rows.map(([k, v]) => (
                <div key={k} className="flex justify-between gap-4 border-b border-dotted border-rule-strong py-1.5">
                  <dt className="text-ink-soft">{k}</dt>
                  <dd className="text-right font-medium tabular-nums">{v}</dd>
                </div>
              ))}
            </dl>
          </section>
        ))}
        <section>
          <h2 className="mb-3 font-semibold">Questions per day</h2>
          {a.questions.per_day.length === 0 ? (
            <p className="text-muted">No questions in this period.</p>
          ) : (
            <>
            <div className="flex h-36 items-end gap-[2px] border-b border-rule-strong" role="img" aria-label={`Questions per day, peak ${max}`}>
              {series.map((d) => (
                <div key={d.date} className="group relative flex h-full flex-1 items-end">
                  <div className="w-full rounded-t-[1px] bg-ledger" style={{ height: d.count ? `${Math.max(3, (d.count / max) * 128)}px` : 0 }} />
                  <span className="pointer-events-none absolute -top-6 left-1/2 hidden -translate-x-1/2 whitespace-nowrap rounded bg-ink px-1.5 py-0.5 text-xs text-paper group-hover:block">
                    {d.date}: {d.count}
                  </span>
                </div>
              ))}
            </div>
            <div className="mt-1 flex justify-between text-xs text-muted">
              <span>{formatDate(series[0].date)}</span>
              <span>Peak {max} a day</span>
              <span>Today</span>
            </div>
            </>
          )}
        </section>
        <section>
          <h2 className="mb-2 font-semibold">Most cited documents</h2>
          {a.top_cited_documents.length === 0 ? (
            <p className="text-muted">Nothing cited yet.</p>
          ) : (
            <ol className="text-[0.95rem]">
              {a.top_cited_documents.map((d) => (
                <li key={d.document_id} className="flex justify-between gap-4 border-b border-dotted border-rule-strong py-1.5">
                  <span>{d.title}</span>
                  <span className="tabular-nums text-ink-soft">{d.citations}</span>
                </li>
              ))}
            </ol>
          )}
        </section>
      </div>
    </div>
  );
}

/* ---------------- Feedback ---------------- */
function FeedbackReview() {
  const [rating, setRating] = useState(-1);
  const { data, isLoading, error } = useQuery({ queryKey: ["admin-feedback", rating], queryFn: () => admin.feedback(rating || undefined) });
  return (
    <div>
      <div className="mb-4 flex items-center gap-3">
        <p className="text-ink-soft">Read rated answers next to the question that produced them, to spot missing or unclear documents.</p>
        <Select className="ml-auto h-8 w-44 py-0 text-sm" value={rating} onChange={(e) => setRating(Number(e.target.value))} aria-label="Rating">
          <option value={-1}>Not helpful</option>
          <option value={1}>Helpful</option>
          <option value={0}>All ratings</option>
        </Select>
      </div>
      {isLoading ? (
        <Loading />
      ) : error ? (
        <ErrorNote error={error} />
      ) : data.length === 0 ? (
        <p className="text-muted">No ratings to show.</p>
      ) : (
        <ul className="space-y-4">
          {data.map((f) => (
            <li key={f.id} className="border border-rule bg-sheet p-4">
              <div className="flex flex-wrap items-center gap-2 text-sm text-muted">
                {f.rating === 1 ? <ThumbsUp size={15} className="text-ledger" /> : <ThumbsDown size={15} className="text-brick" />}
                <span>{f.user_email}</span>
                <span>{formatDate(f.created_at, true)}</span>
                {f.grounded === false && <Badge tone="amber">No answer found</Badge>}
              </div>
              <p className="mt-2 font-medium">{f.question}</p>
              <p className="prose-doc mt-1 line-clamp-4 text-[0.95rem] text-ink-soft">{f.answer.replace(/\s*\[\d+\]/g, "")}</p>
              {f.comment && <p className="mt-2 border-l-2 border-brick pl-3 text-sm">{f.comment}</p>}
              {f.cited_documents.length > 0 && <p className="mt-2 text-sm text-muted">Sources used: {f.cited_documents.join(", ")}</p>}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/* ---------------- Audit ---------------- */
const ACTIONS = ["", "auth.", "admin.", "document.", "user."];
function Audit() {
  const [action, setAction] = useState("");
  const { data, isLoading, error } = useQuery({ queryKey: ["audit", action], queryFn: () => admin.auditLogs(action || undefined) });
  return (
    <div>
      <Select className="mb-4 h-8 w-52 py-0 text-sm" value={action} onChange={(e) => setAction(e.target.value)} aria-label="Event type">
        {ACTIONS.map((a) => (
          <option key={a} value={a}>
            {{ "": "All events", "auth.": "Sign-ins", "admin.": "Admin changes", "document.": "Documents", "user.": "Account changes" }[a]}
          </option>
        ))}
      </Select>
      {isLoading ? (
        <Loading />
      ) : error ? (
        <ErrorNote error={error} />
      ) : (
        <div className="overflow-x-auto border border-rule bg-sheet">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-rule bg-paper text-ink-soft">
              <tr>
                <th className="px-4 py-2 font-medium">When</th>
                <th className="px-4 py-2 font-medium">Event</th>
                <th className="px-4 py-2 font-medium">Details</th>
                <th className="px-4 py-2 font-medium">IP</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-rule">
              {data.map((l) => (
                <tr key={l.id}>
                  <td className="whitespace-nowrap px-4 py-2 text-ink-soft">{formatDate(l.created_at, true)}</td>
                  <td className="px-4 py-2 font-medium">{l.action}</td>
                  <td className="px-4 py-2 text-ink-soft">
                    {l.details ? Object.entries(l.details).map(([k, v]) => `${k}: ${Array.isArray(v) ? v.join(", ") : v}`).join("; ") : ""}
                  </td>
                  <td className="px-4 py-2 text-muted">{l.ip_address}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
