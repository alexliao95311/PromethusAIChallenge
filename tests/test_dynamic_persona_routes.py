"""Endpoint integration tests for Increment 9 dynamic persona routes."""

import json

import pytest

from models.lesson_models import GroundedClaim, Lesson
from services.dynamic_persona_generation import DynamicPersonaGenerationService
from services.lesson_repository import LessonRepository
from tests.fake_firestore import FakeFirestoreClient

LESSON_ID = "hr1-119::v1::abc123"


def _lesson():
    return Lesson(
        lesson_id=LESSON_ID,
        bill_id="hr1-119",
        prompt_version="v1",
        bill_text_hash="abc123",
        lesson_title="Understanding the Community Health Access Act",
        plain_language_summary="A bill expanding health benefits.",
        stakeholders=[GroundedClaim(claim="Rural clinics receive administrative funding support.", section_ids=["section-4"])],
        con_arguments=[GroundedClaim(claim="Compliance reporting could burden small clinics.", section_ids=["section-8"])],
    )


class ScriptedLLM:
    def __init__(self, response):
        self.response = response
        self.call_count = 0

    async def __call__(self, system_prompt, user_prompt, model):
        self.call_count += 1
        return self.response


def _persona_response():
    return json.dumps({
        "role": "School district budget director",
        "location_context": "overseeing a rural county's health-services budget",
        "interests": ["Predictable funding"],
        "likely_concerns": ["New compliance reporting could strain staff time"],
        "position": "Cautiously supportive but concerned about implementation costs",
        "section_ids": ["section-8"],
        "reason_for_selection": "A different lens on cost vs. benefit than a student focused on access.",
    })


@pytest.fixture
def repo():
    return LessonRepository(db=FakeFirestoreClient())


@pytest.fixture
def client_factory(repo, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    import routes.lesson_routes as lesson_routes
    from services.lesson_generation import LessonGenerationService

    monkeypatch.setattr(
        lesson_routes, "_lesson_generation_service", LessonGenerationService(repository=repo)
    )
    monkeypatch.setattr(
        lesson_routes,
        "_dynamic_persona_generation_service",
        DynamicPersonaGenerationService(repository=repo, llm_call=ScriptedLLM(_persona_response())),
    )

    def _make():
        app = FastAPI()
        app.include_router(lesson_routes.router)
        return TestClient(app)

    return _make


def test_endpoint_generate_persona_with_student_context(repo, client_factory):
    repo.create_lesson(_lesson())
    client = client_factory()

    resp = client.post(
        f"/lesson/{LESSON_ID}/debate-persona/generate",
        json={"student_persona": {"occupation": "Student", "state": "CA", "age_range": "Under 18"}},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["role"] == "School district budget director"
    assert data["persona_prompt"].startswith("PERSONA INSTRUCTIONS:")
    assert data["reason_for_selection"]


def test_endpoint_generate_persona_without_student_context(repo, client_factory):
    repo.create_lesson(_lesson())
    client = client_factory()

    resp = client.post(f"/lesson/{LESSON_ID}/debate-persona/generate", json={})
    assert resp.status_code == 200
    data = resp.json()
    assert data["role"]


def test_endpoint_generate_persona_unknown_lesson_returns_502(client_factory):
    client = client_factory()
    resp = client.post("/lesson/no-such-lesson/debate-persona/generate", json={})
    assert resp.status_code == 502


def test_endpoint_hint_requires_existing_persona(repo, client_factory):
    repo.create_lesson(_lesson())
    client = client_factory()
    resp = client.post(
        f"/lesson/{LESSON_ID}/debate-persona/hint",
        json={"persona_id": "no-such-persona", "full_transcript": "x"},
    )
    assert resp.status_code == 404


def test_endpoint_hint_returns_question(repo, client_factory, monkeypatch):
    repo.create_lesson(_lesson())
    client = client_factory()

    gen_resp = client.post(f"/lesson/{LESSON_ID}/debate-persona/generate", json={})
    persona_id = gen_resp.json()["persona_id"]

    import routes.lesson_routes as lesson_routes

    async def fake_hint(persona, transcript, llm_call=None, model=None):
        return "What assumption underlies your claim?"

    monkeypatch.setattr(lesson_routes, "generate_socratic_hint", fake_hint)

    resp = client.post(
        f"/lesson/{LESSON_ID}/debate-persona/hint",
        json={"persona_id": persona_id, "full_transcript": "Pro: funding helps. Con: costs too much."},
    )
    assert resp.status_code == 200
    assert resp.json()["hint"] == "What assumption underlies your claim?"
