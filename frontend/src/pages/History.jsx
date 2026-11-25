import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Pencil, Search, Trash2, X } from "lucide-react";
import { chat } from "../api/endpoints";
import { ConfirmDialog, Empty, ErrorNote, IconButton, Input, Loading, PageHeader, formatDate, useToast } from "../components/ui";

export default function HistoryPage() {
  const [q, setQ] = useState("");
  const [debounced, setDebounced] = useState("");
  const [editing, setEditing] = useState(null);
  const [deleting, setDeleting] = useState(null);
  const qc = useQueryClient();
  const toast = useToast();
  useEffect(() => {
    const t = setTimeout(() => setDebounced(q.trim()), 300);
    return () => clearTimeout(t);
  }, [q]);

  const listQ = useQuery({ queryKey: ["conversations", debounced], queryFn: () => chat.conversations(debounced || undefined) });
  const rename = useMutation({
    mutationFn: ({ id, title }) => chat.rename(id, title),
    onSuccess: () => {
      setEditing(null);
      qc.invalidateQueries({ queryKey: ["conversations"] });
    },
    onError: (e) => toast(e.message, "red"),
  });
  const remove = useMutation({
    mutationFn: (id) => chat.remove(id),
    onSuccess: (_, id) => {
      setDeleting(null);
      qc.removeQueries({ queryKey: ["conversation", id] });
      qc.invalidateQueries({ queryKey: ["conversations"] });
      qc.invalidateQueries({ queryKey: ["stats"] });
      toast("Conversation deleted");
    },
  });

  return (
    <div className="mx-auto max-w-4xl">
      <PageHeader title="Chat history" description="Your conversations are private to you." />
      <div className="relative mb-5 max-w-md">
        <Search size={16} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted" />
        <Input className="pl-9" placeholder="Search titles and messages" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search conversations" />
      </div>
      {listQ.isLoading ? (
        <Loading />
      ) : listQ.error ? (
        <ErrorNote error={listQ.error} />
      ) : listQ.data.length === 0 ? (
        <Empty title={debounced ? "No conversations match" : "No conversations yet"} action={!debounced && <Link className="text-ledger hover:underline" to="/chat">Ask your first question</Link>}>
          {debounced ? "Try another word from the question or answer." : null}
        </Empty>
      ) : (
        <ul className="divide-y divide-rule border-y border-rule bg-sheet">
          {listQ.data.map((c) => (
            <li key={c.id} className="flex items-start gap-3 px-4 py-3">
              <div className="min-w-0 flex-1">
                {editing?.id === c.id ? (
                  <form
                    className="flex items-center gap-1"
                    onSubmit={(e) => {
                      e.preventDefault();
                      if (editing.title.trim()) rename.mutate({ id: c.id, title: editing.title.trim() });
                    }}
                  >
                    <Input autoFocus className="h-8" value={editing.title} maxLength={200} onChange={(e) => setEditing({ ...editing, title: e.target.value })} aria-label="Conversation title" />
                    <IconButton label="Save title" type="submit">
                      <Check size={16} />
                    </IconButton>
                    <IconButton label="Cancel" type="button" onClick={() => setEditing(null)}>
                      <X size={16} />
                    </IconButton>
                  </form>
                ) : (
                  <Link to={`/chat/${c.id}`} className="font-medium hover:underline">
                    {c.title}
                  </Link>
                )}
                {c.last_message_preview && <p className="mt-0.5 line-clamp-1 text-sm text-muted">{c.last_message_preview}</p>}
                <p className="mt-1 text-xs text-muted">
                  {c.message_count} messages, last active {formatDate(c.updated_at, true)}
                </p>
              </div>
              <IconButton label="Rename" onClick={() => setEditing({ id: c.id, title: c.title })}>
                <Pencil size={15} />
              </IconButton>
              <IconButton label="Delete" onClick={() => setDeleting(c)} className="hover:bg-brick-tint hover:text-brick">
                <Trash2 size={15} />
              </IconButton>
            </li>
          ))}
        </ul>
      )}
      <ConfirmDialog
        open={!!deleting}
        title="Delete conversation?"
        body={`"${deleting?.title}" and all its messages will be permanently deleted.`}
        confirmLabel="Delete conversation"
        loading={remove.isPending}
        onConfirm={() => remove.mutate(deleting.id)}
        onClose={() => setDeleting(null)}
      />
    </div>
  );
}
