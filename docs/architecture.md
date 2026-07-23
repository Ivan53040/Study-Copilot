# Study Copilot — Project Study Notes

These notes explain the main engineering techniques used in Study Copilot and
point to the exact files where each technique appears.

## 1. The architecture at a glance

Study Copilot uses a layered architecture:

```text
React UI
   ↓ HTTP/JSON
FastAPI route
   ↓ validated Python objects
Service / business logic
   ↓
SQLite + files + local AI model
   ↓
Typed JSON response
   ↓
React state and rendered UI
```

The main technologies are:

- **React + TypeScript** for the UI.
- **Vite** for the frontend development server and API proxy.
- **FastAPI** for HTTP API endpoints.
- **Pydantic** for request and configuration validation.
- **SQLAlchemy** as the database ORM and transaction layer.
- **SQLite + FTS5** for persistence and full-text search.
- **HTTPX** for calls from Python to LM Studio's OpenAI-compatible API.
- **NumPy** for cosine-similarity vector search.
- **Tauri + Rust** to package the web UI and Python backend as a desktop app.
- **Pytest** for automated tests.

This separation is important. The API route does not contain all the logic.
Routes are kept small, while reusable logic lives in service modules.

## 2. The API method: frontend to backend

### 2.1 The frontend API client

File: `frontend/src/api.ts`

The frontend uses the browser's built-in `fetch()` method:

```ts
const res = await fetch(`${BASE}${path}`, {
  headers: { "Content-Type": "application/json" },
  ...init,
});
```

The generic function is declared as:

```ts
async function request<T>(path: string, init?: RequestInit): Promise<T>
```

`T` is a TypeScript generic. It tells TypeScript what shape the returned JSON
should have:

```ts
health: () => request<Health>("/health")
```

This does not validate JSON at runtime, but it gives editor autocomplete and
compile-time checking.

For a POST request:

```ts
chat: (body) =>
  request<ChatResponse>("/chat", {
    method: "POST",
    body: JSON.stringify(body),
  })
```

Important HTTP ideas:

- **GET** reads data.
- **POST** creates something or runs an operation.
- **PUT** replaces or updates a resource.
- The request body is converted from a JavaScript object to JSON with
  `JSON.stringify()`.
- `Content-Type: application/json` tells FastAPI how to decode the body.
- `res.ok` checks whether the status is in the successful 200–299 range.
- Failed HTTP responses become JavaScript `Error` objects.

The client retries network failures because the packaged desktop app may call
the API before the Python backend has finished starting. It does not retry
normal HTTP errors such as 404 or 422.

### 2.2 Vite's development proxy

File: `frontend/vite.config.ts`

During development the frontend calls `/api/chat`, but Vite forwards it to:

```text
http://127.0.0.1:8000/chat
```

The proxy removes the `/api` prefix:

```ts
rewrite: (path) => path.replace(/^\/api/, "")
```

This lets the frontend use simple relative URLs and avoids most development
CORS issues.

### 2.3 FastAPI routes

Files: `app/main.py` and `app/api/*.py`

Every API area has an `APIRouter`:

```py
router = APIRouter(tags=["chat"])
```

An endpoint is connected to an HTTP method and path with a decorator:

```py
@router.post("/chat")
def post_chat(req: ChatRequest, settings: Settings = Depends(get_settings)):
    ...
```

`app/main.py` registers each router:

```py
app.include_router(chat.router)
app.include_router(search.router)
```

FastAPI automatically creates interactive documentation at `/docs`.

### 2.4 Pydantic request validation

The backend describes the expected JSON using a Pydantic model:

```py
class ChatRequest(BaseModel):
    message: str
    course: str | None = None
    scope_path: str | None = None
    conversation_id: int | None = None
```

FastAPI converts incoming JSON into `ChatRequest`. If a field has the wrong
type or a required field is missing, FastAPI returns a 422 validation response
before the endpoint logic runs.

Some requests use cross-field validation:

```py
@model_validator(mode="after")
def _scope(self):
    if not (self.course or self.scope_path or self.topic):
        raise ValueError("Provide at least a vault scope or a topic.")
    return self
```

This is useful when individual fields are optional, but at least one member of
a group must be provided.

### 2.5 Dependency injection

Routes receive settings with:

```py
settings: Settings = Depends(get_settings)
```

This is FastAPI dependency injection. The endpoint asks for a dependency rather
than loading configuration manually. It makes the code easier to test and
keeps configuration access consistent.

### 2.6 A complete chat request

The full flow is:

```text
ChatPage.send()
  → api.chat({...})
  → POST /api/chat
  → Vite proxy changes it to POST http://127.0.0.1:8000/chat
  → FastAPI creates ChatRequest
  → post_chat()
  → study_agent.answer()
  → retrieval + model generation + validation + database persistence
  → JSON ChatResponse
  → React updates turns, conversation ID, citations and warnings
```

Read these files in order:

1. `frontend/src/pages/Chat.tsx`
2. `frontend/src/api.ts`
3. `app/api/chat.py`
4. `app/agent/study_agent.py`
5. `app/retrieval/service.py`
6. `app/models/chat.py`

## 3. React techniques

### State

The pages use `useState()` for local UI state:

```ts
const [loading, setLoading] = useState(false);
const [error, setError] = useState<string | null>(null);
```

The common async UI pattern is:

```ts
setLoading(true);
try {
  const result = await api.someMethod();
  setData(result);
} catch (e) {
  setError((e as Error).message);
} finally {
  setLoading(false);
}
```

This models four useful UI states:

- idle
- loading
- success
- error

### Effects and cleanup

`useEffect()` runs side effects such as health polling:

```ts
const timer = setInterval(ping, 10000);
return () => clearInterval(timer);
```

The returned cleanup function prevents timers or event listeners from surviving
after the component is removed.

### Optimistic UI

Chat immediately adds the user's message before the server responds:

```ts
setTurns((turns) => [...turns, { role: "user", content: message }]);
```

This makes the interface feel responsive. If the API fails, the error is shown
separately.

### Functional state updates

Code such as:

```ts
setTurns((turns) => [...turns, newTurn]);
```

uses the latest state value. This is safer than reading a possibly stale
`turns` variable during asynchronous work.

### TypeScript interfaces

File: `frontend/src/types.ts`

Interfaces such as `ChatResponse`, `SearchResponse`, and `QuizResult` form a
frontend API contract. If the backend response changes, these types should be
updated too.

## 4. Database and transaction techniques

Files: `app/database/models.py` and `app/database/db.py`

### ORM models

SQLAlchemy maps Python classes to database tables:

```py
class Document(Base):
    __tablename__ = "documents"
    id: Mapped[int] = mapped_column(primary_key=True)
    path: Mapped[str] = mapped_column(String, unique=True)
```

Relationships express links between tables:

```py
chunks: Mapped[list["Chunk"]] = relationship(
    back_populates="document",
    cascade="all, delete-orphan",
)
```

One `Document` has many `Chunk` rows. Deleting a document also removes its
chunks.

### Normalisation and denormalisation

Document metadata is also copied into each chunk:

```py
course
week
source_type
trust_level
```

This is deliberate denormalisation. It duplicates some data, but makes search
queries and citation creation simpler and faster.

### Transaction context manager

Database operations use:

```py
with session_scope(settings) as session:
    ...
```

The context manager:

- commits if the block succeeds;
- rolls back if an exception occurs;
- always closes the session.

This is a clean unit-of-work pattern.

### Constraints

The models use database constraints such as:

```py
UniqueConstraint("document_id", "chunk_index")
```

Constraints protect data even if application code contains a bug.

## 5. Incremental ingestion pipeline

File: `app/ingestion/service.py`

The pipeline is:

```text
scan files
  → calculate SHA-256 hash
  → compare with indexed hash
  → skip unchanged files
  → parse Markdown/PDF/PPTX/text
  → classify metadata
  → split into chunks
  → store Document and Chunk records
```

### Content hashing

Each file has a SHA-256 content hash. On the next scan, unchanged hashes are
skipped. This is called incremental processing and avoids repeating expensive
work.

### Strategy by file type

`_parse_and_chunk()` selects a parser based on the extension. This is a simple
strategy pattern: different implementations share the same output shape.

### Semantic chunking

File: `app/ingestion/chunker.py`

Markdown is split by headings and paragraph boundaries. PDFs are split by page,
with page numbers preserved.

Good chunks are:

- small enough to fit into an AI prompt;
- large enough to contain meaningful context;
- connected to metadata needed for filtering and citations.

The project uses a maximum of roughly 1,500 characters per chunk.

## 6. Search: keyword, vector and hybrid retrieval

### Keyword search with SQLite FTS5

File: `app/retrieval/keyword_search.py`

SQLite FTS5 creates a full-text index over chunk content and headings. The query
uses BM25 ranking.

User input is tokenised and converted into a safe FTS expression:

```text
reliability & validity!
```

becomes:

```text
"reliability" OR "validity"
```

This prevents punctuation from breaking FTS query syntax.

FTS triggers in `app/database/db.py` keep the search index synchronized whenever
a chunk is inserted, updated or deleted.

### Embeddings

File: `app/models/embeddings.py`

An embedding converts text into a vector of numbers. Texts with similar meaning
should have vectors pointing in similar directions.

The production adapter calls the OpenAI-compatible endpoint:

```text
POST {LM_STUDIO_BASE_URL}/embeddings
```

with:

```json
{
  "model": "embedding-model-name",
  "input": ["text to embed"]
}
```

The project also has deterministic hashing embeddings for offline tests and
fallback behaviour.

### Cosine similarity

File: `app/retrieval/vector_search.py`

Stored vectors are compared with the query vector using cosine similarity:

```text
cosine similarity = (A · B) / (|A| × |B|)
```

The code normalises vectors and uses NumPy matrix multiplication:

```py
sims = normalized_matrix @ normalized_query
```

For a small local dataset, brute-force comparison is simple and fast enough. A
large system would normally use a vector database or approximate nearest
neighbour index.

### Reciprocal Rank Fusion

File: `app/retrieval/hybrid_search.py`

Keyword and vector scores use different scales, so they are not added directly.
Instead, Reciprocal Rank Fusion combines their rankings:

```text
RRF score(document) = Σ 1 / (k + rank)
```

A result appearing near the top of both lists receives a stronger combined
score.

Study Copilot then adds a trust bonus. Lower trust-level numbers represent more
authoritative material, so official sources can win close ties.

### Graceful degradation

If LM Studio's embedding endpoint is unavailable, search catches the exception
and still returns keyword results.

This is an important reliability principle: failure of an optional subsystem
should not necessarily break the entire feature.

## 7. RAG: retrieval-augmented generation

RAG means the model is given retrieved source material before it answers.

The project's RAG flow is:

```text
question
  → hybrid search
  → top source chunks
  → numbered context [S1], [S2], ...
  → prompt sent to local chat model
  → generated answer
  → citation validation
  → answer + sources + warnings
```

### Context building

File: `app/agent/context.py`

Search results are turned into a bounded prompt:

```text
[S1] source details
source content

[S2] source details
source content
```

The character budget prevents the prompt from growing without limit.

### Prompt grounding

File: `app/agent/prompts.py`

The system prompt tells the model to:

- use only provided sources;
- cite claims with `[S#]`;
- prefer more trusted material;
- refuse when the answer is absent;
- avoid invented sources.

Prompts guide model behaviour, but they do not guarantee it. That is why the
next validation step exists.

### Citation validation

File: `app/agent/validation.py`

The backend extracts every `[S#]` marker from the answer and checks that it
exists in the context actually sent to the model.

It warns when:

- the model cites a nonexistent source;
- the model makes a non-refusal answer without any valid citation.

This is an example of treating AI output as untrusted input.

### Conversation persistence

Chat conversations and messages are stored in SQLite. Follow-up requests send a
`conversation_id`, and the backend reloads recent messages.

Only a limited number of previous messages are included, controlling prompt
size and cost.

## 8. Adapter pattern for AI providers

Files: `app/models/chat.py` and `app/models/embeddings.py`

The code defines provider-independent protocols:

```py
class ChatAdapter(Protocol):
    def generate(...) -> ChatResponse:
        ...
```

Concrete implementations include:

- `LMStudioChatAdapter`
- `EchoChatAdapter`

The rest of the application depends on the interface, not on LM Studio
directly. This makes providers replaceable and tests deterministic.

LM Studio exposes OpenAI-compatible endpoints:

- `POST /chat/completions`
- `POST /embeddings`

“OpenAI-compatible” means the JSON request and response structure follows the
same general API format, even though the model runs locally.

## 9. Secure file access

File: `app/security/paths.py`

The application resolves every path before checking it:

```py
Path(path).expanduser().resolve()
```

Resolving first collapses `..` and follows symlinks. This helps block path
traversal attempts such as:

```text
StudyCopilot/../../secret.md
```

The RAG subsystem has narrow permissions:

- reads only configured roots;
- never reads denied paths such as `.env`, `.git`, `.ssh`, or `.obsidian`;
- writes generated material only inside `StudyCopilot/`.

The note workspace has a separate policy allowing edits to selected text file
extensions inside the vault. Separating these policies avoids giving the AI
generation subsystem unnecessary write access.

The principle is **least privilege**: each subsystem gets only the access it
needs.

## 10. Quiz and learning techniques

### Structured AI output

File: `app/generation/quizzes.py`

The model is instructed to return strict JSON. The backend then parses and
normalises each question.

It checks:

- allowed question types;
- non-empty questions and answers;
- allowed difficulty values;
- valid MCQ options;
- whether the MCQ answer exactly matches one option.

The answer key is stored only on the server. The client receives the question
and options, but not the correct answer.

### Event-based learning history

Quiz outcomes are recorded as `LearningEvent` rows. Confidence can therefore be
recomputed from historical evidence instead of being an unexplained mutable
number.

### Transparent confidence scoring

File: `app/learning/confidence.py`

The formula combines:

```text
50% recent accuracy
20% long-term accuracy
15% review recency
15% difficulty-weighted performance
```

The result is clamped between 0 and 1 and mapped to:

- weak
- developing
- good
- strong

### Spaced repetition

File: `app/learning/spaced_repetition.py`

The next review date depends on outcome and confidence:

- incorrect: 1 day;
- partial: 3 days;
- correct but low confidence: 7 days;
- good: 14 days;
- strong: 30 days.

This is a simple scheduling policy that can later be replaced behind the same
function with SM-2 or FSRS.

### Deterministic planning

File: `app/learning/planner.py`

Topic priority combines:

```text
50% low confidence
30% exam frequency
20% whether review is due
```

This logic is deterministic and explainable. AI is used where generation is
helpful, while ordinary formulas are used where predictable behaviour is more
important.

## 11. Configuration

Files: `config.yaml` and `app/config/settings.py`

YAML stores user-editable settings. Pydantic converts and validates the YAML as
typed Python objects.

`get_settings()` uses `@lru_cache(maxsize=1)`, so the configuration is loaded
once and reused.

Benefits:

- paths and model names are not scattered through business logic;
- invalid configuration fails early;
- tests can inject different settings;
- local and packaged environments can use different values.

## 12. Desktop packaging

File: `frontend/src-tauri/src/lib.rs`

Tauri packages the React frontend in a native desktop window. In release mode,
the Rust shell starts the Python FastAPI backend as a child process.

The child process is stored in application state and killed when the Tauri app
exits. Its standard output and errors are redirected to a log because a
double-clicked GUI app may not have a valid terminal attached.

The architecture is still client/server, but both parts run on the same
computer:

```text
Tauri webview → localhost FastAPI → SQLite/files/local model
```

## 13. Testing techniques

Folder: `tests/`

The tests use Pytest and cover units plus feature flows.

Examples:

- query sanitisation;
- keyword search;
- vector search with offline embeddings;
- hybrid ranking;
- fallback when embeddings are unavailable;
- citation validation;
- conversation persistence;
- path traversal prevention;
- incremental ingestion;
- sync conflict behaviour;
- confidence and planning formulas.

### Dependency substitution

Tests inject `EchoChatAdapter` instead of calling a real model. This makes tests:

- fast;
- offline;
- repeatable;
- free from random model responses.

### Temporary settings and databases

Pytest fixtures create isolated vaults and databases, so tests do not modify the
real notes.

### What to test around an API endpoint

For each endpoint, think in four groups:

1. valid request and expected response;
2. invalid request validation;
3. missing resource or dependency failure;
4. security and permission boundaries.

## 14. Design principles used throughout the project

### Thin routes, thick services

API routes translate HTTP requests into service calls. Business logic remains
usable from API routes, CLI scripts, tests, and future interfaces.

### Separation of concerns

Parsing, chunking, retrieval, AI calls, database access, API transport, and UI
rendering live in separate modules.

### Dependency inversion

High-level code talks to `ChatAdapter` and `EmbeddingProvider` interfaces rather
than one hard-coded provider.

### Graceful fallback

Keyword search still works without embeddings. Sources still return if the chat
model is unavailable.

### Validate boundaries

The project validates:

- incoming HTTP JSON;
- YAML configuration;
- paths;
- AI-generated JSON;
- AI-generated citations.

### Local-first design

Notes, database records, embeddings, and model calls remain on the user's
machine unless a future cloud provider is explicitly enabled.

## 15. Suggested study order

### Stage 1: Basic API flow

Study:

1. `frontend/src/pages/Search.tsx`
2. `frontend/src/api.ts`
3. `app/api/search.py`
4. `app/retrieval/service.py`

Goal: explain how a button click becomes a Python function call and returns as
rendered results.

### Stage 2: Database

Study:

1. `app/database/models.py`
2. `app/database/db.py`
3. `app/ingestion/service.py`

Goal: understand models, relationships, sessions, commits, rollbacks and
incremental upserts.

### Stage 3: Retrieval

Study:

1. `app/retrieval/keyword_search.py`
2. `app/models/embeddings.py`
3. `app/retrieval/vector_search.py`
4. `app/retrieval/hybrid_search.py`

Goal: explain why keyword and semantic search complement one another.

### Stage 4: RAG and model APIs

Study:

1. `app/models/chat.py`
2. `app/agent/context.py`
3. `app/agent/prompts.py`
4. `app/agent/validation.py`
5. `app/agent/study_agent.py`

Goal: draw the full retrieve → prompt → generate → validate pipeline.

### Stage 5: Safety and reliability

Study:

1. `app/security/paths.py`
2. `tests/test_paths.py`
3. `tests/test_search.py`
4. `tests/test_agent.py`

Goal: understand why AI output and filesystem input are never trusted blindly.

## 16. Practice exercises

### Exercise 1: Add a simple API endpoint

Create:

```text
GET /stats
```

Return the total number of documents, chunks and conversations. Then:

- add a TypeScript `Stats` interface;
- add `api.stats()`;
- display it on the Library page;
- write a Pytest test.

This practises the complete API method.

### Exercise 2: Add request validation

Add a minimum query length to `SearchRequest`, then observe FastAPI's 422
response in `/docs`.

### Exercise 3: Add an API filter

Add a `week` selector to the Search page and send it through:

```text
React → api.ts → SearchRequest → MetadataFilter → SQL query
```

### Exercise 4: Add a provider

Create another class satisfying `ChatAdapter`. The study agent should work
without changing its core logic.

### Exercise 5: Improve retry behaviour

Change the fixed 700 ms retry delay to exponential backoff:

```text
500 ms, 1 s, 2 s, 4 s...
```

Consider which errors should and should not be retried.

### Exercise 6: Upgrade spaced repetition

Research SM-2 or FSRS and replace `next_interval_days()` while keeping its
public interface stable.

## 17. Questions you should be able to answer

1. Why does the frontend use a shared `request<T>()` function?
2. What does Pydantic validate that TypeScript cannot?
3. Why should FastAPI routes remain small?
4. What happens inside `session_scope()` after an exception?
5. Why are source files split into chunks?
6. What is the difference between FTS5 search and embedding search?
7. Why use rank fusion instead of adding BM25 and cosine scores directly?
8. How does the system prevent hallucinated citation IDs?
9. Why are model adapters useful for tests?
10. How does path resolution help prevent directory traversal?
11. Why are quiz answer keys omitted from the frontend response?
12. Which parts of the project are deterministic, and which use an AI model?

If you can answer these in your own words and complete Exercises 1–3, you will
understand the most important engineering techniques used in this project.
