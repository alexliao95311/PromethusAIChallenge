"""Tests for the Increment 3 vocabulary generator, using mocked model
responses (no real OpenRouter/network calls).
"""

import json

import pytest

from services.lesson_repository import LessonRepository
from services.rag.retrieval_service import BillRagService
from services.vocabulary_generation import (
    MAX_CARDS,
    MAX_DEFINITION_LENGTH,
    VocabularyGenerationError,
    VocabularyGenerationService,
    ground_vocabulary_draft,
)
from tests.fake_firestore import FakeFirestoreClient

SAMPLE_BILL = """
SECTION 1. SHORT TITLE.
This Act may be cited as the "Community Health Access Act".

SEC. 2. DEFINITIONS.
In this Act, the term "eligible household" means a household with income at
or below 200 percent of the Federal poverty line.

SEC. 3. ELIGIBILITY REQUIREMENTS.
An individual is eligible for benefits under this Act if the individual is a
member of an eligible household and resides in a participating State.

SEC. 4. STAKEHOLDER IMPACT.
This Act primarily affects low-income families, small businesses operating
rural health clinics, and State Medicaid agencies.

SEC. 5. IMPLEMENTATION.
Not later than 1 year after the date of enactment of this Act, the
Secretary shall issue regulations to carry out this Act.

SEC. 6. AUTHORIZATION OF APPROPRIATIONS.
There is authorized to be appropriated to carry out this Act $500,000,000
for each of fiscal years 2027 through 2031.

SEC. 7. PENALTIES.
Any person who knowingly submits a fraudulent application for benefits
under this Act shall be fined under title 18, United States Code.
"""

BILL_ID = "hr1-119"
LESSON_ID = "hr1-119::v1::abc123"
KNOWN_IDS = {"section-1", "section-2", "section-3", "section-4", "section-5", "section-6", "section-7"}


def _card(term, section_id="section-3", difficulty="intermediate", definition="A short plain-language definition."):
    return {
        "term": term,
        "simple_definition": definition,
        "bill_context": f"This term is used in {section_id} of the bill.",
        "example": "For example, a family of four earning below the threshold would qualify.",
        "section_id": section_id,
        "difficulty": difficulty,
    }


def _vocab_json(cards):
    return json.dumps({"vocabulary": cards})


class CountingLLM:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.call_count = 0
        self.prompts = []

    async def __call__(self, system_prompt, user_prompt, model):
        self.prompts.append(user_prompt)
        response = self.responses[min(self.call_count, len(self.responses) - 1)]
        self.call_count += 1
        return response


@pytest.fixture
def repo():
    return LessonRepository(db=FakeFirestoreClient())


@pytest.fixture
def rag_service():
    return BillRagService()


# ---------------------------------------------------------------------------
# ground_vocabulary_draft: parsing + validation (no LLM/network needed)
# ---------------------------------------------------------------------------

def test_ground_vocabulary_draft_accepts_valid_cards():
    raw = _vocab_json([_card("eligible household", "section-2"), _card("appropriation", "section-6")])
    cards, invalid = ground_vocabulary_draft(raw, KNOWN_IDS, LESSON_ID)
    assert len(cards) == 2
    assert invalid == []
    assert cards[0].card_id == f"{LESSON_ID}-vocab-1"
    assert cards[1].card_id == f"{LESSON_ID}-vocab-2"


def test_ground_vocabulary_draft_rejects_unknown_section_id():
    raw = _vocab_json([_card("eligible household", "section-999")])
    cards, invalid = ground_vocabulary_draft(raw, KNOWN_IDS, LESSON_ID)
    assert cards == []
    assert invalid == ["eligible household"]


def test_ground_vocabulary_draft_deduplicates_case_insensitively():
    raw = _vocab_json([
        _card("Eligible Household", "section-2"),
        _card("eligible household", "section-3"),
        _card("ELIGIBLE HOUSEHOLD", "section-4"),
    ])
    cards, invalid = ground_vocabulary_draft(raw, KNOWN_IDS, LESSON_ID)
    assert len(cards) == 1
    assert cards[0].term == "Eligible Household"


def test_ground_vocabulary_draft_dedup_against_existing_terms():
    raw = _vocab_json([_card("Appropriation", "section-6")])
    cards, invalid = ground_vocabulary_draft(
        raw, KNOWN_IDS, LESSON_ID, existing_terms_lower={"appropriation"}
    )
    assert cards == []


def test_ground_vocabulary_draft_rejects_section_number_as_term():
    raw = _vocab_json([_card("Section 3", "section-3"), _card("SEC. 6.", "section-6")])
    cards, invalid = ground_vocabulary_draft(raw, KNOWN_IDS, LESSON_ID)
    assert cards == []
    assert set(invalid) == {"Section 3", "SEC. 6."}


def test_ground_vocabulary_draft_rejects_pure_numeric_term():
    raw = _vocab_json([_card("500000000", "section-6")])
    cards, invalid = ground_vocabulary_draft(raw, KNOWN_IDS, LESSON_ID)
    assert cards == []


def test_ground_vocabulary_draft_caps_definition_length():
    long_def = "x" * (MAX_DEFINITION_LENGTH + 100)
    raw = _vocab_json([_card("eligible household", "section-2", definition=long_def)])
    cards, _ = ground_vocabulary_draft(raw, KNOWN_IDS, LESSON_ID)
    assert len(cards[0].simple_definition) <= MAX_DEFINITION_LENGTH


def test_ground_vocabulary_draft_normalizes_invalid_difficulty():
    raw = _vocab_json([_card("eligible household", "section-2", difficulty="expert")])
    cards, _ = ground_vocabulary_draft(raw, KNOWN_IDS, LESSON_ID)
    assert cards[0].difficulty == "intermediate"


def test_ground_vocabulary_draft_caps_at_max_cards():
    cards_input = [_card(f"term-{i}", "section-3") for i in range(20)]
    raw = _vocab_json(cards_input)
    cards, _ = ground_vocabulary_draft(raw, KNOWN_IDS, LESSON_ID, max_cards=12)
    assert len(cards) == 12


def test_ground_vocabulary_draft_rejects_malformed_json():
    with pytest.raises(VocabularyGenerationError):
        ground_vocabulary_draft("not json", KNOWN_IDS, LESSON_ID)


def test_ground_vocabulary_draft_handles_empty_vocabulary_list():
    raw = _vocab_json([])
    cards, invalid = ground_vocabulary_draft(raw, KNOWN_IDS, LESSON_ID)
    assert cards == []
    assert invalid == []


# ---------------------------------------------------------------------------
# VocabularyGenerationService.generate_vocabulary (mocked LLM, fake Firestore)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_generate_vocabulary_returns_valid_cards(repo, rag_service):
    llm = CountingLLM(_vocab_json([
        _card("eligible household", "section-2"),
        _card("appropriation", "section-6"),
        _card("Secretary", "section-5"),
    ]))
    service = VocabularyGenerationService(rag_service=rag_service, repository=repo, llm_call=llm)
    cards = await service.generate_vocabulary(BILL_ID, LESSON_ID, SAMPLE_BILL)

    assert len(cards) == 3
    for card in cards:
        assert card.section_id in KNOWN_IDS
        assert card.lesson_id == LESSON_ID


@pytest.mark.asyncio
async def test_generate_vocabulary_persists_cards_with_lesson(repo, rag_service):
    llm = CountingLLM(_vocab_json([_card("eligible household", "section-2")]))
    service = VocabularyGenerationService(rag_service=rag_service, repository=repo, llm_call=llm)
    cards = await service.generate_vocabulary(BILL_ID, LESSON_ID, SAMPLE_BILL)

    fetched = repo.get_flashcard(cards[0].card_id)
    assert fetched is not None
    assert fetched.lesson_id == LESSON_ID


@pytest.mark.asyncio
async def test_generate_vocabulary_regenerates_invalid_cards(repo, rag_service):
    first_response = _vocab_json([
        _card("eligible household", "section-999"),  # invalid section_id
        _card("appropriation", "section-6"),  # valid
    ])
    regeneration_response = _vocab_json([_card("Secretary", "section-5")])
    llm = CountingLLM(first_response, regeneration_response)

    service = VocabularyGenerationService(rag_service=rag_service, repository=repo, llm_call=llm)
    cards = await service.generate_vocabulary(BILL_ID, LESSON_ID, SAMPLE_BILL)

    assert llm.call_count == 2  # initial + one regeneration call
    terms = {c.term for c in cards}
    assert "appropriation" in terms
    assert "Secretary" in terms
    assert "eligible household" not in terms  # never recovered, correctly dropped


@pytest.mark.asyncio
async def test_generate_vocabulary_returns_fewer_than_min_without_failing(repo, rag_service):
    llm = CountingLLM(_vocab_json([_card("eligible household", "section-2")]))
    service = VocabularyGenerationService(rag_service=rag_service, repository=repo, llm_call=llm)
    cards = await service.generate_vocabulary(BILL_ID, LESSON_ID, SAMPLE_BILL, min_cards=6)

    assert len(cards) == 1  # below min_cards, but no exception raised


@pytest.mark.asyncio
async def test_generate_vocabulary_rejects_empty_bill_text(repo, rag_service):
    llm = CountingLLM(_vocab_json([]))
    service = VocabularyGenerationService(rag_service=rag_service, repository=repo, llm_call=llm)
    with pytest.raises(ValueError):
        await service.generate_vocabulary(BILL_ID, LESSON_ID, "   ")


@pytest.mark.asyncio
async def test_generate_vocabulary_full_bill_never_sent_to_model(repo, rag_service):
    llm = CountingLLM(_vocab_json([_card("eligible household", "section-2")]))
    service = VocabularyGenerationService(rag_service=rag_service, repository=repo, llm_call=llm)
    await service.generate_vocabulary(BILL_ID, LESSON_ID, SAMPLE_BILL)
    assert SAMPLE_BILL not in llm.prompts[0]


# ---------------------------------------------------------------------------
# Endpoint integration test: /lesson/generate?include_vocabulary=true
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_endpoint_generate_lesson_with_vocabulary(repo, rag_service, monkeypatch):
    import routes.lesson_routes as lesson_routes
    from services.lesson_generation import LessonGenerationService

    lesson_llm = CountingLLM(json.dumps({
        "lesson_title": "Understanding the Bill",
        "plain_language_summary": "Summary.",
        "learning_objectives": ["Learn things."],
        "major_provisions": [{"claim": "x", "section_ids": ["section-3"]}],
        "stakeholders": [{"claim": "y", "section_ids": ["section-4"]}],
        "pro_arguments": [{"claim": "z", "section_ids": ["section-6"]}],
        "con_arguments": [{"claim": "w", "section_ids": ["section-7"]}],
    }))
    vocab_llm = CountingLLM(_vocab_json([_card("eligible household", "section-2")]))

    lesson_service = LessonGenerationService(rag_service=rag_service, repository=repo, llm_call=lesson_llm)
    vocab_service = VocabularyGenerationService(rag_service=rag_service, repository=repo, llm_call=vocab_llm)
    monkeypatch.setattr(lesson_routes, "_lesson_generation_service", lesson_service)
    monkeypatch.setattr(lesson_routes, "_vocabulary_generation_service", vocab_service)

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    app.include_router(lesson_routes.router)
    client = TestClient(app)

    response = client.post(
        "/lesson/generate",
        json={"bill_id": "vocab-endpoint-bill", "bill_text": SAMPLE_BILL, "include_vocabulary": True},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["lesson_title"] == "Understanding the Bill"
    assert data["vocabulary"] is not None
    assert len(data["vocabulary"]) == 1
    assert data["vocabulary"][0]["term"] == "eligible household"


@pytest.mark.asyncio
async def test_endpoint_generate_lesson_without_vocabulary_flag_omits_it(repo, rag_service, monkeypatch):
    import routes.lesson_routes as lesson_routes
    from services.lesson_generation import LessonGenerationService

    lesson_llm = CountingLLM(json.dumps({
        "lesson_title": "Understanding the Bill",
        "plain_language_summary": "Summary.",
        "learning_objectives": [],
        "major_provisions": [{"claim": "x", "section_ids": ["section-3"]}],
        "stakeholders": [{"claim": "y", "section_ids": ["section-4"]}],
        "pro_arguments": [{"claim": "z", "section_ids": ["section-6"]}],
        "con_arguments": [{"claim": "w", "section_ids": ["section-7"]}],
    }))
    lesson_service = LessonGenerationService(rag_service=rag_service, repository=repo, llm_call=lesson_llm)
    monkeypatch.setattr(lesson_routes, "_lesson_generation_service", lesson_service)

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    app.include_router(lesson_routes.router)
    client = TestClient(app)

    response = client.post(
        "/lesson/generate",
        json={"bill_id": "vocab-endpoint-bill-2", "bill_text": SAMPLE_BILL},
    )
    assert response.status_code == 200
    assert response.json()["vocabulary"] is None
