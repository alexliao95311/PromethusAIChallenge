"""Endpoint integration tests for the Increment 8 POST /lesson/personal-impact."""

import json

import pytest

from models.lesson_models import GroundedClaim, Lesson, PersonaProfile
from services.lesson_repository import LessonRepository
from services.persona_impact_generation import PersonaImpactGenerationService
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
        plain_language_summary="A bill expanding health benefits.",
        stakeholders=[GroundedClaim(claim="Affects families.", section_ids=["section-4"])],
        source_sections=["section-3", "section-4"],
    )


class FakeRag:
    def retrieve_relevant_sections(self, bill_id, query, top_k=4, bill_text=None):
        return [
            RetrievedSection(section_id="section-3", heading="Eligibility",
                             text="Eligible if in an eligible household.", order=0, similarity_score=0.9),
            RetrievedSection(section_id="section-4", heading="Impact",
                             text="Affects low-income families.", order=1, similarity_score=0.8),
        ]


def _impact_json():
    return json.dumps({
        "narrative": "Here is how this bill could affect someone like you.",
        "direct_impacts": [
            {"impact": "You may qualify.", "reasoning": "Income-based eligibility.",
             "section_ids": ["section-3"], "confidence": "medium"}
        ],
        "possible_indirect_impacts": [
            {"impact": "Clinics may adjust.", "reasoning": "Behavioral.",
             "section_ids": ["section-4"], "confidence": "low"}
        ],
        "uncertainties": ["Your eligibility depends on details not given."],
        "questions_to_consider": ["Do you use a clinic?"],
        "confidence": "medium",
    })


class ScriptedLLM:
    def __init__(self, response):
        self.response = response
        self.call_count = 0

    async def __call__(self, system_prompt, user_prompt, model):
        self.call_count += 1
        return self.response


@pytest.fixture
def repo():
    return LessonRepository(db=FakeFirestoreClient())


@pytest.fixture
def client_factory(repo, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    import routes.lesson_routes as lesson_routes
    from services.auth import get_current_user_id
    from services.lesson_generation import LessonGenerationService
    from services.persona_service import PersonaService

    # Route handlers read the lesson through _lesson_generation_service.repository,
    # so point both services at the same fake-backed repo.
    monkeypatch.setattr(
        lesson_routes, "_lesson_generation_service", LessonGenerationService(repository=repo)
    )
    monkeypatch.setattr(lesson_routes, "_persona_service", PersonaService(repository=repo))

    def _make(user_id=None, llm=None):
        monkeypatch.setattr(
            lesson_routes,
            "_persona_impact_service",
            PersonaImpactGenerationService(
                rag_service=FakeRag(), repository=repo, llm_call=llm or ScriptedLLM(_impact_json())
            ),
        )
        app = FastAPI()
        app.include_router(lesson_routes.router)
        if user_id is not None:
            app.dependency_overrides[get_current_user_id] = lambda: user_id
        return TestClient(app)

    return _make


def test_requires_auth(repo, client_factory):
    repo.create_lesson(_lesson())
    client = client_factory()  # no user override
    resp = client.post("/lesson/personal-impact", json={"lesson_id": LESSON_ID, "bill_text": "x"})
    assert resp.status_code == 401


def test_unknown_lesson_returns_404(client_factory):
    client = client_factory(user_id="u1")
    resp = client.post(
        "/lesson/personal-impact",
        json={"lesson_id": "no-such-lesson", "persona": {"occupation": "Nurse"}},
    )
    assert resp.status_code == 404


def test_no_persona_available_returns_400(repo, client_factory):
    repo.create_lesson(_lesson())
    client = client_factory(user_id="u1")  # user has no saved persona, none inline
    resp = client.post("/lesson/personal-impact", json={"lesson_id": LESSON_ID, "bill_text": "x"})
    assert resp.status_code == 400


def test_inline_persona_generates_narrative(repo, client_factory):
    repo.create_lesson(_lesson())
    client = client_factory(user_id="u1")
    resp = client.post(
        "/lesson/personal-impact",
        json={"lesson_id": LESSON_ID, "bill_text": "x",
              "persona": {"occupation": "Nurse", "state": "ca"}},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["narrative"]
    assert data["direct_impacts"][0]["section_ids"] == ["section-3"]
    assert data["confidence"] in {"low", "medium", "high"}
    assert data["persona"]["attributes"]["state"] == "CA"
    assert data["persona"]["is_fictional"] is True
    # Persisted under the authenticated uid.
    narrative = repo.get_personal_impact_narrative(data["impact_id"])
    assert narrative is not None and narrative.user_id == "u1"


def test_saved_persona_used_when_no_inline(repo, client_factory):
    repo.create_lesson(_lesson())
    repo.upsert_persona_profile(PersonaProfile(user_id="u1", occupation="Teacher", state="NY"))
    client = client_factory(user_id="u1")
    resp = client.post("/lesson/personal-impact", json={"lesson_id": LESSON_ID, "bill_text": "x"})
    assert resp.status_code == 200
    assert resp.json()["persona"]["attributes"]["occupation"] == "Teacher"


def test_invalid_inline_persona_returns_422(repo, client_factory):
    repo.create_lesson(_lesson())
    client = client_factory(user_id="u1")
    resp = client.post(
        "/lesson/personal-impact",
        json={"lesson_id": LESSON_ID, "bill_text": "x", "persona": {"state": "Atlantis"}},
    )
    assert resp.status_code == 422


def test_response_omits_no_grounding_and_validates_sections(repo, client_factory):
    repo.create_lesson(_lesson())
    bad = json.loads(_impact_json())
    bad["direct_impacts"][0]["section_ids"] = ["section-999"]  # never retrieved
    client = client_factory(user_id="u1", llm=ScriptedLLM(json.dumps(bad)))
    resp = client.post(
        "/lesson/personal-impact",
        json={"lesson_id": LESSON_ID, "bill_text": "x", "persona": {"occupation": "Nurse"}},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "section-999" not in data["section_ids"]
    assert data["direct_impacts"] == []  # ungrounded direct impact dropped
    assert data["confidence"] != "high"  # capped with no direct impact
