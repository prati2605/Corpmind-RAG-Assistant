# Requirements checklist

Every item from the project brief, where it's implemented, and how it was verified.
"Test" means an automated test in `backend/tests/` (97 tests, run against real PostgreSQL and ChromaDB).
"Browser" means it was exercised in headless Chrome against the running app.

## 1. Technology stack

| Requirement | Implementation |
|---|---|
| React.js frontend | `frontend/`: React 19, Vite, React Router, TanStack Query, Tailwind |
| Python FastAPI backend | `backend/app/` |
| LangChain | `init_chat_model` for the LLM (`services/llm.py`), message types for prompts, `RecursiveCharacterTextSplitter` for chunking |
| API-based LLM, provider configurable | `LLM_PROVIDER` / `LLM_MODEL` in `.env`: OpenAI, Anthropic, Groq, Gemini, Ollama |
| Hugging Face sentence-transformer embeddings | `services/embeddings.py`, default `all-MiniLM-L6-v2`, configurable |
| ChromaDB | `services/vector_store.py`, persistent collection with cosine distance |
| PostgreSQL | SQLAlchemy 2 models, Alembic migrations; also hosts the keyword (full-text) index |
| PyPDF, python-docx, CSV/TXT parsers | `services/ingestion/parsers.py` |

## 2. Document management

| Requirement | Where | Verified |
|---|---|---|
| Authorized admins upload documents | `POST /documents` (Admin, HR) | Test, Browser |
| Multiple files at once | up to 20 per request, per-file result | Test, Browser |
| PDF, DOCX, TXT, CSV | one parser per format | Test (all four formats) |
| Extract and clean text | `cleaning.py`: normalization, invisible characters, hyphenation, headers/footers | Test |
| Meaningful chunks | page-aware recursive splitting at paragraph/sentence boundaries | Test |
| Embeddings per chunk | at ingestion, batched | Test |
| Store in ChromaDB | vector id = Postgres chunk id | Test (consistency check) |
| Metadata in PostgreSQL | `documents`, `document_versions`, `chunks` | Test |
| Names, upload dates, categories, versions | title, `created_at`, category, `version_number`, effective date | Test, Browser |
| Delete with vectors removed | document or single version; file, rows and vectors | Test |
| Avoid duplicate processing | SHA-256 content hash, unique | Test |
| Preserve page numbers and source metadata | PDF pages, DOCX pages + headings, TXT form feeds, CSV row ranges | Test |

## 3. RAG pipeline

| Step | Where |
|---|---|
| 1. Receive query | `POST /chat/ask`, `POST /rag/query` |
| 2. Understand and preprocess | `rag/query.py`: cleaning, small talk, follow-up rewriting, mode and document detection |
| 3. Query embedding | `retrieval.py` |
| 4. Retrieve relevant chunks | hybrid: ChromaDB + PostgreSQL full-text, fused with RRF |
| 5. Relevance threshold | `RELEVANCE_THRESHOLD` / `RERANK_THRESHOLD`, tunable with `evaluation.run --sweep` |
| 6. Optional reranking | cross-encoder `ms-marco-MiniLM-L-6-v2`, `ENABLE_RERANKER` |
| 7. Context to LLM | `rag/prompt.py`: numbered, fenced document blocks |
| 8. Grounded response | system rules plus code enforcement (`generation.py`) |
| 9. Answer with citations | validated `[n]` markers mapped to document, page, section and snippet |
| Hybrid retrieval | yes (test: exact form code found by keyword search) |
| Prioritize company documents over model knowledge | answers without a valid citation are replaced by the fallback; a general-knowledge question is in the evaluation set as must-refuse |

## 4. Chatbot capabilities

| Capability | Implementation | Verified |
|---|---|---|
| Natural-language Q&A | pipeline `qa` mode | Test, Browser |
| Follow-ups with context | history from the database → standalone question before retrieval | Test |
| Answers from multiple documents | top-k across documents, max 4 per document for diversity | Evaluation item |
| Summarization | `summarize` mode reads the whole document in order | Test |
| Policy comparison | `compare` mode retrieves from each named document separately; table format | Test |
| Extract important information | key-points and deadline suggestions; summary format | Browser |
| Dates, policies, procedures | evaluation set has date / procedure / fact questions | Evaluation |
| Citations with names and pages | footnotes, source list, source pane with highlighted sentence | Test, Browser |
| Exact "couldn't find" message | returned without calling the LLM when nothing is relevant, and when the LLM's answer has no valid citation | Test |
| Never fabricate | grounding rules plus citation enforcement in code; faithfulness metric | Test, Evaluation |

## 5. Advanced features

| Feature | Implementation | Verified |
|---|---|---|
| Roles: Admin, HR, Employee | `users.role`, `require_roles` | Test |
| Category-based permissions | `role_category_permissions`, editable matrix in Admin | Test, Browser |
| Conversation history | conversations and messages; history page with search | Test, Browser |
| Document version management | versions, active switch, roll-back, delete version | Test, Browser |
| User feedback | 👍/👎 with comment; admin review | Test, Browser |
| Confidence / relevance indicator | 0–1 score and Strong/Partial/Weak label per answer | Test, Browser |
| Multi-document comparison | compare mode | Test |
| Filters by category and date | chat filters and document list filters | Test, Browser |
| Upload and deletion dashboard | Documents page and detail drawer | Browser |
| Prompt-injection protection | flagging at ingestion, fenced and escaped prompt, output sanitizing | Test (tag-break payload, planted instruction) |
| **Access enforced during retrieval, not just frontend** | filters inside ChromaDB and SQL queries plus a Postgres re-check | Test (corrupted vector metadata still can't leak), Evaluation (0 leaks) |

## 6. Frontend

| Requirement | Verified |
|---|---|
| Login and registration | Browser |
| Dashboard overview | Browser |
| AI chatbot interface | Browser |
| Document management page | Browser |
| Chat history | Browser |
| Profile and settings | Browser |
| Admin panel | Browser |
| Chat: clean layout, input, suggested questions, loading indicator, Markdown answers, clickable citations, feedback buttons, clear-chat | Browser (all) |
| Responsive, polished, minimal | Browser at 1440 px and 390 px |

## 7. Security and reliability

| Requirement | Implementation | Verified |
|---|---|---|
| Secure authentication | Argon2id, JWT access tokens, rotating refresh tokens with reuse detection, httpOnly cookie | Test |
| Role-based authorization | backend dependencies; roles re-read every request | Test (incl. an API-surface test) |
| Input validation | Pydantic schemas, length limits, consistent 422 errors | Test |
| File type and size validation | magic bytes, size cap, zip-bomb and macro checks | Test |
| API keys in environment variables | `.env`, `.env.example`; never in code, responses or logs | Test (log redaction, error responses) |
| Error handling and logging | JSON errors, request ids, generic 500s, structured logs | Test |
| No unauthorized document access | 404 for hidden documents, chunks, downloads; ACL in retrieval | Test |
| Safe handling of untrusted content | sanitized filenames, random storage names, escaped prompt data, no raw HTML rendered | Test |
| Rate limiting | slowapi: sign-in, questions, default | Test |
| No API keys or confidential content in frontend code or logs | keys are backend-only; logs record ids and counts only; Chroma stores no text | Test, review |

Added beyond the brief: an audit log, CSP and security headers, registration restricted to company email
domains, and nginx that overwrites client-supplied `X-Forwarded-For` (spoofing was found and fixed in testing).

## 8. Evaluation

| Metric | Implementation |
|---|---|
| Precision@K, Recall@K | `evaluation/metrics.py` (plus MRR and hit rate) |
| Answer relevance | embedding similarity, or LLM judge (`--judge llm`) |
| Faithfulness | heuristic (words and every number must appear in the retrieved context), or LLM judge |
| Citation correctness | citation precision against the gold documents and pages |
| Latency | p50, p95 and mean, with a per-stage breakdown |
| Sample dataset | `evaluation/dataset.json`: 31 questions with expected answers, key facts and relevant documents/pages |

Also measured: key-fact correctness, correct refusals, confidential-document leaks, injection violations, and a
threshold sweep. Unit-tested with hand-computed values; the full run is tested end to end.

## 9. Deliverables

| Deliverable | Location |
|---|---|
| Complete source code | `backend/`, `frontend/` |
| requirements.txt | `backend/requirements.txt` (pinned) |
| .env.example | `backend/.env.example`, `.env.example` (Docker), `frontend/.env.example` |
| Database schema and migrations | `backend/app/models/`, `backend/alembic/versions/` (3 migrations; up and down tested) |
| API documentation | `docs/API.md` (generated), `docs/openapi.json`, live `/docs` |
| README.md | `README.md` |
| Sample company documents | `backend/sample_docs/` (13 + 1 version) |
| Run locally | `README.md` → Quick start; Docker in `docker-compose.prod.yml` |
| Explanation of each module | `docs/MODULES.md` |
| No placeholder implementations | every feature is wired to a working backend path and tested; test doubles live only in `backend/tests/` |
| Built incrementally, backend first | Phases 1–5 backend, 6 frontend, 7 docs and deployment |

## What could not be verified in the build environment

The build sandbox had no access to Hugging Face, an LLM API, or Docker Hub. So:

- **Real models:** the sentence-transformer embedder and cross-encoder reranker were not run; tests use stand-ins.
  First check on your machine: `python -m app.scripts.download_models`.
- **Real LLM answers:** the provider code path was exercised up to an authentication error (Anthropic SDK with
  an invalid key); actual answers were not generated. First check: ask a question with your key set.
- **Retrieval quality numbers:** run `python -m evaluation.run --retrieval-only --sweep`, then the full run.
- **Docker images were not built.** Their contents were checked instead: the compose file validates, the
  container start-up script was run in production mode against a fresh database, and the nginx config was run
  (nginx 1.24) in front of the app, including a full browser walkthrough under the Content-Security-Policy.
