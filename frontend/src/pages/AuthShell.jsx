/** Shared frame for sign-in and registration: the form on paper, and a cited-answer specimen on ink. */
export default function AuthShell({ title, subtitle, children }) {
  return (
    <div className="grid min-h-full lg:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
      <div className="flex items-center justify-center px-6 py-12">
        <div className="w-full max-w-sm">
          <div className="mb-8 flex items-center gap-2.5">
            <svg width="30" height="30" viewBox="0 0 32 32" aria-hidden="true">
              <rect width="32" height="32" rx="6" fill="#1B2A3A" />
              <path d="M9 8h11l3 3v13H9z" fill="#F6F7F4" />
              <rect x="12" y="15" width="8" height="3" fill="#F3DA63" />
            </svg>
            <span className="text-xl font-semibold tracking-tight">CorpMind</span>
          </div>
          <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
          {subtitle && <p className="mt-1 text-muted">{subtitle}</p>}
          <div className="mt-6">{children}</div>
        </div>
      </div>
      <aside aria-hidden="true" className="hidden items-center justify-center bg-ink p-12 lg:flex">
        <div className="max-w-md">
          <p className="text-xl leading-snug text-paper">
            Answers from your company's own documents, with the page they came from.
          </p>
          <div className="mt-8 rounded-sm bg-sheet p-6 shadow-2xl">
            <p className="text-sm text-muted">Leave Policy, page 2</p>
            <p className="prose-doc mt-3 text-[0.98rem] text-ink">
              <span className="mark">Up to 10 unused annual leave days may be carried forward</span> to the next
              calendar year. Carried-forward days expire on 31 March of the following year.
            </p>
          </div>
          <p className="mt-6 text-sm text-paper/60">
            You only see answers from documents your role is allowed to read.
          </p>
        </div>
      </aside>
    </div>
  );
}
