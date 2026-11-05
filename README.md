# Document and AI Backend

A persistent backend with full CRUD APIs, token-based authentication, pagination, and AI-powered document Q&A. Extends Assignment 2 with RAG (retrieval-augmented generation) using FAISS and Anthropic.

Built with Django 6.1 and Django REST Framework 3.18.

---

## Architecture

```
Streamlit UI  ──HTTP──►  Django / DRF  ──►  LangGraph agent
                                                   │
                                       ┌───────────┼───────────┐
                                       ▼           ▼           ▼
                                      LLM        FAISS    Open-Meteo
                                  (Anthropic)   (local)   (weather)
```

The Streamlit UI talks only to the Django backend. The backend runs the LangGraph agent, which calls the LLM, queries the FAISS vector store, or hits the weather API depending on the question.

---

## Agent graph

The graph has five nodes and three routes:

```
START
  │
  ▼
rewrite_question          Rewrites follow-up questions into standalone ones.
  │
  ▼
decide_route              Classifies the question: documents | weather | general
  │
  ├──► retrieve_docs ──►  write_answer   (documents route)
  │
  ├──► call_weather  ──►  write_answer   (weather route)
  │
  └──────────────────────► write_answer  (general route)
                                │
                               END
```

| Node | What it does |
|---|---|
| `rewrite_question` | Rewrites follow-ups into standalone questions using the conversation transcript. Skipped on the first message. |
| `decide_route` | Sends the rewritten question and the user's document titles to the LLM; returns `documents`, `weather`, or `general`. |
| `retrieve_docs` | Runs a FAISS similarity search over the user's indexed chunks. |
| `call_weather` | Extracts the city name and calls the Open-Meteo tool. |
| `write_answer` | Builds the final prompt from the route's context and calls the LLM to produce the answer. |

---

## Memory

Chat sessions and messages are stored in the database (`ChatSession` and `ChatMessage` models). Each turn loads the last **6 messages** from the session and passes them to the agent. Before routing, `rewrite_question` resolves pronouns and references against that history so follow-up questions ("What was its budget?") become searchable standalone queries ("What was Zorblax's budget?"). The rewrite step fires only when history is non-empty.

---

## Routing

The router receives the user's document titles inside `<user_files>` tags and classifies the question as one of three routes:

- **documents** — the answer could be in one of the uploaded files. Topic matching is used, so a question about "pasta" routes to documents when a file named `pasta.pdf` exists. When in doubt between documents and general, the router picks documents.
- **weather** — the question asks about current weather or temperature.
- **general** — greetings, general knowledge, and coding questions unrelated to the uploaded files.

Because the router sees the file names (not the file contents), **descriptive file names work better than generic ones** (`pasta_recipe.pdf` vs `scan_001.pdf`).

---

## Weather tool

The weather tool is implemented in [assistant/tools.py](assistant/tools.py) using the free **Open-Meteo** API. When the router picks the `weather` route, `call_weather` extracts the city name with an LLM call and then:

1. Geocodes the city at `geocoding-api.open-meteo.com`.
2. Fetches the current temperature, humidity, and weather code at `api.open-meteo.com`.

The result is formatted as a string (`London: 12.5°C, Overcast, humidity 70%`) and passed to `write_answer`, which wraps it in `<weather_data>` tags and sends it to the LLM.

---

## Chat endpoints

#### `POST /api/upload-doc`
Upload and immediately ingest a PDF or TXT file.

- **Body:** multipart form with a `file` field — `.pdf` or `.txt`, max 5 MB.
- **201** — `{ "status": "ingested", "document_id": 12, "title": "...", "chunk_count": 3 }` — PDFs also include `"page_count"`.
- **400** — wrong file type, not valid UTF-8, no extractable text, encrypted PDF.
- **401** — missing or invalid token.
- **413** — file or extracted text exceeds the size limit.

#### `POST /api/chat`
Send a message to the agent.

- **Body:** `{ "message": "...", "session_id": 42 }` — `session_id` is optional; omit to start a new session.
- **200** — `{ "session_id": 42, "answer": "...", "route": "documents", "steps": ["rewrite", "route:documents", "retrieve", "answer"], "tool_output": null, "sources": [{ "document_id": 12, "title": "...", "chunk_text": "..." }] }`
- **400** — blank or oversized message (max 2 000 characters).
- **401** — missing or invalid token.
- **404** — `session_id` does not exist or belongs to another user.
- **502** — the agent or LLM failed.

#### `GET /api/chat/sessions/{id}`
Retrieve the full message history for a session.

- **200** — `{ "session_id": 42, "title": "...", "messages": [{ "role": "user"|"assistant", "content": "..." }] }`
- **401** — missing or invalid token.
- **404** — session does not exist or belongs to another user.

---

## Auth (UI)

The login screen posts credentials to `POST /login` and stores the returned token in **Streamlit's `session_state`**. All subsequent API calls attach the token as `Authorization: Token <token>`. Because `session_state` is in-memory, a **page refresh clears the token and returns the user to the login screen**. A 401 response from any authenticated call also triggers an automatic logout and redirect.

---

## Setup

```bash
# Terminal 1 — Django backend
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env            # set SECRET_KEY and ANTHROPIC_API_KEY
python manage.py migrate
python manage.py runserver

# Terminal 2 — Streamlit UI
source venv/bin/activate
streamlit run ui/app.py
```

If the Django backend is not on port 8000, set `API_URL` before starting Streamlit:

```bash
API_URL=http://localhost:9000 streamlit run ui/app.py
```

---

## Models

| Model | Fields |
|---|---|
| `Document` | id, title, content, uploaded_at, owner |
| `QueryLog` | id, query_text, result_summary, created_at, user |
| `UserSession` | id, user, token, created_at, expires_at |
| `AIQueryLog` | id, user, endpoint, query_text, response_text, sources, created_at |
| `DocumentChunk` | id, document, owner, chunk_index, text, faiss_row |

---

## Notes

The app refuses to start without both `SECRET_KEY` and `ANTHROPIC_API_KEY` set. The first RAG call downloads the `all-MiniLM-L6-v2` embedding model (~90 MB) and caches it locally. The fake key in `.env.example` is enough to run the tests.

---

## Authentication

All endpoints except `POST /register` and `POST /login` require a valid token in the `Authorization` header:

```
Authorization: Token <token>
```

Tokens are issued by `POST /login` and expire after **24 hours**. A missing, invalid, or expired token returns `401` with a `WWW-Authenticate: Token` header. Requests from an inactive user also return `401`.

---

## Endpoints

### Auth

#### `POST /register`
Register a new user.

- **Body:** `username`, `password`
- **201** — `{ id, username }` (password is never returned)
- **400** — duplicate username or password fails validation (too short, too common, all-numeric)

#### `POST /login`
Authenticate and receive a session token.

- **Body:** `username`, `password`
- **200** — `{ token, expires_at }` — token is 64 hex characters
- **400** — missing field
- **401** — invalid credentials

---

### Documents

#### `POST /documents`
Create a document from a JSON body or a file upload.

- **JSON body:** `title`, `content`
- **Multipart upload:** `file` field — allowed types: `.txt`, `.md`, `.csv`, `.json`; max size: 1 MB; must be valid UTF-8. Title defaults to the filename.
- **201** — the created document object. The `owner` field in the request body is ignored; the document is always assigned to the authenticated user.
- **400** — invalid file type or encoding
- **401** — missing or invalid token
- **413** — file or content exceeds 1 MB

#### `GET /documents`
List the authenticated user's documents, newest first.

- **Query params:** `page`, `page_size` (default 10, max 100)
- **200** — `{ count, next, previous, results }`
- **401** — missing or invalid token

#### `GET /documents/{id}`
Retrieve a single document.

- **200** — the document object
- **401** — missing or invalid token
- **404** — not found, or the document belongs to another user

#### `DELETE /documents/{id}`
Delete a document.

- **204** — deleted
- **401** — missing or invalid token
- **403** — the document exists but belongs to another user
- **404** — document does not exist

---

### Search

#### `POST /query`
Search the authenticated user's own documents and log the query.

- **Body:** `query_text` (max 1 000 characters)
- The search is a case-insensitive substring match against both `title` and `content`. Documents belonging to other users are never included.
- **201** — a `QueryLog` object with a `result_summary` (e.g. `"3 documents matched: Report Q1, Notes, Draft"`)
- **400** — blank or oversized `query_text`
- **401** — missing or invalid token

#### `GET /queries`
List the authenticated user's query history, newest first.

- **Query params:** `page`, `page_size` (default 10, max 100)
- **200** — `{ count, next, previous, results }`
- **401** — missing or invalid token

---

### AI

#### `POST /api/ask-ai`
Send a prompt to the LLM and get a response.

- **Body:** `prompt` (max 2 000 characters)
- **200** — `{ "response": "..." }`
- **400** — blank or oversized prompt
- **401** — missing or invalid token
- **502** — Anthropic request failed

#### `POST /api/ingest-doc`
Chunk a document, embed it, and build the user's FAISS index. Idempotent: ingesting the same document twice leaves the same result.

- **Body:** `document_id` (positive integer)
- **200** — `{ "status": "ingested", "document_id": 12, "chunk_count": 3 }` — `chunk_count` is the number of chunks for this document only.
- **400** — missing or invalid `document_id`
- **401** — missing or invalid token
- **404** — document does not exist, or belongs to another user (same response for both)

#### `POST /api/rag-query`
Retrieve the most relevant chunks from the user's index and answer using the LLM. If the user has no ingested documents, returns a fixed "no relevant documents" message with `sources: []` without calling the LLM.

- **Body:** `query` (max 2 000 characters)
- **200** — `{ "answer": "...", "sources": [{ "document_id": 12, "chunk_text": "..." }] }`
- **400** — blank or oversized query
- **401** — missing or invalid token
- **502** — Anthropic request failed

#### `GET /api/query-history`
List the authenticated user's AI query history (both `ask-ai` and `rag-query` calls), newest first.

- **Query params:** `page`, `page_size` (default 10, max 100)
- **200** — `{ count, next, previous, results }` — each result has `id`, `endpoint`, `query_text`, `response_text`, `sources`, `created_at`
- **401** — missing or invalid token

---

### Health

#### `GET /health`
Liveness check. No authentication required.

- **200** — `{ "status": "healthy" }`

---

## How the AI part works

**Chunking** — Documents are split into 500-character chunks with 100 characters of overlap, by character count. Overlap ensures that a sentence cut at a boundary still appears whole in one chunk.

**Embeddings** — `all-MiniLM-L6-v2` (384 dimensions, normalized to unit length, `float32`). The model runs locally and is downloaded on the first RAG call (~90 MB).

**Vector store** — One FAISS `IndexFlatIP` (flat inner-product, equivalent to cosine similarity on normalized vectors) per user, stored at `faiss_indexes/user_<id>.index`. The `DocumentChunk` table is the source of truth: every ingest rebuilds the user's entire index from their current chunks, renumbering `faiss_row` from 0. Because the index path and the chunk lookup both use `user.id`, a search can only ever see its owner's vectors.

**Retrieval** — Top 3 chunks by inner product score.

**LLM** — Anthropic, model from `ANTHROPIC_MODEL` env var, capped at 500 output tokens.

**Prompt templates** — `ask-ai` uses a scoped system prompt (software, data and AI topics) and wraps the user's text in `<user_prompt>` tags. RAG uses a system prompt that instructs the model to answer only from the provided `<context>`, and formats chunks and the question in XML-like tags. Closing tags (`</chunk>`, `</context>`, `</question>`) are escaped in both chunk text and the query before being inserted into the prompt. This reduces the risk of prompt injection from uploaded documents but does not eliminate it — an adversarial document can still include opening tags or other content that influences model behavior.

---

## Pagination

All list endpoints return the same envelope:

```json
{
  "count": 42,
  "next": "http://localhost:8000/documents?page=3",
  "previous": "http://localhost:8000/documents?page=1",
  "results": [...]
}
```

Default page size is **10**. Override with `?page_size=N` (max 100) and `?page=N`.

---

## Known limitations

- **Stale index after document delete.** Deleting a document cascades to its chunks in the database, but the user's FAISS index file is not updated. Searches may return stale results until the next `POST /api/ingest-doc` call on any of the user's documents, which triggers a full index rebuild from the remaining chunks.

- **Partial prompt-injection neutralization.** Closing tags are escaped in chunk text and queries, but opening tags (e.g. `<chunk id="9">`) are not. The system prompt instructs the model to treat context content as data, which reduces the risk but does not eliminate it.

---

## Tests

```bash
python manage.py test
```

Run a single app or module:

```bash
python manage.py test api.tests
python manage.py test ai.tests
python manage.py test assistant.tests
python manage.py test api.tests.test_auth
```

The LLM, the weather HTTP calls, and the embedding model are all faked in the test suite — no network access or real API key needed. `FakeLLM` in `assistant/tests/test_assistant.py` steers each graph node by its system prompt; `fake_httpx_get` returns canned Open-Meteo geocoding and forecast responses; `fake_embed` replaces the sentence-transformer model with a deterministic vector.
