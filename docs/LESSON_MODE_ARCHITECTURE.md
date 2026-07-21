# Lesson Mode Architecture

Status: **Increment 2 — Grounded Lesson Generator.** Adds `POST
/lesson/generate`, producing a structured, section-cited lesson from
retrieved bill sections. Flashcard/quiz generation still does not exist;
existing debate/bill functionality is untouched.

## Why

Lesson Mode turns a bill into a guided learning experience: a RAG pipeline
over the bill's text grounds a generated summary, vocabulary, and pro/con
arguments; students review vocabulary with Leitner-system flashcards, take
AI-graded quizzes, and can build a persona to see a personalized bill impact
and debate an opposing AI persona. This doc tracks the target architecture
and where each increment fits in.

## Existing architecture (as of Increment 0)

DebateSim's backend is a single flat FastAPI app in [`main.py`](../main.py)
(~2900 lines) — there is no router/blueprint split and, until this
increment, no `models/` or `services/` package. Request/response schemas are
Pydantic `BaseModel` classes defined inline next to their route. Supporting
logic lives in flat sibling modules: [`billsearch.py`](../billsearch.py),
[`legiscan_service.py`](../legiscan_service.py),
[`ca_propositions_service.py`](../ca_propositions_service.py), and
[`chains/`](../chains) (LangChain chains for debating, judging, and
training).

Firestore access in `main.py` goes through a module-level `get_firestore_db()`
that lazily initializes `firebase_admin` using the service account key at
`credentials/debatesim-6f403-55fd99aa753a-google-cloud.json`. There is no
server-side Firebase ID token verification today — auth is client-side only
(Firebase Auth in the frontend); values like `userProfile` are passed through
as plain JSON from the client and trusted as-is.

The frontend is React 18 (Vite) under `frontend/src`, with a flat
`components/` directory and Firebase helpers under `frontend/src/firebase/`.
`frontend/src/utils/userProfileService.js` is the existing precedent for the
new `PersonaProfile` concept (used today for personalized bill analysis).

## New backend layout

Increment 0 adds two new top-level packages, following the existing
flat-module convention rather than introducing a router/app-factory
restructure:

```
models/
  __init__.py            # re-exports all lesson-mode models
  lesson_models.py        # Pydantic schemas (this increment)
services/
  __init__.py
  firebase_client.py       # shared lazy Firestore client init (this increment)
  lesson_repository.py     # Firestore repository for lesson-mode entities (this increment)
tests/
  __init__.py
  fake_firestore.py         # in-memory Firestore fake for unit tests
  test_lesson_models.py      # model + repository unit tests
```

`services/firebase_client.py` intentionally duplicates `main.py`'s
`get_firestore_db()` lazy-init pattern instead of importing it from
`main.py`. This avoids a circular import once `main.py` starts wiring up
lesson routes in a later increment (`main.py` would import lesson route
handlers, which import the repository, which would import back into
`main.py`). Both initializers call `firebase_admin.get_app()` defensively
first, so whichever one runs first initializes the Firebase app and the
other just reuses it — safe to run side by side.

Increment 1 adds:

- `routes/lesson_routes.py` — `POST /lesson/retrieve-sections`, mounted from
  `main.py` via `app.include_router(lesson_router)`.
- `services/rag/section_splitter.py` — `split_bill_into_sections(bill_text,
  bill_id)`, the canonical splitter producing `BillSection` chunks. This is
  a distinct implementation from `main.py`'s `extract_key_bill_sections`
  (line ~1200), which lossily truncates a bill into one string to fit an
  LLM's context window and is unrelated to RAG chunking.
- `services/rag/embeddings.py` — `EmbeddingProvider` interface with three
  implementations: `SentenceTransformerEmbeddingProvider` (default: local,
  semantic, no API key), `TfidfEmbeddingProvider` (dependency-light
  fallback), and `OpenAIEmbeddingProvider` (hosted, opt-in). Selectable via
  the `LESSON_EMBEDDING_PROVIDER` env var.
- `services/rag/cache.py` — `EmbeddingCache` interface with an
  `InMemoryEmbeddingCache` default, keyed by `bill_id` + a hash of the
  whitespace-normalized bill text, so unchanged bills skip re-embedding and
  changed bills transparently invalidate. A Firestore- or vector-DB-backed
  cache can implement the same interface later without touching
  `BillRagService`.
- `services/rag/retrieval_service.py` — `BillRagService.retrieve_relevant_sections(bill_id, query, top_k=5, bill_text=None)`,
  the single reusable entry point other increments should call instead of
  sending a full bill to the model. Returns `section_id`, `heading`, `text`,
  `order`, and `similarity_score` per section, ranked by cosine similarity.
  Logs cache hits/misses and retrieval latency.
- `tests/test_bill_rag.py` — splitter, cache, retrieval, and endpoint tests,
  plus a retrieval-quality check against five hand-written queries over a
  known sample bill.

Increment 2 adds:

- `services/lesson_generation.py` — `LessonGenerationService.generate_lesson(bill_id,
  bill_text, model=...)`, producing a `Lesson` (see updated table below).
  Runs six separate `BillRagService` retrieval queries (purpose,
  requirements, stakeholders, benefits, objections, implementation),
  dedupes the results, and sends only those section excerpts to the model
  -- never the full bill text.
- `routes/lesson_routes.py` — `POST /lesson/generate`, added alongside the
  Increment 1 endpoint in the same router (no further `main.py` changes
  needed).
- `tests/test_lesson_generation.py` — parsing/grounding-validation tests
  (no network) plus `generate_lesson` tests against a mocked LLM callable
  covering caching, cache invalidation (text change and prompt-version
  bump), retry-on-missing-pro/con, and Firestore persistence via
  `FakeFirestoreClient`.

Future increments are expected to add:

- Flashcard/quiz generation.
- `frontend/src/components/lesson/` (or similar) for the new UI, following
  the existing flat-components convention.

## Data models (`models/lesson_models.py`)

All lesson-mode models inherit from a small `FirestoreModel` base
(`models/lesson_models.py`) that adds:

- `to_firestore_dict()` — `model_dump(mode="json")`, so datetimes become ISO
  strings and the result is always a plain JSON-compatible dict safe to hand
  to Firestore's `set()`/`update()` (or the Firestore REST API / emulator).
- `from_firestore_dict(data)` — `model_validate(data)`, the inverse, used
  when reading a document back out of Firestore.

| Model | Purpose | Key fields |
|---|---|---|
| `BillSection` | Unit of retrieval for the RAG pipeline | `section_id`, `bill_id`, `heading`, `text`, `order`, `embedding` |
| `GroundedClaim` | A claim tied to the section_id(s) that support it | `claim`, `section_ids` (non-empty) |
| `Lesson` | Generated, grounded lesson for a bill (Increment 2) | `lesson_id`, `bill_id`, `prompt_version`, `bill_text_hash`, `lesson_title`, `plain_language_summary`, `learning_objectives`, `major_provisions`, `stakeholders`, `pro_arguments`, `con_arguments` (all `List[GroundedClaim]`), `source_sections`, `created_at` |
| `Flashcard` | Term/definition grounded in a bill section | `card_id`, `lesson_id`, `term`, `definition`, `section_id` |
| `LeitnerBox` | `IntEnum` (1–5) documenting the Leitner box levels | — |
| `UserCardProgress` | One user's Leitner progress on one flashcard | `user_id`, `card_id`, `leitner_box`, `correct_count`, `last_reviewed`, `next_review_session` |
| `QuizAnswer` | One answer within a quiz attempt | `question_id`, `response`, `is_correct` |
| `QuizAttempt` | A user's full quiz attempt for a lesson | `attempt_id`, `user_id`, `lesson_id`, `score`, `answers`, `feedback`, `created_at` |
| `PersonaProfile` | Student-built persona for personalization | `user_id`, `occupation`, `state`, `age_range`, `income_bracket` |
| `LessonProgress` | Overall per-user progress on a lesson | `user_id`, `lesson_id`, `vocab_mastered`, `vocab_total`, `quiz_attempts`, `best_quiz_score`, `completed`, `updated_at` |

Validation is enforced via Pydantic field constraints (e.g. `BillSection.text`
must be non-empty, `UserCardProgress.leitner_box` is bounded `1..5`,
`QuizAttempt.score` is bounded `0..100`) rather than manual checks.

## Firestore repository (`services/lesson_repository.py`)

`LessonRepository` wraps one Firestore collection per model
(`bill_sections`, `lessons`, `flashcards`, `user_card_progress`,
`quiz_attempts`, `persona_profiles`, `lesson_progress`) behind
`create_*`/`get_*` (or `upsert_*`/`get_*` for per-user documents) methods.
It takes an injectable `db` client in its constructor:

```python
repo = LessonRepository()               # uses the real Firestore client
repo = LessonRepository(db=fake_client)  # unit tests: inject a fake/emulator client
```

Composite-key documents (`UserCardProgress`, `LessonProgress`) use a
deterministic `{user_id}_{...id}` document ID so `upsert_*` naturally
overwrites the same document on repeated calls instead of creating
duplicates.

**Not yet done (by design):** `BillSection` results from Increment 1's RAG
service are still not persisted through `LessonRepository` -- the retrieval
cache is in-memory only (see below). `Lesson` documents *are* persisted:
`LessonGenerationService` calls `repo.create_lesson(...)` after grounding
validation and uses `repo.get_lesson(lesson_id)` as its cache lookup (see
Increment 2 section below).

## Bill-section RAG pipeline (`services/rag/`, Increment 1)

`BillRagService.retrieve_relevant_sections(bill_id, query, top_k=5,
bill_text=None)` is the reusable entry point for finding the bill sections
relevant to a query without sending the whole bill to a model:

```
bill text -> split_bill_into_sections -> embed each section
          -> cache (keyed by bill_id + text hash) -> cosine similarity
          -> top_k sections
```

- On first call for a `bill_id` (or after the bill's text changes), pass
  `bill_text`; sections are split, embedded, and cached. Later calls can
  omit `bill_text` and reuse the cached sections.
- `EmbeddingProvider` is pluggable (`LESSON_EMBEDDING_PROVIDER` env var):
  `sentence-transformers` (default, local, semantic) is not upended by
  vocabulary mismatches the way TF-IDF is, e.g. matching "who qualifies"
  against "eligibility requirements". `tfidf` and `openai` are also
  available.
- `EmbeddingCache` is an interface (`InMemoryEmbeddingCache` is the only
  implementation today); a Firestore- or vector-DB-backed cache can be
  swapped in later without changing `BillRagService`.
- Endpoint: `POST /lesson/retrieve-sections` (`bill_id`, `query`, `top_k`,
  optional `bill_text`) returns `section_id`, `heading`, `text`, `order`,
  `similarity_score` per result.
- Cache hits/misses and retrieval latency are logged via the standard
  `logging` module (`services/rag/retrieval_service.py`).

## Grounded lesson generator (`services/lesson_generation.py`, Increment 2)

`LessonGenerationService.generate_lesson(bill_id, bill_text, model=...)`
produces a `Lesson`:

```
bill_id, bill_text -> 6 BillRagService queries (purpose, requirements,
  stakeholders, benefits, objections, implementation) -> dedupe sections
  -> prompt the model for structured JSON (citing only those section_ids)
  -> validate with Pydantic -> drop/trim claims citing unknown section_ids
  -> retry once if pro_arguments or con_arguments end up empty
  -> Lesson, persisted + cached via LessonRepository
```

- **Caching**: `lesson_id = f"{bill_id}::{LESSON_PROMPT_VERSION}::{sha256(normalized bill_text)[:16]}"`.
  `generate_lesson` checks `repo.get_lesson(lesson_id)` first; an unchanged
  bill and unchanged `LESSON_PROMPT_VERSION` return the cached lesson
  without calling the model. Changing the bill text or bumping
  `LESSON_PROMPT_VERSION` (do this whenever the prompt wording changes)
  produces a new `lesson_id` and forces regeneration.
- **Grounding enforcement**: `ground_lesson_draft(raw_text, known_section_ids)`
  parses the model's JSON (tolerating ` ```json ` fences) and, per claim,
  keeps only the section_ids that were actually retrieved -- a claim with
  no valid section_ids left is dropped entirely rather than kept uncited.
  If the result has no `pro_arguments` or no `con_arguments`, one retry is
  attempted with a corrective instruction; if still missing, generation
  raises `LessonGenerationError` rather than returning an ungrounded or
  one-sided lesson.
- **Reuses `OpenRouterChat`** from `chains/debater_chain.py` (the existing
  OpenRouter-backed LangChain chat model) for the actual model call, so
  lesson generation goes through the same OpenRouter config/model routing
  as debates. It does *not* reuse that module's multi-round markdown debate
  *template* (`get_debater_chain`) -- that's built for a live back-and-forth
  round structure with free-form prose output and strict word counts, the
  wrong contract for single-shot structured JSON. The pro/con instructions
  in `CORE_LESSON_SYSTEM_PROMPT` instead adapt that template's reasoning
  style (only argue points the source text supports, weigh impact, engage
  with substance) into the grounded-claim JSON shape.
- **Testability**: the LLM call is injected as `llm_call: (system_prompt,
  user_prompt, model) -> Awaitable[str]`, defaulting to the real
  `OpenRouterChat`-based implementation. Tests inject a fake callable
  returning canned JSON, so `tests/test_lesson_generation.py` never makes a
  network call.
- Endpoint: `POST /lesson/generate` (`bill_id`, `bill_text`, optional
  `model`) returns the full `Lesson` JSON.

## Testing

`tests/fake_firestore.py` implements the minimal subset of the
`google-cloud-firestore` client surface (`collection().document().set()` /
`.get().exists` / `.get().to_dict()`) as an in-memory dict, so
`LessonRepository` can be exercised in `tests/test_lesson_models.py` without
a live Firestore project or the Firestore emulator. Swapping in a real
Firestore emulator client (`google.cloud.firestore.Client` pointed at
`FIRESTORE_EMULATOR_HOST`) is a drop-in replacement for `FakeFirestoreClient`
since `LessonRepository` only depends on that same `collection/document/set/get`
surface.

`tests/test_bill_rag.py` covers the RAG pipeline: section splitting, cache
hit/miss/invalidation behavior, top_k and ordering, validation errors, and
a retrieval-quality check (five hand-written queries against a known sample
bill, expecting the right section in the top 3), plus the
`/lesson/retrieve-sections` endpoint mounted standalone (no `main.py`
dependency chain required).

Run the suite with:

```bash
python -m pytest tests/ -v
```

## Non-goals for this increment

- No flashcard/quiz *generation* logic -- that's a future increment.
- No frontend pages.
- Retrieved `BillSection`s are not yet persisted through `LessonRepository`
  (in-memory cache only); only generated `Lesson`s are persisted.
- No changes to `chains/debater_chain.py` itself -- `OpenRouterChat` is
  imported and reused as-is, not modified, so existing debate behavior is
  unaffected.
- No changes to any existing route, chain, or service in `main.py` besides
  the Increment 1 two-line router mount (import +
  `app.include_router(lesson_router)`); `billsearch.py`,
  `legiscan_service.py`, `ca_propositions_service.py`, and the rest of
  `chains/` are untouched.
