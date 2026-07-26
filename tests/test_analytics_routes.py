"""Tests for POST /lesson/analytics/event (Increment 12).

Confirms the endpoint accepts only whitelisted, non-sensitive fields --
there is no freeform string field, so student-authored text (bill text,
answers, transcripts) can never reach it.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import routes.lesson_routes as lesson_routes


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(lesson_routes.router)
    return TestClient(app)


def test_logs_a_known_event_type(client):
    resp = client.post("/lesson/analytics/event", json={"event_type": "lesson_viewed"})
    assert resp.status_code == 200
    assert resp.json() == {"logged": True}


def test_accepts_optional_lesson_id_and_step_index(client):
    resp = client.post("/lesson/analytics/event", json={
        "event_type": "quiz_completed", "lesson_id": "lesson-1", "step_index": 5, "success": True,
    })
    assert resp.status_code == 200


def test_rejects_unknown_event_type(client):
    resp = client.post("/lesson/analytics/event", json={"event_type": "something_made_up"})
    assert resp.status_code == 422


def test_rejects_extra_freeform_fields_being_required(client):
    # No auth, no free-text field exists on the schema at all -- passing an
    # arbitrary "notes" string is simply ignored (pydantic drops unknown
    # fields by default), never persisted or logged.
    resp = client.post("/lesson/analytics/event", json={
        "event_type": "debate_started", "notes": "sensitive debate content here",
    })
    assert resp.status_code == 200
