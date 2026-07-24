"""Endpoint integration tests for the Increment 7 persona routes."""

import pytest

from services.lesson_repository import LessonRepository
from services.persona_service import PersonaService
from tests.fake_firestore import FakeFirestoreClient


@pytest.fixture
def repo():
    return LessonRepository(db=FakeFirestoreClient())


@pytest.fixture
def client_factory(repo, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    import routes.lesson_routes as lesson_routes
    from services.auth import get_current_user_id

    monkeypatch.setattr(lesson_routes, "_persona_service", PersonaService(repository=repo))

    def _make(user_id=None):
        app = FastAPI()
        app.include_router(lesson_routes.router)
        if user_id is not None:
            app.dependency_overrides[get_current_user_id] = lambda: user_id
        return TestClient(app)

    return _make


# ---------------------------------------------------------------------------
# Options (public)
# ---------------------------------------------------------------------------

def test_options_endpoint_is_public_and_lists_choices(client_factory):
    client = client_factory()  # no auth
    resp = client.get("/lesson/persona/options")
    assert resp.status_code == 200
    data = resp.json()
    assert data["all_fields_optional"] is True
    assert data["persona_may_be_fictional"] is True
    assert {"code": "CA", "name": "California"} in data["states"]
    assert "18-24" in data["age_ranges"]
    assert "exact income" in data["not_collected"]


# ---------------------------------------------------------------------------
# Auth is required for per-user routes
# ---------------------------------------------------------------------------

def test_get_persona_requires_auth(client_factory):
    client = client_factory()  # no user override
    assert client.get("/lesson/persona").status_code == 401


def test_save_persona_requires_auth(client_factory):
    client = client_factory()
    resp = client.put("/lesson/persona", json={"occupation": "Nurse"})
    assert resp.status_code == 401


def test_delete_persona_requires_auth(client_factory):
    client = client_factory()
    assert client.delete("/lesson/persona").status_code == 401


# ---------------------------------------------------------------------------
# Save / get / edit / delete lifecycle
# ---------------------------------------------------------------------------

def test_get_persona_when_none_saved(client_factory):
    client = client_factory(user_id="u1")
    resp = client.get("/lesson/persona")
    assert resp.status_code == 200
    assert resp.json()["has_persona"] is False


def test_save_complete_persona(client_factory, repo):
    client = client_factory(user_id="u1")
    resp = client.put(
        "/lesson/persona",
        json={
            "occupation": "Small-business owner",
            "state": "tx",
            "age_range": "45-54",
            "income_bracket": "$100,000-$199,999",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["has_persona"] is True
    assert data["state"] == "TX"  # normalized to uppercase code
    assert data["impact_representation"]["is_fictional"] is True
    assert "Texas" in data["impact_representation"]["descriptor"]

    # Persisted, and keyed to the authenticated uid.
    assert repo.get_persona_profile("u1").occupation == "Small-business owner"


def test_save_persona_with_only_one_field(client_factory):
    client = client_factory(user_id="u1")
    resp = client.put("/lesson/persona", json={"state": "OR"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["state"] == "OR"
    assert data["occupation"] is None
    assert data["age_range"] is None


def test_save_then_get_persona(client_factory):
    client = client_factory(user_id="u1")
    client.put("/lesson/persona", json={"occupation": "Teacher", "state": "NY"})

    resp = client.get("/lesson/persona")
    assert resp.status_code == 200
    data = resp.json()
    assert data["has_persona"] is True
    assert data["occupation"] == "Teacher"
    assert data["state"] == "NY"


def test_edit_persona_overwrites(client_factory, repo):
    client = client_factory(user_id="u1")
    client.put("/lesson/persona", json={"occupation": "Student", "state": "CA"})
    client.put("/lesson/persona", json={"occupation": "Teacher", "state": "NY", "age_range": "25-34"})

    persona = repo.get_persona_profile("u1")
    assert persona.occupation == "Teacher"
    assert persona.state == "NY"
    assert persona.age_range == "25-34"


def test_save_rejects_invalid_choice(client_factory):
    client = client_factory(user_id="u1")
    resp = client.put("/lesson/persona", json={"state": "Atlantis"})
    assert resp.status_code == 422


def test_delete_persona(client_factory, repo):
    client = client_factory(user_id="u1")
    client.put("/lesson/persona", json={"occupation": "Nurse"})

    resp = client.delete("/lesson/persona")
    assert resp.status_code == 200
    assert resp.json()["deleted"] is True
    assert repo.get_persona_profile("u1") is None


def test_delete_when_nothing_saved_returns_false(client_factory):
    client = client_factory(user_id="u1")
    resp = client.delete("/lesson/persona")
    assert resp.status_code == 200
    assert resp.json()["deleted"] is False


def test_users_cannot_read_each_others_personas(client_factory):
    client_factory(user_id="u1").put("/lesson/persona", json={"occupation": "Nurse"})
    other = client_factory(user_id="u2")
    assert other.get("/lesson/persona").json()["has_persona"] is False
