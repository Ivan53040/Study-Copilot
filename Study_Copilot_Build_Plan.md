---
title: Study Copilot Build Plan
aliases:
  - Personal AI Study Copilot
  - Obsidian Learning Assistant
tags:
  - ai-engineering
  - study-copilot
  - obsidian
  - rag
  - local-llm
  - side-project
created: 2026-06-17
status: planned
priority: high
---

# Study Copilot Build Plan

## 1. Project Goal

Build a local-first AI Study Copilot that can ingest an existing Obsidian vault, lecture materials, past papers, mock exams, assignment feedback, and learning history.

The system should:

- Search and understand past study materials
- Generate source-grounded revision notes
- Track weak concepts and repeated mistakes
- Generate quizzes and mock exams
- Mark answers using rubrics
- Create daily study plans
- Write new outputs into a dedicated Obsidian folder
- Preserve original source files as read-only
- Support local LLMs through LM Studio
- Optionally use cloud models for difficult tasks
- Evaluate retrieval and answer reliability

## 2. Core Product Flow

```text
Existing Obsidian Notes
Lecture Slides / PDFs
Past Papers
Mock Exams
Assignment Feedback
Quiz History
        ↓
Document Ingestion Pipeline
        ↓
Search Index + Metadata Store
        ↓
Study Copilot Agent
        ↓
Revision Notes / Quizzes / Study Plans / Weak-Topic Tracking
        ↓
Dedicated Obsidian Output Folder
```

The system should maintain persistent learning memory:

```text
What the user studied
What the user answered correctly
What the user answered incorrectly
Which concepts are weak
When each concept was last reviewed
Which concepts appear frequently in exams
What should be reviewed next
```

## 3. Safety and Vault Permissions

Recommended first-version permissions:

```text
Read access:
Entire approved Obsidian vault and study folders

Write access:
StudyCopilot/ folder only
```

Recommended vault structure:

```text
ObsidianVault/
├── Existing Notes/                 # Read-only
├── Courses/                        # Read-only
├── Resources/                      # Read-only
├── PDFs/                           # Read-only
└── StudyCopilot/                   # Writable
    ├── Generated Notes/
    ├── Daily Plans/
    ├── Quiz Results/
    ├── Mock Exams/
    ├── Weak Topics/
    ├── Concept Profiles/
    └── Reports/
```

Core rule:

> Never overwrite original notes or source materials automatically.

Any modification outside `StudyCopilot/` should require explicit approval.

## 4. MVP Scope

Build the first version for one course only.

Recommended first course:

```text
REIT6811
```

Initial supported files:

- Markdown
- PDF
- Plain text
- Images referenced by Markdown

Initial functions:

1. Import course materials
2. Search notes and PDFs
3. Answer questions with citations
4. Generate weekly revision notes
5. Generate quizzes
6. Store quiz results
7. Track weak topics
8. Generate a daily study plan
9. Save outputs to Obsidian

Do not include in the first release:

- Full multi-agent system
- Automatic modification of old notes
- Graph database
- Voice assistant
- Mobile application
- Multi-user support

## 5. Suggested Technology Stack

### Backend

- Python 3.11+
- FastAPI
- Pydantic
- SQLAlchemy
- Uvicorn

### Local Model

- LM Studio
- OpenAI-compatible local endpoint
- Qwen or another instruction/tool-capable model

```text
http://127.0.0.1:1234/v1
```

### Cloud Fallback

Optional:

- OpenAI
- Claude
- Gemini

Cloud use should be disabled by default for private documents.

### Document Parsing

Start with:

- PyMuPDF
- python-frontmatter
- Markdown parser
- Pillow

Add later:

- Docling
- Marker
- OCR fallback
- Vision-language model

### Retrieval

First version:

- SQLite
- SQLite FTS5
- Chroma or Qdrant

Production-style option:

- PostgreSQL
- pgvector
- PostgreSQL full-text search

### Testing

- pytest
- Retrieval evaluation dataset
- Citation correctness tests
- Tool-call tests
- Path-permission tests

## 6. High-Level Architecture

```text
Obsidian Vault / Files
        ↓
File Scanner / Watcher
        ↓
Document Processing
        ↓
Metadata + Full-Text + Vector Storage
        ↓
Hybrid Retrieval + Reranking
        ↓
Study Copilot Agent
        ↓
Obsidian Output Writer
```

Detailed components:

```text
File Scanner
- Detect new and changed files
- Compute content hashes
- Skip unchanged files

Document Processor
- Parse Markdown and YAML
- Extract PDF text
- Preserve page numbers
- Split by semantic structure
- Attach metadata

Knowledge Store
- Document metadata
- Full-text index
- Vector index
- Learning history

Study Agent
- Q&A
- Revision notes
- Quiz generation
- Marking
- Weak-topic updates
- Study planning
```

## 7. Suggested Repository Structure

```text
study-copilot/
├── app/
│   ├── main.py
│   ├── api/
│   │   ├── chat.py
│   │   ├── ingest.py
│   │   ├── courses.py
│   │   ├── quizzes.py
│   │   ├── plans.py
│   │   └── health.py
│   ├── config/
│   ├── ingestion/
│   │   ├── scanner.py
│   │   ├── markdown_parser.py
│   │   ├── pdf_parser.py
│   │   ├── chunker.py
│   │   ├── metadata.py
│   │   └── hashing.py
│   ├── retrieval/
│   │   ├── keyword_search.py
│   │   ├── vector_search.py
│   │   ├── hybrid_search.py
│   │   ├── reranker.py
│   │   └── citations.py
│   ├── models/
│   │   ├── base.py
│   │   ├── lmstudio.py
│   │   └── router.py
│   ├── agent/
│   │   ├── study_agent.py
│   │   ├── tools.py
│   │   ├── prompts.py
│   │   └── workflows.py
│   ├── learning/
│   │   ├── concepts.py
│   │   ├── confidence.py
│   │   ├── mistakes.py
│   │   ├── spaced_repetition.py
│   │   └── planner.py
│   ├── generation/
│   │   ├── revision_notes.py
│   │   ├── quizzes.py
│   │   ├── mock_exams.py
│   │   └── feedback.py
│   ├── obsidian/
│   │   ├── vault.py
│   │   ├── writer.py
│   │   ├── templates.py
│   │   └── links.py
│   ├── database/
│   └── security/
├── evals/
├── tests/
├── templates/
├── scripts/
├── docker-compose.yml
├── Dockerfile
├── pyproject.toml
├── .env.example
└── README.md
```

## 8. Metadata Standard

### Source Note

```yaml
---
title: Week 4 Research Ethics
course: REIT6811
type: lecture-source
week: 4
source_type: official-course-material
authoritative: true
read_only: true
---
```

### Generated Revision Note

```yaml
---
title: Week 4 Revision Notes
course: REIT6811
type: revision-note
week: 4
source_type: ai-generated
reviewed_by_user: false
generated_at: 2026-06-17
derived_from:
  - "[[Week 4 Research Ethics]]"
---
```

### Concept Profile

```yaml
---
title: Reliability
course: REIT6811
type: concept-profile
confidence: 0.55
status: weak
last_reviewed: 2026-06-15
next_review: 2026-06-18
correct_answers: 1
incorrect_answers: 2
past_paper_frequency: 3
---
```

### Quiz Result

```yaml
---
title: REIT6811 Quiz 2026-06-17
course: REIT6811
type: quiz-result
date: 2026-06-17
score: 7
total: 10
duration_minutes: 18
---
```

## 9. Source Trust Levels

Recommended ranking:

```text
1. Official lecture material
2. Official assignment brief or rubric
3. Official past paper
4. Lecturer or tutor feedback
5. User-written notes
6. User-reviewed AI notes
7. Unreviewed AI notes
8. External web content
```

Retrieval should prefer higher-trust sources and label the type of source used.

## 10. Data Model

### Document

```text
id
path
title
course
document_type
source_type
trust_level
content_hash
created_at
modified_at
indexed_at
```

### Chunk

```text
id
document_id
content
page_number
heading
chunk_index
metadata
```

### Concept

```text
id
name
course
description
importance
exam_frequency
```

### Learning Event

```text
id
course
concept_id
event_type
score
maximum_score
timestamp
source_reference
```

Possible event types:

```text
quiz_correct
quiz_incorrect
partial_answer
manual_review
mock_exam
note_read
concept_review
```

### Concept Progress

```text
concept_id
confidence
correct_count
incorrect_count
last_reviewed
next_review
status
```

## 11. Ingestion Pipeline

```text
Scan
→ Parse
→ Classify
→ Chunk
→ Index
→ Verify
```

### Scan

- Read approved folders
- Ignore hidden and unsupported files
- Calculate content hashes
- Detect new, changed, and deleted files

### Parse

Markdown:

- YAML
- Headings
- Links
- Tags
- Code blocks
- Embedded images

PDF:

- Page text
- Headings where possible
- Page numbers
- Tables where possible

### Classify

Infer or read:

- Course
- Week
- Topic
- Document type
- Source type
- Trust level

Do not rewrite source files automatically.

### Chunk

Prefer semantic chunks:

```text
Document
→ Heading
→ Subheading
→ Paragraph group
```

Each chunk should preserve:

- Document title
- Course
- Week
- Heading
- Page number
- Source type
- Trust level
- Original path

## 12. Retrieval Pipeline

```text
User Query
    ↓
Query Classification
    ↓
Metadata Filters
    ↓
Keyword Search + Vector Search
    ↓
Result Fusion
    ↓
Reranking
    ↓
Trust-Level Adjustment
    ↓
Top Context Chunks
    ↓
Answer with Citations
```

Do not rely only on vector search.

Use:

```text
Keyword search
+ Vector search
+ Metadata filtering
+ Reranking
```

## 13. Citation Rules

Every grounded answer should provide:

```text
Document title
Course
Week
Page or heading
Obsidian link or file path
```

Example:

```text
Source:
[[REIT6811 Week 4 Research Ethics]]
Page 18
Section: Valid Informed Consent
```

Never invent page numbers.

## 14. Model Adapter

Use a provider-independent interface:

```python
from typing import Protocol

class ModelAdapter(Protocol):
    async def generate(
        self,
        messages: list[dict],
        *,
        tools: list[dict] | None = None,
        temperature: float = 0.0,
    ) -> dict:
        ...
```

Initial adapter:

```text
LMStudioAdapter
```

Later:

```text
OpenAIAdapter
ClaudeAdapter
GeminiAdapter
```

Routing examples:

```text
Private note Q&A       → Local model
Simple quiz generation → Local model
Complex rubric marking → Cloud model with approval
Vision-heavy PDF       → Vision model
```

## 15. Core Agent Tools

```text
search_documents
read_document_chunk
list_course_materials
get_concept_profile
get_learning_history
create_revision_note
create_quiz
record_quiz_result
update_concept_progress
create_daily_plan
write_obsidian_file
```

All write operations must validate that the target path is inside:

```text
StudyCopilot/
```

## 16. Main Workflows

### Source-Grounded Q&A

```text
Question
→ Identify course/topic
→ Retrieve trusted sources
→ Rerank
→ Generate answer
→ Attach citations
→ Validate citations
```

### Revision Notes

```text
Select course/week
→ Retrieve official sources
→ Identify concepts
→ Generate structured note
→ Add source links
→ Preview
→ Write to StudyCopilot/
```

### Quiz and Marking

```text
Select concepts
→ Generate questions
→ Present quiz
→ Mark answers
→ Explain mistakes
→ Record learning events
→ Update confidence
```

### Daily Study Plan

```text
Read available time
→ Read exam dates
→ Read weak concepts
→ Read review history
→ Calculate priorities
→ Generate plan
→ Save to Obsidian
```

## 17. Confidence Score

Start with a transparent formula:

```text
confidence =
  0.50 × recent accuracy
+ 0.20 × long-term accuracy
+ 0.15 × review recency
+ 0.15 × difficulty performance
```

Status bands:

```text
0.00–0.39 = Weak
0.40–0.69 = Developing
0.70–0.84 = Good
0.85–1.00 = Strong
```

Store the evidence behind the score.

## 18. Spaced Repetition

Simple first version:

```text
Incorrect answer:
Review tomorrow

Partially correct:
Review in 3 days

Correct with low confidence:
Review in 7 days

Correct repeatedly:
Review in 14–30 days
```

Later add FSRS or SM-2.

## 19. Development Phases

### Phase 0 — Setup

- [ ] Create Git repository
- [ ] Create Python environment
- [ ] Add FastAPI
- [ ] Add settings and logging
- [ ] Add SQLite
- [ ] Add tests
- [ ] Configure vault path

### Phase 1 — Ingestion

- [ ] Scan Markdown and PDF files
- [ ] Parse YAML
- [ ] Extract page text
- [ ] Calculate file hashes
- [ ] Store metadata
- [ ] Create chunks
- [ ] Preserve source references

### Phase 2 — Search

- [ ] Add SQLite FTS5
- [ ] Add embeddings
- [ ] Add vector store
- [ ] Add metadata filters
- [ ] Build hybrid search
- [ ] Return source references

### Phase 3 — Grounded Chat

- [ ] Build LM Studio adapter
- [ ] Add context builder
- [ ] Require citations
- [ ] Validate citations
- [ ] Add conversation state

### Phase 4 — Obsidian Generation

- [ ] Add templates
- [ ] Generate weekly notes
- [ ] Preview Markdown
- [ ] Validate target paths
- [ ] Write only to StudyCopilot/
- [ ] Add backlinks
- [ ] Label AI-generated notes

### Phase 5 — Learning History

- [ ] Generate quizzes
- [ ] Accept answers
- [ ] Mark questions
- [ ] Store results
- [ ] Create learning events
- [ ] Update concept confidence

### Phase 6 — Planning

- [ ] Generate weak-topic report
- [ ] Add review scheduling
- [ ] Add exam dates
- [ ] Add available-time input
- [ ] Generate daily plans

### Phase 7 — Past Papers

- [ ] Parse past papers
- [ ] Link questions to concepts
- [ ] Estimate topic frequency
- [ ] Generate mock exams
- [ ] Add rubric-based feedback

### Phase 8 — Evaluation

- [ ] Create 30–50 evaluation questions
- [ ] Measure retrieval Recall@K
- [ ] Test citation correctness
- [ ] Test answer faithfulness
- [ ] Test marking consistency
- [ ] Test path restrictions
- [ ] Add regression reports

## 20. First Four Weeks

### Week 1 — Foundation

- Set up FastAPI
- Configure vault path
- Scan Markdown and PDFs
- Store metadata in SQLite
- Add file hashing
- Add tests

Deliverable:

```text
Index one course folder
```

### Week 2 — Search and Q&A

- Add FTS5
- Add embeddings
- Add hybrid retrieval
- Connect LM Studio
- Return answers with sources

Deliverable:

```text
Ask REIT6811 questions with citations
```

### Week 3 — Obsidian Generation

- Add templates
- Generate weekly notes
- Validate paths
- Add preview-before-write
- Add backlinks

Deliverable:

```text
Generate Week 1 revision notes in StudyCopilot/
```

### Week 4 — Learning Memory

- Generate quizzes
- Record answers
- Track concept performance
- Build weak-topic list
- Generate daily study plan

Deliverable:

```text
Study Copilot identifies weak topics and recommends review
```

## 21. API Endpoints

```text
POST /ingest/scan
POST /ingest/file
GET  /courses
GET  /courses/{course}/documents
POST /search
POST /chat
POST /notes/generate
POST /quizzes/generate
POST /quizzes/{quiz_id}/submit
GET  /progress/{course}
POST /plans/daily
GET  /health
```

## 22. Evaluation Plan

### Retrieval

- Recall@K
- Precision@K
- Correct source retrieval
- Correct page retrieval
- Trust-level preference

### Answers

- Faithfulness
- Completeness
- Citation correctness
- Unsupported claim rate

### Quizzes

- Question relevance
- Answer-key correctness
- Difficulty alignment
- Marking consistency

### Learning Memory

- Wrong answers reduce confidence
- Correct answers increase confidence
- Repeated errors are detected
- Review dates update correctly

### Safety

- Attempt to overwrite an original note
- Path traversal
- Writing outside StudyCopilot/
- Reading `.env`
- Malicious instructions inside a PDF
- AI-generated note treated as authoritative

## 23. Configuration Example

```yaml
vault:
  root: "C:/Users/ivank/ObsidianVault"

  read_paths:
    - "Courses/**"
    - "Existing Notes/**"
    - "Resources/**"

  write_paths:
    - "StudyCopilot/**"

  denied_paths:
    - "**/.obsidian/plugins/**"
    - "**/.git/**"
    - "**/.env"
    - "**/.ssh/**"

models:
  default_provider: lmstudio

  lmstudio:
    base_url: "http://127.0.0.1:1234/v1"
    model: "local-model-name"

  cloud_fallback:
    enabled: false
    require_approval: true

retrieval:
  keyword_limit: 20
  vector_limit: 20
  final_context_limit: 8

generation:
  temperature: 0.1
  require_citations: true
```

## 24. Definition of Done for MVP

- [ ] One course can be indexed
- [ ] Existing Obsidian notes can be searched
- [ ] PDFs can be searched with page references
- [ ] Answers include valid source links
- [ ] Weekly revision notes can be generated
- [ ] Original notes remain unchanged
- [ ] A quiz can be generated and submitted
- [ ] Wrong answers update concept progress
- [ ] A daily plan can be generated
- [ ] Outputs are written into StudyCopilot/
- [ ] Basic evaluation tests pass
- [ ] README explains setup and architecture

## 25. Portfolio Deliverables

Prepare:

```text
README.md
Architecture diagram
Demo video
Sample Obsidian vault
Evaluation report
Retrieval benchmark
Security model
Design decisions
Known limitations
Future roadmap
```

Recommended demo:

```text
1. Import a course
2. Ask a source-grounded question
3. Generate a revision note
4. Complete a quiz
5. Show confidence changing
6. Generate a daily study plan
7. Show that original notes remain untouched
```

Resume description:

> Built a local-first AI Study Copilot that ingests Obsidian notes, lecture materials and past papers, generates source-grounded revision content, tracks concept-level learning progress, and produces adaptive quizzes and study plans using hybrid retrieval and local LLM inference.

## 26. Future Extensions

- Multimodal slide understanding
- Table and diagram extraction
- OCR for scanned papers
- Hermes Companion integration
- Obsidian plugin
- Apple Watch revision prompts
- Voice quiz mode
- Calendar-aware scheduling
- Secure MCP Gateway integration
- Agent Evaluation Lab integration
- Multiple courses
- Cross-course concept linking
- FSRS spaced repetition
- Mobile companion app

## 27. Core Design Principles

> Preserve original learning materials.

> Treat AI-generated notes as lower-trust until reviewed.

> Every important answer should link back to a source.

> Learning progress must be based on recorded evidence.

> Prefer a small working system over a large unreliable agent.

> Use local models by default for private study materials.

> Make all write operations transparent and reversible.

> Evaluate retrieval, answers, marking, and safety independently.
