"""Dynamic opposing debate persona generation for Lesson Mode (Increment 9).

Generates one grounded stakeholder persona -- someone with a legitimate,
bill-grounded interest that meaningfully differs from the student's own
perspective -- and formats it as a `persona_prompt` string that plugs
directly into the *existing, unmodified* debate engine
(`chains.debater_chain.get_debater_chain`). No second debate engine is
built here: this module only produces text that `debater_chain.py`'s
`process_inputs` already knows how to consume.

This is distinct from Increment 8's `services/persona_impact_generation.py`,
which explains how a bill affects the *student's own* persona
(`PersonalImpactNarrative`) -- this module instead produces the AI's
*opposing debate voice*. `PersonaOverride`/`PersonaProfile` (the optional
student-context input) is shared between the two features.

`chains/debater_chain.py:1097` extracts persona instructions from whichever
of three markers appears in the caller-supplied prompt: `"SPEAKING STYLE:"`,
`"DEBATE STYLE INSTRUCTIONS:"`, or `"PERSONA INSTRUCTIONS:"` (checked in
that priority order), truncating at the first of `"Instructions:"`,
`"Your role:"`, `"Bill description:"`, or `"Debate topic:"` that appears
after it. This module uses `"PERSONA INSTRUCTIONS:"` (the only one of the
three not already used by the frontend's fixed celebrity personas) and
avoids the truncation markers appearing anywhere in the generated body.
"""

import logging
from typing import List, Optional

from pydantic import BaseModel, Field, ValidationError

from models.lesson_models import DynamicPersona, GroundedClaim, Lesson, PersonaProfile
from services.json_utils import extract_json_object
from services.lesson_generation import DEFAULT_LESSON_MODEL, LLMCallable, _default_llm_call
from services.lesson_repository import LessonRepository

logger = logging.getLogger(__name__)

PERSONA_INSTRUCTIONS_MARKER = "PERSONA INSTRUCTIONS:"

# Substrings debater_chain.py's extractor treats as "end of persona
# instructions" -- the generated persona_prompt body must never contain
# these, or the engine would silently truncate the persona early.
_TRUNCATION_MARKERS = ("Instructions:", "Your role:", "Bill description:", "Debate topic:")

PERSONA_SYSTEM_PROMPT = """Create an educational debate opponent representing a stakeholder with a
meaningfully different perspective from the student's own perspective, based only on the bill
facts provided.

The opponent must:
- have a legitimate interest affected by the bill
- use arguments grounded in the provided bill facts -- never invent a fact
- avoid stereotypes: never infer the opponent's views, competence, or concerns from the
  student's demographic traits (age, location, income, etc.) -- ground the opponent's
  position only in a concrete role and interest that the bill itself affects
- acknowledge uncertainty where the bill's effects are genuinely unclear
- challenge the student's reasoning respectfully, never with hostility or personal attacks

Return only structured JSON."""

_JSON_SCHEMA_INSTRUCTIONS = """Return ONLY a single JSON object (no markdown fences, no commentary) with exactly this shape:

{
  "role": "string -- a specific role/title, e.g. 'School district budget director'",
  "location_context": "string -- where/how this role operates, not a demographic guess about the student",
  "interests": ["string", ...],
  "likely_concerns": ["string", ...],
  "position": "string -- this stakeholder's overall position on the bill",
  "section_ids": ["section-id", ...],
  "reason_for_selection": "string -- why this stakeholder offers a meaningfully different, educational perspective from the student's"
}

section_ids must come only from the "Available facts" list below -- never invent one."""


class DynamicPersonaGenerationError(Exception):
    """Raised when a persona cannot be produced (no lesson content to draw
    from, or the model's output is unparseable)."""


class _PersonaDraft(BaseModel):
    role: str = Field(min_length=1)
    location_context: str = Field(min_length=1)
    interests: List[str] = Field(min_length=1)
    likely_concerns: List[str] = Field(min_length=1)
    position: str = Field(min_length=1)
    section_ids: List[str] = Field(min_length=1)
    reason_for_selection: str = Field(min_length=1)


def _collect_facts(lesson: Lesson) -> List[GroundedClaim]:
    """Gather the lesson's own grounded claims as the only material the
    persona may draw from -- stakeholder impacts and con-arguments first
    (most likely to surface a genuine opposing interest), then provisions."""
    facts: List[GroundedClaim] = []
    facts.extend(lesson.stakeholders)
    facts.extend(lesson.con_arguments)
    facts.extend(lesson.pro_arguments)
    facts.extend(lesson.major_provisions)
    return facts


def _format_student_context(student_persona: Optional[PersonaProfile]) -> str:
    if student_persona is None:
        return "No student context was provided -- do not assume any demographic details."
    parts = []
    if student_persona.occupation:
        parts.append(f"occupation/role: {student_persona.occupation}")
    if student_persona.state:
        parts.append(f"location: {student_persona.state}")
    if student_persona.age_range:
        parts.append(f"age range: {student_persona.age_range}")
    if student_persona.income_bracket:
        parts.append(f"income bracket: {student_persona.income_bracket}")
    if not parts:
        return "No student context was provided -- do not assume any demographic details."
    return "Student context (use only to gauge which stakeholder perspective would be " \
        "meaningfully different -- never to assume the opponent's traits): " + "; ".join(parts)


def _build_prompt(facts: List[GroundedClaim], student_context: str) -> str:
    fact_blocks = "\n".join(f"- [{'/'.join(c.section_ids)}] {c.claim}" for c in facts)
    return (
        f"{student_context}\n\n"
        f"Available facts about the bill (cite ONLY these section_ids):\n{fact_blocks}\n\n"
        f"{_JSON_SCHEMA_INSTRUCTIONS}"
    )


def ground_persona_draft(raw_text: str, known_section_ids: set) -> _PersonaDraft:
    """Parse and validate the model's JSON response, dropping any
    section_id it cites that wasn't part of the supplied facts."""
    try:
        data = extract_json_object(raw_text)
        draft = _PersonaDraft.model_validate(data)
    except (ValidationError, ValueError) as e:
        raise DynamicPersonaGenerationError(f"Model output failed schema validation: {e}") from e

    filtered_ids = [sid for sid in draft.section_ids if sid in known_section_ids]
    if not filtered_ids:
        raise DynamicPersonaGenerationError(
            "Model's persona cited no section_ids that were actually supplied"
        )
    draft.section_ids = filtered_ids
    return draft


def _sanitize_for_persona_prompt(text: str) -> str:
    """Strip any substring debater_chain.py's extractor would treat as an
    early end-of-persona marker, so the generated body is never silently
    truncated by the (unmodified) existing engine."""
    sanitized = text
    for marker in _TRUNCATION_MARKERS:
        sanitized = sanitized.replace(marker, marker.rstrip(":"))
    return sanitized


def build_persona_prompt(draft: _PersonaDraft) -> str:
    """Format a `_PersonaDraft` as the exact string `debater_chain.py`'s
    existing `process_inputs` extracts persona instructions from -- this is
    the entire integration surface with the existing debate engine."""
    concerns = "; ".join(draft.likely_concerns)
    interests = "; ".join(draft.interests)
    body = (
        f"{PERSONA_INSTRUCTIONS_MARKER}\n"
        f"You are role-playing as {draft.role}, {draft.location_context}. "
        f"Your interests: {interests}. Your concerns about this bill: {concerns}. "
        f"Your position: {draft.position}\n"
        "Argue from this stakeholder's grounded perspective. Support your points with the bill "
        "facts you were given. Challenge the other side's reasoning respectfully and "
        "substantively -- never with hostility, insults, or dismissiveness. Acknowledge "
        "genuine uncertainty where the bill's effects are unclear rather than overstating your "
        "case. Do not assume anything about the other debater's personal background or identity."
    )
    return _sanitize_for_persona_prompt(body)


class DynamicPersonaGenerationService:
    """Generates and persists a grounded opposing debate persona for a lesson."""

    def __init__(
        self,
        repository: Optional[LessonRepository] = None,
        llm_call: Optional[LLMCallable] = None,
    ):
        self._repository = repository or LessonRepository()
        self._llm_call = llm_call or _default_llm_call

    async def generate_persona(
        self,
        lesson_id: str,
        student_persona: Optional[PersonaProfile] = None,
        model: str = DEFAULT_LESSON_MODEL,
    ) -> DynamicPersona:
        lesson = self._repository.get_lesson(lesson_id)
        if lesson is None:
            raise DynamicPersonaGenerationError(f"No lesson found for lesson_id={lesson_id!r}")

        facts = _collect_facts(lesson)
        if not facts:
            raise DynamicPersonaGenerationError(
                f"No lesson content available to generate a persona for lesson_id={lesson_id!r}"
            )
        known_section_ids = {sid for c in facts for sid in c.section_ids}

        student_context = _format_student_context(student_persona)
        prompt = _build_prompt(facts, student_context)
        raw_text = await self._llm_call(PERSONA_SYSTEM_PROMPT, prompt, model)
        draft = ground_persona_draft(raw_text, known_section_ids)

        persona_id = f"{lesson_id}-persona-{'skipped' if student_persona is None else student_persona.user_id}"
        persona = DynamicPersona(
            persona_id=persona_id,
            lesson_id=lesson_id,
            role=draft.role,
            location_context=draft.location_context,
            interests=draft.interests,
            likely_concerns=draft.likely_concerns,
            position=draft.position,
            section_ids=draft.section_ids,
            reason_for_selection=draft.reason_for_selection,
            persona_prompt=build_persona_prompt(draft),
        )

        self._repository.create_dynamic_persona(persona)
        logger.info(
            "dynamic_persona_generation lesson_id=%s persona_id=%s role=%s",
            lesson_id, persona.persona_id, persona.role,
        )
        return persona


SOCRATIC_HINT_SYSTEM_PROMPT = """You are a Socratic debate coach helping a high-school student improve their
reasoning during a practice debate. You are not a debater in this round.

Given the debate transcript so far and the opposing persona's stated position, ask ONE short,
thought-provoking question that helps the student notice a gap, assumption, or angle in their
own argument -- without telling them what to say or giving away the answer. Do not argue a side.
Do not evaluate whether the student is winning or losing. Keep it to one or two sentences.

Return only the question text, with no preamble, labels, or quotation marks."""


def _build_hint_prompt(persona: DynamicPersona, full_transcript: str) -> str:
    return (
        f"Opposing persona: {persona.role} (position: {persona.position})\n\n"
        f"Debate transcript so far:\n{full_transcript}\n\n"
        "Ask one Socratic question for the student."
    )


async def generate_socratic_hint(
    persona: DynamicPersona,
    full_transcript: str,
    llm_call: Optional[LLMCallable] = None,
    model: str = DEFAULT_LESSON_MODEL,
) -> str:
    """A single-shot helper for learning-mode hints -- reuses the same
    OpenRouter-backed call pattern as the rest of Lesson Mode generation,
    not a new debate/reasoning engine."""
    call = llm_call or _default_llm_call
    prompt = _build_hint_prompt(persona, full_transcript)
    hint = await call(SOCRATIC_HINT_SYSTEM_PROMPT, prompt, model)
    return hint.strip()
