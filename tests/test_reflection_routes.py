"""Endpoint integration tests for the Increment 10 reflection routes:
POST /lesson/{lesson_id}/reflection and GET /lesson/reflection/progress."""

import json

import pytest

from models.lesson_models import GroundedClaim, Lesson
from services.lesson_repository import LessonRepository
from services.reflection_generation import ReflectionGenerationService
from tests.fake_firestore import FakeFirestoreClient

BILL_ID = "hr1-119"
LESSON_ID = "hr1-119::v1::abc123"

TRANSCRIPT = (
    "## Pro (Round 1)\nThe bill guarantees funding for rural clinics.\n\n"
    "## Con (Round 1)\nThe funding is capped and may not keep pace with rising costs.\n"
)


def _lesson(lesson_id=LESSON_ID):
    return Lesson(
        lesson_id=lesson_id,
        bill_id=BILL_ID,
        prompt_version="v1",
        bill_text_hash="abc123",
        lesson_title="Understanding the Community Health Access Act",
        plain_language_summary="A bill expanding health benefits.",
        stakeholders=[GroundedClaim(claim="Affects families.", section_ids=["section-4"])],
        source_sections=["section-3", "section-4"],
    )


def _analysis_json():
    return json.dumps({
        "strongest_student_argument": {
            "feedback": "Good point about guaranteed funding.",
            "transcript_excerpt": "The bill guarantees funding for rural clinics.",
        },
        "weakest_reasoning_step": {
            "feedback": "Didn't address the cost cap.",
            "transcript_excerpt": None,
        },
        "evidence_use_feedback": {"feedback": "No figures cited.", "transcript_excerpt": None},
        "missed_opponent_point": {
            "feedback": "Never addressed rising costs.",
            "transcript_excerpt": "The funding is capped and may not keep pace with rising costs.",
        },
        "perspective_understanding": {"feedback": "Engaged with the opponent.", "transcript_excerpt": None},
        "recommended_skill": "Address the opponent's strongest point directly",
        "recommended_next_activity": "Retake the quiz for this lesson",
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

    monkeypatch.setattr(
        lesson_routes, "_lesson_generation_service", LessonGenerationService(repository=repo)
    )

    def _make(user_id=None, llm=None):
        monkeypatch.setattr(
            lesson_routes,
            "_reflection_generation_service",
            ReflectionGenerationService(repository=repo, llm_call=llm or ScriptedLLM(_analysis_json())),
        )
        app = FastAPI()
        app.include_router(lesson_routes.router)
        if user_id is not None:
            app.dependency_overrides[get_current_user_id] = lambda: user_id
        return TestClient(app)

    return _make


def test_submit_reflection_requires_auth(repo, client_factory):
    repo.create_lesson(_lesson())
    client = client_factory()  # no user override
    resp = client.post(
        f"/lesson/{LESSON_ID}/reflection",
        json={"transcript": TRANSCRIPT, "view_changed": "yes"},
    )
    assert resp.status_code == 401


def test_submit_reflection_unknown_lesson_returns_404(client_factory):
    client = client_factory(user_id="u1")
    resp = client.post(
        "/lesson/no-such-lesson/reflection",
        json={"transcript": TRANSCRIPT, "view_changed": "yes"},
    )
    assert resp.status_code == 404


def test_submit_reflection_invalid_view_changed_returns_422(repo, client_factory):
    repo.create_lesson(_lesson())
    client = client_factory(user_id="u1")
    resp = client.post(
        f"/lesson/{LESSON_ID}/reflection",
        json={"transcript": TRANSCRIPT, "view_changed": "totally"},
    )
    assert resp.status_code == 422


def test_submit_reflection_returns_grounded_feedback(repo, client_factory):
    repo.create_lesson(_lesson())
    client = client_factory(user_id="u1")
    resp = client.post(
        f"/lesson/{LESSON_ID}/reflection",
        json={
            "transcript": TRANSCRIPT,
            "view_changed": "somewhat",
            "explanation": "The cost cap point was new to me.",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["view_changed"] == "somewhat"
    assert data["explanation"] == "The cost cap point was new to me."
    assert data["strongest_student_argument"]["transcript_excerpt"] == (
        "The bill guarantees funding for rural clinics."
    )
    assert data["evidence_use_feedback"]["transcript_excerpt"] is None
    assert data["recommended_skill"]
    assert data["recommended_next_activity"]
    # No winner/loser fields leak in -- this is a separate rubric from judge_chain's.
    assert "winner" not in data and "decision" not in data

    persisted = repo.get_debate_reflection(data["reflection_id"])
    assert persisted is not None and persisted.user_id == "u1" and persisted.lesson_id == LESSON_ID


def test_submit_reflection_never_infers_view_changed_from_model(repo, client_factory):
    """The model's JSON output has no view_changed field at all -- confirm the
    persisted/returned value always comes from the student's own request,
    never from the LLM."""
    repo.create_lesson(_lesson())
    client = client_factory(user_id="u1")
    resp = client.post(
        f"/lesson/{LESSON_ID}/reflection",
        json={"transcript": TRANSCRIPT, "view_changed": "no"},
    )
    assert resp.status_code == 200
    assert resp.json()["view_changed"] == "no"


def test_reflection_progress_requires_auth(client_factory):
    client = client_factory()
    resp = client.get("/lesson/reflection/progress")
    assert resp.status_code == 401


def test_reflection_progress_spans_multiple_lesson_debates(repo, client_factory):
    repo.create_lesson(_lesson(LESSON_ID))
    other_lesson_id = "hr2-119::v1::def456"
    repo.create_lesson(_lesson(other_lesson_id))
    client = client_factory(user_id="u1")

    client.post(f"/lesson/{LESSON_ID}/reflection", json={"transcript": TRANSCRIPT, "view_changed": "yes"})
    client.post(f"/lesson/{other_lesson_id}/reflection", json={"transcript": TRANSCRIPT, "view_changed": "no"})

    resp = client.get("/lesson/reflection/progress")
    assert resp.status_code == 200
    reflections = resp.json()["reflections"]
    assert len(reflections) == 2
    assert {r["lesson_id"] for r in reflections} == {LESSON_ID, other_lesson_id}


def test_reflection_progress_scoped_to_authenticated_user(repo, client_factory):
    repo.create_lesson(_lesson())
    client_u1 = client_factory(user_id="u1")
    client_u1.post(f"/lesson/{LESSON_ID}/reflection", json={"transcript": TRANSCRIPT, "view_changed": "yes"})

    client_u2 = client_factory(user_id="u2")
    resp = client_u2.get("/lesson/reflection/progress")
    assert resp.status_code == 200
    assert resp.json()["reflections"] == []
