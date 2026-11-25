import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Eraser, Filter, Plus, SendHorizontal, ThumbsDown, ThumbsUp, X } from "lucide-react";
import { chat, me } from "../api/endpoints";
import { AnswerMarkdown, Confidence, SourceList } from "../components/Answer";
import SourcePane from "../components/SourcePane";
import { Button, ConfirmDialog, ErrorNote, IconButton, Input, Loading, Textarea, cx, relativeTime, useToast } from "../components/ui";

const EMPTY_FILTERS = { category_ids: [], date_from: "", date_to: "" };

export default function ChatPage() {
  const { conversationId } = useParams();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const toast = useToast();
  const [source, setSource] = useState(null); // { citation, answer, messageId }
  const [pending, setPending] = useState(null); // question being answered
  const [filters, setFilters] = useState(EMPTY_FILTERS);
  const [confirmClear, setConfirmClear] = useState(false);
  const endRef = useRef(null);

  const convQ = useQuery({
    queryKey: ["conversation", conversationId],
    queryFn: () => chat.conversation(conversationId),
    enabled: !!conversationId,
  });
  const listQ = useQuery({ queryKey: ["conversations"], queryFn: () => chat.conversations() });
  const messages = conversationId ? convQ.data?.messages || [] : [];

  useEffect(() => {
    setSource(null);
  }, [conversationId]);
  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "end" });
  }, [messages.length, pending]);

  const ask = useMutation({
    mutationFn: ({ question }) => chat.ask(question, conversationId, cleanFilters(filters)),
    onMutate: ({ question }) => setPending(question),
    onSuccess: (res) => {
      qc.setQueryData(["conversation", res.conversation_id], (old) => ({
        id: res.conversation_id,
        title: res.conversation_title,
        messages: [...(old?.messages || []), res.user_message, res.assistant_message],
      }));
      qc.invalidateQueries({ queryKey: ["conversations"] });
      qc.invalidateQueries({ queryKey: ["stats"] });
      if (res.conversation_id !== conversationId) navigate(`/chat/${res.conversation_id}`, { replace: !conversationId });
    },
    onSettled: () => setPending(null),
  });

  const clear = useMutation({
    mutationFn: () => chat.clear(conversationId),
    onSuccess: () => {
      qc.setQueryData(["conversation", conversationId], (old) => ({ ...old, messages: [] }));
      qc.invalidateQueries({ queryKey: ["conversations"] });
      setConfirmClear(false);
      setSource(null);
      toast("Chat cleared");
    },
  });

  const openCitation = (msg) => (citation) => setSource({ citation, answer: msg.content, messageId: msg.id });

  return (
    <div className={cx("grid h-full", source ? "xl:grid-cols-[15rem_minmax(0,1fr)_26rem] lg:grid-cols-[minmax(0,1fr)_24rem]" : "xl:grid-cols-[15rem_minmax(0,1fr)]")}>
      {/* Conversation list */}
      <nav aria-label="Conversations" className="hidden min-h-0 flex-col border-r border-rule bg-sheet xl:flex">
        <div className="p-3">
          <Button variant="secondary" className="w-full" onClick={() => navigate("/chat")}>
            <Plus size={16} /> New conversation
          </Button>
        </div>
        <ul className="flex-1 overflow-y-auto px-2 pb-3">
          {listQ.data?.map((c) => (
            <li key={c.id}>
              <Link
                to={`/chat/${c.id}`}
                className={cx(
                  "block rounded-[4px] px-2.5 py-2",
                  c.id === conversationId ? "bg-ledger-tint" : "hover:bg-paper",
                )}
              >
                <span className="line-clamp-2 text-sm font-medium leading-snug">{c.title}</span>
                <span className="text-xs text-muted">{relativeTime(c.updated_at)}</span>
              </Link>
            </li>
          ))}
          {listQ.data?.length === 0 && <li className="px-2.5 py-2 text-sm text-muted">Your conversations will appear here.</li>}
        </ul>
      </nav>

      {/* Conversation */}
      <section className="flex min-h-0 min-w-0 flex-col">
        <header className="flex items-center justify-between gap-3 border-b border-rule bg-sheet px-5 py-2.5">
          <h1 className="truncate font-semibold">{conversationId ? convQ.data?.title || " " : "New conversation"}</h1>
          <div className="flex shrink-0 items-center gap-1">
            <IconButton label="New conversation" className="xl:hidden" onClick={() => navigate("/chat")}>
              <Plus size={18} />
            </IconButton>
            {conversationId && messages.length > 0 && (
              <Button size="sm" variant="ghost" className="whitespace-nowrap" onClick={() => setConfirmClear(true)}>
                <Eraser size={15} /> Clear chat
              </Button>
            )}
          </div>
        </header>

        <div className="flex-1 overflow-y-auto">
          <div className="mx-auto max-w-3xl px-5 py-6">
            {conversationId && convQ.isLoading && <Loading />}
            {convQ.error && <ErrorNote error={convQ.error} />}
            {!conversationId && !pending && <Welcome onPick={(q) => ask.mutate({ question: q })} />}
            {conversationId && !convQ.isLoading && messages.length === 0 && !pending && (
              <Welcome onPick={(q) => ask.mutate({ question: q })} cleared />
            )}

            <ol className="space-y-7">
              {messages.map((m) =>
                m.role === "user" ? (
                  <UserBubble key={m.id} text={m.content} />
                ) : (
                  <AssistantMessage
                    key={m.id}
                    msg={m}
                    conversationId={conversationId}
                    onCite={openCitation(m)}
                    activeIndex={source?.messageId === m.id ? source.citation.index : null}
                  />
                ),
              )}
              {pending && (
                <>
                  <UserBubble text={pending} />
                  <li className="flex items-center gap-3 text-muted" aria-live="polite">
                    <span className="typing flex gap-1 text-ledger" aria-hidden="true">
                      <span>●</span>
                      <span>●</span>
                      <span>●</span>
                    </span>
                    Searching your documents
                  </li>
                </>
              )}
            </ol>
            <div ref={endRef} />
          </div>
        </div>

        <Composer
          busy={ask.isPending}
          error={ask.error}
          filters={filters}
          setFilters={setFilters}
          onSend={(q) => ask.mutate({ question: q })}
          onRetry={() => ask.variables && ask.mutate(ask.variables)}
        />
      </section>

      {/* Source pane: side column on wide screens, overlay on narrow ones */}
      {source && (
        <div className="fixed inset-0 z-40 bg-ink/30 lg:static lg:z-auto lg:bg-transparent" onClick={() => setSource(null)}>
          <div className="absolute inset-y-0 right-0 w-full max-w-md lg:static lg:h-full lg:max-w-none" onClick={(e) => e.stopPropagation()}>
            <SourcePane
              key={`${source.messageId}-${source.citation.index}`}
              citation={source.citation}
              answer={source.answer}
              onClose={() => setSource(null)}
            />
          </div>
        </div>
      )}

      <ConfirmDialog
        open={confirmClear}
        title="Clear this chat?"
        body="All messages in this conversation will be deleted. The conversation stays in your history, empty."
        confirmLabel="Clear chat"
        loading={clear.isPending}
        onConfirm={() => clear.mutate()}
        onClose={() => setConfirmClear(false)}
      />
    </div>
  );
}

function cleanFilters(f) {
  return {
    category_ids: f.category_ids.length ? f.category_ids : null,
    date_from: f.date_from || null,
    date_to: f.date_to || null,
  };
}

function UserBubble({ text }) {
  return (
    <li className="flex justify-end">
      <p className="max-w-[85%] whitespace-pre-wrap rounded-md rounded-br-[2px] bg-ink px-4 py-2.5 text-paper">{text}</p>
    </li>
  );
}

function AssistantMessage({ msg, onCite, activeIndex, conversationId }) {
  const notFound = msg.grounded === false && msg.mode !== "small_talk";
  return (
    <li>
      <div className={cx("border-l-2 pl-4", notFound ? "border-amber" : "border-ledger")}>
        {notFound ? (
          <div>
            <p className="prose-doc">{msg.content}</p>
            <p className="mt-2 text-sm text-muted">
              Try different wording, remove filters, or ask your HR or IT team whether this is documented.
            </p>
          </div>
        ) : (
          <AnswerMarkdown text={msg.content} citations={msg.citations} onCite={onCite} activeIndex={activeIndex} />
        )}
        <SourceList citations={msg.citations} onCite={onCite} activeIndex={activeIndex} />
        <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-2">
          {!notFound && msg.mode !== "small_talk" && <Confidence label={msg.confidence_label} score={msg.confidence} />}
          {msg.mode === "summarize" && <span className="text-xs text-muted">Summary</span>}
          {msg.mode === "compare" && <span className="text-xs text-muted">Comparison</span>}
          {msg.mode !== "small_talk" && <Feedback msg={msg} conversationId={conversationId} />}
        </div>
      </div>
    </li>
  );
}

function Feedback({ msg, conversationId }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [asking, setAsking] = useState(false);
  const [comment, setComment] = useState("");
  const setRating = (rating) =>
    qc.setQueryData(["conversation", conversationId], (old) =>
      old ? { ...old, messages: old.messages.map((m) => (m.id === msg.id ? { ...m, feedback: rating } : m)) } : old,
    );
  const send = useMutation({
    mutationFn: ({ rating, comment }) =>
      rating === null ? chat.removeFeedback(msg.id) : chat.feedback(msg.id, rating, comment),
    onSuccess: (_, { rating }) => {
      setRating(rating);
      setAsking(false);
      if (rating !== null) toast("Thanks, feedback saved");
    },
    onError: (e) => toast(e.message, "red"),
  });
  const rate = (r) => {
    if (msg.feedback === r) return send.mutate({ rating: null });
    if (r === -1) return setAsking(true);
    send.mutate({ rating: 1 });
  };
  return (
    <div className="flex items-center gap-1">
      <IconButton label="Helpful" onClick={() => rate(1)} className={cx(msg.feedback === 1 && "bg-ledger-tint text-ledger-dark")} aria-pressed={msg.feedback === 1}>
        <ThumbsUp size={15} />
      </IconButton>
      <IconButton label="Not helpful" onClick={() => rate(-1)} className={cx(msg.feedback === -1 && "bg-brick-tint text-brick")} aria-pressed={msg.feedback === -1}>
        <ThumbsDown size={15} />
      </IconButton>
      {asking && (
        <form
          className="ml-1 flex items-center gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            send.mutate({ rating: -1, comment });
          }}
        >
          <Input autoFocus className="h-8 w-64 text-sm" placeholder="What was wrong? (optional)" maxLength={1000} value={comment} onChange={(e) => setComment(e.target.value)} />
          <Button size="sm" type="submit" loading={send.isPending}>
            Send
          </Button>
          <IconButton label="Cancel" type="button" onClick={() => setAsking(false)}>
            <X size={15} />
          </IconButton>
        </form>
      )}
    </div>
  );
}

function Welcome({ onPick, cleared }) {
  const { data, isLoading } = useQuery({ queryKey: ["suggestions"], queryFn: chat.suggestions });
  return (
    <div className="mb-8">
      <h2 className="text-xl font-semibold tracking-tight">{cleared ? "This chat is empty" : "What do you need to find?"}</h2>
      <p className="mt-1 max-w-xl text-muted">
        Ask about policies, procedures, dates or amounts. Every answer cites the document and page it came from.
      </p>
      {isLoading ? (
        <Loading label="Loading suggestions…" />
      ) : data?.length ? (
        <div className="mt-5">
          <p className="mb-2 text-sm font-medium text-ink-soft">Try asking</p>
          <ul className="grid gap-2 sm:grid-cols-2">
            {data.map((q) => (
              <li key={q}>
                <button
                  onClick={() => onPick(q)}
                  className="h-full w-full rounded-[4px] border border-rule bg-sheet px-3 py-2.5 text-left text-[0.93rem] hover:border-ledger hover:bg-ledger-tint"
                >
                  {q}
                </button>
              </li>
            ))}
          </ul>
        </div>
      ) : (
        <p className="mt-4 text-sm text-muted">No documents are available to you yet. Ask an administrator to upload some.</p>
      )}
    </div>
  );
}

function Composer({ busy, error, onSend, onRetry, filters, setFilters }) {
  const [text, setText] = useState("");
  const [showFilters, setShowFilters] = useState(false);
  const ref = useRef(null);
  const catsQ = useQuery({ queryKey: ["my-categories"], queryFn: me.categories });
  const catName = useMemo(() => Object.fromEntries((catsQ.data || []).map((c) => [c.id, c.name])), [catsQ.data]);
  const active = filters.category_ids.length + (filters.date_from ? 1 : 0) + (filters.date_to ? 1 : 0);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 200) + "px";
  }, [text]);

  function submit(e) {
    e?.preventDefault();
    const q = text.trim();
    if (!q || busy) return;
    onSend(q);
    setText("");
  }

  return (
    <div className="border-t border-rule bg-sheet">
      <div className="mx-auto max-w-3xl px-5 py-3">
        {error && (
          <div className="mb-2 flex items-center gap-3">
            <ErrorNote error={error} className="flex-1" />
            <Button size="sm" variant="secondary" onClick={onRetry}>
              Try again
            </Button>
          </div>
        )}
        {active > 0 && (
          <div className="mb-2 flex flex-wrap items-center gap-1.5 text-sm">
            <span className="text-muted">Searching only:</span>
            {filters.category_ids.map((id) => (
              <Chip key={id} onRemove={() => setFilters({ ...filters, category_ids: filters.category_ids.filter((x) => x !== id) })}>
                {catName[id] || "Category"}
              </Chip>
            ))}
            {filters.date_from && <Chip onRemove={() => setFilters({ ...filters, date_from: "" })}>From {filters.date_from}</Chip>}
            {filters.date_to && <Chip onRemove={() => setFilters({ ...filters, date_to: "" })}>Until {filters.date_to}</Chip>}
          </div>
        )}
        {showFilters && (
          <div className="mb-3 rounded-md border border-rule bg-paper p-3">
            <p className="mb-2 text-sm font-medium">Search in these categories</p>
            <div className="flex flex-wrap gap-x-4 gap-y-1.5">
              {catsQ.data?.map((c) => (
                <label key={c.id} className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    className="accent-ledger"
                    checked={filters.category_ids.includes(c.id)}
                    onChange={(e) =>
                      setFilters({
                        ...filters,
                        category_ids: e.target.checked ? [...filters.category_ids, c.id] : filters.category_ids.filter((x) => x !== c.id),
                      })
                    }
                  />
                  {c.name}
                </label>
              ))}
            </div>
            <div className="mt-3 flex flex-wrap items-end gap-3">
              <label className="text-sm">
                <span className="mb-1 block font-medium">Documents dated from</span>
                <Input type="date" className="h-9 w-44" value={filters.date_from} onChange={(e) => setFilters({ ...filters, date_from: e.target.value })} />
              </label>
              <label className="text-sm">
                <span className="mb-1 block font-medium">Until</span>
                <Input type="date" className="h-9 w-44" value={filters.date_to} onChange={(e) => setFilters({ ...filters, date_to: e.target.value })} />
              </label>
              <Button size="sm" variant="ghost" onClick={() => setFilters(EMPTY_FILTERS)}>
                Reset
              </Button>
            </div>
          </div>
        )}
        <form onSubmit={submit} className="flex items-end gap-2">
          <IconButton
            type="button"
            label={showFilters ? "Hide search filters" : "Show search filters"}
            onClick={() => setShowFilters(!showFilters)}
            className={cx("mb-1", (showFilters || active) && "bg-ledger-tint text-ledger-dark")}
            aria-expanded={showFilters}
          >
            <Filter size={17} />
          </IconButton>
          <Textarea
            ref={ref}
            rows={1}
            value={text}
            maxLength={2000}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) submit(e);
            }}
            placeholder="Ask about a policy, procedure or date…"
            aria-label="Your question"
            className="max-h-[200px] min-h-[42px] resize-none py-2.5"
          />
          <Button type="submit" className="h-[42px] px-3.5" disabled={!text.trim()} loading={busy} aria-label="Send">
            {!busy && <SendHorizontal size={18} />}
          </Button>
        </form>
        <p className="mt-1.5 text-xs text-muted">Enter to send, Shift+Enter for a new line. Answers come only from documents you can access.</p>
      </div>
    </div>
  );
}

function Chip({ children, onRemove }) {
  return (
    <span className="inline-flex items-center gap-1 rounded-full border border-ledger/30 bg-ledger-tint py-0.5 pl-2.5 pr-1 text-ledger-dark">
      {children}
      <button type="button" aria-label={`Remove filter ${children}`} onClick={onRemove} className="rounded-full p-0.5 hover:bg-ledger/15">
        <X size={13} />
      </button>
    </span>
  );
}
