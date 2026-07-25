# Lesson Mode Architecture

Status: **Increment 9 — Dynamic Opposing Debate Persona.** Adds a
generated, bill-grounded opposing stakeholder persona that plugs into
DebateSim's existing, unmodified debate engine (`chains/debater_chain.py`)
via the `"PERSONA INSTRUCTIONS:"` marker it already supported but the
frontend never used. Distinct from Increment 8's `PersonalImpactNarrative`
(which explains impact on the *student's own* persona): this generates the
*opposing debate voice*. Flashcard/quiz analytics and a Lesson Mode
frontend page still do not exist; existing debate/bill functionality is
untouched -- see "Dynamic debate persona" below.

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

Increment 3 adds:

- `services/vocabulary_generation.py` — `VocabularyGenerationService.generate_vocabulary(bill_id,
  lesson_id, bill_text, model=...)`, producing 0-12 `Flashcard`s (see
  updated table below) from the same category-query retrieval used for
  lesson generation. `services/json_utils.py` was factored out of
  `lesson_generation.py` so both services share one JSON-fence-tolerant
  parser instead of duplicating it.
- `GenerateLessonRequest.include_vocabulary` (default `False`) on `POST
  /lesson/generate`; when true, the response (`GenerateLessonResponse`, a
  `Lesson` subclass) also includes a `vocabulary` list.
- `regenerate_invalid_cards` — a standalone regeneration path: if any card
  from the first pass cited an unretrieved section_id or was really a name/
  section-number rather than a term, one follow-up model call asks
  specifically for replacements, before falling back to just dropping them.
- `tests/test_vocabulary_generation.py` — parsing/grounding/dedup/term-
  quality/length-cap tests (no network) plus `generate_vocabulary` tests
  against a mocked LLM callable, and the `/lesson/generate` endpoint with
  and without `include_vocabulary`.

Increment 4 adds:

- `services/auth.py` — `get_current_user_id`, a FastAPI dependency that
  verifies a Firebase ID token (`Authorization: Bearer <token>`) via
  `firebase_admin.auth.verify_id_token` and returns its `uid`. **This is the
  first server-side auth check anywhere in DebateSim** -- see "Auth" below.
- `services/flashcard_review.py` — `FlashcardReviewService` (session
  tracking, due-card queries, mastery/box-distribution reporting) and the
  pure scheduling functions `compute_next_due_session`, `is_card_due`,
  `apply_answer`.
- Three new endpoints on the existing `/lesson` router, all requiring
  `Depends(get_current_user_id)`: `POST /lesson/{lesson_id}/review/start-session`,
  `GET /lesson/{lesson_id}/review/state`, `POST /lesson/{lesson_id}/review/answer`.
- `Lesson.vocabulary_card_ids` (new field) -- `POST /lesson/generate` now
  persists the generated vocabulary's card_ids onto the lesson doc when
  `include_vocabulary=true`, so the review endpoints can list a lesson's
  flashcards without a Firestore compound query.
- `frontend/src/components/LessonFlashcards.jsx` (+ `.css`) — the review UI:
  term-first reveal flow, mastery bar, due count, box-distribution badges, a
  "Needs review"/"Mastered" label per card, and a session-completion state.
- First frontend test tooling in the repo: Vitest + React Testing Library
  (`frontend/src/components/LessonFlashcards.test.jsx`), wired via
  `vite.config.js`'s new `test` block and `npm test`.

Increment 5 adds:

- `services/quiz_generation.py` — `QuizGenerationService.generate_quiz(lesson_id,
  model=...)`, producing 5-8 `QuizQuestion`s from an *already-generated*
  lesson's own grounded content (`Lesson.major_provisions`/`stakeholders`
  and its `Flashcard` vocabulary) -- quizzes take `lesson_id`, not raw bill
  text, since the correct answers are pulled directly from data Increments
  2/3 already validated against real sections, never re-invented by a model
  call. A single phrasing-only model call writes a natural question stem +
  explanation + difficulty per fact; the *distractor pipeline* (embedding
  similarity first, one constrained LLM fallback call second, both
  rejecting near-duplicates-of-correct and case-insensitive dupes) is the
  genuinely new logic in this increment -- see "Quiz generation" below.
- `Lesson.quiz_question_ids` (new field), persisted by
  `QuizGenerationService.generate_quiz` itself (mirroring how vocabulary's
  card ids get merged onto the lesson), so `GET /lesson/{id}/quiz` can list
  a lesson's questions without a Firestore compound query.
- `GenerateLessonRequest.include_quiz` (default `False`) on `POST
  /lesson/generate`, alongside two new endpoints: `GET /lesson/{lesson_id}/quiz`
  (public quiz-taking shape -- no `correct_answer_index`/`explanation`) and
  `POST /lesson/{lesson_id}/quiz/submit` (requires `Depends(get_current_user_id)`;
  scores the submission, saves a `QuizAttempt`, and returns immediate
  per-question explanations).
- `frontend/src/components/LessonQuiz.jsx` (+ `.css`) — the quiz-taking UI:
  answer-choice selection, a submit button gated on every question being
  answered, and an immediate per-question correct/incorrect + explanation
  view plus an overall score banner once submitted.
- `tests/test_quiz_generation.py` (backend) and
  `frontend/src/components/LessonQuiz.test.jsx` (frontend) -- see Testing.

Increment 6 adds:

- `services/open_response_generation.py` — `OpenResponseGenerationService.generate_question(lesson_id,
  model=...)`, producing the lesson's single `OpenResponseQuestion`.
  `_select_question_material` picks the richest available question type
  from the lesson's own grounded content -- `pro_con_comparison` when both
  pro and con arguments exist (most substantive), else `stakeholder_perspective`,
  else `implementation_challenge` (reusing quiz generation's
  `_classify_provision_type` keyword heuristic), else `impact_prediction` --
  and, like quiz generation, never invents the underlying facts. A single
  model call phrases the question text and a 2-4 item `expected_points`
  grading checklist from those facts. Idempotent: a lesson has at most one
  such question, so a second call reuses the existing one instead of
  regenerating.
- `services/open_response_grading.py` — `OpenResponseGradingService.grade_answer(question,
  student_answer, model=...)`, the two-stage grader described in "Grading"
  below.
- `Lesson.open_response_question_id` (new field, singular -- not a list,
  since there's exactly one question per lesson), persisted by
  `OpenResponseGenerationService.generate_question` itself.
- `GenerateLessonRequest.include_open_response` (default `False`) on `POST
  /lesson/generate`, alongside two new endpoints: `GET /lesson/{lesson_id}/open-response`
  (public shape -- no `expected_points`/`context_excerpt`) and `POST
  /lesson/{lesson_id}/open-response/submit` (requires
  `Depends(get_current_user_id)`; grades the answer, saves an
  `OpenResponseAttempt`, and returns the grade immediately).
- `frontend/src/components/LessonOpenResponse.jsx` (+ `.css`) — a textarea,
  a submit button, and a feedback view (score badge, feedback text,
  accurate/missed points, relevant sections, and a "Try Again" reset).
- `tests/test_open_response_generation.py`, `tests/test_open_response_grading.py`,
  `tests/test_open_response_routes.py` (backend) and
  `frontend/src/components/LessonOpenResponse.test.jsx` (frontend) -- see
  Testing.

Increment 7 adds:

- `services/persona_service.py` — `PersonaService` with `get_persona`,
  `save_persona` (validate + upsert; raises `PersonaValidationError` on bad
  input), `delete_persona`, and `field_options`. See "Student persona
  builder" below.
- Broad-choice constants + Pydantic `field_validator`s on `PersonaProfile`
  (`US_STATES`, `AGE_RANGES`, `INCOME_BRACKETS`, `OCCUPATION_CATEGORIES`),
  plus `PersonaProfile.to_impact_representation()`, `is_empty()`, and
  `field_options()`.
- `LessonRepository.delete_persona_profile(user_id)` (and a `.delete()`
  method on `tests/fake_firestore.py`'s document ref).
- Persona routes on the lesson router: `GET /lesson/persona/options`
  (public), `GET`/`PUT`/`DELETE /lesson/persona` (auth).
- `frontend/src/components/PersonaBuilder.jsx` (+ `.css`) and the four
  persona API helpers in `frontend/src/api.js`.
- `tests/test_persona_service.py`, `tests/test_persona_routes.py` (backend)
  and `frontend/src/components/PersonaBuilder.test.jsx` (frontend) -- see
  Testing.

Increment 8 adds:

- `services/persona_impact_generation.py` --
  `PersonaImpactGenerationService.generate_impact(persona, lesson,
  bill_text=..., model=...)`, plus `_ground_impact_draft` (parse + validate
  + drop ungrounded impacts + cap confidence) and `_build_persona_queries`
  (persona-driven RAG queries). See "Personalized bill-impact narrative"
  below.
- `PersonalImpact` and `PersonalImpactNarrative` models, and
  `LessonRepository.create_personal_impact_narrative` /
  `get_personal_impact_narrative` over the new `personal_impact_narratives`
  collection.
- `POST /lesson/personal-impact` (auth): resolves the persona (inline
  possibly-fictional override, else the caller's saved persona), generates
  the grounded narrative, and returns it.
- `frontend/src/components/LessonPersonalImpact.jsx` (+ `.css`) and the
  `getPersonalImpact` helper in `frontend/src/api.js`.
- `tests/test_persona_impact_generation.py`,
  `tests/test_persona_impact_routes.py` (backend) and
  `frontend/src/components/LessonPersonalImpact.test.jsx` (frontend) -- see
  Testing.

Increment 9 adds:

- `services/dynamic_persona_generation.py` — `DynamicPersonaGenerationService.generate_persona(lesson_id,
  student_persona=None, model=...)`, producing one `DynamicPersona`: a
  bill-grounded opposing stakeholder (never inventing facts -- drawn from
  the lesson's own `stakeholders`/`con_arguments`/`pro_arguments`/`major_provisions`
  `GroundedClaim`s, the same source material Increment 6 uses).
  `student_persona` reuses `PersonaOverride`/`PersonaProfile` (Increment
  7's validated student-context model) -- omitting it is the "persona
  skipped" path, and the system prompt explicitly forbids inferring the
  opponent's traits from the student's demographics either way. This is a
  distinct feature from Increment 8's `PersonaImpactGenerationService`:
  that explains impact on the student's own persona; this generates the
  AI's opposing debate voice, and does not duplicate the impact narrative.
- **The entire integration surface with the existing debate engine is one
  function**: `build_persona_prompt(draft)` formats the persona as a
  `"PERSONA INSTRUCTIONS:"` block. `chains/debater_chain.py`'s existing,
  *unmodified* `process_inputs` (line ~1097) already extracts persona
  instructions from exactly that marker (alongside `"SPEAKING STYLE:"`,
  used by the frontend's fixed celebrity personas, and
  `"DEBATE STYLE INSTRUCTIONS:"`, unused by either) -- so wiring a
  generated persona into a live debate requires zero changes to
  `chains/debater_chain.py` or `main.py`'s `/generate-response` endpoint.
  `_sanitize_for_persona_prompt` strips any of the four substrings
  (`"Instructions:"`, `"Your role:"`, `"Bill description:"`, `"Debate topic:"`)
  that the existing extractor treats as an early end-of-persona marker, so
  the generated body is never silently truncated by that unmodified logic.
- `generate_socratic_hint(persona, full_transcript, ...)` — a single-shot
  helper for an optional "learning mode" hint (one Socratic question, not
  an answer), reusing the same `OpenRouterChat`-backed call pattern as the
  rest of Lesson Mode generation. This is additive, not a new debate
  engine or a mode switch inside `chains/debater_chain.py`: competition
  mode simply never calls the hint endpoint.
- Two new endpoints: `POST /lesson/{lesson_id}/debate-persona/generate`
  (`student_persona` optional) and `POST /lesson/{lesson_id}/debate-persona/hint`.
  Neither endpoint requires auth (no per-user state is written -- a
  generated persona is lesson-scoped, reusable content, like a quiz
  question) and neither touches `main.py`.
- `tests/test_debater_chain_integration.py` — integration tests against
  the **real** `chains.debater_chain.get_debater_chain(...)` pipeline
  (only `OpenRouterChat._agenerate` is stubbed to avoid a network call),
  proving a generated persona's full text reaches the final rendered
  prompt untruncated, alongside regression coverage for Public Forum,
  Lincoln-Douglas, the default bill-debate format, the existing
  `"SPEAKING STYLE:"` fixed-persona path, the "persona skipped" path, and
  the AI-vs-AI detailed-prompt bypass.

Future increments are expected to add: a full Lesson Mode page/route that
actually mounts `LessonFlashcards`/`LessonQuiz`/`LessonOpenResponse`/
`LessonPersonalImpact`/the dynamic persona flow (only `PersonaBuilder` is
mounted so far, at `/lesson/persona`; the rest are built + tested but await
the lesson page -- see Non-goals). No frontend wiring exists yet for the
dynamic persona endpoints specifically (see Non-goals for details).

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
| `Lesson` | Generated, grounded lesson for a bill (Increment 2) | `lesson_id`, `bill_id`, `prompt_version`, `bill_text_hash`, `lesson_title`, `plain_language_summary`, `learning_objectives`, `major_provisions`, `stakeholders`, `pro_arguments`, `con_arguments` (all `List[GroundedClaim]`), `source_sections`, `vocabulary_card_ids` (Increment 4), `quiz_question_ids` (Increment 5), `open_response_question_id` (Increment 6, singular), `created_at` |
| `Flashcard` | Bill-specific vocabulary card, grounded in one section (Increment 3) | `card_id`, `lesson_id`, `term`, `simple_definition`, `bill_context`, `example`, `section_id`, `difficulty` (`beginner`\|`intermediate`\|`advanced`) |
| `LeitnerBox` | `IntEnum` (1–3, Increment 4) documenting the Leitner box levels | — |
| `UserCardProgress` | One user's Leitner progress on one flashcard (Increment 4 shape) | `user_id`, `card_id`, `leitner_box` (1-3), `correct_count`, `incorrect_count`, `last_reviewed_session`, `next_due_session` |
| `QuizQuestion` | A grounded multiple-choice question (Increment 5) | `question_id`, `lesson_id`, `question`, `answer_choices` (4, order randomized), `correct_answer_index`, `explanation`, `section_ids`, `difficulty`, `question_type` (`vocabulary`\|`stakeholder_impact`\|`provision`\|`implementation`) |
| `QuizAnswer` | One answer within a quiz attempt | `question_id`, `response` (the selected index, as a string), `is_correct` |
| `QuizAttempt` | A user's full quiz attempt for a lesson | `attempt_id`, `user_id`, `lesson_id`, `score`, `answers`, `feedback`, `created_at` |
| `OpenResponseQuestion` | The lesson's one open-ended question (Increment 6) | `question_id`, `lesson_id`, `question`, `question_type` (`stakeholder_perspective`\|`tradeoff`\|`pro_con_comparison`\|`implementation_challenge`\|`impact_prediction`), `expected_points`, `section_ids`, `context_excerpt` |
| `OpenResponseAttempt` | A user's graded attempt at that question | `attempt_id`, `user_id`, `lesson_id`, `question_id`, `student_answer`, `score` (0-3), `feedback`, `missed_points`, `accurate_points`, `section_ids`, `created_at` |
| `PersonaProfile` | Student-built, optional, possibly-fictional persona for personalization (Increment 7) | `user_id`, `occupation` (broad category or free text, ≤80 chars), `state` (two-letter USPS code), `age_range` (one of `AGE_RANGES`), `income_bracket` (one of `INCOME_BRACKETS`) — every field except `user_id` optional; `to_impact_representation()` yields the generator-facing view |
| `PersonalImpact` | One grounded way a bill could affect a persona (Increment 8) | `impact` (what), `reasoning` (why), `section_ids` (validated, non-empty), `confidence` (`high`\|`medium`\|`low`) |
| `PersonalImpactNarrative` | A persona-specific, grounded bill-impact explanation (Increment 8) | `impact_id`, `lesson_id`, `bill_id`, `user_id`, `prompt_version`, `persona` (snapshot), `narrative`, `direct_impacts`/`possible_indirect_impacts` (`List[PersonalImpact]`), `uncertainties`, `questions_to_consider`, `confidence`, `section_ids` (validated union), `created_at` |
| `DynamicPersona` | A grounded opposing *debate* persona (Increment 9) | `persona_id`, `lesson_id`, `role`, `location_context`, `interests`, `likely_concerns`, `position`, `section_ids`, `reason_for_selection`, `persona_prompt`, `created_at` |
| `LessonProgress` | Overall per-user progress on a lesson | `user_id`, `lesson_id`, `vocab_mastered`, `vocab_total`, `quiz_attempts`, `best_quiz_score`, `completed`, `current_session` (Increment 4: Leitner session counter), `updated_at` |

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

## Vocabulary generator (`services/vocabulary_generation.py`, Increment 3)

`VocabularyGenerationService.generate_vocabulary(bill_id, lesson_id,
bill_text, model=...)` produces `Flashcard`s:

```
bill_id, bill_text -> same 6 BillRagService category queries used for the
  lesson -> prompt for 6-12 vocabulary cards (citing only retrieved
  section_ids) -> ground_vocabulary_draft: term-quality filter + dedupe
  (case-insensitive) + section_id validation + difficulty normalization +
  definition length cap -> regenerate_invalid_cards (one retry, for
  replacement terms only) -> persisted via LessonRepository.create_flashcard
```

- **Term-quality filtering** (`_is_educationally_valid_term`) rejects
  terms under 2 or over 60 characters, pure numbers, and section-number-
  shaped strings (e.g. "Section 3", "SEC. 6.") per requirement #2 -- these
  are rejected even if the model cites a valid section_id, since the
  problem is the term itself, not its grounding.
- **Deduplication** is case-insensitive and applies both within one
  generation call and against `existing_terms_lower` passed into
  `regenerate_invalid_cards`, so a regeneration pass can't reintroduce a
  term already accepted.
- **No hard minimum**: unlike lesson pro/con arguments, ending up with
  fewer than `MIN_CARDS` (6) -- or even zero -- is not an error. A bill
  with little jargon may legitimately need fewer cards; `generate_vocabulary`
  logs this rather than raising.
- **Regeneration is a distinct, independently callable method**
  (`regenerate_invalid_cards`), not just a retry loop inlined into
  `generate_vocabulary` -- it takes the specific invalid terms and the
  running set of accepted terms, and returns only newly grounded
  replacement cards for the caller to merge in.
- Endpoint: vocabulary is opt-in via `include_vocabulary: bool = False` on
  `POST /lesson/generate`; the response is a `Lesson` subclass
  (`GenerateLessonResponse`) with an added `vocabulary: Optional[List[Flashcard]]`
  field, so the Increment 2 response shape (`lesson_title` etc. at the top
  level) is unchanged when the flag is omitted.

## Auth (`services/auth.py`, Increment 4)

Before this increment, DebateSim had **no server-side auth anywhere**:
per-user Firestore writes (transcripts, user docs) went straight from the
browser via the Firebase client SDK, protected only by Firestore security
rules, and no FastAPI route ever verified who was calling it. Flashcard
review progress is the first feature where the *backend itself* must know
and trust who the caller is -- one user must never be able to read or
overwrite another user's Leitner progress -- so this increment adds the
first `Depends(...)` auth dependency in the codebase:

- `get_current_user_id(authorization: str = Header(...))` reads
  `Authorization: Bearer <Firebase ID token>`, calls
  `firebase_admin.auth.verify_id_token(...)`, and returns the decoded
  `uid`. Missing/malformed headers and invalid/expired tokens both raise
  `401`; if `firebase-admin` isn't installed, `503`.
- **The uid is never accepted from a request body or query param.** Every
  review endpoint takes `user_id` only from this dependency, so a client
  cannot claim to be another user no matter what it sends -- this is what
  actually enforces "prevent users from modifying another user's
  progress," not any check inside `FlashcardReviewService` itself (that
  service trusts whatever `user_id` it's given, by design, since its only
  caller is the route layer).
- Frontend: `frontend/src/api.js`'s new review functions
  (`startReviewSession`, `getReviewState`, `submitReviewAnswer`) attach a
  fresh `auth.currentUser.getIdToken()` as the bearer token on every call --
  the first place in the frontend that sends an auth token to the FastAPI
  backend at all (existing per-user features never did; they used the
  Firebase client SDK directly instead).

## Flashcard review scheduling (`services/flashcard_review.py`, Increment 4)

Leitner scheduling is driven by a **review-session counter**
(`LessonProgress.current_session`) per user + lesson, not wall-clock time:

- **Boxes**: 1 (new/missed), 2 (correct once), 3 (correct at least twice,
  capped -- `MAX_BOX = 3`). `apply_answer` moves a card up one box on a
  correct answer or resets it straight to Box 1 on an incorrect one,
  regardless of its prior box.
- **Due-session math** (`compute_next_due_session`): a card is due
  `interval - 1` sessions after the session it was last reviewed in, where
  `interval` is `{1: 1, 2: 3, 3: 7}` for boxes 1/2/3 -- i.e. inclusive
  counting from the review session itself (reviewed on session *s* is that
  cycle's "session 1", so a Box 2 card's cycle "session 3" is `s + 2`). A
  card with no `UserCardProgress` record yet is always due (it's new).
  `tests/test_flashcard_review.py::test_scheduling_scenario_matches_manual_test_spec`
  encodes the spec's exact walkthrough (session 1 all due; correct A -> Box
  2 not due at session 2, due again at session 3; promote to Box 3, not due
  again until session 9).
- **Sessions are explicit, not auto-advanced on every request**: `GET
  .../review/state` only *reads* the current session (auto-initializing it
  to 1 on a user's very first visit to a lesson) -- it never advances it.
  Only `POST .../review/start-session` increments
  `LessonProgress.current_session`. This is what makes a browser refresh
  mid-session safe: refetching state mid-review shows the same due cards
  instead of silently skipping ahead a session.
- `GET .../review/state` returns due cards plus `total_cards`, `due_count`,
  `box_distribution` (`{"1": n, "2": n, "3": n}`), and `mastery_percent`
  (share of cards in Box 3) in one payload, so the frontend's mastery
  bar/due count/box counts can all be driven by a single fetch.
- `Lesson.vocabulary_card_ids` lets `_load_lesson_cards` find a lesson's
  flashcards without a Firestore compound query -- `POST /lesson/generate`
  persists this list onto the lesson doc whenever `include_vocabulary=true`
  (merging with any ids from a prior vocabulary-generation call for the
  same lesson).

## Frontend: `LessonFlashcards` component (Increment 4)

`frontend/src/components/LessonFlashcards.jsx` (+ `.css`) is a standalone,
reusable review UI -- term-first reveal, correct/incorrect buttons, a
mastery bar, due count, per-box counts, and a "Needs review"/"Learning"/
"Mastered" label per card (driven by `is_due`/`leitner_box` from `GET
.../review/state`). Answering optimistically updates the mastery bar/due
count/box counts locally (matching the "changes immediately" requirement)
without waiting for a refetch; a completion state with "Start Next Session"
appears once the due queue is empty.

**No Lesson Mode page exists yet to mount this component into** -- see
Non-goals. It's built and tested standalone, ready to be dropped into that
page once it exists.

This is also the first frontend test tooling added to the repo: Vitest +
React Testing Library (`vitest.config` lives inside `vite.config.js`'s new
`test` block, environment `jsdom`, run via `npm test`).
`LessonFlashcards.test.jsx` mocks `../api` entirely (never calls the real
`VITE_API_URL`-gated `api.js` module body), covering: term-shown-before-
reveal, reveal shows definition/context/example, correct/incorrect answer
submission, immediate mastery-bar/due-count updates, the completion state,
starting a new session, the "Needs review" label, and a load-error state.

## Quiz generation (`services/quiz_generation.py`, Increment 5)

```
Lesson + its Flashcards -> build_fact_pool (vocabulary/stakeholder/
  provision/implementation facts, each already grounded to a section_id
  from Increment 2/3) -> select_target_facts (round-robin up to 8) ->
  one phrasing-only model call (question stem + explanation + difficulty
  per fact -- never invents the correct answer) -> per question:
  distractor pipeline -> shuffle_choices -> QuizQuestion, persisted +
  merged onto Lesson.quiz_question_ids
```

- **Facts are never model-generated.** `build_fact_pool` pulls correct
  answers straight from `Lesson.stakeholders`/`major_provisions`
  (`GroundedClaim`s) and each `Flashcard.simple_definition` -- all already
  validated against real bill sections by Increments 2/3. `_classify_provision_type`
  splits `major_provisions` into `"provision"` vs `"implementation"` by a
  keyword heuristic (`implement`, `regulation`, `shall issue`, `enactment`,
  `agency`, ...) rather than a separate retrieval/LLM call. This is why a
  quiz question's `section_ids` need no additional grounding check here --
  it inherits grounding from where the fact came from.
- **Distractor pipeline** (the genuinely new logic): `select_embedding_distractors`
  ranks every *other* fact in the same lesson by cosine similarity
  (`services.rag.embeddings.get_embedding_provider`) to the correct answer
  and keeps the most similar ones below `MAX_DISTRACTOR_SIMILARITY` (0.92)
  -- similar enough to be plausible, not so similar it could reasonably be
  considered correct too, deduped case-insensitively. If fewer than
  `NUM_DISTRACTORS` (3) survive, `_generate_fallback_distractors` makes one
  constrained model call (`DISTRACTOR_FALLBACK_SYSTEM_PROMPT`, the prompt
  given in the spec verbatim) for the remainder, validated the same way. If
  still short, the question is dropped entirely rather than shipped with
  fewer than 4 choices.
- **Randomization**: `shuffle_choices` is a standalone, directly-testable
  function -- `tests/test_quiz_generation.py` calls it dozens of times and
  asserts the correct answer doesn't always land in the same slot.
- **Invalid model output**: `ground_phrasing` drops any `fact_index` that's
  out of range or a duplicate (silently -- other valid questions still
  proceed) but raises `QuizGenerationError` if the phrasing response is
  unparseable JSON at all, matching "invalid model output is regenerated or
  rejected."
- Endpoints: `GET /lesson/{lesson_id}/quiz` returns the public,
  answer-hidden shape; `POST /lesson/{lesson_id}/quiz/submit` (auth
  required) grades against the stored `correct_answer_index`, saves a
  `QuizAttempt`, and returns per-question `correct`/`correct_answer_index`/`explanation`
  immediately in the same response -- no separate "reveal explanation"
  round-trip.

## Open-response question and grading (Increment 6)

```
Lesson's own grounded content -> _select_question_material (pick the
  richest available type + underlying claims) -> one model call phrases
  question + expected_points -> OpenResponseQuestion, persisted +
  linked via Lesson.open_response_question_id (idempotent: one per lesson)

student_answer -> local_precheck (blank / too short / copied-the-question /
  embedding-irrelevant -> deterministic score 0, no model call) -> if none
  fire: one model call at temperature=0 against expected_points +
  context_excerpt -> ground_grade_draft (validate score 0-3, filter
  section_ids to the question's own) -> OpenResponseGrade
```

- **Generation reuses quiz generation's grounding discipline**: `_select_question_material`
  picks `pro_con_comparison` (needs both pro and con arguments -- the
  richest material), else `stakeholder_perspective`, else
  `implementation_challenge` (reusing `quiz_generation._classify_provision_type`),
  else `impact_prediction`, pulling straight from `Lesson.pro_arguments`/`con_arguments`/`stakeholders`/`major_provisions`
  -- never inventing the underlying facts, only phrasing them into a
  question + a short `expected_points` grading checklist.
- **The local pre-check is the main novel piece of "grading" logic.**
  `_is_blank`, `_is_too_short` (`< 4` words or `< 15` chars),
  `_is_copied_from_question` (`difflib.SequenceMatcher` ratio `>= 0.85`
  against the question text), and `_is_irrelevant` (embedding cosine
  similarity between the answer and `question + expected_points` `< 0.15`,
  via the same `services.rag.embeddings.get_embedding_provider` used
  elsewhere) all fire *before* any model call -- cheaper and perfectly
  stable for these degenerate cases. Crucially, the pre-check only screens
  for degenerate input, never reasoning quality or writing style: an
  informal-but-on-topic or a correct-conclusion-with-wrong-reasoning answer
  both pass through untouched to the real grader (see
  `tests/test_open_response_grading.py`'s edge-case tests).
- **Deterministic model settings**: unlike lesson/vocabulary/quiz
  generation's temperature=0.3 (there's a creative-writing goal there),
  `_default_grading_llm_call` uses temperature=0 -- there's only a rubric to
  apply consistently, not prose to vary.
- **Grounding**: the grading prompt supplies only `question.context_excerpt`
  (the same underlying claim text the question itself was built from) as
  "the supplied bill sections," and `ground_grade_draft` drops any
  `section_ids` the model cites outside `question.section_ids`. One retry
  is attempted on unparseable JSON before raising `OpenResponseGradingError`.
- Endpoints: `GET /lesson/{lesson_id}/open-response` returns the public
  shape (no `expected_points`/`context_excerpt`, so the rubric isn't given
  away before answering); `POST /lesson/{lesson_id}/open-response/submit`
  (auth required) grades the answer, saves an `OpenResponseAttempt`, and
  returns the full grade -- score, feedback, missed/accurate points, and
  section_ids -- immediately in the same response.

## Student persona builder (Increment 7)

```
GET  /lesson/persona/options  (public)  -> broad choice sets + privacy
  disclaimer (states, age ranges, income brackets, occupation suggestions,
  and the explicit `not_collected` list) so the builder UI and backend
  validation share one source of truth (PersonaProfile.field_options()).

GET    /lesson/persona           (auth) -> the caller's saved persona, or
  { has_persona: false }
PUT    /lesson/persona           (auth) -> validate + upsert (create/edit),
  returns the persona + impact_representation
DELETE /lesson/persona           (auth) -> delete; { deleted: bool }
```

- **Optional and possibly fictional by design.** Every field except
  `user_id` is optional: a student can save a persona with a single field,
  or skip persona creation entirely (the frontend simply never calls
  `PUT` — nothing is persisted implicitly). The UI states plainly that the
  persona may be fictional.
- **Broad choices only, no sensitive data.** `state` is stored as a
  two-letter USPS code; `age_range`/`income_bracket` must be one of the
  predefined broad ranges; `occupation` accepts a broad category *or* free
  text (a current or intended role), capped at 80 chars. The model
  deliberately has **no** field for exact age, exact income, home address,
  employer, race, religion, health, or political affiliation, and
  `field_options().not_collected` surfaces that list to the UI. Validation
  lives on the `PersonaProfile` model (Pydantic `field_validator`s), so a
  direct repository write and the service reject the same bad input;
  `PersonaService.save_persona` re-raises validation failures as
  `PersonaValidationError` (HTTP 422).
- **Per-user and auth-gated.** The persona is keyed by the verified `uid`
  from the Firebase token (never a request body), so read/save/delete only
  ever touch the caller's own document and a save is naturally an upsert
  (editing overwrites in place). `LessonRepository.delete_persona_profile`
  returns whether a document existed.
- **Generator-facing representation, but no narrative yet.**
  `PersonaProfile.to_impact_representation()` returns the set attributes, a
  plain-language `descriptor`, and an explicit `is_fictional: true` flag for
  the (future, Increment 8) personal-impact generator to consume. This
  increment generates no impact narrative.
- **Frontend**: `frontend/src/components/PersonaBuilder.jsx` — accessible
  labelled fields (`<label htmlFor>`, `aria-describedby`, `aria-invalid`,
  `role="alert"`/`role="status"`), a "Prefer not to say" default on every
  dropdown, a free-text occupation with a `<datalist>` of suggestions and
  a length check, and Save (auth-gated) / Skip / Delete actions. Saving is
  disabled with a sign-in prompt when the user is not authenticated.

## Personalized bill-impact narrative (Increment 8)

```
persona -> _build_persona_queries (one base query + one per set attribute:
  occupation / state / income / age) -> BillRagService retrieves the bill
  sections most relevant to THIS persona -> dedupe by section_id (keep max
  similarity), cap at MAX_CITABLE_SECTIONS -> these are the only citable ids

persona descriptor + lesson summary + citable sections -> one model call ->
  _ground_impact_draft: validate JSON, drop any impact whose cited sections
  are all unknown, trim invalid ids, normalize per-impact confidence, cap
  OVERALL confidence at "medium" when no direct impact survives ->
  PersonalImpactNarrative, persisted + cached by lesson_id + persona hash
```

- **Personalization comes from retrieval, not just phrasing.** The RAG
  queries are built from the persona's own attributes
  (`_build_persona_queries`), so a small-business owner and a retiree
  retrieve different provisions and therefore get different grounded
  impacts. This is what makes the narratives "meaningfully different" rather
  than the same summary reworded (see
  `test_different_personas_same_bill_get_different_impacts`).
- **Grounding + section-id validation** reuse the lesson-generation
  discipline: the model may cite only the retrieved section_ids, and
  `_ground_impact_draft` drops any impact whose citations are all invalid
  (never storing an uncited impact) and trims partially-invalid ones. The
  stored `section_ids` is the validated union across all impacts.
- **Certainty is never overstated.** Each impact carries its own confidence,
  and direct effects are separated from `possible_indirect_impacts` and
  `uncertainties`. Crucially, if no *direct* impact survives validation the
  overall confidence is capped at `medium` -- the narrative cannot claim the
  bill "definitely" affects the student unless the text established a direct
  effect. Unknown/oddly-worded confidences normalize to the conservative
  `low`.
- **Persona resolution + privacy.** `POST /lesson/personal-impact` (auth
  required) uses an inline persona override when supplied (so a student can
  explore a fictional persona without saving), else the caller's saved
  persona; the `user_id` always comes from the verified token. The persona
  snapshot stored on the narrative carries `is_fictional: true`, and the
  prompt instructs the model not to infer any sensitive trait beyond the
  persona given.
- **Caching**: `impact_id = {lesson_id}::impact::{IMPACT_PROMPT_VERSION}::{persona_hash[:16]}`,
  so the same persona on the same bill is idempotent (no second model call)
  and a changed persona regenerates.
- **Frontend**: `LessonPersonalImpact.jsx` renders the narrative
  prominently -- an overall-confidence banner, then direct effects, possible
  indirect effects, uncertainties, and questions-to-consider, each impact
  showing its "why", its cited bill section(s), and a per-impact confidence
  badge. Generation is an explicit button (it's a model call). Like the
  other `Lesson*` components it is built + tested but not yet mounted in a
  page (no Lesson Mode page exists -- see Non-goals).

## Dynamic debate persona (`services/dynamic_persona_generation.py`, Increment 9)

```
Lesson's own grounded facts (stakeholders/con/pro/provisions) + optional
  student PersonaProfile -> one model call (never invents facts, never
  infers opponent traits from student demographics) -> DynamicPersona
  (role, interests, concerns, position, section_ids, reason_for_selection)
  -> build_persona_prompt: format as a "PERSONA INSTRUCTIONS:" block ->
  handed to the EXISTING, UNMODIFIED chains.debater_chain.get_debater_chain(...)
  exactly as the frontend already hands it a "SPEAKING STYLE:" block for
  Trump/Harris/Musk/Drake
```

- **No second debate engine.** `chains/debater_chain.py` and `main.py` have
  a **zero-line diff** from this increment (verified: `git diff --stat
  chains/debater_chain.py main.py frontend/` is empty). The only
  integration surface is the text format: `process_inputs`
  (`chains/debater_chain.py:1097`) already scans an incoming prompt for
  `"SPEAKING STYLE:"`, `"DEBATE STYLE INSTRUCTIONS:"`, or
  `"PERSONA INSTRUCTIONS:"` and extracts everything up to the first of
  `"Instructions:"`/`"Your role:"`/`"Bill description:"`/`"Debate topic:"`.
  This module targets the third marker (the only one of the three the
  frontend doesn't already use), so a caller wires a generated persona into
  a live debate the same way the frontend wires a fixed persona: pass
  `persona.persona_prompt` as both `request.prompt` and (implicitly,
  because `main.py:280` already forwards `prompt` as `persona_prompt` too)
  the extraction input -- no backend change needed to make that work.
- **Grounding**: the model receives only the lesson's own `GroundedClaim`s
  (stakeholders and con-arguments first, since they're most likely to
  surface a genuine opposing interest, then pro-arguments and provisions)
  as "Available facts," and `ground_persona_draft` drops any `section_ids`
  outside that set -- raising `DynamicPersonaGenerationError` if *none* of
  the model's cited sections survive, so a persona is never returned
  ungrounded.
- **No stereotyping**: the system prompt explicitly instructs the model to
  ground the opponent's position "only in a concrete role and interest
  that the bill itself affects," never in the student's demographic
  traits, and `_format_student_context` labels the student fields as "use
  only to gauge which stakeholder perspective would be meaningfully
  different -- never to assume the opponent's traits." When no student
  context is supplied (the "persona skipped" path), the prompt says so
  explicitly rather than silently omitting the instruction.
- **"Show the student why this stakeholder was selected"**:
  `reason_for_selection` is a first-class field on `DynamicPersona` and the
  public API response -- never buried in the persona_prompt sent to the
  debate engine (that text is written for the *opponent* to argue from,
  not for the student to read as an explanation).
- **Distinct from Increment 8**: `student_persona` reuses the same
  `PersonaOverride`/`PersonaProfile` shape as the personal-impact feature
  (both need the same optional occupation/state/age_range/income_bracket
  context), but this module does not generate or duplicate a personal-
  impact narrative -- that remains `PersonaImpactGenerationService`'s job.
  `DynamicPersona` has no `personalized_impact_narrative` field.
- **Learning mode / Socratic hints**: `generate_socratic_hint(persona,
  full_transcript, ...)` is an independent, single-shot helper (its own
  system prompt instructs the model to coach, not debate) reusing the same
  `OpenRouterChat`-backed call pattern as the rest of Lesson Mode
  generation -- not a second reasoning engine. `POST
  /lesson/{lesson_id}/debate-persona/hint` is purely additive: competition
  mode is "standard mode" unchanged, since it simply never calls this
  endpoint. There is no `learning_mode` flag inside `chains/debater_chain.py`
  itself, preserving that module exactly as it was.

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

`tests/test_vocabulary_generation.py` covers `ground_vocabulary_draft`
(valid cards, unknown-section-id rejection, case-insensitive dedup within
a batch and against `existing_terms_lower`, section-number/numeric term
rejection, definition-length capping, difficulty normalization, max-cards
capping, malformed JSON) and `generate_vocabulary` against a mocked LLM
(persistence, the regenerate-invalid-cards path, returning fewer than
`MIN_CARDS` without failing, and the `/lesson/generate` endpoint with and
without `include_vocabulary`).

`tests/test_flashcard_review.py` covers the pure scheduling functions
(`compute_next_due_session`, `is_card_due`, `apply_answer` including the
Box-3 cap and incorrect-resets-from-any-box case), the full manual-test
scheduling scenario from the spec, `FlashcardReviewService` against a fake
Firestore client (session start/read, due-card listing, box distribution,
mastery percent, unknown-lesson/card errors), that two different users'
progress is fully independent, the `get_current_user_id` auth dependency
(missing header, malformed header, invalid token, valid token), and the
three review endpoints mounted standalone with `app.dependency_overrides`
substituting a fixed test uid for the real Firebase token verification.

`tests/test_quiz_generation.py` covers: fact-pool construction and
implementation-vs-provision classification, `select_target_facts`
round-robin diversity, `ground_phrasing` (valid input, out-of-range/duplicate
`fact_index` dropped, malformed JSON raises), the embedding distractor
selector (rejects an exact duplicate of the correct answer, case-insensitive
dedup, empty pool), `shuffle_choices` (all choices present, correct index
varies across repeated calls), end-to-end `generate_quiz` against a scripted
LLM (5-8 grounded questions with no duplicate choices, persistence, unknown
lesson / no-content errors, the distractor-fallback path when the embedding
pool is too small, and dropping a question when even the fallback can't
produce enough distractors), and the three quiz endpoints (public shape
hides the answer, 404s for a missing lesson/ungenerated quiz, auth required
to submit, scoring + `QuizAttempt` persistence, rejecting a `question_id`
that doesn't belong to the lesson). `frontend/src/components/LessonQuiz.test.jsx`
covers rendering all questions/choices, submit disabled until every question
is answered, submitting and showing the score, immediate per-question
explanations after submission, locking answers post-submission, and a
load-error state.

`tests/test_open_response_generation.py` covers question-type selection
priority (pro/con > stakeholders > implementation > generic provisions,
and the "no content at all" case), draft parsing, end-to-end generation
against a scripted LLM, persistence + linking onto `Lesson.open_response_question_id`,
and idempotency (a second call reuses the existing question without a new
model call). `tests/test_open_response_grading.py` covers the local
pre-check in isolation (blank, whitespace-only, one-word, very-short,
copied-the-question, and semantically-irrelevant answers all score 0
without a model call; a full-length relevant answer and an informal-but-
on-topic answer both pass through) plus the fixed test set required by the
spec -- complete, mostly-correct, partial, and irrelevant sample answers,
each checked for a stable score across repeated runs -- and the edge cases
(blank, one-word, long-but-irrelevant, informal-but-correct, and
correct-conclusion-with-wrong-reasoning, the last two confirmed to reach
the real grader rather than being pre-filtered). `tests/test_open_response_routes.py`
covers the public question shape (no `expected_points`/`context_excerpt`),
404s, auth requirement, scoring + `OpenResponseAttempt` persistence, and
that a blank submission never triggers a model call.
`frontend/src/components/LessonOpenResponse.test.jsx` covers rendering the
question and an empty textarea, submitting and displaying score/feedback,
showing both accurate and missed points, the "Try Again" reset, and a
load-error state.

`tests/test_dynamic_persona_generation.py` covers section_id grounding
(filtering unknown ids, raising when none survive), `build_persona_prompt`
(starts with the `"PERSONA INSTRUCTIONS:"` marker, never contains a
truncation marker, includes role/position, instructs respectful
challenge), generation with and without student context (and that
demographic details never leak into the "no context" prompt), persistence,
unknown-lesson/no-content errors, a grounding check across ten generated
personas (all `section_ids` subsets of the lesson's own facts), and the
Socratic hint helper. `tests/test_debater_chain_integration.py` is the
integration suite required by the spec: it runs the **real**
`get_debater_chain(...)` pipeline with only `OpenRouterChat._agenerate`
stubbed out, proving a generated persona's full text reaches the rendered
prompt untruncated, plus regression tests for Public Forum,
Lincoln-Douglas, the default bill-debate format, the existing
`"SPEAKING STYLE:"` fixed-persona extraction, the persona-skipped path,
and the AI-vs-AI detailed-prompt bypass. `tests/test_dynamic_persona_routes.py`
covers both new endpoints (persona provided/skipped, unknown lesson,
missing persona for a hint request).

Run the Python suite with:

```bash
python -m pytest tests/ -v
```

Run the frontend component tests with:

```bash
cd frontend && npm test
```

## Non-goals for this increment

- No Lesson Mode *page* -- there is still no route/page in the frontend
  that fetches a lesson and mounts `LessonFlashcards`/`LessonQuiz`/`LessonOpenResponse`;
  they exist only as standalone, tested components awaiting that page.
- No quiz/open-response *analytics* beyond one attempt record per
  submission (no aggregate best-score tracking wired into
  `LessonProgress.best_quiz_score` yet, no retake limits, no attempt
  history view).
- No automated verification that graded feedback text itself references
  the student's exact wording -- the grading prompt instructs this, and
  the pre-check's own feedback always quotes the answer directly for
  degenerate cases, but the LLM grader's compliance for non-degenerate
  answers is enforced by prompt engineering, not a separate programmatic
  check.
- No refresh-token handling beyond what `getIdToken()` does by default, and
  no session/box data denormalized onto `PersonaProfile` or anywhere else.
- Retrieved `BillSection`s are not yet persisted through `LessonRepository`
  (in-memory cache only); generated `Lesson`s and their `Flashcard`s are
  persisted.
- No changes to `chains/debater_chain.py` itself -- `OpenRouterChat` is
  imported and reused as-is, not modified, so existing debate behavior is
  unaffected.
- No changes to any existing route, chain, or service in `main.py` besides
  the Increment 1 two-line router mount (import +
  `app.include_router(lesson_router)`); `billsearch.py`,
  `legiscan_service.py`, `ca_propositions_service.py`, and the rest of
  `chains/` are untouched.
- No frontend wiring for the Increment 9 dynamic persona flow yet:
  `Legislation.jsx` doesn't call `POST /lesson/{lesson_id}/debate-persona/generate`
  or pass a generated `persona_prompt` into `Debate.jsx`'s existing
  `generateAIResponse(...)` call the way it already does for fixed
  personas -- that wiring, plus a "why this stakeholder" UI and a hint
  button for learning mode, is left for a future increment. The backend
  contract (a `persona_prompt` string in the exact shape
  `debater_chain.py` already parses) is what makes that wiring a small,
  low-risk frontend-only change when it happens.
- No `bill_id` is currently threaded from `Legislation.jsx` into
  `Debate.jsx`'s location state -- only already-extracted `billText`/`billTitle`
  survive that navigation. Wiring the persona endpoints into the real
  debate flow will need a `lesson_id` (or `bill_id`) added to that state,
  which is a `Legislation.jsx` change, not a backend one.
- Increment 9's dynamic debate persona endpoints are unauthenticated (no
  per-user state is written), unlike Increment 7/8's persona/impact
  endpoints which require auth.
