"""Tests for the Increment 5 grounded multiple-choice quiz generator:
fact-pool construction, phrasing validation, the embedding-first ->
LLM-fallback distractor pipeline, answer shuffling, end-to-end generation
against a mocked LLM, and the quiz endpoints.
"""

import json

import pytest

from models.lesson_models import Flashcard, GroundedClaim, Lesson
from services.lesson_repository import LessonRepository
from services.quiz_generation import (
    MAX_DISTRACTOR_SIMILARITY,
    MAX_QUESTIONS,
    MIN_QUESTIONS,
    NUM_DISTRACTORS,
    QuizGenerationError,
    QuizGenerationService,
    build_fact_pool,
    ground_phrasing,
    select_embedding_distractors,
    select_target_facts,
    shuffle_choices,
)
from tests.fake_firestore import FakeFirestoreClient

LESSON_ID = "hr1-119::v1::abc123"


def _lesson(**overrides):
    defaults = dict(
        lesson_id=LESSON_ID,
        bill_id="hr1-119",
        prompt_version="v1",
        bill_text_hash="abc123",
        lesson_title="Understanding the Community Health Access Act",
        plain_language_summary="A bill expanding health benefits.",
        stakeholders=[
            GroundedClaim(claim="Low-income families gain access to preventive care.", section_ids=["section-4"]),
            GroundedClaim(claim="Rural health clinics receive administrative funding support.", section_ids=["section-4"]),
        ],
        major_provisions=[
            GroundedClaim(claim="Eligibility requires membership in an eligible household.", section_ids=["section-3"]),
            GroundedClaim(claim="The Secretary shall issue implementing regulations within one year.", section_ids=["section-5"]),
            GroundedClaim(claim="The Act authorizes $500 million per year for five years.", section_ids=["section-6"]),
        ],
        pro_arguments=[GroundedClaim(claim="Funding is guaranteed and predictable.", section_ids=["section-6"])],
        con_arguments=[GroundedClaim(claim="Fraud penalties could deter honest applicants.", section_ids=["section-7"])],
        vocabulary_card_ids=["card-1", "card-2", "card-3"],
    )
    defaults.update(overrides)
    return Lesson(**defaults)


def _flashcard(card_id, term, definition, section_id):
    return Flashcard(
        card_id=card_id,
        lesson_id=LESSON_ID,
        term=term,
        simple_definition=definition,
        bill_context="Used to define eligibility.",
        example="An example sentence.",
        section_id=section_id,
    )


FLASHCARDS = [
    _flashcard("card-1", "eligible household", "A household at or below 200% of the poverty line.", "section-2"),
    _flashcard("card-2", "appropriation", "Money the government sets aside for a specific purpose.", "section-6"),
    _flashcard("card-3", "Secretary", "The head of the Department of Health and Human Services.", "section-5"),
]


def _seed_lesson(repo, lesson=None, flashcards=None):
    repo.create_lesson(lesson or _lesson())
    for card in (flashcards if flashcards is not None else FLASHCARDS):
        repo.create_flashcard(card)


def _phrasing_response(facts):
    """Build a valid phrasing-model JSON response for the given facts list,
    one question per fact, in order."""
    return json.dumps({
        "questions": [
            {
                "fact_index": i,
                "question": f"Question about {f.context}?",
                "explanation": f"This is correct because of {f.section_ids[0]}.",
                "difficulty": "intermediate",
            }
            for i, f in enumerate(facts)
        ]
    })


class ScriptedLLM:
    """Returns queued responses in order; falls back to `default_response`
    (typically empty distractors) once exhausted."""

    def __init__(self, *responses, default_response=None):
        self.responses = list(responses)
        self.default_response = default_response if default_response is not None else json.dumps({"distractors": []})
        self.call_count = 0
        self.prompts = []

    async def __call__(self, system_prompt, user_prompt, model):
        self.prompts.append((system_prompt, user_prompt))
        if self.call_count < len(self.responses):
            response = self.responses[self.call_count]
        else:
            response = self.default_response
        self.call_count += 1
        return response


@pytest.fixture
def repo():
    return LessonRepository(db=FakeFirestoreClient())


# ---------------------------------------------------------------------------
# Fact pool construction
# ---------------------------------------------------------------------------

def test_build_fact_pool_includes_all_categories():
    lesson = _lesson()
    facts = build_fact_pool(lesson, FLASHCARDS)
    types = {f.question_type for f in facts}
    assert "vocabulary" in types
    assert "stakeholder_impact" in types
    assert "provision" in types
    assert "implementation" in types  # "Secretary shall issue...regulations" claim


def test_build_fact_pool_classifies_implementation_by_keyword():
    lesson = _lesson()
    facts = build_fact_pool(lesson, [])
    implementation_facts = [f for f in facts if f.question_type == "implementation"]
    assert any("Secretary shall issue" in f.text for f in implementation_facts)


def test_build_fact_pool_empty_lesson_returns_empty():
    empty_lesson = _lesson(stakeholders=[], major_provisions=[], vocabulary_card_ids=[])
    facts = build_fact_pool(empty_lesson, [])
    assert facts == []


def test_select_target_facts_round_robins_across_types():
    lesson = _lesson()
    facts = build_fact_pool(lesson, FLASHCARDS)
    selected = select_target_facts(facts, target_count=4)
    # First 4 selections should hit 4 different types given round-robin order.
    assert len(selected) == 4
    assert len({f.question_type for f in selected}) >= 2


# ---------------------------------------------------------------------------
# Phrasing validation
# ---------------------------------------------------------------------------

def test_ground_phrasing_accepts_valid_response():
    lesson = _lesson()
    facts = build_fact_pool(lesson, FLASHCARDS)
    raw = _phrasing_response(facts)
    parsed = ground_phrasing(raw, num_facts=len(facts))
    assert len(parsed) == len(facts)


def test_ground_phrasing_drops_out_of_range_fact_index():
    raw = json.dumps({"questions": [{"fact_index": 99, "question": "q?", "explanation": "e", "difficulty": "beginner"}]})
    parsed = ground_phrasing(raw, num_facts=3)
    assert parsed == []


def test_ground_phrasing_drops_duplicate_fact_index():
    raw = json.dumps({"questions": [
        {"fact_index": 0, "question": "q1?", "explanation": "e1", "difficulty": "beginner"},
        {"fact_index": 0, "question": "q2?", "explanation": "e2", "difficulty": "beginner"},
    ]})
    parsed = ground_phrasing(raw, num_facts=3)
    assert len(parsed) == 1
    assert parsed[0].question == "q1?"


def test_ground_phrasing_rejects_malformed_json():
    with pytest.raises(QuizGenerationError):
        ground_phrasing("not json", num_facts=3)


# ---------------------------------------------------------------------------
# Distractor pipeline: embedding selection
# ---------------------------------------------------------------------------

def test_select_embedding_distractors_rejects_exact_duplicate_of_correct_answer():
    correct = "The Secretary shall issue implementing regulations within one year."
    candidates = [correct, "Eligibility requires membership in an eligible household.", "Funding is guaranteed and predictable."]
    distractors = select_embedding_distractors(correct, candidates, num_needed=2)
    assert correct not in distractors
    assert len(distractors) <= 2


def test_select_embedding_distractors_deduplicates_case_insensitively():
    correct = "Funding is guaranteed and predictable."
    candidates = [
        "Eligibility requires membership.",
        "ELIGIBILITY REQUIRES MEMBERSHIP.",
        "The Secretary shall issue regulations.",
    ]
    distractors = select_embedding_distractors(correct, candidates, num_needed=3)
    lowered = [d.lower() for d in distractors]
    assert len(lowered) == len(set(lowered))


def test_select_embedding_distractors_returns_empty_for_empty_pool():
    assert select_embedding_distractors("correct answer", [], num_needed=3) == []


def test_max_distractor_similarity_threshold_is_high():
    # Sanity check the threshold is strict enough to only reject near-duplicates.
    assert MAX_DISTRACTOR_SIMILARITY >= 0.85


# ---------------------------------------------------------------------------
# Answer shuffling: correct answer position varies
# ---------------------------------------------------------------------------

def test_shuffle_choices_includes_correct_answer_and_all_distractors():
    correct = "correct"
    distractors = ["wrong1", "wrong2", "wrong3"]
    choices, index = shuffle_choices(correct, distractors)
    assert set(choices) == {correct, *distractors}
    assert choices[index] == correct
    assert len(choices) == 4


def test_shuffle_choices_correct_index_is_not_always_the_same_position():
    positions = set()
    for _ in range(40):
        _, index = shuffle_choices("correct", ["a", "b", "c"])
        positions.add(index)
    assert len(positions) > 1  # extremely unlikely to always land in one slot


# ---------------------------------------------------------------------------
# End-to-end quiz generation (mocked LLM, fake Firestore)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_generate_quiz_produces_grounded_questions(repo):
    _seed_lesson(repo)
    lesson = repo.get_lesson(LESSON_ID)
    facts = build_fact_pool(lesson, FLASHCARDS)
    target = min(MAX_QUESTIONS, len(facts))
    selected = select_target_facts(facts, target)
    llm = ScriptedLLM(_phrasing_response(selected))

    service = QuizGenerationService(repository=repo, llm_call=llm)
    questions = await service.generate_quiz(LESSON_ID)

    assert MIN_QUESTIONS <= len(questions) <= MAX_QUESTIONS
    for q in questions:
        assert len(q.answer_choices) == NUM_DISTRACTORS + 1
        assert len(set(c.lower() for c in q.answer_choices)) == len(q.answer_choices)  # no duplicates
        assert 0 <= q.correct_answer_index < len(q.answer_choices)
        assert len(q.section_ids) >= 1
        assert q.explanation


@pytest.mark.asyncio
async def test_generate_quiz_persists_questions(repo):
    _seed_lesson(repo)
    lesson = repo.get_lesson(LESSON_ID)
    facts = build_fact_pool(lesson, FLASHCARDS)
    selected = select_target_facts(facts, min(MAX_QUESTIONS, len(facts)))
    llm = ScriptedLLM(_phrasing_response(selected))

    service = QuizGenerationService(repository=repo, llm_call=llm)
    questions = await service.generate_quiz(LESSON_ID)

    for q in questions:
        fetched = repo.get_quiz_question(q.question_id)
        assert fetched is not None
        assert fetched.question == q.question


@pytest.mark.asyncio
async def test_generate_quiz_raises_for_unknown_lesson(repo):
    service = QuizGenerationService(repository=repo, llm_call=ScriptedLLM("{}"))
    with pytest.raises(QuizGenerationError):
        await service.generate_quiz("no-such-lesson")


@pytest.mark.asyncio
async def test_generate_quiz_raises_when_no_content(repo):
    empty_lesson = _lesson(stakeholders=[], major_provisions=[], vocabulary_card_ids=[])
    repo.create_lesson(empty_lesson)
    service = QuizGenerationService(repository=repo, llm_call=ScriptedLLM("{}"))
    with pytest.raises(QuizGenerationError):
        await service.generate_quiz(LESSON_ID)


@pytest.mark.asyncio
async def test_generate_quiz_uses_distractor_fallback_when_pool_too_small(repo):
    # A lesson with only ONE fact total means the embedding pool (all OTHER
    # facts) is empty, so every question must go through the LLM fallback.
    tiny_lesson = _lesson(
        stakeholders=[GroundedClaim(claim="Only one fact exists in this lesson.", section_ids=["section-4"])],
        major_provisions=[],
        vocabulary_card_ids=[],
    )
    repo.create_lesson(tiny_lesson)

    facts = build_fact_pool(tiny_lesson, [])
    phrasing = _phrasing_response(facts)
    fallback = json.dumps({"distractors": ["Wrong fact A.", "Wrong fact B.", "Wrong fact C."]})
    llm = ScriptedLLM(phrasing, fallback)

    service = QuizGenerationService(repository=repo, llm_call=llm)
    questions = await service.generate_quiz(LESSON_ID, min_questions=1, max_questions=1)

    assert len(questions) == 1
    assert len(questions[0].answer_choices) == 4
    assert llm.call_count == 2  # phrasing call + one fallback distractor call


@pytest.mark.asyncio
async def test_generate_quiz_drops_question_when_fallback_insufficient(repo):
    tiny_lesson = _lesson(
        stakeholders=[GroundedClaim(claim="Only one fact exists in this lesson.", section_ids=["section-4"])],
        major_provisions=[],
        vocabulary_card_ids=[],
    )
    repo.create_lesson(tiny_lesson)
    facts = build_fact_pool(tiny_lesson, [])
    phrasing = _phrasing_response(facts)
    # Fallback returns too few distractors -> question must be dropped.
    fallback = json.dumps({"distractors": ["Only one wrong answer."]})
    llm = ScriptedLLM(phrasing, fallback)

    service = QuizGenerationService(repository=repo, llm_call=llm)
    with pytest.raises(QuizGenerationError):
        await service.generate_quiz(LESSON_ID, min_questions=1, max_questions=1)


# ---------------------------------------------------------------------------
# Endpoint integration tests
# ---------------------------------------------------------------------------

@pytest.fixture
def client_factory(repo, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    import routes.lesson_routes as lesson_routes
    from services.auth import get_current_user_id
    from services.lesson_generation import LessonGenerationService
    from services.quiz_generation import QuizGenerationService as QGS

    # Point every service the routes use at the same fake-Firestore-backed
    # repository the test seeded, so endpoint calls see that data.
    monkeypatch.setattr(
        lesson_routes, "_lesson_generation_service", LessonGenerationService(repository=repo)
    )
    monkeypatch.setattr(lesson_routes, "_quiz_generation_service", QGS(repository=repo))

    def _make(user_id=None):
        app = FastAPI()
        app.include_router(lesson_routes.router)
        if user_id is not None:
            app.dependency_overrides[get_current_user_id] = lambda: user_id
        return TestClient(app)

    return _make


def test_endpoint_get_quiz_returns_public_shape_without_answers(repo, client_factory):
    _seed_lesson(repo)
    lesson = repo.get_lesson(LESSON_ID)
    facts = build_fact_pool(lesson, FLASHCARDS)
    selected = select_target_facts(facts, min(MAX_QUESTIONS, len(facts)))

    import asyncio

    from services.quiz_generation import QuizGenerationService as QGS

    llm = ScriptedLLM(_phrasing_response(selected))
    service = QGS(repository=repo, llm_call=llm)
    asyncio.run(service.generate_quiz(LESSON_ID))

    client = client_factory()
    resp = client.get(f"/lesson/{LESSON_ID}/quiz")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) >= MIN_QUESTIONS
    for q in data:
        assert "correct_answer_index" not in q
        assert "explanation" not in q
        assert len(q["answer_choices"]) == 4


def test_endpoint_get_quiz_unknown_lesson_returns_404(client_factory):
    client = client_factory()
    resp = client.get("/lesson/no-such-lesson/quiz")
    assert resp.status_code == 404


def test_endpoint_get_quiz_no_quiz_generated_yet_returns_404(repo, client_factory):
    repo.create_lesson(_lesson())
    client = client_factory()
    resp = client.get(f"/lesson/{LESSON_ID}/quiz")
    assert resp.status_code == 404


def test_endpoint_submit_quiz_requires_auth(repo, client_factory):
    repo.create_lesson(_lesson())
    client = client_factory()  # no user override -> unauthenticated
    resp = client.post(f"/lesson/{LESSON_ID}/quiz/submit", json={"answers": [{"question_id": "x", "selected_index": 0}]})
    assert resp.status_code == 401


def test_endpoint_submit_quiz_scores_and_saves_attempt(repo, client_factory):
    _seed_lesson(repo)
    lesson = repo.get_lesson(LESSON_ID)
    facts = build_fact_pool(lesson, FLASHCARDS)
    selected = select_target_facts(facts, min(MAX_QUESTIONS, len(facts)))

    import asyncio

    from services.quiz_generation import QuizGenerationService as QGS

    llm = ScriptedLLM(_phrasing_response(selected))
    service = QGS(repository=repo, llm_call=llm)
    questions = asyncio.run(service.generate_quiz(LESSON_ID))

    client = client_factory(user_id="user-1")
    answers = [
        {"question_id": q.question_id, "selected_index": q.correct_answer_index}
        for q in questions
    ]
    resp = client.post(f"/lesson/{LESSON_ID}/quiz/submit", json={"answers": answers})
    assert resp.status_code == 200
    data = resp.json()
    assert data["score"] == 100.0
    assert all(r["correct"] for r in data["results"])
    assert all(r["explanation"] for r in data["results"])

    attempt = repo.get_quiz_attempt(data["attempt_id"])
    assert attempt is not None
    assert attempt.user_id == "user-1"
    assert attempt.score == 100.0


def test_endpoint_submit_quiz_rejects_question_not_in_lesson(repo, client_factory):
    _seed_lesson(repo)
    lesson = repo.get_lesson(LESSON_ID)
    facts = build_fact_pool(lesson, FLASHCARDS)
    selected = select_target_facts(facts, min(MAX_QUESTIONS, len(facts)))

    import asyncio

    from services.quiz_generation import QuizGenerationService as QGS

    llm = ScriptedLLM(_phrasing_response(selected))
    service = QGS(repository=repo, llm_call=llm)
    asyncio.run(service.generate_quiz(LESSON_ID))

    client = client_factory(user_id="user-1")
    resp = client.post(
        f"/lesson/{LESSON_ID}/quiz/submit",
        json={"answers": [{"question_id": "bogus-question", "selected_index": 0}]},
    )
    assert resp.status_code == 400
