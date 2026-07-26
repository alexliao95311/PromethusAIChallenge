"""Tests for the Increment 10 post-debate reflection generator, using
scripted model responses (no network)."""

import json

import pytest

from services.lesson_repository import LessonRepository
from services.reflection_generation import (
    ReflectionGenerationError,
    ReflectionGenerationService,
    _ground_analysis_draft,
    _verify_excerpt,
)
from tests.fake_firestore import FakeFirestoreClient

LESSON_ID = "hr1-119::v1::abc123"

TRANSCRIPT = (
    "## Pro (Round 1)\n"
    "The bill guarantees funding for rural clinics, which is a concrete benefit.\n\n"
    "## Con (Round 1)\n"
    "The funding is capped and may not keep pace with rising costs.\n\n"
    "## Pro (Round 2)\n"
    "Even a capped increase is better than the current baseline of zero.\n"
)


def _analysis_json(**overrides):
    base = {
        "strongest_student_argument": {
            "feedback": "The student's point about the funding cap being better than zero was strong.",
            "transcript_excerpt": "Even a capped increase is better than the current baseline of zero.",
        },
        "weakest_reasoning_step": {
            "feedback": "The student never explained why the cap wouldn't matter in practice.",
            "transcript_excerpt": "The bill guarantees funding for rural clinics, which is a concrete benefit.",
        },
        "evidence_use_feedback": {
            "feedback": "The student did not cite any specific figures.",
            "transcript_excerpt": None,
        },
        "missed_opponent_point": {
            "feedback": "The student never addressed the opponent's point about rising costs.",
            "transcript_excerpt": "The funding is capped and may not keep pace with rising costs.",
        },
        "perspective_understanding": {
            "feedback": "The student engaged directly with the opponent's framing.",
            "transcript_excerpt": "Even a capped increase is better than the current baseline of zero.",
        },
        "recommended_skill": "Responding directly to the opponent's strongest objection",
        "recommended_next_activity": "Debate this bill again from the opposing side",
    }
    base.update(overrides)
    return json.dumps(base)


class ScriptedLLM:
    def __init__(self, response):
        self.response = response
        self.call_count = 0
        self.last_prompt = None

    async def __call__(self, system_prompt, user_prompt, model):
        self.call_count += 1
        self.last_prompt = user_prompt
        return self.response


@pytest.fixture
def repo():
    return LessonRepository(db=FakeFirestoreClient())


def test_verify_excerpt_accepts_verbatim_substring():
    assert _verify_excerpt("capped increase is better", TRANSCRIPT) is not None


def test_verify_excerpt_rejects_fabricated_quote():
    assert _verify_excerpt("The student is clearly wrong about everything", TRANSCRIPT) is None


def test_verify_excerpt_none_passthrough():
    assert _verify_excerpt(None, TRANSCRIPT) is None


def test_ground_analysis_draft_keeps_verbatim_excerpts():
    items, skill, activity, dropped = _ground_analysis_draft(_analysis_json(), TRANSCRIPT)
    assert items["strongest_student_argument"].transcript_excerpt == (
        "Even a capped increase is better than the current baseline of zero."
    )
    assert items["evidence_use_feedback"].transcript_excerpt is None
    assert skill and activity
    assert dropped == []


def test_ground_analysis_draft_drops_ungrounded_excerpt():
    bad = json.loads(_analysis_json())
    bad["missed_opponent_point"]["transcript_excerpt"] = "This sentence never appears anywhere."
    items, _, _, dropped = _ground_analysis_draft(json.dumps(bad), TRANSCRIPT)
    # Feedback text is kept even though the excerpt didn't verify.
    assert items["missed_opponent_point"].feedback
    assert items["missed_opponent_point"].transcript_excerpt is None
    assert len(dropped) == 1


@pytest.mark.asyncio
async def test_generate_reflection_persists_self_reported_view_change(repo):
    llm = ScriptedLLM(_analysis_json())
    service = ReflectionGenerationService(repository=repo, llm_call=llm)

    reflection = await service.generate_reflection(
        reflection_id="refl-1",
        lesson_id=LESSON_ID,
        user_id="u1",
        transcript=TRANSCRIPT,
        view_changed="somewhat",
        explanation="I hadn't considered the cost side before.",
    )

    assert reflection.view_changed == "somewhat"
    assert reflection.explanation == "I hadn't considered the cost side before."
    assert reflection.strongest_student_argument.transcript_excerpt is not None
    persisted = repo.get_debate_reflection("refl-1")
    assert persisted is not None and persisted.user_id == "u1"


@pytest.mark.asyncio
async def test_generate_reflection_rejects_empty_transcript(repo):
    service = ReflectionGenerationService(repository=repo, llm_call=ScriptedLLM(_analysis_json()))
    with pytest.raises(ValueError):
        await service.generate_reflection(
            reflection_id="refl-2",
            lesson_id=LESSON_ID,
            user_id="u1",
            transcript="   ",
            view_changed="no",
        )


@pytest.mark.asyncio
async def test_generate_reflection_retries_on_bad_json_then_succeeds(repo):
    class FlakyLLM:
        def __init__(self):
            self.call_count = 0

        async def __call__(self, system_prompt, user_prompt, model):
            self.call_count += 1
            if self.call_count == 1:
                return "not json at all"
            return _analysis_json()

    llm = FlakyLLM()
    service = ReflectionGenerationService(repository=repo, llm_call=llm)
    reflection = await service.generate_reflection(
        reflection_id="refl-3",
        lesson_id=LESSON_ID,
        user_id="u1",
        transcript=TRANSCRIPT,
        view_changed="yes",
    )
    assert llm.call_count == 2
    assert reflection.reflection_id == "refl-3"


@pytest.mark.asyncio
async def test_generate_reflection_raises_after_exhausting_retries(repo):
    service = ReflectionGenerationService(repository=repo, llm_call=ScriptedLLM("not json"))
    with pytest.raises(ReflectionGenerationError):
        await service.generate_reflection(
            reflection_id="refl-4",
            lesson_id=LESSON_ID,
            user_id="u1",
            transcript=TRANSCRIPT,
            view_changed="no",
        )


@pytest.mark.asyncio
async def test_get_progress_returns_reflections_across_lessons_oldest_first(repo):
    llm = ScriptedLLM(_analysis_json())
    service = ReflectionGenerationService(repository=repo, llm_call=llm)

    await service.generate_reflection(
        reflection_id="refl-a", lesson_id="lesson-1", user_id="u1",
        transcript=TRANSCRIPT, view_changed="yes",
    )
    await service.generate_reflection(
        reflection_id="refl-b", lesson_id="lesson-2", user_id="u1",
        transcript=TRANSCRIPT, view_changed="no",
    )
    await service.generate_reflection(
        reflection_id="refl-c", lesson_id="lesson-1", user_id="u2",
        transcript=TRANSCRIPT, view_changed="somewhat",
    )

    progress = service.get_progress("u1")
    assert [r.reflection_id for r in progress] == ["refl-a", "refl-b"]
    assert {r.lesson_id for r in progress} == {"lesson-1", "lesson-2"}
