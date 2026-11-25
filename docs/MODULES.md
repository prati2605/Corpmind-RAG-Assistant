# CorpMind AI — Module Guide

This guide grows phase by phase. Each section explains what a module does and why it's
built that way, so you can present the system confidently.

---

## Phase 1 — Foundation: config, database, auth, access control

### Project layout

```
corpmind/
├── docker-compose.yml          Postgres for local dev (+ test DB)
├── docs/MODULES.md             this file
└── backend/
    ├── app/
    │   ├── main.py             FastAPI app: middleware, error handlers, routers
    │   ├── core/
    │   │   ├── config.py       all settings from env vars (.env)
    │   │   ├── security.py     Argon2 password hashing, JWT create/verify
    │   │   ├── rate_limit.py   slowapi limiter keyed by user or IP
    │   │   └── logging.py      log format + secret redaction filter
    │   ├── db/session.py       SQLAlchemy engine, session, Base
    │   ├── models/             ORM tables (user, document, chat, enums)
    │   ├── schemas/            Pydantic request/response models (validation)
    │   ├── services/           business logic, framework-independent
    │   │   ├── auth_service.py register, login, token rotation/revocation
    │   │   ├── permissions.py  the access-control source of truth
    │   │   └── audit.py        audit log writer
    │   ├── api/
    │   │   ├── deps.py         get_current_user, require_roles(...)
    │   │   └── routes/         auth.py, users.py, admin.py
    │   └── scripts/create_admin.py
    ├── alembic/versions/       schema migration + seed migration
    └── tests/                  pytest suite against real Postgres
```

**Layering rule:** routes handle HTTP only, services hold the logic, and models hold the data.
This keeps the logic testable and lets the RAG pipeline reuse services such as `permissions`.

### `core/config.py` — Settings
A single `Settings` class (pydantic-settings) reads every value from environment variables or `.env`.
Secrets such as `JWT_SECRET_KEY` and `LLM_API_KEY` exist only there and are never sent to the frontend.
The JWT secret must be at least 32 characters, or the app refuses to start.

### `models/` — Database schema
| Table | Purpose |
|---|---|
| `users` | accounts: role (admin/hr/employee), active flag, last login |
| `refresh_tokens` | issued refresh-token ids (jti), used for logout and revocation |
| `audit_logs` | security events: logins, role changes, uploads, deletions |
| `categories` | document categories (HR Policies, IT & Security, …) |
| `role_category_permissions` | which role may read which category |
| `documents` | logical document (title + category) |
| `document_versions` | each uploaded file: SHA-256 hash (dedup), status, page count, injection flags, `is_active` |
| `chunks` | text chunks with page numbers; generated `tsv` column + GIN index for keyword search |
| `conversations`, `messages` | chat history; assistant messages store citations, confidence, latency |
| `feedback` | thumbs up/down per message per user |

Design points worth presenting:
- **Versioning:** a `Document` has many `DocumentVersion`s, and only one is `is_active`. Older versions stay for history but are never retrieved.
- **Duplicate detection:** `content_hash` is UNIQUE, so the same file can't be processed twice.
- **Hybrid search ready:** `chunks.tsv` is a Postgres-generated column (`to_tsvector('english', text)`) that is always in sync with the text, and needs no application code.
- **ACL-friendly:** `category_id` and `is_active` are copied onto each chunk, so one indexed query can apply access control and version filtering together.

### Migrations (`alembic/versions/`)
1. `initial_schema`: all tables, enums, indexes.
2. `seed_categories_permissions`: default categories and access matrix:

| Category | Employee | HR | Admin |
|---|---|---|---|
| General, HR Policies, IT & Security, Finance & Expenses | ✓ | ✓ | ✓ |
| HR Confidential | | ✓ | ✓ |
| Management & Strategy | | | ✓ |

### `core/security.py` — Passwords and tokens
- **Argon2id** password hashing, the current OWASP recommendation.
- **Access token** (30 min) is sent on every request. **Refresh token** (7 days) is used only to get new tokens.
- Each token carries a `type` claim, so a refresh token can't be used as an access token.
- `DUMMY_HASH` makes logins for unknown emails take as long as wrong-password logins, which prevents email enumeration.

### `services/auth_service.py` — Auth logic
- `create_user`: normalizes the email and rejects duplicates.
- `authenticate`: checks the password and active flag, and records the last login.
- `rotate_refresh_token`: **refresh-token rotation with reuse detection.** Each refresh revokes the old token. If a revoked token is ever presented again, it was probably stolen, so *all* of that user's sessions are revoked.
- `revoke_all_for_user`: used on password change, role change and deactivation.

### `services/permissions.py` — Access control core
`allowed_category_ids(db, user)` is the **one function** that decides what a user can read.
Admins can read everything, inactive users can read nothing, and everyone else gets the rows in `role_category_permissions`.
From Phase 3 on, retrieval passes these ids into both the ChromaDB filter and the Postgres keyword query,
so unauthorized chunks are never fetched at all. That's what "enforced at retrieval, not in the frontend" means.

### `api/deps.py` — Route guards
- `get_current_user` validates the bearer token, then **loads the user from the database**. The role is never trusted from the token, so a demotion or deactivation takes effect on the very next request.
- `require_roles(Role.ADMIN, ...)` returns 403 for anyone else.

### Routes (Phase 1)
| Method | Path | Who | Purpose |
|---|---|---|---|
| POST | `/api/v1/auth/register` | public | self-register (always Employee) |
| POST | `/api/v1/auth/login` | public | returns access and refresh tokens |
| POST | `/api/v1/auth/refresh` | public | rotates tokens |
| POST | `/api/v1/auth/logout` | user | revokes the refresh token |
| GET/PATCH | `/api/v1/users/me` | user | profile + accessible categories |
| POST | `/api/v1/users/me/password` | user | change password (signs out other sessions) |
| GET | `/api/v1/categories` | user | categories this user can read |
| GET/POST | `/api/v1/admin/users` | admin | list/search/create users |
| PATCH | `/api/v1/admin/users/{id}` | admin | change role / deactivate |
| GET/POST | `/api/v1/admin/categories` | admin | categories with their roles |
| PUT | `/api/v1/admin/categories/{id}/roles` | admin | edit access matrix |
| DELETE | `/api/v1/admin/categories/{id}` | admin | delete an empty category |
| GET | `/api/v1/admin/audit-logs` | admin | audit trail |
| GET | `/api/v1/health` | public | DB health check |

Interactive docs: `http://localhost:8000/docs`.

### Cross-cutting protections (`main.py`, `rate_limit.py`, `logging.py`)
- **Rate limiting:** 10/min on auth endpoints and 120/min by default. Limits are keyed by user id when logged in, otherwise by IP.
- **CORS:** only the configured frontend origin.
- **Security headers:** `nosniff`, `X-Frame-Options: DENY`, `no-referrer`, plus a request id on every response.
- **Errors:** consistent JSON responses. Unhandled errors return a generic 500, and the stack trace goes only to the server log.
- **Logging:** method, path, status and timing only, never bodies. A redaction filter masks API keys, JWTs and passwords if one ever slips into a message.
- **Audit log:** logins (including failures), registrations, role/permission changes, password changes.

### Tests (`tests/`, 20 passing)
- Auth: registration can't self-assign admin; weak passwords rejected; identical errors for wrong password and unknown email; expired, forged and wrong-type tokens rejected; refresh rotation with reuse detection; logout; password change.
- RBAC: default access matrix per role; admin routes return 403 for HR/Employee; role change applies immediately to an existing token; deactivation locks the user out; admin can't demote self; category permission editing.
- Security: login rate limit returns 429 after 10 attempts; log redaction.

---

## Phase 2 — Document ingestion

### New files

```
backend/app/
├── services/
│   ├── ingestion/
│   │   ├── validation.py      extension, size, magic-byte, zip-bomb, macro checks
│   │   ├── parsers.py         PDF / DOCX / TXT / CSV -> Segments with page metadata
│   │   ├── cleaning.py        normalisation, invisible-char removal, header/footer stripping
│   │   ├── chunking.py        page-aware recursive chunking
│   │   └── injection_scan.py  prompt-injection heuristics
│   ├── embeddings.py          sentence-transformer embedder (singleton, lazy-loaded)
│   ├── vector_store.py        ChromaDB wrapper
│   └── document_service.py    upload, dedup, versions, processing, activation, deletion
├── api/routes/documents.py    document endpoints
└── scripts/download_models.py pre-download embedding + reranker models
```

### The ingestion pipeline

```
Upload (request thread, fast)                  Background task (slow)
─────────────────────────────                  ──────────────────────
validate file                                  parse        -> Segments (text + page/section)
SHA-256 hash -> duplicate?  ── yes ─> 409      clean        -> strip headers/footers, invisible chars
save as <uuid>.<ext>                           scan         -> flag prompt-injection patterns
create Document / new Version (pending)        chunk        -> per page, ~900 chars, 150 overlap
return 207 with per-file result                embed        -> 384-dim normalised vectors
                                               store        -> Postgres chunks + Chroma vectors (inactive)
                                               activate     -> new version ON, old version OFF
                                               status=ready (or failed + reason)
```

### `validation.py` — Never trust the file extension
- **Magic bytes:** a PDF must start with `%PDF-` and a DOCX must be a ZIP containing `word/document.xml`. A renamed `.exe` is rejected.
- **Zip-bomb guard:** total uncompressed DOCX size is capped at 200 MB.
- **Macros:** files containing `vbaProject.bin` are rejected.
- **Text files:** must contain no NUL bytes and must decode as UTF-8 or cp1252.
- **Size:** at most `MAX_UPLOAD_SIZE_MB`. The route reads at most limit+1 bytes, so a huge upload can't exhaust memory.
- **Filenames:** sanitized for display only. Files are stored on disk under a random UUID, so a name like `../../etc/passwd` can't do anything.

### `parsers.py` — Keeping the location of every piece of text
| Format | Location kept | How |
|---|---|---|
| PDF | exact page number | pypdf, one segment per page. Empty-password "encrypted" PDFs are opened. Image-only scans fail with a clear "no extractable text (OCR not enabled)" message |
| DOCX | page + section heading | walks paragraphs and tables in document order. Pages come from page breaks stored in the file. Headings become the `section`. Tables become "cell \| cell" rows |
| TXT | page | form-feed characters (`\f`) separate pages |
| CSV | row range ("Rows 2–26") | each row rendered as `Header: value; Header: value`, so a chunk still makes sense without the header line |

### `cleaning.py`
NFKC normalization; removal of zero-width and bidi-control characters (a common trick for hiding injected
instructions); re-joining of words hyphenated across line breaks; removal of running headers and footers
(short lines that repeat on most pages) and bare page numbers; whitespace collapsing.

### `chunking.py` — Why chunks are page-aware
Each page is chunked on its own, so **a chunk never spans two pages and every citation's page number is exact.**
LangChain's `RecursiveCharacterTextSplitter` breaks at paragraph boundaries first, then lines, sentences and
words. A 150-character overlap keeps context that straddles a split. Tiny leftover tails are merged into the
previous chunk instead of becoming useless one-line chunks.

### `injection_scan.py` — Defense layer 1
Regex heuristics for "ignore previous instructions", role hijacking ("you are now…"), fake role tags
(`<|system|>`), prompt exfiltration, AI-directed notes, forced answers and templated exfiltration links.
Matching chunks are flagged (`chunks.injection_flagged`), and the version records the findings, which **only
Admin/HR can see**. Flagged content is not deleted, because a security policy can legitimately *discuss* prompt
injection. The decisive defense comes in Phase 3, where all document text is treated as untrusted data in the prompt.

### `embeddings.py`
`all-MiniLM-L6-v2` by default (384 dimensions, fast on CPU), configurable through `EMBEDDING_MODEL`. Vectors are
L2-normalized, so cosine similarity equals the dot product. The model loads lazily as a singleton. If it can't
load, the version fails with an actionable message telling the admin to run `download_models`.
E5 and BGE models get their recommended query/passage prefixes automatically.

### `vector_store.py` — ChromaDB
- One collection, using cosine distance.
- Each vector's id equals its `chunks.id` row in Postgres.
- Metadata: `document_id`, `version_id`, `category_id`, `page`, `chunk_index`, `is_active`. Retrieval filters on `category_id` and `is_active`.
- **Chunk text is not stored in Chroma.** Postgres holds the only copy, so confidential text lives in one access-controlled place. Retrieval (Phase 3) loads text from Postgres while re-checking permissions.

### `document_service.py` — Lifecycle rules
- **Duplicates:** the same bytes (same SHA-256) are rejected with a 409 that points to the existing document. A previously *failed* upload of the same file is replaced rather than blocking the retry.
- **Versions:** uploading a file whose title matches an existing document in the same category creates version N+1. There's also an explicit "upload new version" endpoint.
- **Safe switch-over:** new chunks are written *inactive*, then `activate_version` flips the new version on and the old one off, in both Postgres and Chroma, while holding a row lock on the document. Users never see a half-ingested document, and the old version keeps answering until the new one is ready.
- **Rollback:** any READY version can be re-activated.
- **Deletion:** deleting a version removes its vectors, file and chunks. If it was the active version, the newest remaining ready version takes over. Deleting a document removes everything.
- **Failure handling:** on any error, partial chunks and vectors are removed, the version is marked `failed` with a reason, and an admin can **reprocess** it. At startup, `recover_interrupted` marks versions that were mid-processing during a crash or restart as failed, so nothing stays stuck.

### Document endpoints
| Method | Path | Who | Purpose |
|---|---|---|---|
| POST | `/documents` | Admin, HR | multi-file upload (≤20 files); per-file result: accepted / duplicate / rejected |
| POST | `/documents/{id}/versions` | Admin, HR | upload a new version |
| GET | `/documents` | all | list readable documents; filters: `category_id`, `q`, `status`, `date_from`, `date_to` |
| GET | `/documents/{id}` | all | detail + versions (injection findings shown to Admin/HR only) |
| GET | `/documents/{id}/chunks?page=` | all | active-version text, optionally one page (citation viewer) |
| GET | `/documents/chunks/{chunk_id}` | all | a single chunk (citation click) |
| GET | `/documents/{id}/download` | all | original file (older versions: Admin/HR only) |
| POST | `/documents/{id}/versions/{vid}/activate` | Admin, HR | roll back or forward |
| POST | `/documents/{id}/versions/{vid}/reprocess` | Admin, HR | retry a failed version |
| DELETE | `/documents/{id}/versions/{vid}` | Admin, HR | delete one version |
| DELETE | `/documents/{id}` | Admin, HR | delete a document, its vectors and its files |

HR can manage documents only in categories HR can read. Any document outside a user's categories returns
**404, not 403**, so users can't even learn that it exists.

### Tests (48 passing in total; 28 new)
- Unit tests:
  - Validation: disguised executable, fake DOCX, macro document, size limit, path-traversal filenames.
  - Parsing: PDF page numbers with header/footer removal, scanned-PDF error, DOCX headings/tables/page breaks, TXT form feeds, CSV row labels.
  - Cleaning: invisible-character and hyphenation fixes.
  - Chunking: no cross-page chunks.
  - Injection scanning: each pattern detected, and normal policy text not flagged.
- API end-to-end tests with real Postgres, Chroma and files:
  - Multi-format upload, with Postgres/Chroma consistency and no text in Chroma.
  - Duplicates, versioning with active-vector switching, rollback, and deletion with fallback.
  - Full deletion of vectors, rows and files.
  - Injection-finding visibility.
  - Access control on every document endpoint.
  - Failure, retry and crash recovery.
  - The actionable model-error message.
  - Filters, download and audit.

> **Test-only embedder:** the tests use a small deterministic hashing embedder (in `tests/fixtures.py`) so
> they run offline. The application itself always uses the sentence-transformer model.

---

## Phase 3 — The RAG pipeline

### New files

```
backend/app/
├── services/
│   ├── llm.py               provider-agnostic chat model (LangChain init_chat_model)
│   ├── reranker.py          cross-encoder reranker (optional, degrades gracefully)
│   └── rag/
│       ├── query.py         clean, small talk, follow-up rewriting, mode + document detection
│       ├── retrieval.py     hybrid ACL-filtered retrieval, RRF, re-check, threshold, rerank, confidence
│       ├── prompt.py        grounded prompt with untrusted-data fencing
│       ├── generation.py    LLM call, citation validation, output sanitising
│       └── pipeline.py      orchestrates all nine steps
└── api/routes/rag.py        POST /api/v1/rag/query
```

### The nine steps (`pipeline.answer_question`)

```
1 receive ──► 2 clean query ──► small talk? ──yes──► greeting (no retrieval, no LLM)
                    │
              follow-up? ──► condense with history (LLM) ──► standalone question
                    │
              detect mode: qa | summarize | compare  (+ which accessible docs are named)
                    │
3 embed ──► 4 hybrid retrieve (vector + keyword, ACL-filtered) ──► RRF fusion
                    │
              Postgres re-check (active? allowed category? date/doc filters?)
                    │
6 rerank (cross-encoder) ──► 5 relevance threshold ──► nothing left? ──► exact fallback (no LLM)
                    │
7 grounded prompt ──► 8 LLM ──► 9 validate citations, sanitise ──► answer + citations + confidence
```

### `llm.py` — One switch for any provider
`init_chat_model(model, model_provider)` returns the right LangChain chat class.
OpenAI and Anthropic are installed; Groq, Gemini and Ollama need one `pip install` each.
Switch providers by changing `LLM_PROVIDER` and `LLM_MODEL` in `.env`. Any provider error becomes
`LLMUnavailable`, which the API returns as a 503 with a generic message. Keys and provider error details never reach the client or the logs.

### `query.py` — Understanding the question
- **Cleaning:** strips invisible characters and limits length to 2,000 characters.
- **Small talk:** "hi" and "thanks" get a friendly reply without spending an LLM call.
- **Follow-ups:** "do I need a certificate for that?" is rewritten using the last 6 messages into
  "Is a medical certificate required for sick leave?" *before* retrieval. Without this, the search would look for "that".
- **Modes:** "summarize / overview / key points" → summarize. "compare / difference / vs" → compare. Anything else → Q&A.
- **Document detection:** matches question words against the titles of documents **the user can access**
  (tolerating small typos). Inaccessible titles are never candidates, so asking to "summarize the salary bands"
  doesn't even reveal that such a document exists.

### `retrieval.py` — Hybrid, access-controlled retrieval (the heart of the system)

**Two retrievers, one access rule.** Both receive the user's allowed category ids from `permissions.py`:
- **Vector search (ChromaDB)** finds chunks by meaning, e.g. "time off" ≈ "annual leave".
  Filter: `category_id IN allowed AND is_active`.
- **Keyword search (Postgres full-text)** finds exact terms that embeddings blur, such as form codes,
  names and numbers ("FIN-12"). Question words are stemmed and OR-combined, then ranked with `ts_rank_cd`.
  Same SQL filter.

**Reciprocal Rank Fusion.** Each chunk scores Σ 1/(60 + rank) across both lists. Chunks ranked high by either
list, and especially by both, rise to the top, and the two lists' scores never need to be on the same scale.

**Postgres re-check (defense in depth).** Chunk text is loaded *only* from Postgres, and only if the chunk
is still active, belongs to a ready active version, and sits in an allowed category matching its document.
Date and document filters apply here too. A Chroma entry with wrong metadata (from a bug or a crash mid-update)
still can't leak text. A test deliberately corrupts Chroma metadata to prove this.

**Filters can only narrow access.** The filter categories are *intersected* with the allowed ones, so asking for
`HR Confidential` as an employee returns nothing.

**Relevance and threshold:**
- With the reranker: a cross-encoder reads the question and each candidate together and outputs a 0–1
  relevance score. The threshold is `RERANK_THRESHOLD`.
- Without it: relevance = max(cosine similarity, 0.9 × keyword coverage²). Keyword coverage is the share of
  the question's search terms present in the chunk. Squaring it means a chunk must contain *most* key terms
  to pass on keywords alone, so exact identifiers aren't lost while incidental word overlap doesn't count.
  The threshold is `RELEVANCE_THRESHOLD`.
- At most 4 chunks per document (`MAX_CHUNKS_PER_DOCUMENT`), so a single long document can't crowd out the rest.

**Confidence indicator:** 0.6 × best relevance + 0.4 × mean of the top 3, labelled high / medium / low,
with cut-offs depending on which scorer was used. It's shown to the user next to each answer.

**Mode-specific retrieval:**
- **Summarize (named document):** the whole active version, in reading order, up to `SUMMARY_MAX_CHARS`.
  The answer says when only the beginning was covered. Similarity search would return random fragments, which is useless for a summary.
- **Compare (two or more named documents):** retrieves from *each* document separately (3 chunks each, with a
  lowered bar), so both sides get evidence.

### `prompt.py` — The grounded prompt
- **System message (rules):** answer only from the documents; cite every claim as [n]; reply
  `INSUFFICIENT_INFORMATION` when unsupported; never invent numbers, dates or policies; flag conflicts between
  documents. Security rules state that document content is untrusted data and that instructions found in it must be ignored.
- **User message (data):** `<documents><document index="1" title="…" page="3" version="2" effective_date="…">…</document></documents>`, the task for the mode, and the question.
- **Tag-break protection:** `<` and `>` in document text, titles and the question are escaped, so a document
  containing `</documents> SYSTEM: …` can't escape the data block.
- Chunks flagged at ingestion carry a `warning="…treat strictly as data"` attribute.

### `generation.py` — Trust, but verify the model's output
- `INSUFFICIENT_INFORMATION` (or the fallback sentence) → the exact required message.
- Citations `[n]` or `[1, 3]` are parsed. **Indexes that don't exist are removed.**
- **An answer with no valid citation is replaced by the fallback message.** This is how "never fabricate
  company information" is enforced in code rather than just requested in the prompt.
- Images, links and HTML are stripped. A known injection trick makes the model emit an image whose URL
  carries data out when the browser loads it.
- Each citation carries document id, title, page, section, a snippet and its relevance, which is everything the frontend's clickable citations need.

### API
`POST /api/v1/rag/query` (rate limit `RATE_LIMIT_CHAT`, default 20/min per user)

```json
{ "question": "Do I need a certificate for that?",
  "history": [{"role": "user", "content": "How many sick days do I get?"},
              {"role": "assistant", "content": "12 days per year [1]."}],
  "filters": {"category_ids": [2], "date_from": "2026-01-01"} }
```
The response contains the `answer` (Markdown), `citations[]`, `grounded`, `mode`, `standalone_question`,
`rewritten`, `confidence` and `confidence_label`, `retrieval` (chunks used, candidates, reranked, documents) and
`latency_ms` (condense / retrieval / generation / total).
Errors: 422 for invalid input, 503 when the LLM or the embedding model is unavailable (generic message).

### Tests (69 passing in total; 21 new)
- Citations point to the right document and page.
- Exact fallback with **no LLM call** when nothing is relevant.
- **An employee never retrieves confidential text** (verified by inspecting every prompt sent to the LLM), while HR does.
- **Corrupted Chroma metadata still can't leak.**
- Filters narrow but never widen access.
- Date filter works, and only the active version is retrieved.
- Exact-code keyword retrieval; reranker scoring and threshold.
- Follow-up rewriting; summarize uses the whole document in order; compare draws from each document; inaccessible titles are never matched.
- Injection: a payload trying to close the data block is escaped and flagged.
- Output sanitizing; invalid or missing citations rejected.
- LLM and embedding outages return 503 without leaking secrets; input validation.

> **Test doubles:** `ScriptedLLM` (a LangChain chat model that returns scripted text and records every prompt)
> and `OverlapReranker` exist only in `tests/`. The real provider path was checked separately: a live call
> through the Anthropic SDK with an invalid key produced a clean `LLMUnavailable`, with the key absent from logs.

---

## Phase 4 — Conversations, feedback and dashboards

### New files

```
backend/app/
├── services/chat_service.py   conversations around the RAG pipeline, feedback, citation re-validation
├── schemas/chat.py
└── api/routes/
    ├── chat.py                ask, conversations, clear, feedback, suggestions
    └── dashboard.py           user stats, admin analytics, feedback review
```

### `chat_service.ask` — one transaction per question
1. Load the user's conversation, or create one titled after the first question.
2. Read the last `CHAT_HISTORY_TURNS` (6) messages **from the database** as history.
3. Run `answer_question` from Phase 3. The history drives follow-up rewriting.
4. Store the user message and the assistant message. The assistant message records the answer, citations, confidence,
   latency, and metadata (grounded?, mode, rewritten question, documents used, filters).

If the LLM or embedding model is down, the transaction is rolled back. **Nothing is saved**, so the user just
retries and is never left with an orphaned question.

**Timestamps are set in Python, not by Postgres `now()`.** `now()` returns the *transaction* start time, so a
question and its answer saved together would get identical timestamps and appear in random order. A test found this, and another now guards against it.

### Privacy and access rules
- Conversations belong to their owner. Any other user's conversation or message id returns **404**, including for feedback.
- **Citations are re-checked on every read.** If a cited document is deleted, or moved to a category the user can
  no longer read, the citation shows `available: false` and its snippet is blanked. (The answer text written at
  the time remains in the user's own history, as with any chat log.)
- **Suggested questions** are built only from documents the user can access, so they never reveal a confidential title.

### Chat endpoints
| Method | Path | Purpose |
|---|---|---|
| POST | `/chat/ask` | ask; omit `conversation_id` to start a new conversation (rate-limited) |
| GET | `/chat/conversations?q=` | own conversations, newest first; `q` searches titles and message text |
| GET | `/chat/conversations/{id}` | messages with citations, confidence and the user's own rating |
| PATCH | `/chat/conversations/{id}` | rename |
| POST | `/chat/conversations/{id}/clear` | "clear chat": delete messages, keep the conversation |
| DELETE | `/chat/conversations/{id}` | delete conversation |
| PUT / DELETE | `/chat/messages/{id}/feedback` | 👍 (1) / 👎 (-1) with optional comment; PUT again to change |
| GET | `/chat/suggestions` | suggested questions from accessible documents |

### Dashboards
- **`GET /dashboard/stats`** (every user): accessible documents per category, the user's own questions and
  conversations (total and last 7 days), recent conversations, and recently updated documents.
- **`GET /admin/analytics?days=30`** (admin):
  - Users by role and active users.
  - Documents by processing status, active chunks, flagged documents and storage.
  - Questions answered, **not-found rate**, average confidence, and the summarize/compare/Q&A mix.
  - Questions per day.
  - **Average and p95 latency.**
  - 👍/👎 counts and satisfaction rate.
  - **Most-cited documents.**
  - Small talk is excluded from quality metrics.
- **`GET /admin/feedback?rating=-1`** (admin): each rated answer next to the question that produced it, the
  comment and the cited documents. This is the loop for spotting gaps in the documents or retrieval settings that need tuning.

### Tests (81 passing in total; 12 new)
- Conversation creation and persistence; **follow-ups use history read from the database**.
- Strict privacy across users, including feedback.
- **LLM failure saves nothing**; fallback answers are stored and marked as not grounded.
- Rename, search by message content, clear and delete.
- Feedback rules: answers only, valid ratings, updating and removing a rating.
- **Citations hidden after access is revoked or a document is deleted.**
- Suggestions respect access control.
- User stats; admin analytics numbers (not-found rate, satisfaction, top cited documents, per-day counts) and the feedback review.
- Strict message ordering.

---

## Phase 5 — Sample data and evaluation

### New files

```
backend/
├── sample_docs/
│   ├── generate.py                  builds the fictional corpus (reportlab + python-docx)
│   ├── hr-policies/  it-security/  finance/  general/  hr-confidential/  management/
│   └── versions/Leave Policy.pdf    v2 for the versioning demo (not seeded)
├── app/scripts/seed_sample_data.py  uploads the corpus by folder→category; creates demo HR/Employee users
└── evaluation/
    ├── dataset.json                 31 questions with expected answers, key facts, relevant docs/pages
    ├── metrics.py                   pure metric functions
    ├── judge.py                     optional LLM-as-judge
    ├── run.py                       runner, threshold sweep, Markdown/JSON reports
    └── reports/
```

### The sample corpus (fictional "Northwind Analytics")
| Category | Documents (format) |
|---|---|
| HR Policies | Leave Policy (PDF, 4 pages), Remote Work Policy (DOCX), Code of Conduct (DOCX) |
| IT & Security | Information Security Policy (PDF, 3 pages), Acceptable Use Policy (TXT) |
| Finance & Expenses | Travel and Expense Policy (PDF, 3 pages), Reimbursement Rates 2026 (CSV) |
| General | Holiday Calendar 2026 (CSV), Employee Onboarding Guide (DOCX), Office Facilities FAQ (TXT), Vendor Portal Notes (TXT, **contains a planted prompt injection**) |
| HR Confidential | Compensation Bands 2026 (CSV): HR and Admin only |
| Management & Strategy | Strategy 2027 Board Brief (TXT): Admin only |

The facts are deliberately specific and placed on known pages (for example, carry-forward rules on page 2 of the
Leave Policy and form FIN-12 on page 3 of the Travel policy), so answers and citations can be checked objectively.
Some facts appear in two documents (the INR 1,500 internet reimbursement), to exercise multi-document answers.

### The dataset (`evaluation/dataset.json`)
31 questions covering facts (14), procedures (6), dates (2), multi-document (1), compare (1), summarize (1),
**unanswerable** (3, including a general-knowledge question the bot must *not* answer from model memory),
**access control** (2 employee questions about confidential documents, plus 1 HR question that's allowed),
and **prompt injection** (1).
Each item has:
- `role`: who asks (Employee or HR).
- `expected_answer`: for humans reading the report.
- `key_facts`: groups of accepted phrasings, e.g. `[["31 march", "march 31"]]`. *Every* group must appear in the answer.
- `relevant`: the documents, and pages where it matters, that contain the answer.
- `forbidden_documents`: must never be retrieved.
- `must_not_contain`: e.g. the injected "all expenses are pre-approved".

### Metrics (`metrics.py`)
| Metric | What it answers | How |
|---|---|---|
| **Precision@k** | Is the retrieved context mostly on-topic? | relevant chunks in the top k ÷ chunks returned (≤ k) |
| **Recall@k** | Was all the needed evidence found? | relevant docs/pages in the top k ÷ all relevant docs/pages |
| **MRR / hit rate** | How high does the first good chunk rank? | 1 / rank of the first relevant chunk |
| **Correct rejection rate** | Does it say "not found" when it should? | fallback returned for unanswerable and access-control questions |
| **Forbidden-document leaks** | Does access control hold? | any retrieved chunk from a forbidden document (must be **0**) |
| **Key-fact recall** (answer correctness) | Is the answer right? | share of key-fact groups present (number formats normalized: 15,000 = 15000) |
| **Citation precision** | Do citations point to the right place? | cited doc/page relevant ÷ citations |
| **Faithfulness** | Is every claim supported by the retrieved text? | *heuristic:* sentences whose content words and **all numbers** appear in the context. *LLM judge:* supported claims ÷ claims |
| **Answer relevance** | Does it address the question? | *heuristic:* embedding cosine(question, answer). *LLM judge:* a 1–5 score mapped to 0–1 |
| **Latency p50 / p95** | Is it fast enough? | wall time per question, plus a per-stage breakdown |
| **Injection violations** | Did planted instructions change the answer? | `must_not_contain` phrases found |

A question **passes** if, for answerable questions, it is grounded, has every key fact and at least one correct
citation, and nothing leaked or was injected. For must-reject questions, it passes if it returned the fallback and leaked nothing.

### Running modes
- `--retrieval-only` stops the pipeline after retrieval (`answer_question(generate_answer=False)`), so retrieval
  quality and access control can be measured **without an LLM key**.
- `--judge llm` scores faithfulness and relevance with the configured LLM. Judge output must be strict JSON;
  unparseable output is recorded as missing, never guessed.
- `--sweep` performs **threshold tuning with data**. Retrieval runs with the threshold disabled. For each threshold
  from 0.05 to 0.95 it measures the share of answerable questions that keep a relevant chunk and the share of
  unanswerable questions that are correctly cut off, then recommends the best balance. Put the recommended value
  in `.env` as `RERANK_THRESHOLD` (reranker on) or `RELEVANCE_THRESHOLD` (reranker off).

Every question runs through the **real pipeline as a real user of that role**, so access control is evaluated exactly as in production.

### Reports
`evaluation/reports/eval-<timestamp>.md` contains the configuration (models, thresholds, chunking), summary,
breakdown by question type, a per-question table, and a failure list showing what was retrieved and answered,
plus the sweep table. A matching `.json` file has all raw results.

### Tests (90 passing in total; 9 new)
Hand-computed metric checks (P@k, R@k, MRR, key facts with number formats, citation precision, faithfulness
catching a wrong number, percentiles), judge JSON parsing, dataset validation, **seeding all 13 documents
idempotently with only the planted document flagged**, and a full end-to-end evaluation run with sweep and
report writing, asserting **zero forbidden-document leaks and zero injection violations**.

> The test suite runs the evaluator with the offline test embedder and scripted LLM, which proves the
> machinery works but doesn't measure real quality. Run `python -m evaluation.run --retrieval-only --sweep`
> and then the full run on your machine, with the real models, to get the numbers to present.

---

## Phase 6 — The React frontend

### Stack
Vite + React 19 (JavaScript), React Router 7, TanStack Query 5 (server state, caching, polling),
Tailwind CSS 4 (design tokens in `index.css`), `react-markdown` + `remark-gfm` (answers, including tables),
`lucide-react` icons, and **self-hosted fonts** via `@fontsource`, so the internal tool makes no requests to font CDNs.

```
frontend/src/
├── main.jsx               providers: React Query, Router, Toasts, Auth
├── App.jsx                routes; RequireAuth / admin guard; lazy-loaded secondary pages
├── index.css              design tokens (colors, type scale), answer typography, highlighter mark
├── api/client.js          fetch wrapper: in-memory access token, silent refresh, friendly errors, file download
├── api/endpoints.js       one function per backend endpoint
├── auth/AuthContext.jsx   session resume, login, logout, role flags
├── components/
│   ├── ui.jsx             Button, Field, Input, Select, Modal, ConfirmDialog, Badge, Toasts, formatters
│   ├── Layout.jsx         sidebar navigation (collapses to a menu on mobile), skip link
│   ├── Answer.jsx         Markdown answer with footnote citations, source list, match-strength indicator
│   └── SourcePane.jsx     the cited source as a page, with the supporting sentences highlighted
└── pages/                 Login, Register, Dashboard, Chat, History, Documents, Settings, Admin
```

### Design
- **The idea:** a records office. Ink navy, cool paper, ledger green for actions, and a highlighter
  yellow used **only** to mark cited text. Public Sans for the interface. Source Serif 4 for anything that comes
  *from documents* (answers and excerpts), which makes the boundary between app voice and document content visible.
- **The one bold element: citations.** Each answer cites with small footnote markers placed after punctuation, like
  a printed report. Clicking a marker, or a line in the source list, opens the **source pane**, which shows the cited
  passage laid out as a page with headings, the page number in the corner, and **the sentences that support the answer
  marked in highlighter**. The pane matches the words of the answer sentences that cite that source against
  the passage's sentences. "Show whole page" and "Open original" let the reader verify further.
- **The match-strength indicator** (three bars: Strong / Partial / Weak match) shows retrieval confidence in plain words.
- When no answer is found, the reply gets an amber rule and a suggestion of what to do next, rather than a dead end.

### Security in the browser
- **The access token lives only in memory**, never in localStorage, so an injected script can't harvest it from storage.
- **The refresh token is an httpOnly cookie** (`SameSite=Strict`, path limited to `/api/v1/auth`, `Secure` in
  production) set by the backend. JavaScript can't read it at all. On a page reload the app resumes the session by calling
  `/auth/refresh`; on any 401 the client refreshes once, sharing a single refresh across concurrent requests, and retries.
- Answers render through `react-markdown`, which does **not** render raw HTML. Links and images were already stripped by the backend.
- Original files are downloaded with the Authorization header (blob download), so there are no public file URLs.
- The frontend only hides what a role can't use. **Every rule is enforced by the backend.**

### Pages
| Page | What it does |
|---|---|
| Sign in / Create account | Validation as you type; new accounts are Employees |
| Overview | Greeting and a one-sentence summary of access and usage, quick ask box, recent conversations, recently updated documents, categories. Admins also see **Needs your attention** (failed processing, flagged documents, negative feedback) |
| Ask (chat) | Conversation list, suggested questions, Markdown answers, footnote citations and source pane, match strength, 👍/👎 with optional comment, **Clear chat**, search filters (categories and date range, shown as removable chips), Enter to send. Retries after an outage |
| Chat history | Search titles and message text, rename, delete |
| Documents | Filter by title, category, status and date. Table with version and status, polling while processing. Detail drawer: versions, use an older version, reprocess, delete version, open the original, **injection warnings with excerpts** (Admin/HR). Upload dialog: drag and drop multiple files with per-file results (accepted / already uploaded / rejected) |
| Profile and settings | Name and department, role and readable categories, password change (signs out everywhere) |
| Admin | Users (search, change role, activate or deactivate, add user). **Access by category** (a tickbox matrix of roles × categories). Usage and quality (questions, not-found rate, match, satisfaction, latency, per-day chart, most-cited documents). Answer feedback review. Audit log |

### Quality floor
Responsive down to phone width (the sidebar becomes a menu; the source pane becomes an overlay), visible keyboard
focus, a skip link, labelled icon buttons, `aria-live` loading and toasts, dialogs that close on Escape and return
focus, and `prefers-reduced-motion` respected (the only motion is the pane sliding in when you open it).

### How it was verified
The app was built for production and driven in **headless Chrome** (`scripts/screenshots.mjs`, using
`puppeteer-core`) against the real backend, seeded with the sample corpus, as an Employee and as an Admin,
at desktop and phone sizes. The backend ran with the offline test embedder and scripted LLM, so the answers in
the screenshots are stand-ins. The walkthrough found and fixed:
- **A crash that blanked the page after every answer.** Recent Chrome returns a Promise from `scrollIntoView()`,
  and an expression-bodied `useEffect` handed it to React as a "cleanup function".
- Filter fields stretching full width (a CSS class conflict), and a one-day chart rendering as a solid block.
- Source text losing its headings, and PDF line wraps showing up as paragraph breaks.
- Injection excerpts cut mid-word (fixed in the backend), "0.0 s" latencies, "1 pages", and a wrapping button.

---

## Phase 7 — Documentation and deployment

### Deployment (`docker-compose.prod.yml`)
| Container | What it is |
|---|---|
| `postgres` | PostgreSQL 16 with a health check and the `pgdata` volume |
| `backend` | `backend/Dockerfile`: Python 3.13 slim, CPU-only PyTorch, non-root user, models pre-downloaded at build time (`PRELOAD_MODELS`), health check. `scripts/docker-entrypoint.sh` runs `alembic upgrade head`, then one uvicorn worker trusting nginx's forwarded IP |
| `frontend` | `frontend/Dockerfile`: builds the React app with Node, then serves it with nginx (`frontend/nginx.conf`) |

Only nginx is published (port 8080 by default). nginx serves the app, sends client-side routes to `index.html`,
caches hashed assets for a year, proxies `/api` to the backend with a 120 s timeout for slow LLM answers, allows
upload requests up to 410 MB, and adds security headers with a strict **Content-Security-Policy** (everything
self-hosted, no inline scripts, no framing).

**One security fix found in testing:** nginx's usual `$proxy_add_x_forwarded_for` *appends* to whatever
`X-Forwarded-For` the client sends. Because the backend trusts that header, a client could put any IP in the
audit log and dodge the per-IP login rate limit by rotating fake addresses. A test login proved the spoof worked.
nginx now overwrites the header with the real connecting address.

New settings:
- `COOKIE_SECURE`: send the session cookie only over HTTPS. Defaults to on in production; the compose file
  turns it off until TLS is set up, because browsers drop `Secure` cookies on plain HTTP to anything but localhost.
- `REGISTRATION_EMAIL_DOMAINS`: only these email domains may self-register. Without it, anyone who can reach
  the site could make an Employee account and read Employee documents.

### API documentation (`docs/API.md`)
Generated by `python -m app.scripts.gen_api_docs` from the running application, so it can't go stale:
- Hand-written guide: the auth flow, the access model, error codes, rate limits, and the answer format.
- Every endpoint with who may call it, its parameters, request fields and response.
- All schemas, plus `docs/openapi.json`.

The "who may call it" column is **read from each route's real dependencies** (`get_current_user` /
`require_roles`). The same inspection powers `tests/test_api_surface.py`, which fails if any endpoint other than
health, register, login and refresh becomes callable without signing in, if any `/admin` route loses its admin
check, or if a document write loses its Admin/HR check.

> Recent FastAPI versions keep included routers nested instead of flattening them into `app.routes`;
> the generator walks the nesting. (Its first version silently found only the health endpoint.)

### Requirements
`docs/REQUIREMENTS.md` maps every item of the original brief to where it's implemented and how it was
verified, and states plainly what couldn't be verified in the build environment.
