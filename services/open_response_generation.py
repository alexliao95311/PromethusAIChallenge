"""Open-ended question generation for Lesson Mode (Increment 6).

Exactly one open-response question is generated per lesson, chosen from
whichever question type the lesson's own grounded content best supports
(pro/con comparison, stakeholder perspective, implementation challenge, or
impact prediction) -- never invented from scratch. A single model call
phrases the question text and a short grading checklist
(`expected_points`), given only the relevant already-grounded claims as
context (never the full bill), mirroring how Increment 5's quiz phrasing
call works.

Generation is idempotent: a lesson has at most one open-response question,
so a second call for the same lesson returns the existing one rather than
generating (and persisting) a new one.
"""

import logging
from typing import List, Optional, Tuple

from pydantic import BaseModel, Field, ValidationError

from models.lesson_models import GroundedClaim, Lesson, OpenResponseQuestion
from services.json_utils import extract_json_object
from services.lesson_generation import DEFAULT_LESSON_MODEL, LLMCallable, _default_llm_call
from services.lesson_repository import LessonRepository
from services.quiz_generation import _classify_provision_type

logger = logging.getLogger(__name__)

OPEN_RESPONSE_SYSTEM_PROMPT = """You are writing one open-ended civic-education question for a high-school
student about a bill, based only on the facts provided.

Depending on the facts given, write a question that asks the student to do ONE of the following:
- explain a stakeholder's perspective (why they might support or oppose the bill)
- explain a tradeoff the bill involves
- compare pro and con reasoning about the bill
- explain a challenge in implementing the bill
- predict an impact of the bill using the evidence given

Also write 2 to 4 short "expected_points" -- the key ideas a complete answer should include, based
only on the facts provided. Do not introduce facts, numbers, or claims that are not present in what
was given.

Return only structured JSON."""

_JSON_SCHEMA_INSTRUCTIONS = """Return ONLY a single JSON object (no markdown fences, no commentary) with exactly this shape:

{
  "question": "string",
  "expected_points": ["string", ...]
}"""


class OpenResponseGenerationError(Exception):
    """Raised when an open-response question cannot be produced (no lesson
    content to draw from, or the model's output is unparseable)."""


class _OpenResponseDraft(BaseModel):
    question: str = Field(min_length=1)
    expected_points: List[str] = Field(min_length=1)


def _select_question_material(lesson: Lesson) -> Tuple[str, List[GroundedClaim], List[str]]:
    """Pick a question_type and the grounded claims to build it from,
    preferring the richest available content: a pro/con comparison needs
    both sides argued, which is the most substantive material a lesson can
    offer; the rest fall back in order of how directly the lesson's
    sections cover them."""
    if lesson.pro_arguments and lesson.con_arguments:
        claims = list(lesson.pro_arguments) + list(lesson.con_arguments)
        return "pro_con_comparison", claims, [c.claim for c in claims]

    if lesson.stakeholders:
        return "stakeholder_perspective", list(lesson.stakeholders), [c.claim for c in lesson.stakeholders]

    implementation_claims = [c for c in lesson.major_provisions if _classify_provision_type(c.claim) == "implementation"]
    if implementation_claims:
        return "implementation_challenge", implementation_claims, [c.claim for c in implementation_claims]

    if lesson.major_provisions:
        return "impact_prediction", list(lesson.major_provisions), [c.claim for c in lesson.major_provisions]

    return "", [], []


def _build_prompt(question_type: str, claims: List[GroundedClaim]) -> str:
    fact_blocks = "\n".join(f"- [{'/'.join(c.section_ids)}] {c.claim}" for c in claims)
    return (
        f"Question focus: {question_type.replace('_', ' ')}\n\n"
        f"Facts to base the question on:\n{fact_blocks}\n\n"
        f"{_JSON_SCHEMA_INSTRUCTIONS}"
    )


def ground_open_response_draft(raw_text: str) -> _OpenResponseDraft:
    """Parse the model's JSON response. Unparseable output or a missing
    question/expected_points raises `OpenResponseGenerationError`."""
    try:
        data = extract_json_object(raw_text)
        return _OpenResponseDraft.model_validate(data)
    except (ValidationError, ValueError) as e:
        raise OpenResponseGenerationError(f"Model output failed schema validation: {e}") from e


class OpenResponseGenerationService:
    """Generates and persists the single open-response question for a lesson."""

    def __init__(
        self,
        repository: Optional[LessonRepository] = None,
        llm_call: Optional[LLMCallable] = None,
    ):
        self._repository = repository or LessonRepository()
        self._llm_call = llm_call or _default_llm_call

    async def generate_question(
        self, lesson_id: str, model: str = DEFAULT_LESSON_MODEL
    ) -> OpenResponseQuestion:
        lesson = self._repository.get_lesson(lesson_id)
        if lesson is None:
            raise OpenResponseGenerationError(f"No lesson found for lesson_id={lesson_id!r}")

        if lesson.open_response_question_id:
            existing = self._repository.get_open_response_question(lesson.open_response_question_id)
            if existing is not None:
                logger.info(
                    "open_response_generation cache_hit lesson_id=%s question_id=%s",
                    lesson_id, existing.question_id,
                )
                return existing

        question_type, claims, _ = _select_question_material(lesson)
        if not claims:
            raise OpenResponseGenerationError(
                f"No lesson content available to generate an open-response question for lesson_id={lesson_id!r}"
            )

        prompt = _build_prompt(question_type, claims)
        raw_text = await self._llm_call(OPEN_RESPONSE_SYSTEM_PROMPT, prompt, model)
        draft = ground_open_response_draft(raw_text)

        section_ids = sorted({sid for c in claims for sid in c.section_ids})
        context_excerpt = "\n".join(f"- {c.claim}" for c in claims)

        question = OpenResponseQuestion(
            question_id=f"{lesson_id}-open-response",
            lesson_id=lesson_id,
            question=draft.question,
            question_type=question_type,
            expected_points=draft.expected_points,
            section_ids=section_ids,
            context_excerpt=context_excerpt,
        )

        self._repository.create_open_response_question(question)
        lesson = lesson.model_copy(update={"open_response_question_id": question.question_id})
        self._repository.create_lesson(lesson)

        logger.info(
            "open_response_generation lesson_id=%s question_id=%s question_type=%s",
            lesson_id, question.question_id, question_type,
        )
        return question
