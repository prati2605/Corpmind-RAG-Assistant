import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, SendHorizontal } from "lucide-react";
import { admin, chat, me } from "../api/endpoints";
import { useAuth } from "../auth/AuthContext";
import { Button, ErrorNote, Input, Loading, formatDate, relativeTime } from "../components/ui";

const plural = (n, one, many = one + "s") => `${n} ${n === 1 ? one : many}`;

export default function DashboardPage() {
  const { user, isAdmin } = useAuth();
  const { data: s, isLoading, error } = useQuery({ queryKey: ["stats"], queryFn: me.stats });
  const hour = new Date().getHours();
  const greeting = hour < 12 ? "Good morning" : hour < 17 ? "Good afternoon" : "Good evening";

  return (
    <div className="mx-auto max-w-5xl">
      <h1 className="text-3xl font-semibold tracking-tight">
        {greeting}, {user.full_name.split(" ")[0]}
      </h1>
      {isLoading ? (
        <Loading />
      ) : error ? (
        <ErrorNote error={error} className="mt-4" />
      ) : (
        <>
          <p className="mt-2 max-w-2xl text-lg text-ink-soft">
            You can search {plural(s.accessible_documents, "document")} across{" "}
            {plural(s.categories.length, "category", "categories")}.{" "}
            {s.my_questions_last_7_days > 0
              ? `You asked ${plural(s.my_questions_last_7_days, "question")} in the last 7 days.`
              : "Ask your first question below."}
          </p>

          <QuickAsk />

          {isAdmin && <NeedsAttention />}

          <div className="mt-10 grid gap-10 lg:grid-cols-[1.2fr_1fr]">
            <section>
              <div className="mb-3 flex items-baseline justify-between">
                <h2 className="text-lg font-semibold">Recent conversations</h2>
                <Link to="/history" className="text-sm text-ledger hover:underline">
                  All history
                </Link>
              </div>
              {s.recent_conversations.length === 0 ? (
                <p className="text-muted">No conversations yet.</p>
              ) : (
                <ul className="divide-y divide-rule border-y border-rule">
                  {s.recent_conversations.map((c) => (
                    <li key={c.id}>
                      <Link to={`/chat/${c.id}`} className="flex items-baseline justify-between gap-4 px-1 py-2.5 hover:bg-sheet">
                        <span className="truncate">{c.title}</span>
                        <span className="shrink-0 text-sm text-muted">{relativeTime(c.updated_at)}</span>
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
            </section>

            <section>
              <h2 className="mb-3 text-lg font-semibold">Recently updated documents</h2>
              {s.recent_documents.length === 0 ? (
                <p className="text-muted">No documents yet.</p>
              ) : (
                <ul className="space-y-2.5">
                  {s.recent_documents.map((d) => (
                    <li key={d.id}>
                      <Link to={`/documents?open=${d.id}`} className="font-medium hover:underline">
                        {d.title}
                      </Link>
                      <p className="text-sm text-muted">
                        {d.category}, updated {formatDate(d.processed_at)}
                      </p>
                    </li>
                  ))}
                </ul>
              )}
              <h2 className="mb-2 mt-8 text-lg font-semibold">Your categories</h2>
              <ul className="text-[0.95rem]">
                {s.categories.map((c) => (
                  <li key={c.id} className="flex justify-between border-b border-dotted border-rule-strong py-1.5">
                    <span>{c.name}</span>
                    <span className="text-muted">{plural(c.documents, "document")}</span>
                  </li>
                ))}
              </ul>
            </section>
          </div>
        </>
      )}
    </div>
  );
}

function QuickAsk() {
  const [q, setQ] = useState("");
  const navigate = useNavigate();
  const qc = useQueryClient();
  const ask = useMutation({
    mutationFn: () => chat.ask(q.trim(), null, {}),
    onSuccess: (res) => {
      qc.setQueryData(["conversation", res.conversation_id], {
        id: res.conversation_id,
        title: res.conversation_title,
        messages: [res.user_message, res.assistant_message],
      });
      qc.invalidateQueries({ queryKey: ["conversations"] });
      navigate(`/chat/${res.conversation_id}`);
    },
  });
  return (
    <form
      className="mt-6 max-w-2xl"
      onSubmit={(e) => {
        e.preventDefault();
        if (q.trim()) ask.mutate();
      }}
    >
      <div className="flex gap-2">
        <Input
          aria-label="Ask a question"
          placeholder="How many days of annual leave do I get?"
          value={q}
          maxLength={2000}
          onChange={(e) => setQ(e.target.value)}
          className="h-12 text-base"
        />
        <Button type="submit" className="h-12" loading={ask.isPending} disabled={!q.trim()}>
          {!ask.isPending && <SendHorizontal size={18} />} Ask
        </Button>
      </div>
      <ErrorNote error={ask.error} className="mt-2" />
    </form>
  );
}

function NeedsAttention() {
  const { data } = useQuery({ queryKey: ["analytics", 30], queryFn: () => admin.analytics(30) });
  if (!data) return null;
  const failed = data.documents.versions_by_status.failed;
  const flagged = data.documents.injection_flagged;
  const negative = data.feedback.negative;
  const items = [
    failed > 0 && { text: `${plural(failed, "document version")} failed to process`, to: "/documents?status=failed" },
    flagged > 0 && { text: `${plural(flagged, "document")} contain text that looks like instructions to the AI`, to: "/documents" },
    negative > 0 && { text: `${plural(negative, "answer")} rated not helpful in the last 30 days`, to: "/admin?tab=feedback" },
  ].filter(Boolean);
  if (!items.length) return null;
  return (
    <section className="mt-8 max-w-2xl border-l-4 border-amber bg-amber-tint/60 px-4 py-3">
      <h2 className="flex items-center gap-2 font-semibold text-amber">
        <AlertTriangle size={17} /> Needs your attention
      </h2>
      <ul className="mt-1.5 space-y-1">
        {items.map((i) => (
          <li key={i.text}>
            <Link to={i.to} className="text-ink underline-offset-2 hover:underline">
              {i.text}
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}
