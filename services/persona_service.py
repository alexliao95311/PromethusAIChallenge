"""Student persona builder service (Increment 7).

Before a lesson, a student may optionally build a lightweight persona
(occupation-or-role, state, age range, income bracket) so a later increment
can generate a personalized bill-impact narrative. This service is the
authenticated read/save/edit/delete layer over `PersonaProfile`; it does
*not* generate any narrative yet -- see docs/LESSON_MODE_ARCHITECTURE.md.

Design notes:
- Every field is optional. A student may save a persona with a single field.
- Skipping persona creation simply means never calling `save_persona`; an
  empty persona is only written if the student explicitly saves one.
- Validation (allowed states / age ranges / income brackets, occupation
  length) lives on the `PersonaProfile` model, so both this service and any
  direct repository write reject the same bad input. Invalid input surfaces
  here as `PersonaValidationError`.
"""

import logging
from typing import Optional

from pydantic import ValidationError

from models.lesson_models import PersonaProfile
from services.lesson_repository import LessonRepository

logger = logging.getLogger(__name__)


class PersonaValidationError(ValueError):
    """Raised when submitted persona fields fail model validation."""


class PersonaService:
    def __init__(self, repository: Optional[LessonRepository] = None):
        self.repository = repository or LessonRepository()

    def get_persona(self, user_id: str) -> Optional[PersonaProfile]:
        """Return the user's saved persona, or None if they have none."""
        return self.repository.get_persona_profile(user_id)

    def save_persona(
        self,
        user_id: str,
        *,
        occupation: Optional[str] = None,
        state: Optional[str] = None,
        age_range: Optional[str] = None,
        income_bracket: Optional[str] = None,
    ) -> PersonaProfile:
        """Create or overwrite (edit) the authenticated user's persona.

        The persona is keyed by ``user_id`` so a save is naturally an upsert:
        calling it again edits the existing persona rather than duplicating
        it. Blank/omitted fields are stored as ``None`` (a skipped field).
        """
        try:
            profile = PersonaProfile(
                user_id=user_id,
                occupation=occupation,
                state=state,
                age_range=age_range,
                income_bracket=income_bracket,
            )
        except ValidationError as e:
            raise PersonaValidationError(str(e)) from e

        self.repository.upsert_persona_profile(profile)
        logger.info(
            "Saved persona for user_id=%s (fields set: %s)",
            user_id,
            [
                k
                for k in ("occupation", "state", "age_range", "income_bracket")
                if getattr(profile, k) is not None
            ],
        )
        return profile

    def delete_persona(self, user_id: str) -> bool:
        """Delete the user's persona. Returns True if one existed."""
        deleted = self.repository.delete_persona_profile(user_id)
        logger.info("Delete persona for user_id=%s existed=%s", user_id, deleted)
        return deleted

    @staticmethod
    def field_options() -> dict:
        """Choice sets + privacy disclaimer for the persona builder UI."""
        return PersonaProfile.field_options()
