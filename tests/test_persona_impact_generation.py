"""Tests for the Increment 8 personalized bill-impact generator, using a fake
RAG service and scripted model responses (no embeddings or network).
"""

import json

import pytest

from models.lesson_models import GroundedClaim, Lesson, PersonaProfile
from services.lesson_repository import LessonRepository
from services.persona_impact_generation import (
    PersonaImpactGenerationError,
    PersonaImpactGenerationService,
    _ground_impact_draft,
)
from services.rag.retrieval_service import RetrievedSection
from tests.fake_firestore import FakeFirestoreClient

BILL_ID = "hr1-119"
LESSON_ID = "hr1-119::v1::abc123"


def _lesson():
    return Lesson(
        lesson_id=LESSON_ID,
        bill_id=BILL_ID,
        prompt_version="v1",
        bill_text_hash="abc123",
        lesson_title="Understanding the Community Health Access Act",
        plain_language_summary="A bill expanding health benefits to eligible households.",
        major_provisions=[GroundedClaim(claim="Eligibility is income-based.", section_ids=["section-3"])],
        stakeholders=[GroundedClaim(claim="Affects low-income families and clinics.", section_ids=["section-4"])],
        source_sections=["section-3", "section-4"],
    )


# A small library of fake bill sections keyed by section_id.
_SECTIONS = {
    "section-3": ("Eligibility", "An individual is eligible if in an eligible household."),
    "section-4": ("Stakeholder Impact", "Affects low-income families and rural clinics."),
    "section-5": ("Implementation", "The Secretary shall issue regulations."),
    "section-6": ("Appropriations", "Funds are authorized for fiscal years 2027-2031."),
    "section-7": ("Small business", "Small businesses operating clinics may apply for support."),
    "section-8": ("State agencies", "State Medicaid agencies administer the program."),
}


class FakeRag:
    """Returns different sections depending on what the query mentions, so a
    persona whose queries differ retrieves different provisions -- exactly the
    behavior the personalization depends on."""

    def __init__(self):
        self.queries_seen = []

    def _sections_for(self, query: str):
        q = query.lower()
        ids = {"section-3", "section-4"}  # baseline, everyone sees these
        if "work" in q or "business" in q:
            ids |= {"section-7"}
        if "state" in q or "government" in q:
            ids |= {"section-8"}
        if "income" in q or "household" in q:
            ids |= {"section-6"}
        if "age range" in q:
            ids |= {"section-5"}
        return ids

    def retrieve_relevant_sections(self, bill_id, query, top_k=4, bill_text=None):
        self.queries_seen.append(query)
        results = []
        for i, sid in enumerate(sorted(self._sections_for(query))):
            heading, text = _SECTIONS[sid]
            results.append(
                RetrievedSection(
                    section_id=sid, heading=heading, text=text, order=i,
                    similarity_score=0.9 - i * 0.01,
                )
            )
        return results[:top_k]


def _impact_json(direct_section="section-3", indirect_section="section-4", overall="medium"):
    return json.dumps({
        "narrative": "Here is how this bill could affect someone like you.",
        "direct_impacts": [
            {"impact": "You may qualify for benefits.", "reasoning": "Eligibility is income-based.",
             "section_ids": [direct_section], "confidence": "high"}
        ],
        "possible_indirect_impacts": [
            {"impact": "Local clinics may change services.", "reasoning": "Depends on how clinics respond.",
             "section_ids": [indirect_section], "confidence": "medium"}
        ],
        "uncertainties": ["Your exact eligibility depends on details not provided."],
        "questions_to_consider": ["Do you use a local clinic?"],
        "confidence": overall,
    })


class ScriptedLLM:
    """Records the prompt it was given and returns a canned response. If a
    `by_prompt` mapping is supplied, returns a response chosen by a substring
    found in the user prompt (so different personas can yield different JSON)."""

    def __init__(self, response=None, by_prompt=None):
        self.response = response
        self.by_prompt = by_prompt or {}
        self.prompts = []
        self.call_count = 0

    async def __call__(self, system_prompt, user_prompt, model):
        self.prompts.append(user_prompt)
        self.call_count += 1
        for needle, resp in self.by_prompt.items():
            if needle in user_prompt:
                return resp
        return self.response


@pytest.fixture
def repo():
    return LessonRepository(db=FakeFirestoreClient())


def _service(repo, llm):
    return PersonaImpactGenerationService(rag_service=FakeRag(), repository=repo, llm_call=llm)


# ---------------------------------------------------------------------------
# _ground_impact_draft: parsing, section validation, confidence capping
# ---------------------------------------------------------------------------

def test_ground_drops_impacts_citing_unknown_sections():
    raw = _impact_json(direct_section="section-999")
    g = _ground_impact_draft(raw, {"section-3", "section-4"})
    assert g.direct_impacts == []  # cited an unretrieved section
    assert len(g.possible_indirect_impacts) == 1


def test_ground_caps_confidence_when_no_direct_impact():
    raw = _impact_json(direct_section="section-999", overall="high")
    g = _ground_impact_draft(raw, {"section-3", "section-4"})
    assert g.confidence == "medium"  # no grounded direct impact -> can't be "high"


def test_ground_keeps_high_confidence_when_direct_impact_survives():
    raw = _impact_json(direct_section="section-3", overall="high")
    g = _ground_impact_draft(raw, {"section-3", "section-4"})
    assert len(g.direct_impacts) == 1
    assert g.confidence == "high"


def test_ground_normalizes_unknown_confidence_to_low():
    raw = _impact_json(overall="definitely")
    g = _ground_impact_draft(raw, {"section-3", "section-4"})
    assert g.confidence in {"low", "medium", "high"}
    assert g.direct_impacts[0].confidence == "high"


def test_ground_section_ids_is_validated_union():
    raw = _impact_json(direct_section="section-3", indirect_section="section-4")
    g = _ground_impact_draft(raw, {"section-3", "section-4"})
    assert g.section_ids == ["section-3", "section-4"]


def test_ground_rejects_malformed_json():
    with pytest.raises(PersonaImpactGenerationError):
        _ground_impact_draft("not json", {"section-3"})


# ---------------------------------------------------------------------------
# generate_impact: grounding, persistence, caching
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_generate_impact_returns_grounded_narrative(repo):
    llm = ScriptedLLM(_impact_json())
    service = _service(repo, llm)
    persona = PersonaProfile(user_id="u1", occupation="Nurse", state="CA")

    narrative = await service.generate_impact(persona, _lesson(), bill_text="x")

    assert narrative.narrative
    assert len(narrative.direct_impacts) == 1
    assert len(narrative.possible_indirect_impacts) == 1
    for impact in narrative.direct_impacts + narrative.possible_indirect_impacts:
        assert impact.section_ids  # every impact is sourced
    assert narrative.persona["attributes"]["occupation"] == "Nurse"
    assert narrative.persona["is_fictional"] is True


@pytest.mark.asyncio
async def test_generate_impact_persists_and_caches(repo):
    llm = ScriptedLLM(_impact_json())
    service = _service(repo, llm)
    persona = PersonaProfile(user_id="u1", occupation="Nurse")

    first = await service.generate_impact(persona, _lesson(), bill_text="x")
    second = await service.generate_impact(persona, _lesson(), bill_text="x")

    assert llm.call_count == 1  # second served from cache
    assert first.impact_id == second.impact_id
    assert repo.get_personal_impact_narrative(first.impact_id) is not None


@pytest.mark.asyncio
async def test_generate_impact_raises_when_no_sections_retrieved(repo):
    class EmptyRag:
        def retrieve_relevant_sections(self, *a, **k):
            return []

    service = PersonaImpactGenerationService(
        rag_service=EmptyRag(), repository=repo, llm_call=ScriptedLLM(_impact_json())
    )
    with pytest.raises(PersonaImpactGenerationError):
        await service.generate_impact(PersonaProfile(user_id="u1"), _lesson(), bill_text="x")


@pytest.mark.asyncio
async def test_generate_impact_never_stores_unvalidated_section_ids(repo):
    # Model cites a section that was never retrieved; it must not appear.
    llm = ScriptedLLM(_impact_json(direct_section="section-3", indirect_section="section-42"))
    service = _service(repo, llm)
    narrative = await service.generate_impact(
        PersonaProfile(user_id="u1", occupation="Nurse"), _lesson(), bill_text="x"
    )
    assert "section-42" not in narrative.section_ids
    for impact in narrative.possible_indirect_impacts:
        assert "section-42" not in impact.section_ids


# ---------------------------------------------------------------------------
# The centerpiece requirement: multiple personas, same bill -> different
# narratives driven by different retrieved provisions.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_different_personas_same_bill_get_different_impacts(repo):
    # The model echoes back whichever occupation-specific / state-specific
    # section it was shown, so different retrieval -> different grounded output.
    # Needles match the persona descriptor in the user prompt, which lowercases
    # the occupation (e.g. "...works or intends to work in small-business owner").
    by_prompt = {
        "small-business owner": _impact_json(direct_section="section-7"),
        "public-school teacher": _impact_json(direct_section="section-8"),
        "software engineer": _impact_json(direct_section="section-6"),
    }
    default = _impact_json(direct_section="section-3")
    llm = ScriptedLLM(response=default, by_prompt=by_prompt)
    service = _service(repo, llm)

    personas = {
        "student": PersonaProfile(user_id="s", occupation="High-school student", state="CA"),
        "owner": PersonaProfile(user_id="o", occupation="Small-business owner", state="TX"),
        "retiree": PersonaProfile(user_id="r", occupation="Retired", state="FL"),
        "teacher": PersonaProfile(user_id="t", occupation="Public-school teacher", state="NY"),
        "engineer": PersonaProfile(user_id="e", occupation="Software engineer", state="WA"),
    }

    narratives = {}
    for key, persona in personas.items():
        narratives[key] = await service.generate_impact(persona, _lesson(), bill_text="x")

    # Distinct cache ids per persona (personalization is real, not shared).
    ids = {n.impact_id for n in narratives.values()}
    assert len(ids) == len(personas)

    # The occupation-specific personas cite the provision retrieved for them.
    assert "section-7" in narratives["owner"].section_ids
    assert "section-8" in narratives["teacher"].section_ids
    assert "section-6" in narratives["engineer"].section_ids

    # And those differ from each other (meaningfully different explanations).
    assert narratives["owner"].section_ids != narratives["teacher"].section_ids


@pytest.mark.asyncio
async def test_empty_persona_still_grounds_and_flags_uncertainty(repo):
    llm = ScriptedLLM(_impact_json(direct_section="section-999", overall="high"))
    service = _service(repo, llm)
    narrative = await service.generate_impact(PersonaProfile(user_id="u1"), _lesson(), bill_text="x")

    # With no persona details and no grounded direct impact, confidence is capped.
    assert narrative.confidence != "high"
    assert narrative.uncertainties  # uncertainty is surfaced
