# Document API

A persistent backend with full CRUD APIs, token-based authentication, and pagination.

Built with Django 6.1 and Django REST Framework 3.18.

---

## Models

| Model | Fields |
|---|---|
| `Document` | id, title, content, uploaded_at, owner |
| `QueryLog` | id, query_text, result_summary, created_at, user |
| `UserSession` | id, user, token, created_at, expires_at |

---

## Setup

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env            # set SECRET_KEY in .env
python manage.py migrate
python manage.py runserver
```

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

### Health

#### `GET /health`
Liveness check. No authentication required.

- **200** — `{ "status": "healthy" }`

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

## Tests

```bash
python manage.py test api.tests
```

Run a single module:

```bash
python manage.py test api.tests.test_auth
python manage.py test api.tests.test_documents
python manage.py test api.tests.test_queries
```

25 tests total across three files.
