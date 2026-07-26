"""End-to-end integration tests for Increment 12: the connected Lesson Mode
workflow (choose a bill -> lesson -> vocabulary -> quiz -> open response ->
debate -> reflection -> mastery dashboard), driven entirely through the
mounted FastAPI router with a fake Firestore-backed repository.

Generation-step *correctness* (grounding, retries, schema validation) is
already covered by each increment's own test suite (test_lesson_generation,
test_quiz_generation, test_dynamic_persona_generation, etc.) -- these tests
instead validate *connectivity*: that a student's data flows correctly from
one already-tested step's endpoint into the next, and that the mastery
dashboard reflects the whole trip. To keep scope focused on that
connectivity (not re-deriving already-tested generation internals), quiz
questions/open-response questions are seeded directly into the repository
exactly as a real `/generate` call would have populated them, rather than
re-running the full multi-call quiz/vocabulary generation pipelines here.
"""

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from models.lesson_models import GroundedClaim, Lesson, OpenResponseQuestion, QuizQuestion
from services.auth import get_current_user_id
from services.dynamic_persona_generation import DynamicPersonaGenerationService
from services.lesson_generation import LessonGenerationService
from services.lesson_repository import LessonRepository
from services.mastery_dashboard import MasteryDashboardService
from services.open_response_grading import OpenResponseGradingService
from services.reflection_generation import ReflectionGenerationService
from tests.fake_firestore import FakeFirestoreClient

import routes.lesson_routes as lesson_routes

LESSON_ID = "hr1-119::v1::abc123"
USER_ID = "student-1"


def _lesson():
    return Lesson(
        lesson_id=LESSON_ID,
        bill_id="hr1-119",
        prompt_version="v1",
        bill_text_hash="abc123",
        lesson_title="Community Health Access Act",
        plain_language_summary="A bill expanding health benefits to eligible households.",
        major_provisions=[GroundedClaim(claim="Eligibility is income-based.", section_ids=["section-3"])],
        stakeholders=[GroundedClaim(claim="Affects low-income families and clinics.", section_ids=["section-4"])],
        pro_arguments=[GroundedClaim(claim="Funding is guaranteed for five years.", section_ids=["section-6"])],
        con_arguments=[GroundedClaim(claim="Fraud penalties may deter legitimate applicants.", section_ids=["section-7"])],
        quiz_question_ids=["q1"],
        open_response_question_id="or1",
    )


def _quiz_question():
    return QuizQuestion(
        question_id="q1", lesson_id=LESSON_ID, question="Who is eligible for benefits?",
        answer_choices=["Eligible households", "All households", "No one", "Only clinics"],
        correct_answer_index=0, explanation="Eligibility is income-based.",
        section_ids=["section-3"], question_type="provision",
    )


def _open_response_question():
    return OpenResponseQuestion(
        question_id="or1", lesson_id=LESSON_ID,
        question="How might this bill affect a rural health clinic?",
        question_type="stakeholder_perspective",
        expected_points=["Clinics may see more patients", "Funding supports rural clinics"],
        section_ids=["section-4"], context_excerpt="Affects low-income families and clinics.",
    )


def _persona_json():
    return json.dumps({
        "role": "Rural health clinic administrator",
        "location_context": "runs a small clinic serving a low-income county",
        "interests": ["Predictable funding", "Simple compliance"],
        "likely_concerns": ["Reporting requirements could strain limited staff time"],
        "position": "Supportive but worried about implementation costs",
        "section_ids": ["section-4"],
        "reason_for_selection": "Offers a stakeholder view distinct from a general student perspective.",
    })


def _grading_json():
    return json.dumps({
        "score": 2, "feedback": "Good understanding of clinic funding impacts.",
        "missed_points": ["Did not mention compliance reporting"],
        "accurate_points": ["Clinics may see more patients"], "section_ids": ["section-4"],
    })


TRANSCRIPT = (
    "## Pro (Round 1)\nThe bill guarantees funding for rural clinics.\n\n"
    "## Con (Round 1)\nThe funding is capped and may not keep pace with rising costs.\n"
)


def _reflection_json():
    return json.dumps({
        "strongest_student_argument": {
            "feedback": "Good point about guaranteed funding.",
            "transcript_excerpt": "The bill guarantees funding for rural clinics.",
        },
        "weakest_reasoning_step": {"feedback": "Did not address the cost cap.", "transcript_excerpt": None},
        "evidence_use_feedback": {"feedback": "No figures cited.", "transcript_excerpt": None},
        "missed_opponent_point": {
            "feedback": "Never addressed rising costs.",
            "transcript_excerpt": "The funding is capped and may not keep pace with rising costs.",
        },
        "perspective_understanding": {"feedback": "Engaged with the opponent.", "transcript_excerpt": None},
        "recommended_skill": "Address the opponent's strongest point directly",
        "recommended_next_activity": "Debate this bill again from the opposing side",
    })


class ScriptedLLM:
    """Routes by a keyword unique to each generator's own system prompt, so
    one fake stands in for every generation service mounted on the router."""

    def __init__(self):
        self.calls = []

    async def __call__(self, system_prompt, user_prompt, model):
        self.calls.append(system_prompt[:40])
        if "debate coach" in system_prompt:
            return _reflection_json()
        if "opposing" in system_prompt or "stakeholder" in system_prompt:
            return _persona_json()
        if "grading a high-school" in system_prompt:
            return _grading_json()
        raise AssertionError(f"Unexpected system prompt in E2E test: {system_prompt[:80]!r}")


@pytest.fixture
def repo():
    return LessonRepository(db=FakeFirestoreClient())


@pytest.fixture
def client(repo, monkeypatch):
    llm = ScriptedLLM()
    monkeypatch.setattr(
        lesson_routes, "_lesson_generation_service", LessonGenerationService(repository=repo)
    )
    monkeypatch.setattr(
        lesson_routes, "_dynamic_persona_generation_service",
        DynamicPersonaGenerationService(repository=repo, llm_call=llm),
    )
    monkeypatch.setattr(
        lesson_routes, "_open_response_grading_service", OpenResponseGradingService(llm_call=llm)
    )
    monkeypatch.setattr(
        lesson_routes, "_reflection_generation_service",
        ReflectionGenerationService(repository=repo, llm_call=llm),
    )
    monkeypatch.setattr(
        lesson_routes, "_mastery_dashboard_service", MasteryDashboardService(repository=repo)
    )

    app = FastAPI()
    app.include_router(lesson_routes.router)
    app.dependency_overrides[get_current_user_id] = lambda: USER_ID
    return TestClient(app)


def _seed_lesson(repo):
    repo.create_lesson(_lesson())
    repo.create_quiz_question(_quiz_question())
    repo.create_open_response_question(_open_response_question())


def test_full_happy_path_lesson_to_dashboard(repo, client):
    _seed_lesson(repo)

    # 1-4: choose a bill / read the lesson (already generated+seeded above).
    lesson_resp = client.get(f"/lesson/{LESSON_ID}")
    assert lesson_resp.status_code == 200
    assert lesson_resp.json()["lesson_title"] == "Community Health Access Act"

    # 6: complete the quiz.
    quiz_resp = client.post(
        f"/lesson/{LESSON_ID}/quiz/submit", json={"answers": [{"question_id": "q1", "selected_index": 0}]}
    )
    assert quiz_resp.status_code == 200
    assert quiz_resp.json()["score"] == 100.0

    # 7: answer the open-response question (long/relevant enough to skip the
    # local precheck and hit the scripted grading LLM).
    or_resp = client.post(
        f"/lesson/{LESSON_ID}/open-response/submit",
        json={"student_answer": "Rural clinics would likely see more patients able to afford care under this bill."},
    )
    assert or_resp.status_code == 200
    assert or_resp.json()["score"] == 2

    # 8: debate a dynamically generated opposing stakeholder.
    persona_resp = client.post(f"/lesson/{LESSON_ID}/debate-persona/generate", json={})
    assert persona_resp.status_code == 200
    persona = persona_resp.json()
    assert persona["role"] == "Rural health clinic administrator"

    # 9-10: report whether the student's view changed + get educational feedback.
    reflection_resp = client.post(
        f"/lesson/{LESSON_ID}/reflection",
        json={"transcript": TRANSCRIPT, "view_changed": "somewhat", "persona_id": persona["persona_id"]},
    )
    assert reflection_resp.status_code == 200
    reflection = reflection_resp.json()
    assert reflection["recommended_skill"]
    assert "wins" not in json.dumps(reflection).lower()  # no winner/loser leaks from a separate rubric

    # 11: mastery dashboard reflects the entire trip.
    dashboard_resp = client.get("/lesson/mastery-dashboard")
    assert dashboard_resp.status_code == 200
    dashboard = dashboard_resp.json()
    assert dashboard["has_activity"] is True
    lesson_summary = dashboard["lessons"][0]
    assert lesson_summary["lesson_id"] == LESSON_ID
    assert lesson_summary["completed"] is True
    assert lesson_summary["quiz_attempts"] == 1
    assert lesson_summary["open_response_attempts"] == 1
    assert dashboard["debate_skill"]["reflections_count"] == 1
    assert dashboard["debate_skill"]["is_estimate"] is True
    # Fully completed with a reflection already recorded -> nothing left to
    # nudge toward on this lesson; explore a new bill is the only sane default.
    assert dashboard["recommended_activity"]["activity_type"] == "explore_new_bill"


def test_quiz_generation_failure_does_not_block_the_route(repo, client):
    # No quiz was ever generated for this lesson (quiz_question_ids empty).
    repo.create_lesson(_lesson().model_copy(update={"quiz_question_ids": []}))
    resp = client.get(f"/lesson/{LESSON_ID}/quiz")
    assert resp.status_code == 404


def test_debate_persona_generation_failure_leaves_existing_progress_intact(repo, client, monkeypatch):
    _seed_lesson(repo)
    client.post(
        f"/lesson/{LESSON_ID}/quiz/submit", json={"answers": [{"question_id": "q1", "selected_index": 0}]}
    )
    client.post(
        f"/lesson/{LESSON_ID}/open-response/submit",
        json={"student_answer": "Rural clinics would likely see more patients able to afford care under this bill."},
    )

    async def _broken_llm(system_prompt, user_prompt, model):
        raise ValueError("OpenRouter API error: 500 - upstream model unavailable")

    monkeypatch.setattr(
        lesson_routes, "_dynamic_persona_generation_service",
        DynamicPersonaGenerationService(repository=repo, llm_call=_broken_llm),
    )

    persona_resp = client.post(f"/lesson/{LESSON_ID}/debate-persona/generate", json={})
    assert persona_resp.status_code == 500

    # Requirement: a failed generation step must never erase already-completed
    # progress -- the quiz/open-response attempts are still on the dashboard.
    dashboard = client.get("/lesson/mastery-dashboard").json()
    lesson_summary = dashboard["lessons"][0]
    assert lesson_summary["quiz_attempts"] == 1
    assert lesson_summary["open_response_attempts"] == 1
    assert lesson_summary["completed"] is True


def test_reflection_generation_failure_leaves_earlier_progress_intact(repo, client, monkeypatch):
    _seed_lesson(repo)
    client.post(
        f"/lesson/{LESSON_ID}/quiz/submit", json={"answers": [{"question_id": "q1", "selected_index": 0}]}
    )

    async def _malformed_llm(system_prompt, user_prompt, model):
        return "this is not json"

    monkeypatch.setattr(
        lesson_routes, "_reflection_generation_service",
        ReflectionGenerationService(repository=repo, llm_call=_malformed_llm),
    )

    reflection_resp = client.post(
        f"/lesson/{LESSON_ID}/reflection", json={"transcript": TRANSCRIPT, "view_changed": "no"}
    )
    assert reflection_resp.status_code == 502

    dashboard = client.get("/lesson/mastery-dashboard").json()
    assert dashboard["has_activity"] is True
    assert dashboard["lessons"][0]["quiz_attempts"] == 1
    assert dashboard["debate_skill"] is None  # the failed reflection was never persisted
