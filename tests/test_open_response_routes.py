"""Endpoint integration tests for Increment 6 open-response routes."""

import asyncio
import json

import pytest

from models.lesson_models import GroundedClaim, Lesson
from services.lesson_repository import LessonRepository
from services.open_response_generation import OpenResponseGenerationService
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
        stakeholders=[GroundedClaim(claim="Rural clinics receive funding support.", section_ids=["section-4"])],
    )


class ScriptedLLM:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.call_count = 0

    async def __call__(self, system_prompt, user_prompt, model):
        response = self.responses[min(self.call_count, len(self.responses) - 1)]
        self.call_count += 1
        return response


def _generation_response():
    return json.dumps({
        "question": "Why might a rural health clinic support this bill?",
        "expected_points": ["Mentions administrative funding support", "Mentions section-4"],
    })


def _grade_response(score=2):
    return json.dumps({
        "score": score,
        "feedback": "Reasonable but incomplete answer.",
        "missed_points": [],
        "accurate_points": ["Administrative funding support"],
        "section_ids": ["section-4"],
    })


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
    from services.open_response_grading import OpenResponseGradingService

    monkeypatch.setattr(
        lesson_routes, "_lesson_generation_service", LessonGenerationService(repository=repo)
    )

    def _make(user_id=None, grading_llm=None):
        monkeypatch.setattr(
            lesson_routes,
            "_open_response_grading_service",
            OpenResponseGradingService(llm_call=grading_llm or ScriptedLLM(_grade_response())),
        )
        app = FastAPI()
        app.include_router(lesson_routes.router)
        if user_id is not None:
            app.dependency_overrides[get_current_user_id] = lambda: user_id
        return TestClient(app)

    return _make


def _seed_question(repo):
    repo.create_lesson(_lesson())
    service = OpenResponseGenerationService(repository=repo, llm_call=ScriptedLLM(_generation_response()))
    return asyncio.run(service.generate_question(LESSON_ID))


def test_endpoint_get_open_response_returns_public_shape(repo, client_factory):
    _seed_question(repo)
    client = client_factory()

    resp = client.get(f"/lesson/{LESSON_ID}/open-response")
    assert resp.status_code == 200
    data = resp.json()
    assert data["question"] == "Why might a rural health clinic support this bill?"
    assert "expected_points" not in data
    assert "context_excerpt" not in data


def test_endpoint_get_open_response_unknown_lesson_returns_404(client_factory):
    client = client_factory()
    resp = client.get("/lesson/no-such-lesson/open-response")
    assert resp.status_code == 404


def test_endpoint_get_open_response_not_generated_yet_returns_404(repo, client_factory):
    repo.create_lesson(_lesson())
    client = client_factory()
    resp = client.get(f"/lesson/{LESSON_ID}/open-response")
    assert resp.status_code == 404


def test_endpoint_submit_requires_auth(repo, client_factory):
    _seed_question(repo)
    client = client_factory()  # no user override
    resp = client.post(f"/lesson/{LESSON_ID}/open-response/submit", json={"student_answer": "some answer"})
    assert resp.status_code == 401


def test_endpoint_submit_grades_and_saves_attempt(repo, client_factory):
    _seed_question(repo)
    client = client_factory(user_id="user-1", grading_llm=ScriptedLLM(_grade_response(score=2)))

    resp = client.post(
        f"/lesson/{LESSON_ID}/open-response/submit",
        json={"student_answer": "It gives clinics funding support to help operate under section 4."},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["score"] == 2
    assert data["feedback"]
    assert "Administrative funding support" in data["accurate_points"]

    attempt = repo.get_open_response_attempt(data["attempt_id"])
    assert attempt is not None
    assert attempt.user_id == "user-1"
    assert attempt.score == 2


def test_endpoint_submit_blank_answer_scores_zero_without_model_call(repo, client_factory):
    _seed_question(repo)
    llm = ScriptedLLM(_grade_response(score=3))  # would prove pre-check bypassed if ever used
    client = client_factory(user_id="user-1", grading_llm=llm)

    resp = client.post(f"/lesson/{LESSON_ID}/open-response/submit", json={"student_answer": ""})
    assert resp.status_code == 200
    data = resp.json()
    assert data["score"] == 0
    assert llm.call_count == 0


def test_endpoint_submit_unknown_lesson_returns_404(client_factory):
    client = client_factory(user_id="user-1")
    resp = client.post("/lesson/no-such-lesson/open-response/submit", json={"student_answer": "x"})
    assert resp.status_code == 404
