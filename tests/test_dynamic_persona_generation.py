"""Tests for Increment 9 dynamic opposing debate persona generation:
grounding, persona-prompt formatting (the entire integration surface with
the existing debate engine), student-context handling (provided vs
skipped), and the Socratic hint helper.
"""

import json

import pytest

from models.lesson_models import DynamicPersona, GroundedClaim, Lesson, PersonaProfile
from services.dynamic_persona_generation import (
    DynamicPersonaGenerationError,
    DynamicPersonaGenerationService,
    PERSONA_INSTRUCTIONS_MARKER,
    _TRUNCATION_MARKERS,
    build_persona_prompt,
    generate_socratic_hint,
    ground_persona_draft,
)
from services.lesson_repository import LessonRepository
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
            GroundedClaim(claim="Rural health clinics receive administrative funding support.", section_ids=["section-4"]),
        ],
        con_arguments=[
            GroundedClaim(claim="Compliance reporting could burden small clinics with limited staff.", section_ids=["section-8"]),
        ],
        major_provisions=[
            GroundedClaim(claim="The Act authorizes $500 million per year for five fiscal years.", section_ids=["section-6"]),
        ],
    )
    defaults.update(overrides)
    return Lesson(**defaults)


def _persona_response(**overrides):
    payload = {
        "role": "School district budget director",
        "location_context": "overseeing a rural county school district's health-services budget",
        "interests": ["Predictable funding", "Minimizing new administrative burden"],
        "likely_concerns": ["New compliance reporting could strain limited staff time"],
        "position": "Cautiously supportive of the funding but concerned about implementation costs",
        "section_ids": ["section-8"],
        "reason_for_selection": "A budget director weighs implementation cost against funding benefit, a different lens than a student focused on access.",
    }
    payload.update(overrides)
    return json.dumps(payload)


class ScriptedLLM:
    def __init__(self, response):
        self.response = response
        self.call_count = 0
        self.prompts = []

    async def __call__(self, system_prompt, user_prompt, model):
        self.prompts.append(user_prompt)
        self.call_count += 1
        return self.response


@pytest.fixture
def repo():
    return LessonRepository(db=FakeFirestoreClient())


# ---------------------------------------------------------------------------
# Grounding
# ---------------------------------------------------------------------------

def test_ground_persona_draft_accepts_valid_response():
    draft = ground_persona_draft(_persona_response(), known_section_ids={"section-4", "section-8", "section-6"})
    assert draft.role == "School district budget director"
    assert draft.section_ids == ["section-8"]


def test_ground_persona_draft_filters_unknown_section_ids():
    raw = _persona_response(section_ids=["section-8", "section-999"])
    draft = ground_persona_draft(raw, known_section_ids={"section-8"})
    assert draft.section_ids == ["section-8"]


def test_ground_persona_draft_raises_when_no_valid_section_ids_remain():
    raw = _persona_response(section_ids=["section-999"])
    with pytest.raises(DynamicPersonaGenerationError):
        ground_persona_draft(raw, known_section_ids={"section-8"})


def test_ground_persona_draft_rejects_malformed_json():
    with pytest.raises(DynamicPersonaGenerationError):
        ground_persona_draft("not json", known_section_ids={"section-8"})


# ---------------------------------------------------------------------------
# persona_prompt formatting -- the entire integration surface with
# chains/debater_chain.py's existing (unmodified) extraction logic
# ---------------------------------------------------------------------------

def test_build_persona_prompt_starts_with_the_marker_debater_chain_extracts():
    draft = ground_persona_draft(_persona_response(), known_section_ids={"section-8"})
    prompt = build_persona_prompt(draft)
    assert prompt.startswith(PERSONA_INSTRUCTIONS_MARKER)


def test_build_persona_prompt_never_contains_a_truncation_marker():
    draft = ground_persona_draft(_persona_response(), known_section_ids={"section-8"})
    prompt = build_persona_prompt(draft)
    for marker in _TRUNCATION_MARKERS:
        assert marker not in prompt


def test_build_persona_prompt_includes_role_and_position():
    draft = ground_persona_draft(_persona_response(), known_section_ids={"section-8"})
    prompt = build_persona_prompt(draft)
    assert "School district budget director" in prompt
    assert "Cautiously supportive" in prompt


def test_build_persona_prompt_instructs_respectful_challenge():
    draft = ground_persona_draft(_persona_response(), known_section_ids={"section-8"})
    prompt = build_persona_prompt(draft)
    assert "respectfully" in prompt.lower()
    assert "never" in prompt.lower()  # "never with hostility"


# ---------------------------------------------------------------------------
# End-to-end generation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_generate_persona_with_student_context(repo):
    repo.create_lesson(_lesson())
    llm = ScriptedLLM(_persona_response())
    service = DynamicPersonaGenerationService(repository=repo, llm_call=llm)

    student = PersonaProfile(user_id="student-1", occupation="Student", state="CA", age_range="Under 18")
    persona = await service.generate_persona(LESSON_ID, student_persona=student)

    assert isinstance(persona, DynamicPersona)
    assert persona.role == "School district budget director"
    assert persona.persona_prompt.startswith(PERSONA_INSTRUCTIONS_MARKER)
    assert "CA" in llm.prompts[0]  # student context reached the prompt


@pytest.mark.asyncio
async def test_generate_persona_without_student_context_skips_demographics(repo):
    repo.create_lesson(_lesson())
    llm = ScriptedLLM(_persona_response())
    service = DynamicPersonaGenerationService(repository=repo, llm_call=llm)

    persona = await service.generate_persona(LESSON_ID, student_persona=None)

    assert isinstance(persona, DynamicPersona)
    assert "No student context was provided" in llm.prompts[0]
    assert "do not assume any demographic details" in llm.prompts[0]


@pytest.mark.asyncio
async def test_generate_persona_persists(repo):
    repo.create_lesson(_lesson())
    llm = ScriptedLLM(_persona_response())
    service = DynamicPersonaGenerationService(repository=repo, llm_call=llm)

    persona = await service.generate_persona(LESSON_ID)
    fetched = repo.get_dynamic_persona(persona.persona_id)
    assert fetched == persona


@pytest.mark.asyncio
async def test_generate_persona_raises_for_unknown_lesson(repo):
    service = DynamicPersonaGenerationService(repository=repo, llm_call=ScriptedLLM("{}"))
    with pytest.raises(DynamicPersonaGenerationError):
        await service.generate_persona("no-such-lesson")


@pytest.mark.asyncio
async def test_generate_persona_raises_when_no_content(repo):
    repo.create_lesson(_lesson(stakeholders=[], con_arguments=[], pro_arguments=[], major_provisions=[]))
    service = DynamicPersonaGenerationService(repository=repo, llm_call=ScriptedLLM("{}"))
    with pytest.raises(DynamicPersonaGenerationError):
        await service.generate_persona(LESSON_ID)


@pytest.mark.asyncio
async def test_generate_persona_grounding_across_multiple_calls(repo):
    # Simulates "inspect at least ten opponent claims" -- every persona's
    # section_ids must be a subset of the lesson's own grounded facts.
    repo.create_lesson(_lesson())
    known_ids = {"section-4", "section-6", "section-8"}
    llm = ScriptedLLM(_persona_response())
    service = DynamicPersonaGenerationService(repository=repo, llm_call=llm)

    for i in range(10):
        student = PersonaProfile(user_id=f"student-{i}", occupation="student")
        persona = await service.generate_persona(LESSON_ID, student_persona=student)
        assert set(persona.section_ids).issubset(known_ids)
        assert len(persona.section_ids) >= 1


# ---------------------------------------------------------------------------
# Socratic hints (learning mode)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_generate_socratic_hint_returns_stripped_text():
    persona = DynamicPersona(
        persona_id="p1", lesson_id=LESSON_ID, role="Budget director",
        location_context="context", interests=["x"], likely_concerns=["y"],
        position="cautious", section_ids=["section-8"], reason_for_selection="r",
        persona_prompt="PERSONA INSTRUCTIONS:\nx",
    )
    llm = ScriptedLLM("  What assumption is your argument relying on?  \n")
    hint = await generate_socratic_hint(persona, "some transcript", llm_call=llm)
    assert hint == "What assumption is your argument relying on?"


@pytest.mark.asyncio
async def test_generate_socratic_hint_prompt_includes_persona_and_transcript():
    persona = DynamicPersona(
        persona_id="p1", lesson_id=LESSON_ID, role="Budget director",
        location_context="context", interests=["x"], likely_concerns=["y"],
        position="cautious", section_ids=["section-8"], reason_for_selection="r",
        persona_prompt="PERSONA INSTRUCTIONS:\nx",
    )
    llm = ScriptedLLM("A question?")
    await generate_socratic_hint(persona, "Pro: funding is good. Con: costs too much.", llm_call=llm)
    assert "Budget director" in llm.prompts[0]
    assert "costs too much" in llm.prompts[0]
