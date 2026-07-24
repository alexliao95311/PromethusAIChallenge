"""Tests for Increment 6 open-response grading: the deterministic local
pre-check (blank/short/copied/irrelevant), draft parsing and section_id
filtering, end-to-end grading against a fixed set of sample answers (mocked
LLM), stability across repeated runs, and the grading endpoints.
"""

import json

import pytest

from models.lesson_models import OpenResponseQuestion
from services.open_response_grading import (
    MIN_ANSWER_CHARS,
    MIN_ANSWER_WORDS,
    OpenResponseGradingError,
    OpenResponseGradingService,
    ground_grade_draft,
    local_precheck,
)

QUESTION = OpenResponseQuestion(
    question_id="q1-open-response",
    lesson_id="lesson-1",
    question="Why might a small-business owner oppose this bill?",
    question_type="stakeholder_perspective",
    expected_points=[
        "Identifies the administrative/compliance cost of the new requirements",
        "Explains how that cost could affect hiring or operations",
    ],
    section_ids=["section-8"],
    context_excerpt="- Businesses with 50+ employees must file quarterly compliance reports under section 8.",
)


def _grade_response(score=2, feedback="Good but incomplete.", missed=None, accurate_points=None, section_ids=None):
    return json.dumps({
        "score": score,
        "feedback": feedback,
        "missed_points": missed or [],
        "accurate_points": accurate_points or [],
        "section_ids": section_ids or ["section-8"],
    })


class ScriptedLLM:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.call_count = 0

    async def __call__(self, system_prompt, user_prompt, model):
        response = self.responses[min(self.call_count, len(self.responses) - 1)]
        self.call_count += 1
        return response


# ---------------------------------------------------------------------------
# Local pre-check: deterministic, no model call
# ---------------------------------------------------------------------------

def test_precheck_blank_answer_scores_zero():
    grade = local_precheck(QUESTION, "")
    assert grade is not None
    assert grade.score == 0
    assert grade.missed_points == QUESTION.expected_points


def test_precheck_whitespace_only_answer_scores_zero():
    grade = local_precheck(QUESTION, "   \n  ")
    assert grade is not None
    assert grade.score == 0


def test_precheck_one_word_answer_scores_zero():
    grade = local_precheck(QUESTION, "idk")
    assert grade is not None
    assert grade.score == 0


def test_precheck_very_short_answer_references_the_actual_answer():
    grade = local_precheck(QUESTION, "compliance costs")
    assert grade is not None
    assert grade.score == 0
    assert "compliance costs" in grade.feedback


def test_precheck_copied_question_scores_zero():
    grade = local_precheck(QUESTION, "Why might a small-business owner oppose this bill?")
    assert grade is not None
    assert grade.score == 0


def test_precheck_irrelevant_answer_scores_zero():
    grade = local_precheck(
        QUESTION,
        "My favorite video game has really fun graphics and a great soundtrack that I enjoy a lot.",
    )
    assert grade is not None
    assert grade.score == 0


def test_precheck_passes_through_a_relevant_full_length_answer():
    grade = local_precheck(
        QUESTION,
        "A small-business owner might oppose this bill because the new quarterly compliance "
        "reports required under section 8 would take staff time and money away from hiring.",
    )
    assert grade is None  # should proceed to real grading


def test_precheck_does_not_penalize_informal_but_on_topic_answers():
    # Informal phrasing, but clearly on-topic and long enough -- should NOT
    # be caught by the short/copied/irrelevant pre-checks (writing style is
    # not something the local pre-check should judge).
    grade = local_precheck(
        QUESTION,
        "honestly probably bc filling out all that paperwork every few months costs "
        "time and money they'd rather spend on their actual business",
    )
    assert grade is None


def test_precheck_is_stable_across_repeated_calls():
    results = [local_precheck(QUESTION, "idk") for _ in range(5)]
    assert all(r.score == 0 for r in results)


def test_min_thresholds_are_reasonable():
    assert MIN_ANSWER_WORDS >= 2
    assert MIN_ANSWER_CHARS >= 5


# ---------------------------------------------------------------------------
# Draft parsing / grounding
# ---------------------------------------------------------------------------

def test_ground_grade_draft_accepts_valid_response():
    grade = ground_grade_draft(_grade_response(score=3), known_section_ids={"section-8"})
    assert grade.score == 3


def test_ground_grade_draft_filters_unknown_section_ids():
    raw = _grade_response(section_ids=["section-8", "section-999"])
    grade = ground_grade_draft(raw, known_section_ids={"section-8"})
    assert grade.section_ids == ["section-8"]


def test_ground_grade_draft_rejects_malformed_json():
    with pytest.raises(OpenResponseGradingError):
        ground_grade_draft("not json", known_section_ids={"section-8"})


def test_ground_grade_draft_rejects_out_of_range_score():
    raw = json.dumps({"score": 5, "feedback": "x", "missed_points": [], "accurate_points": [], "section_ids": []})
    with pytest.raises(OpenResponseGradingError):
        ground_grade_draft(raw, known_section_ids=set())


# ---------------------------------------------------------------------------
# End-to-end grading with a fixed test set: complete / mostly correct /
# partial / irrelevant answers, each run multiple times for stability.
# ---------------------------------------------------------------------------

COMPLETE_ANSWER = (
    "A small-business owner might oppose this bill because the quarterly compliance "
    "reports required under section 8 create an administrative burden that costs time "
    "and money, which could mean less budget available for hiring new employees."
)
MOSTLY_CORRECT_ANSWER = (
    "They might oppose it because filing compliance reports every quarter takes staff "
    "time and costs the business money."
)
PARTIAL_ANSWER = "It costs them money to follow the new rules."
IRRELEVANT_ANSWER = "My favorite color is blue and I enjoy hiking with my dog on weekends."


@pytest.mark.asyncio
async def test_grade_answer_complete_answer_scores_high_and_is_stable():
    llm = ScriptedLLM(_grade_response(
        score=3,
        feedback="You correctly identified both the compliance cost and its effect on hiring.",
        accurate_points=["Administrative burden", "Possible effect on hiring"],
    ))
    service = OpenResponseGradingService(llm_call=llm)

    for _ in range(3):
        grade = await service.grade_answer(QUESTION, COMPLETE_ANSWER)
        assert grade.score == 3


@pytest.mark.asyncio
async def test_grade_answer_mostly_correct_scores_two():
    llm = ScriptedLLM(_grade_response(
        score=2,
        feedback="You identified the compliance cost but did not explain how it could affect hiring.",
        accurate_points=["Administrative burden"],
        missed=["Possible effect on hiring"],
    ))
    service = OpenResponseGradingService(llm_call=llm)
    grade = await service.grade_answer(QUESTION, MOSTLY_CORRECT_ANSWER)
    assert grade.score == 2
    assert "Possible effect on hiring" in grade.missed_points


@pytest.mark.asyncio
async def test_grade_answer_partial_answer_scores_one():
    llm = ScriptedLLM(_grade_response(
        score=1,
        feedback="You mentioned cost but did not explain the compliance requirement or its effect on hiring.",
        missed=["Administrative burden", "Possible effect on hiring"],
    ))
    service = OpenResponseGradingService(llm_call=llm)
    grade = await service.grade_answer(QUESTION, PARTIAL_ANSWER)
    assert grade.score == 1


@pytest.mark.asyncio
async def test_grade_answer_irrelevant_answer_caught_by_precheck_without_llm_call():
    llm = ScriptedLLM(_grade_response(score=3))  # would be wrong if ever called
    service = OpenResponseGradingService(llm_call=llm)
    grade = await service.grade_answer(QUESTION, IRRELEVANT_ANSWER)
    assert grade.score == 0
    assert llm.call_count == 0  # pre-check handled it locally


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_edge_case_blank_response():
    service = OpenResponseGradingService(llm_call=ScriptedLLM(_grade_response(score=3)))
    grade = await service.grade_answer(QUESTION, "")
    assert grade.score == 0


@pytest.mark.asyncio
async def test_edge_case_one_word_response():
    service = OpenResponseGradingService(llm_call=ScriptedLLM(_grade_response(score=3)))
    grade = await service.grade_answer(QUESTION, "money")
    assert grade.score == 0


@pytest.mark.asyncio
async def test_edge_case_long_but_irrelevant_response():
    long_irrelevant = (
        "I think basketball is a really fun sport to watch and my favorite team has been "
        "doing great this season with some exciting new players who scored a lot of points."
    )
    service = OpenResponseGradingService(llm_call=ScriptedLLM(_grade_response(score=3)))
    grade = await service.grade_answer(QUESTION, long_irrelevant)
    assert grade.score == 0


@pytest.mark.asyncio
async def test_edge_case_correct_idea_written_informally_reaches_llm():
    llm = ScriptedLLM(_grade_response(score=2, accurate_points=["Administrative burden"]))
    service = OpenResponseGradingService(llm_call=llm)
    grade = await service.grade_answer(
        QUESTION,
        "prob bc all that extra paperwork every quarter eats into time n money they could spend elsewhere",
    )
    assert llm.call_count == 1  # reached the model, not rejected by pre-check
    assert grade.score == 2


@pytest.mark.asyncio
async def test_edge_case_correct_conclusion_wrong_reasoning_reaches_llm_and_is_gradeable():
    # The pre-check should not judge reasoning quality -- only degenerate
    # inputs. A wrong-reasoning-but-on-topic answer must reach the model.
    llm = ScriptedLLM(_grade_response(
        score=1,
        feedback="You concluded the business would oppose it, but the reasoning given (that it's a tax) is incorrect.",
        missed=["Administrative burden", "Possible effect on hiring"],
    ))
    service = OpenResponseGradingService(llm_call=llm)
    grade = await service.grade_answer(
        QUESTION,
        "They'd oppose it because it's basically a new tax on small businesses that the government created.",
    )
    assert llm.call_count == 1
    assert grade.score == 1


@pytest.mark.asyncio
async def test_grade_answer_retries_on_malformed_model_output():
    llm = ScriptedLLM("not json", _grade_response(score=2))
    service = OpenResponseGradingService(llm_call=llm)
    grade = await service.grade_answer(QUESTION, COMPLETE_ANSWER, max_attempts=2)
    assert grade.score == 2
    assert llm.call_count == 2


@pytest.mark.asyncio
async def test_grade_answer_raises_after_exhausting_retries():
    llm = ScriptedLLM("not json", "still not json")
    service = OpenResponseGradingService(llm_call=llm)
    with pytest.raises(OpenResponseGradingError):
        await service.grade_answer(QUESTION, COMPLETE_ANSWER, max_attempts=2)
