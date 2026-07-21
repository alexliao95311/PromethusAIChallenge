"""Tests for the Increment 4 adaptive flashcard review system: Leitner box
transitions, session-based due scheduling, ownership/auth enforcement, and
the review endpoints.
"""

import pytest

from models.lesson_models import Flashcard, Lesson, UserCardProgress
from services.flashcard_review import (
    CardNotInLessonError,
    FlashcardReviewService,
    LessonNotFoundError,
    apply_answer,
    compute_next_due_session,
    is_card_due,
)
from services.lesson_repository import LessonRepository
from tests.fake_firestore import FakeFirestoreClient

LESSON_ID = "hr1-119::v1::abc123"


def _flashcard(card_id, term="eligible household", section_id="section-2"):
    return Flashcard(
        card_id=card_id,
        lesson_id=LESSON_ID,
        term=term,
        simple_definition="A short definition.",
        bill_context="Used to define eligibility.",
        example="An example sentence.",
        section_id=section_id,
    )


def _lesson(card_ids):
    return Lesson(
        lesson_id=LESSON_ID,
        bill_id="hr1-119",
        prompt_version="v1",
        bill_text_hash="abc123",
        lesson_title="t",
        plain_language_summary="s",
        vocabulary_card_ids=card_ids,
    )


@pytest.fixture
def repo():
    return LessonRepository(db=FakeFirestoreClient())


@pytest.fixture
def service(repo):
    return FlashcardReviewService(repository=repo)


def _seed_lesson_with_cards(repo, card_ids):
    repo.create_lesson(_lesson(card_ids))
    for cid in card_ids:
        repo.create_flashcard(_flashcard(cid))


# ---------------------------------------------------------------------------
# Pure scheduling logic (no Firestore)
# ---------------------------------------------------------------------------

def test_compute_next_due_session_box1_due_next_session():
    assert compute_next_due_session(1, reviewed_session=1) == 1


def test_compute_next_due_session_box2_due_every_third_session():
    assert compute_next_due_session(2, reviewed_session=1) == 3


def test_compute_next_due_session_box3_due_every_seventh_session():
    assert compute_next_due_session(3, reviewed_session=1) == 7


def test_is_card_due_new_card_with_no_progress_is_always_due():
    assert is_card_due(None, current_session=1) is True
    assert is_card_due(None, current_session=99) is True


def test_is_card_due_respects_next_due_session():
    progress = UserCardProgress(user_id="u1", card_id="c1", next_due_session=5)
    assert is_card_due(progress, current_session=4) is False
    assert is_card_due(progress, current_session=5) is True
    assert is_card_due(progress, current_session=6) is True


def test_apply_answer_correct_moves_up_one_box():
    progress = UserCardProgress(user_id="u1", card_id="c1", leitner_box=1)
    updated = apply_answer(progress, correct=True, session=1)
    assert updated.leitner_box == 2
    assert updated.correct_count == 1
    assert updated.incorrect_count == 0
    assert updated.last_reviewed_session == 1
    assert updated.next_due_session == 3  # box 2 -> due every 3rd session


def test_apply_answer_correct_caps_at_max_box_3():
    progress = UserCardProgress(user_id="u1", card_id="c1", leitner_box=3)
    updated = apply_answer(progress, correct=True, session=5)
    assert updated.leitner_box == 3
    assert updated.next_due_session == 11  # 5 + (7-1)


def test_apply_answer_incorrect_resets_to_box_1_from_any_box():
    progress = UserCardProgress(user_id="u1", card_id="c1", leitner_box=3, correct_count=2)
    updated = apply_answer(progress, correct=False, session=10)
    assert updated.leitner_box == 1
    assert updated.incorrect_count == 1
    assert updated.correct_count == 2  # unchanged
    assert updated.next_due_session == 10  # box 1 -> due next session


# ---------------------------------------------------------------------------
# Full scheduling scenario from the spec's manual test
# ---------------------------------------------------------------------------

def test_scheduling_scenario_matches_manual_test_spec():
    card_a = UserCardProgress(user_id="u1", card_id="card-a")
    card_b = UserCardProgress(user_id="u1", card_id="card-b")

    # Session 1: both new -> both due.
    assert is_card_due(None, current_session=1) is True

    # Correct card A -> Box 2; miss card B -> stays Box 1.
    card_a = apply_answer(card_a, correct=True, session=1)
    card_b = apply_answer(card_b, correct=False, session=1)
    assert card_a.leitner_box == 2
    assert card_b.leitner_box == 1

    # Session 2: B due, A not due.
    assert is_card_due(card_b, current_session=2) is True
    assert is_card_due(card_a, current_session=2) is False

    # Session 3: A becomes due again.
    assert is_card_due(card_a, current_session=3) is True

    # Promote A to Box 3 at session 3, verify it's due on session 9 (7th
    # session inclusive of session 3) but not before.
    card_a = apply_answer(card_a, correct=True, session=3)
    assert card_a.leitner_box == 3
    for s in range(3, 9):
        assert is_card_due(card_a, current_session=s) is False
    assert is_card_due(card_a, current_session=9) is True


# ---------------------------------------------------------------------------
# FlashcardReviewService (Firestore-backed via fake client)
# ---------------------------------------------------------------------------

def test_get_review_state_new_lesson_all_cards_due_and_new(repo, service):
    _seed_lesson_with_cards(repo, ["c1", "c2", "c3"])
    state = service.get_review_state("u1", LESSON_ID)

    assert state.session == 1
    assert state.total_cards == 3
    assert state.due_count == 3
    assert all(c.is_new and c.is_due for c in state.due_cards)
    assert state.box_distribution == {"1": 3, "2": 0, "3": 0}
    assert state.mastery_percent == 0.0


def test_submit_answer_updates_box_and_progress(repo, service):
    _seed_lesson_with_cards(repo, ["c1"])
    updated = service.submit_answer("u1", LESSON_ID, "c1", correct=True)
    assert updated.leitner_box == 2

    fetched = repo.get_user_card_progress("u1", "c1")
    assert fetched.leitner_box == 2


def test_submit_answer_rejects_card_not_in_lesson(repo, service):
    _seed_lesson_with_cards(repo, ["c1"])
    with pytest.raises(CardNotInLessonError):
        service.submit_answer("u1", LESSON_ID, "not-a-real-card", correct=True)


def test_submit_answer_rejects_unknown_lesson(repo, service):
    with pytest.raises(LessonNotFoundError):
        service.submit_answer("u1", "no-such-lesson", "c1", correct=True)


def test_start_session_advances_session_counter(repo, service):
    _seed_lesson_with_cards(repo, ["c1"])
    assert service.start_session("u1", LESSON_ID) == 1  # first-ever call
    assert service.start_session("u1", LESSON_ID) == 2
    assert service.start_session("u1", LESSON_ID) == 3


def test_review_state_reflects_answers_across_sessions(repo, service):
    _seed_lesson_with_cards(repo, ["card-a", "card-b"])

    # Session 1 (auto-initialized by get_review_state): both due.
    state = service.get_review_state("u1", LESSON_ID)
    assert state.session == 1
    assert state.due_count == 2

    service.submit_answer("u1", LESSON_ID, "card-a", correct=True)   # -> box 2
    service.submit_answer("u1", LESSON_ID, "card-b", correct=False)  # -> box 1

    # Still session 1 until start_session is explicitly called (refresh-safe).
    state = service.get_review_state("u1", LESSON_ID)
    assert state.session == 1

    service.start_session("u1", LESSON_ID)  # -> session 2
    state = service.get_review_state("u1", LESSON_ID)
    due_ids = {c.card_id for c in state.due_cards}
    assert state.session == 2
    assert due_ids == {"card-b"}  # card-a (box 2) not due until session 3

    service.start_session("u1", LESSON_ID)  # -> session 3
    state = service.get_review_state("u1", LESSON_ID)
    due_ids = {c.card_id for c in state.due_cards}
    assert due_ids == {"card-b", "card-a"}


# ---------------------------------------------------------------------------
# Ownership: two users never see or affect each other's progress
# ---------------------------------------------------------------------------

def test_users_have_independent_progress(repo, service):
    _seed_lesson_with_cards(repo, ["c1"])

    service.submit_answer("user-a", LESSON_ID, "c1", correct=True)
    service.submit_answer("user-b", LESSON_ID, "c1", correct=False)

    progress_a = repo.get_user_card_progress("user-a", "c1")
    progress_b = repo.get_user_card_progress("user-b", "c1")

    assert progress_a.leitner_box == 2
    assert progress_b.leitner_box == 1

    session_a = repo.get_lesson_progress("user-a", LESSON_ID)
    session_b = repo.get_lesson_progress("user-b", LESSON_ID)
    assert session_a.current_session == 1
    assert session_b.current_session == 1  # independent counters


# ---------------------------------------------------------------------------
# Auth dependency
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_current_user_id_rejects_missing_header():
    from fastapi import HTTPException

    from services.auth import get_current_user_id

    with pytest.raises(HTTPException) as exc_info:
        await get_current_user_id(authorization=None)
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_get_current_user_id_rejects_malformed_header():
    from fastapi import HTTPException

    from services.auth import get_current_user_id

    with pytest.raises(HTTPException) as exc_info:
        await get_current_user_id(authorization="not-a-bearer-token")
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_get_current_user_id_rejects_invalid_token(monkeypatch):
    from fastapi import HTTPException

    import services.auth as auth_module

    def _raise(*args, **kwargs):
        raise ValueError("bad token")

    monkeypatch.setattr(auth_module.firebase_auth, "verify_id_token", _raise)

    with pytest.raises(HTTPException) as exc_info:
        await auth_module.get_current_user_id(authorization="Bearer garbage")
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_get_current_user_id_returns_uid_from_valid_token(monkeypatch):
    import services.auth as auth_module

    monkeypatch.setattr(
        auth_module.firebase_auth, "verify_id_token", lambda token: {"uid": "user-123"}
    )

    uid = await auth_module.get_current_user_id(authorization="Bearer valid-token")
    assert uid == "user-123"


# ---------------------------------------------------------------------------
# Endpoint integration tests (router mounted standalone, auth dependency
# overridden per-user like a real test double for a verified token)
# ---------------------------------------------------------------------------

@pytest.fixture
def client_factory(repo):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    import routes.lesson_routes as lesson_routes
    from services.auth import get_current_user_id

    review_service = FlashcardReviewService(repository=repo)
    lesson_routes._flashcard_review_service = review_service

    def _make(user_id: str):
        app = FastAPI()
        app.include_router(lesson_routes.router)
        app.dependency_overrides[get_current_user_id] = lambda: user_id
        return TestClient(app)

    return _make, review_service


def test_endpoint_requires_auth_without_override():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    import routes.lesson_routes as lesson_routes

    app = FastAPI()
    app.include_router(lesson_routes.router)
    client = TestClient(app)

    response = client.get(f"/lesson/{LESSON_ID}/review/state")
    assert response.status_code == 401


def test_endpoint_start_session_and_get_state(repo, client_factory):
    _seed_lesson_with_cards(repo, ["c1", "c2"])
    make_client, _ = client_factory
    client = make_client("user-1")

    resp = client.post(f"/lesson/{LESSON_ID}/review/start-session")
    assert resp.status_code == 200
    assert resp.json()["session"] == 1

    resp = client.get(f"/lesson/{LESSON_ID}/review/state")
    assert resp.status_code == 200
    data = resp.json()
    assert data["due_count"] == 2
    assert data["box_distribution"] == {"1": 2, "2": 0, "3": 0}


def test_endpoint_submit_answer(repo, client_factory):
    _seed_lesson_with_cards(repo, ["c1"])
    make_client, _ = client_factory
    client = make_client("user-1")

    resp = client.post(
        f"/lesson/{LESSON_ID}/review/answer", json={"card_id": "c1", "correct": True}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["leitner_box"] == 2
    assert data["correct_count"] == 1


def test_endpoint_users_cannot_affect_each_others_progress(repo, client_factory):
    _seed_lesson_with_cards(repo, ["c1"])
    make_client, _ = client_factory

    client_a = make_client("user-a")
    client_b = make_client("user-b")

    client_a.post(f"/lesson/{LESSON_ID}/review/answer", json={"card_id": "c1", "correct": True})
    client_b.post(f"/lesson/{LESSON_ID}/review/answer", json={"card_id": "c1", "correct": False})

    box_a = repo.get_user_card_progress("user-a", "c1").leitner_box
    box_b = repo.get_user_card_progress("user-b", "c1").leitner_box
    assert box_a == 2
    assert box_b == 1


def test_endpoint_answer_rejects_card_not_in_lesson(repo, client_factory):
    _seed_lesson_with_cards(repo, ["c1"])
    make_client, _ = client_factory
    client = make_client("user-1")

    resp = client.post(
        f"/lesson/{LESSON_ID}/review/answer", json={"card_id": "bogus", "correct": True}
    )
    assert resp.status_code == 400


def test_endpoint_state_unknown_lesson_returns_404(client_factory):
    make_client, _ = client_factory
    client = make_client("user-1")
    resp = client.get("/lesson/no-such-lesson/review/state")
    assert resp.status_code == 404
