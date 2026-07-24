"""Unit tests for the Increment 7 student persona builder.

Covers persona validation (broad choices, no sensitive fields), the
save/edit/delete lifecycle through a mocked Firestore repository, optional
fields, and the impact representation handed to the (future) personal-impact
generator.
"""

import pytest
from pydantic import ValidationError

from models.lesson_models import (
    AGE_RANGES,
    INCOME_BRACKETS,
    OCCUPATION_CATEGORIES,
    OCCUPATION_MAX_LENGTH,
    US_STATES,
    PersonaProfile,
)
from services.lesson_repository import LessonRepository
from services.persona_service import PersonaService, PersonaValidationError
from tests.fake_firestore import FakeFirestoreClient


@pytest.fixture
def repo():
    return LessonRepository(db=FakeFirestoreClient())


@pytest.fixture
def service(repo):
    return PersonaService(repository=repo)


# ---------------------------------------------------------------------------
# Model validation: broad choices only, everything optional
# ---------------------------------------------------------------------------

def test_all_fields_optional_except_user_id():
    profile = PersonaProfile(user_id="u1")
    assert profile.occupation is None
    assert profile.state is None
    assert profile.age_range is None
    assert profile.income_bracket is None
    assert profile.is_empty() is True


def test_single_field_persona_is_valid():
    profile = PersonaProfile(user_id="u1", occupation="Nurse")
    assert profile.occupation == "Nurse"
    assert profile.is_empty() is False


def test_occupation_is_trimmed_and_blank_becomes_none():
    assert PersonaProfile(user_id="u1", occupation="  Teacher ").occupation == "Teacher"
    assert PersonaProfile(user_id="u1", occupation="   ").occupation is None
    assert PersonaProfile(user_id="u1", occupation="").occupation is None


def test_occupation_rejects_overly_long_value():
    with pytest.raises(ValidationError):
        PersonaProfile(user_id="u1", occupation="x" * (OCCUPATION_MAX_LENGTH + 1))


def test_state_normalized_to_uppercase_code():
    assert PersonaProfile(user_id="u1", state="ca").state == "CA"
    assert PersonaProfile(user_id="u1", state=" ny ").state == "NY"


def test_state_rejects_unknown_code():
    with pytest.raises(ValidationError):
        PersonaProfile(user_id="u1", state="ZZ")


def test_state_rejects_full_name():
    # We store the two-letter code, not the spelled-out name.
    with pytest.raises(ValidationError):
        PersonaProfile(user_id="u1", state="California")


@pytest.mark.parametrize("age_range", AGE_RANGES)
def test_all_predefined_age_ranges_accepted(age_range):
    assert PersonaProfile(user_id="u1", age_range=age_range).age_range == age_range


def test_age_range_rejects_exact_age():
    # Guards the privacy requirement: we never accept an exact age.
    with pytest.raises(ValidationError):
        PersonaProfile(user_id="u1", age_range="42")


@pytest.mark.parametrize("bracket", INCOME_BRACKETS)
def test_all_predefined_income_brackets_accepted(bracket):
    assert PersonaProfile(user_id="u1", income_bracket=bracket).income_bracket == bracket


def test_income_bracket_rejects_exact_amount():
    with pytest.raises(ValidationError):
        PersonaProfile(user_id="u1", income_bracket="$63,500")


def test_no_sensitive_fields_exist_on_model():
    # Privacy contract: the model must not carry any of these attributes.
    forbidden = {
        "exact_age", "age", "birthdate", "date_of_birth",
        "exact_income", "income", "salary",
        "address", "street", "zip", "zipcode", "postal_code",
        "employer", "company",
        "race", "ethnicity", "religion",
        "health", "medical", "disability",
        "political_affiliation", "party", "politics",
    }
    assert forbidden.isdisjoint(PersonaProfile.model_fields.keys())


# ---------------------------------------------------------------------------
# Field options for the builder UI
# ---------------------------------------------------------------------------

def test_field_options_exposes_broad_choices_and_disclaimer():
    options = PersonaService.field_options()
    assert options["all_fields_optional"] is True
    assert options["persona_may_be_fictional"] is True
    assert options["occupation_allows_custom"] is True
    assert options["occupation_max_length"] == OCCUPATION_MAX_LENGTH
    assert options["age_ranges"] == AGE_RANGES
    assert options["income_brackets"] == INCOME_BRACKETS
    assert options["occupation_suggestions"] == OCCUPATION_CATEGORIES
    assert len(options["states"]) == len(US_STATES)
    assert {"code": "CA", "name": "California"} in options["states"]
    # The privacy disclaimer must enumerate what we never ask for.
    for item in ("exact age", "exact income", "home address", "employer name",
                 "race", "religion", "health information", "political affiliation"):
        assert item in options["not_collected"]


# ---------------------------------------------------------------------------
# Save / get lifecycle
# ---------------------------------------------------------------------------

def test_get_persona_returns_none_when_unsaved(service):
    assert service.get_persona("nobody") is None


def test_save_complete_persona_then_get(service):
    saved = service.save_persona(
        "u1",
        occupation="Small-business owner",
        state="TX",
        age_range="45-54",
        income_bracket="$100,000-$199,999",
    )
    assert saved.user_id == "u1"
    fetched = service.get_persona("u1")
    assert fetched.occupation == "Small-business owner"
    assert fetched.state == "TX"
    assert fetched.age_range == "45-54"
    assert fetched.income_bracket == "$100,000-$199,999"


def test_save_persona_with_only_one_field(service):
    saved = service.save_persona("u1", state="OR")
    assert saved.state == "OR"
    assert saved.occupation is None
    assert saved.age_range is None
    fetched = service.get_persona("u1")
    assert fetched.state == "OR"
    assert fetched.is_empty() is False


def test_save_empty_persona_is_allowed_but_marked_empty(service):
    saved = service.save_persona("u1")
    assert saved.is_empty() is True
    assert service.get_persona("u1") is not None


def test_save_persona_rejects_invalid_field(service):
    with pytest.raises(PersonaValidationError):
        service.save_persona("u1", state="Atlantis")
    # Nothing should have been written on a rejected save.
    assert service.get_persona("u1") is None


# ---------------------------------------------------------------------------
# Editing (upsert)
# ---------------------------------------------------------------------------

def test_editing_persona_overwrites_in_place(service):
    service.save_persona("u1", occupation="Student", state="CA")
    service.save_persona("u1", occupation="Teacher", state="NY", age_range="25-34")

    fetched = service.get_persona("u1")
    assert fetched.occupation == "Teacher"
    assert fetched.state == "NY"
    assert fetched.age_range == "25-34"


def test_editing_can_clear_a_field(service):
    service.save_persona("u1", occupation="Teacher", state="NY")
    service.save_persona("u1", occupation="Teacher")  # state omitted -> cleared

    fetched = service.get_persona("u1")
    assert fetched.occupation == "Teacher"
    assert fetched.state is None


# ---------------------------------------------------------------------------
# Deletion
# ---------------------------------------------------------------------------

def test_delete_removes_persona(service):
    service.save_persona("u1", occupation="Nurse")
    assert service.get_persona("u1") is not None

    assert service.delete_persona("u1") is True
    assert service.get_persona("u1") is None


def test_delete_missing_persona_returns_false(service):
    assert service.delete_persona("ghost") is False


def test_delete_only_affects_the_requesting_user(service):
    service.save_persona("u1", occupation="Nurse")
    service.save_persona("u2", occupation="Engineer")

    service.delete_persona("u1")
    assert service.get_persona("u1") is None
    assert service.get_persona("u2").occupation == "Engineer"


# ---------------------------------------------------------------------------
# Impact representation for the personal-impact generator
# ---------------------------------------------------------------------------

def test_impact_representation_of_empty_persona():
    rep = PersonaProfile(user_id="u1").to_impact_representation()
    assert rep["has_persona"] is False
    assert rep["attributes"] == {}
    assert rep["descriptor"] == ""
    assert rep["is_fictional"] is True


def test_impact_representation_includes_only_set_fields():
    rep = PersonaProfile(user_id="u1", occupation="Farmer", state="IA").to_impact_representation()
    assert rep["has_persona"] is True
    assert rep["attributes"]["occupation"] == "Farmer"
    assert rep["attributes"]["state"] == "IA"
    assert rep["attributes"]["state_name"] == "Iowa"
    assert "age_range" not in rep["attributes"]
    assert "income_bracket" not in rep["attributes"]
    assert "Iowa" in rep["descriptor"]
    assert rep["is_fictional"] is True
