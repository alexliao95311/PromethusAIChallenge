"""Tests for Increment 6 open-response question generation: question-type
selection, draft parsing, end-to-end generation (mocked LLM), and
idempotency (a lesson has at most one open-response question).
"""

import json

import pytest

from models.lesson_models import GroundedClaim, Lesson
from services.lesson_repository import LessonRepository
from services.open_response_generation import (
    OpenResponseGenerationError,
    OpenResponseGenerationService,
    _select_question_material,
    ground_open_response_draft,
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
        stakeholders=[],
        major_provisions=[],
        pro_arguments=[],
        con_arguments=[],
    )
    defaults.update(overrides)
    return Lesson(**defaults)


class ScriptedLLM:
    def __init__(self, response):
        self.response = response
        self.call_count = 0
        self.prompts = []

    async def __call__(self, system_prompt, user_prompt, model):
        self.prompts.append(user_prompt)
        self.call_count += 1
        return self.response


def _draft_response(question="Why might this matter?", points=("Point A", "Point B")):
    return json.dumps({"question": question, "expected_points": list(points)})


@pytest.fixture
def repo():
    return LessonRepository(db=FakeFirestoreClient())


# ---------------------------------------------------------------------------
# Question-type / material selection
# ---------------------------------------------------------------------------

def test_selects_pro_con_comparison_when_both_present():
    lesson = _lesson(
        pro_arguments=[GroundedClaim(claim="Funding is guaranteed.", section_ids=["section-6"])],
        con_arguments=[GroundedClaim(claim="Fraud penalties could deter applicants.", section_ids=["section-7"])],
    )
    qtype, claims, _ = _select_question_material(lesson)
    assert qtype == "pro_con_comparison"
    assert len(claims) == 2


def test_selects_stakeholder_perspective_when_only_stakeholders():
    lesson = _lesson(
        stakeholders=[GroundedClaim(claim="Rural clinics receive funding support.", section_ids=["section-4"])],
    )
    qtype, claims, _ = _select_question_material(lesson)
    assert qtype == "stakeholder_perspective"
    assert len(claims) == 1


def test_selects_implementation_challenge_when_only_implementation_provisions():
    lesson = _lesson(
        major_provisions=[
            GroundedClaim(claim="The Secretary shall issue implementing regulations within one year.", section_ids=["section-5"]),
        ],
    )
    qtype, claims, _ = _select_question_material(lesson)
    assert qtype == "implementation_challenge"
    assert len(claims) == 1


def test_selects_impact_prediction_when_only_generic_provisions():
    lesson = _lesson(
        major_provisions=[
            GroundedClaim(claim="Eligibility requires membership in an eligible household.", section_ids=["section-3"]),
        ],
    )
    qtype, claims, _ = _select_question_material(lesson)
    assert qtype == "impact_prediction"
    assert len(claims) == 1


def test_selects_nothing_when_lesson_has_no_content():
    lesson = _lesson()
    qtype, claims, _ = _select_question_material(lesson)
    assert qtype == ""
    assert claims == []


def test_pro_con_comparison_takes_priority_over_stakeholders():
    lesson = _lesson(
        pro_arguments=[GroundedClaim(claim="Funding is guaranteed.", section_ids=["section-6"])],
        con_arguments=[GroundedClaim(claim="Fraud penalties could deter applicants.", section_ids=["section-7"])],
        stakeholders=[GroundedClaim(claim="Rural clinics receive funding support.", section_ids=["section-4"])],
    )
    qtype, _, _ = _select_question_material(lesson)
    assert qtype == "pro_con_comparison"


# ---------------------------------------------------------------------------
# Draft parsing
# ---------------------------------------------------------------------------

def test_ground_open_response_draft_accepts_valid_response():
    draft = ground_open_response_draft(_draft_response())
    assert draft.question == "Why might this matter?"
    assert draft.expected_points == ["Point A", "Point B"]


def test_ground_open_response_draft_rejects_malformed_json():
    with pytest.raises(OpenResponseGenerationError):
        ground_open_response_draft("not json")


def test_ground_open_response_draft_rejects_missing_expected_points():
    raw = json.dumps({"question": "Why?"})
    with pytest.raises(OpenResponseGenerationError):
        ground_open_response_draft(raw)


# ---------------------------------------------------------------------------
# End-to-end generation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_generate_question_produces_grounded_question(repo):
    lesson = _lesson(
        pro_arguments=[GroundedClaim(claim="Funding is guaranteed and predictable.", section_ids=["section-6"])],
        con_arguments=[GroundedClaim(claim="Fraud penalties could deter applicants.", section_ids=["section-7"])],
    )
    repo.create_lesson(lesson)
    llm = ScriptedLLM(_draft_response("Which side's reasoning is stronger, and why?", ["Weighs funding stability", "Weighs fraud deterrence risk"]))
    service = OpenResponseGenerationService(repository=repo, llm_call=llm)

    question = await service.generate_question(LESSON_ID)

    assert question.question_type == "pro_con_comparison"
    assert question.expected_points == ["Weighs funding stability", "Weighs fraud deterrence risk"]
    assert set(question.section_ids) == {"section-6", "section-7"}
    assert "Funding is guaranteed" in question.context_excerpt


@pytest.mark.asyncio
async def test_generate_question_persists_and_links_to_lesson(repo):
    lesson = _lesson(stakeholders=[GroundedClaim(claim="Rural clinics receive funding.", section_ids=["section-4"])])
    repo.create_lesson(lesson)
    llm = ScriptedLLM(_draft_response())
    service = OpenResponseGenerationService(repository=repo, llm_call=llm)

    question = await service.generate_question(LESSON_ID)

    fetched_lesson = repo.get_lesson(LESSON_ID)
    assert fetched_lesson.open_response_question_id == question.question_id
    fetched_question = repo.get_open_response_question(question.question_id)
    assert fetched_question == question


@pytest.mark.asyncio
async def test_generate_question_is_idempotent(repo):
    lesson = _lesson(stakeholders=[GroundedClaim(claim="Rural clinics receive funding.", section_ids=["section-4"])])
    repo.create_lesson(lesson)
    llm = ScriptedLLM(_draft_response())
    service = OpenResponseGenerationService(repository=repo, llm_call=llm)

    first = await service.generate_question(LESSON_ID)
    second = await service.generate_question(LESSON_ID)

    assert first.question_id == second.question_id
    assert llm.call_count == 1  # second call reused the cached question


@pytest.mark.asyncio
async def test_generate_question_raises_for_unknown_lesson(repo):
    service = OpenResponseGenerationService(repository=repo, llm_call=ScriptedLLM("{}"))
    with pytest.raises(OpenResponseGenerationError):
        await service.generate_question("no-such-lesson")


@pytest.mark.asyncio
async def test_generate_question_raises_when_no_content(repo):
    repo.create_lesson(_lesson())
    service = OpenResponseGenerationService(repository=repo, llm_call=ScriptedLLM("{}"))
    with pytest.raises(OpenResponseGenerationError):
        await service.generate_question(LESSON_ID)
