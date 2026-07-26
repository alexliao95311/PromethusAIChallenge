"""Endpoint integration test for GET /lesson/mastery-dashboard (Increment 11)."""

import pytest

from models.lesson_models import Lesson, QuizAttempt
from services.lesson_repository import LessonRepository
from services.mastery_dashboard import MasteryDashboardService
from tests.fake_firestore import FakeFirestoreClient

LESSON_ID = "hr1-119::v1::abc123"


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

    monkeypatch.setattr(
        lesson_routes, "_lesson_generation_service", LessonGenerationService(repository=repo)
    )
    monkeypatch.setattr(
        lesson_routes, "_mastery_dashboard_service", MasteryDashboardService(repository=repo)
    )

    def _make(user_id=None):
        app = FastAPI()
        app.include_router(lesson_routes.router)
        if user_id is not None:
            app.dependency_overrides[get_current_user_id] = lambda: user_id
        return TestClient(app)

    return _make


def test_mastery_dashboard_requires_auth(client_factory):
    client = client_factory()
    resp = client.get("/lesson/mastery-dashboard")
    assert resp.status_code == 401


def test_mastery_dashboard_empty_state_for_new_user(client_factory):
    client = client_factory(user_id="u1")
    resp = client.get("/lesson/mastery-dashboard")
    assert resp.status_code == 200
    data = resp.json()
    assert data["has_activity"] is False
    assert data["lessons"] == []
    assert data["recommended_activity"]["activity_type"] == "generate_lesson"
    # No misleading combined score field anywhere in the response.
    assert "overall_score" not in data
    assert "intelligence_score" not in data


def test_mastery_dashboard_reflects_quiz_activity(repo, client_factory):
    repo.create_lesson(Lesson(
        lesson_id=LESSON_ID, bill_id="hr1-119", prompt_version="v1", bill_text_hash="abc123",
        lesson_title="Test Lesson", plain_language_summary="s", quiz_question_ids=["q1"],
    ))
    repo.create_quiz_attempt(QuizAttempt(attempt_id="a1", user_id="u1", lesson_id=LESSON_ID, score=88.0))

    client = client_factory(user_id="u1")
    resp = client.get("/lesson/mastery-dashboard")
    assert resp.status_code == 200
    data = resp.json()
    assert data["has_activity"] is True
    assert data["lessons"][0]["latest_quiz_score"] == 88.0
    assert len(data["recent_quiz_scores"]) == 1
