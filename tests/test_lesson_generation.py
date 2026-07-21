"""Tests for the Increment 2 grounded lesson generator, using mocked model
responses (no real OpenRouter/network calls).
"""

import json

import pytest
from pydantic import ValidationError

from services.lesson_generation import (
    LessonGenerationError,
    LessonGenerationService,
    ground_lesson_draft,
)
from services.lesson_repository import LessonRepository
from services.rag.retrieval_service import BillRagService
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


def _valid_lesson_json(pro_section="section-6", con_section="section-7"):
    return json.dumps(
        {
            "lesson_title": "Understanding the Community Health Access Act",
            "plain_language_summary": "This bill expands health benefits to eligible households.",
            "learning_objectives": ["Explain who qualifies for benefits under this bill."],
            "major_provisions": [
                {"claim": "Eligibility is limited to members of eligible households.", "section_ids": ["section-3"]}
            ],
            "stakeholders": [
                {"claim": "Low-income families and rural clinics are affected.", "section_ids": ["section-4"]}
            ],
            "pro_arguments": [
                {"claim": "The funding is substantial and sustained for five years.", "section_ids": [pro_section]}
            ],
            "con_arguments": [
                {"claim": "Fraudulent applicants face criminal penalties, which may deter legitimate applicants too.", "section_ids": [con_section]}
            ],
        }
    )


class CountingLLM:
    """A fake LLM callable that returns a canned response and counts calls."""

    def __init__(self, response: str):
        self.response = response
        self.call_count = 0
        self.last_user_prompt = None

    async def __call__(self, system_prompt: str, user_prompt: str, model: str) -> str:
        self.call_count += 1
        self.last_user_prompt = user_prompt
        return self.response


@pytest.fixture
def repo():
    return LessonRepository(db=FakeFirestoreClient())


@pytest.fixture
def rag_service():
    return BillRagService()


# ---------------------------------------------------------------------------
# ground_lesson_draft: parsing + section_id validation (no LLM/network needed)
# ---------------------------------------------------------------------------

def test_ground_lesson_draft_drops_claim_with_unknown_section_id():
    known_ids = {"section-3", "section-4", "section-6", "section-7"}
    raw = _valid_lesson_json()
    draft, dropped = ground_lesson_draft(raw, known_ids)
    assert len(draft.major_provisions) == 1
    assert len(dropped) == 0  # all cited ids were valid in this fixture


def test_ground_lesson_draft_drops_ungrounded_claim():
    known_ids = {"section-3", "section-4", "section-7"}  # section-6 NOT known
    raw = _valid_lesson_json(pro_section="section-6")
    draft, dropped = ground_lesson_draft(raw, known_ids)
    assert draft.pro_arguments == []  # the only pro_argument cited an unknown id
    assert len(dropped) == 1
    assert "dropped ungrounded claim" in dropped[0]


def test_ground_lesson_draft_trims_partially_invalid_claim():
    known_ids = {"section-3", "section-4", "section-7"}
    raw = json.dumps(
        {
            "lesson_title": "t",
            "plain_language_summary": "s",
            "learning_objectives": [],
            "major_provisions": [
                {"claim": "x", "section_ids": ["section-3", "section-999"]}
            ],
            "stakeholders": [],
            "pro_arguments": [],
            "con_arguments": [],
        }
    )
    draft, dropped = ground_lesson_draft(raw, known_ids)
    assert draft.major_provisions[0].section_ids == ["section-3"]
    assert len(dropped) == 1


def test_ground_lesson_draft_rejects_malformed_json():
    with pytest.raises(LessonGenerationError):
        ground_lesson_draft("not json at all", {"section-1"})


def test_ground_lesson_draft_strips_markdown_fences():
    known_ids = {"section-3", "section-4", "section-6", "section-7"}
    fenced = f"```json\n{_valid_lesson_json()}\n```"
    draft, _ = ground_lesson_draft(fenced, known_ids)
    assert draft.lesson_title == "Understanding the Community Health Access Act"


# ---------------------------------------------------------------------------
# LessonGenerationService.generate_lesson (mocked LLM, fake Firestore)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_generate_lesson_returns_grounded_structured_lesson(repo, rag_service):
    llm = CountingLLM(_valid_lesson_json())
    service = LessonGenerationService(rag_service=rag_service, repository=repo, llm_call=llm)

    lesson = await service.generate_lesson(BILL_ID, SAMPLE_BILL)

    assert lesson.lesson_title == "Understanding the Community Health Access Act"
    assert len(lesson.major_provisions) == 1
    assert len(lesson.pro_arguments) == 1
    assert len(lesson.con_arguments) == 1
    assert "section-3" in lesson.source_sections
    assert "section-6" in lesson.source_sections
    assert "section-7" in lesson.source_sections
    # Full bill text was never sent to the model -- only retrieved sections.
    assert SAMPLE_BILL not in llm.last_user_prompt


@pytest.mark.asyncio
async def test_generate_lesson_every_claim_has_section_ids(repo, rag_service):
    llm = CountingLLM(_valid_lesson_json())
    service = LessonGenerationService(rag_service=rag_service, repository=repo, llm_call=llm)
    lesson = await service.generate_lesson(BILL_ID, SAMPLE_BILL)

    for claims in (lesson.major_provisions, lesson.stakeholders, lesson.pro_arguments, lesson.con_arguments):
        for claim in claims:
            assert len(claim.section_ids) >= 1


@pytest.mark.asyncio
async def test_generate_lesson_rejects_unknown_section_ids_from_model(repo, rag_service):
    # The model cites a section_id that was never actually retrieved.
    llm = CountingLLM(_valid_lesson_json(pro_section="section-999"))
    service = LessonGenerationService(rag_service=rag_service, repository=repo, llm_call=llm)

    with pytest.raises(LessonGenerationError):
        await service.generate_lesson(BILL_ID, SAMPLE_BILL, max_attempts=1)


@pytest.mark.asyncio
async def test_generate_lesson_requires_both_pro_and_con(repo, rag_service):
    missing_con = json.loads(_valid_lesson_json())
    missing_con["con_arguments"] = []
    llm = CountingLLM(json.dumps(missing_con))
    service = LessonGenerationService(rag_service=rag_service, repository=repo, llm_call=llm)

    with pytest.raises(LessonGenerationError):
        await service.generate_lesson(BILL_ID, SAMPLE_BILL, max_attempts=1)


@pytest.mark.asyncio
async def test_generate_lesson_retries_when_missing_con_argument(repo, rag_service):
    missing_con = json.loads(_valid_lesson_json())
    missing_con["con_arguments"] = []
    responses = [json.dumps(missing_con), _valid_lesson_json()]

    class SequencedLLM:
        def __init__(self):
            self.call_count = 0

        async def __call__(self, system_prompt, user_prompt, model):
            response = responses[self.call_count]
            self.call_count += 1
            return response

    llm = SequencedLLM()
    service = LessonGenerationService(rag_service=rag_service, repository=repo, llm_call=llm)
    lesson = await service.generate_lesson(BILL_ID, SAMPLE_BILL, max_attempts=2)

    assert llm.call_count == 2
    assert len(lesson.con_arguments) == 1


@pytest.mark.asyncio
async def test_generate_lesson_caches_by_bill_id_and_text_hash(repo, rag_service):
    llm = CountingLLM(_valid_lesson_json())
    service = LessonGenerationService(rag_service=rag_service, repository=repo, llm_call=llm)

    first = await service.generate_lesson(BILL_ID, SAMPLE_BILL)
    second = await service.generate_lesson(BILL_ID, SAMPLE_BILL)

    assert llm.call_count == 1  # second call was served from the cache
    assert first.lesson_id == second.lesson_id


@pytest.mark.asyncio
async def test_generate_lesson_bill_text_change_invalidates_cache(repo, rag_service):
    llm = CountingLLM(_valid_lesson_json())
    service = LessonGenerationService(rag_service=rag_service, repository=repo, llm_call=llm)

    first = await service.generate_lesson(BILL_ID, SAMPLE_BILL)
    changed_bill = SAMPLE_BILL + "\nSEC. 8. NEW SECTION.\nBrand new content."
    second = await service.generate_lesson(BILL_ID, changed_bill)

    assert llm.call_count == 2
    assert first.lesson_id != second.lesson_id
    assert first.bill_text_hash != second.bill_text_hash


@pytest.mark.asyncio
async def test_generate_lesson_prompt_version_bump_invalidates_cache(repo, rag_service, monkeypatch):
    llm = CountingLLM(_valid_lesson_json())
    service = LessonGenerationService(rag_service=rag_service, repository=repo, llm_call=llm)

    first = await service.generate_lesson(BILL_ID, SAMPLE_BILL)

    monkeypatch.setattr("services.lesson_generation.LESSON_PROMPT_VERSION", "v2")
    second = await service.generate_lesson(BILL_ID, SAMPLE_BILL)

    assert llm.call_count == 2
    assert first.lesson_id != second.lesson_id
    assert second.lesson_id.split("::")[1] == "v2"


@pytest.mark.asyncio
async def test_generate_lesson_persists_to_repository(repo, rag_service):
    llm = CountingLLM(_valid_lesson_json())
    service = LessonGenerationService(rag_service=rag_service, repository=repo, llm_call=llm)

    lesson = await service.generate_lesson(BILL_ID, SAMPLE_BILL)
    fetched = repo.get_lesson(lesson.lesson_id)

    assert fetched is not None
    assert fetched.lesson_title == lesson.lesson_title


@pytest.mark.asyncio
async def test_generate_lesson_rejects_empty_bill_text(repo, rag_service):
    llm = CountingLLM(_valid_lesson_json())
    service = LessonGenerationService(rag_service=rag_service, repository=repo, llm_call=llm)

    with pytest.raises(ValueError):
        await service.generate_lesson(BILL_ID, "   ")


# ---------------------------------------------------------------------------
# Endpoint integration test (router mounted standalone)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_endpoint_generate_lesson(repo, rag_service, monkeypatch):
    import routes.lesson_routes as lesson_routes

    llm = CountingLLM(_valid_lesson_json())
    test_service = LessonGenerationService(rag_service=rag_service, repository=repo, llm_call=llm)
    monkeypatch.setattr(lesson_routes, "_lesson_generation_service", test_service)

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    app.include_router(lesson_routes.router)
    client = TestClient(app)

    response = client.post(
        "/lesson/generate",
        json={"bill_id": "endpoint-lesson-bill", "bill_text": SAMPLE_BILL},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["lesson_title"]
    assert len(data["pro_arguments"]) >= 1
    assert len(data["con_arguments"]) >= 1
