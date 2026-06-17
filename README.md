# Study Copilot

A local-first AI study assistant over an Obsidian vault. It ingests your course
materials, past papers and notes; will answer source-grounded questions, generate
revision notes and quizzes, track concept-level progress, and write outputs back
into a dedicated `StudyCopilot/` folder — **never** modifying your original notes.

Built incrementally against the [build plan](Study_Copilot_Build_Plan.md).

## Status

| Phase | Description | State |
|-------|-------------|-------|
| 0 | Setup: config, SQLite, FastAPI, logging, path-security | ✅ Done |
| 1 | Ingestion: scan → parse → classify → chunk → index | ✅ Done |
| 2 | Search: FTS5 + embeddings + hybrid retrieval | ✅ Done |
| 3 | Grounded chat (LM Studio) with citations | ✅ Done |
| 4 | Obsidian note generation | ⏳ Next |
| 5 | Learning history (quizzes, confidence) | ⏳ |
| 6 | Planning (weak topics, daily plans) | ⏳ |
| 7 | Past papers / mock exams | ⏳ |
| 8 | Evaluation | ⏳ |

## Setup

```bash
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt   # Windows
# source .venv/bin/activate && pip install -r requirements.txt # macOS/Linux
```

Edit [`config.yaml`](config.yaml) to point at your vault and choose which folders
are readable. The defaults target the REIT6811 course, plus a folder of
past-paper PDFs.

### Local vault + iCloud sync

iCloud Drive on Windows is unreliable at syncing *newly created* notes (they get
stuck as online-only placeholders). So the copilot works against a **local**
vault and syncs to iCloud on a timer:

- `vault.root` → `C:/Users/ivank/Documents/StudyVault` (local working copy)
- `sync.icloud_root` → the iCloud Obsidian folder
- Point **Obsidian itself at the local `StudyVault`** going forward.

Three sync modes (`sync.mode`):

| Mode | Engine | Behaviour |
|------|--------|-----------|
| `twoway` *(default)* | `app/sync/twoway.py` | Bidirectional. Manifest-based: propagates creates/edits/deletes both ways; conflicts resolved newer-wins with a `(sync-conflict …)` backup of the loser; a deleted file that was edited on the other side is resurrected. |
| `mirror` | `robocopy /MIR` | One-way exact copy local→iCloud (deletes extras in iCloud). |
| `additive` | `robocopy /E` | One-way local→iCloud, never deletes. |

The two-way engine keeps a manifest at `data/sync_state.json` (the last synced
state) so it can tell "deleted here" from "created there". High-churn junk
(`.obsidian/workspace*.json`, `.trash/`, `.DS_Store`, `*.icloud`) is excluded.

Manual sync:

```bash
python -m scripts.sync --dry-run   # preview, change nothing
python -m scripts.sync             # sync now
```

### Run sync automatically (Windows Scheduled Task)

The sync also runs as a standalone, CWD-independent script
([`scripts/sync_standalone.py`](scripts/sync_standalone.py)) suitable for Task
Scheduler. To register a task that runs every 5 minutes for your user:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install_sync_task.ps1
```

Remove it with `scripts\uninstall_sync_task.ps1`. Each run appends to
`data/sync.log`. (`sync.run_in_app: false` in config keeps the app from also
syncing, so you don't get double runs.)

## Usage

Ingest all configured material (incremental — unchanged files are skipped):

```bash
python -m scripts.ingest
```

Run the API:

```bash
python -m app.main          # http://127.0.0.1:8000  (docs at /docs)
```

Index embeddings for vector search (needs an embedding model loaded in LM
Studio, e.g. `nomic-embed-text`; otherwise set `embeddings.provider: hash` in
config for an offline fallback):

```bash
python -m scripts.embed            # embed chunks missing an embedding
python -m scripts.embed --reindex  # re-embed everything
```

Endpoints live so far:

- `GET  /health` — config + vault sanity check
- `POST /ingest/scan` — full incremental ingest
- `POST /ingest/file` — ingest a single readable file
- `GET  /courses` — document/chunk counts per course
- `GET  /courses/{course}/documents` — list indexed documents
- `POST /search` — hybrid (keyword + vector) search with citations; filter by
  `course`/`week`/`source_type`/`max_trust_level`
- `POST /chat` — grounded Q&A; `{message, course?, conversation_id?}` → answer
  with `[S#]` citations, validated source list, and warnings
- `GET  /conversations/{id}` — replay a conversation
- `GET  /sync/status` — background sync state
- `POST /sync/run` — trigger a sync (`?dry_run=true` to preview)

### Grounded chat (Phase 3)

`POST /chat` retrieves with hybrid search, builds a numbered source context,
and asks the local model (LM Studio) to answer **only** from those sources with
`[S#]` citations. The answer's citations are then **validated** against the
sources actually provided — hallucinated markers and uncited claims are flagged
in `warnings`. If the model is unavailable, the endpoint still returns the
retrieved sources with a note. Conversations persist (`conversations`/`messages`
tables) so follow-up questions keep context.

> Needs a chat model loaded in LM Studio. The model never sees anything beyond
> the retrieved chunks, so answers stay grounded in your own materials.

### Retrieval design (Phase 2)

- **Keyword:** SQLite FTS5 (BM25), kept in sync with `chunks` via triggers.
- **Vector:** embeddings stored as float32 blobs; brute-force cosine in numpy
  (swap for Chroma/Qdrant later behind the same interface).
- **Hybrid:** Reciprocal Rank Fusion of keyword + vector, then a trust-level
  bonus so official material outranks unreviewed notes on ties.
- **Graceful:** if the embedding endpoint is down, search returns keyword-only
  results with a note instead of failing.

## Tests

```bash
python -m pytest
```

## Safety model

- **Reads** are confined to the vault's `read_paths` + configured
  `external_sources`, and `denied_paths` (`.env`, `.git`, `.obsidian`, `.ssh`)
  are always blocked — even against path-traversal attempts.
- **Writes** are confined to `StudyCopilot/` and nothing else.
- Source files are never rewritten; classification is inferred, never persisted
  back to your notes.

All path enforcement lives in [`app/security/paths.py`](app/security/paths.py)
and is covered by [`tests/test_paths.py`](tests/test_paths.py).

## Layout

```
app/
  config/       settings loaded from config.yaml
  security/     path permission enforcement (read/write/denied)
  database/     SQLAlchemy models (Document, Chunk) + session
  ingestion/    scanner, markdown/pdf parsers, classifier, chunker, service
  models/       embedding + chat adapters (LM Studio / offline fallbacks)
  retrieval/    keyword (FTS5), vector, hybrid fusion, citations, service
  agent/        context builder, prompts, citation validation, study agent
  sync/         local-vault -> iCloud mirror (robocopy) + background scheduler
  api/          FastAPI routers (health, ingest, courses, search, chat, sync)
scripts/        CLI entrypoints (ingest, embed, sync)
tests/          pytest suite
```
