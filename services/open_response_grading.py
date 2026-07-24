"""Open-response answer grading for Lesson Mode (Increment 6).

Grading has two stages:

1. A lightweight, fully deterministic local pre-check (`local_precheck`)
   that catches blank, extremely short, question-copied, and semantically
   irrelevant answers *without calling the model at all* -- cheaper and
   perfectly stable for these degenerate cases, where an LLM call would add
   cost and a small chance of an inconsistent score.
2. If the pre-check doesn't fire, one model call grades the answer against
   the question's own `expected_points` and grounded `context_excerpt`
   (never the full bill), using temperature=0 for maximally deterministic
   scoring -- unlike lesson/vocabulary/quiz generation's temperature=0.3,
   there is no creative-writing goal here, only a rubric to apply
   consistently.
"""

import difflib
import logging
from typing import List, Optional

from pydantic import BaseModel, Field, ValidationError

from models.lesson_models import OpenResponseQuestion
from services.json_utils import extract_json_object
from services.lesson_generation import DEFAULT_LESSON_MODEL, LLMCallable
from services.rag.embeddings import get_embedding_provider

logger = logging.getLogger(__name__)

MIN_ANSWER_WORDS = 4
MIN_ANSWER_CHARS = 15
COPIED_SIMILARITY_THRESHOLD = 0.85
MIN_RELEVANCE_SIMILARITY = 0.15

GRADING_SYSTEM_PROMPT = """You are grading a high-school civic-education response.

Evaluate conceptual understanding and reasoning. Do not grade grammar or writing sophistication.

Use only:
- the question
- expected points
- the student's answer
- the supplied bill sections

Assign:
0 = incorrect or irrelevant
1 = partial understanding
2 = mostly correct but incomplete
3 = complete, accurate, and clearly reasoned

Identify:
- what the student understood correctly
- what important points were missed
- one specific way to improve

Do not claim the student said something that is absent from their answer.
Return only the required JSON."""

_GRADING_JSON_SCHEMA_INSTRUCTIONS = """Return ONLY a single JSON object (no markdown fences, no commentary) with exactly this shape:

{
  "score": 0,
  "feedback": "string -- specific feedback that references what the student actually wrote",
  "missed_points": ["string", ...],
  "accurate_points": ["string", ...],
  "section_ids": ["section-id", ...]
}

section_ids must come only from the "Relevant bill sections" listed below -- never invent one."""


class OpenResponseGradingError(Exception):
    """Raised when a grade cannot be produced (model output unparseable
    after all retry attempts)."""


class OpenResponseGrade(BaseModel):
    """The grading result -- not itself persisted; routes wrap this into an
    `OpenResponseAttempt` alongside the user_id/question_id/answer."""

    score: int = Field(ge=0, le=3)
    feedback: str = Field(min_length=1)
    missed_points: List[str] = Field(default_factory=list)
    accurate_points: List[str] = Field(default_factory=list)
    section_ids: List[str] = Field(default_factory=list)


class _GradeDraft(BaseModel):
    score: int = Field(ge=0, le=3)
    feedback: str = Field(min_length=1)
    missed_points: List[str] = Field(default_factory=list)
    accurate_points: List[str] = Field(default_factory=list)
    section_ids: List[str] = Field(default_factory=list)


async def _default_grading_llm_call(system_prompt: str, user_prompt: str, model: str) -> str:
    from chains.debater_chain import OpenRouterChat
    from langchain_core.messages import HumanMessage, SystemMessage

    llm = OpenRouterChat(model_name=model, temperature=0.0)  # deterministic: a rubric, not creative writing
    message = await llm.ainvoke(
        [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)]
    )
    return message.content


def _cosine_similarity(vec_a: List[float], vec_b: List[float]) -> float:
    import numpy as np

    a = np.array(vec_a, dtype=float)
    b = np.array(vec_b, dtype=float)
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float((a @ b) / (norm_a * norm_b))


def _is_blank(student_answer: str) -> bool:
    return not student_answer or not student_answer.strip()


def _is_too_short(student_answer: str) -> bool:
    stripped = student_answer.strip()
    if len(stripped) < MIN_ANSWER_CHARS:
        return True
    return len(stripped.split()) < MIN_ANSWER_WORDS


def _is_copied_from_question(student_answer: str, question: str) -> bool:
    ratio = difflib.SequenceMatcher(None, student_answer.strip().lower(), question.strip().lower()).ratio()
    return ratio >= COPIED_SIMILARITY_THRESHOLD


def _is_irrelevant(student_answer: str, question: OpenResponseQuestion) -> bool:
    reference = question.question + " " + " ".join(question.expected_points)
    provider = get_embedding_provider()
    texts = [student_answer, reference]
    provider.fit(texts)
    vectors = provider.embed_batch(texts)
    similarity = _cosine_similarity(vectors[0], vectors[1])
    return similarity < MIN_RELEVANCE_SIMILARITY


def local_precheck(question: OpenResponseQuestion, student_answer: str) -> Optional[OpenResponseGrade]:
    """Deterministically score degenerate answers without a model call.
    Returns `None` if the answer should proceed to real grading."""
    if _is_blank(student_answer):
        return OpenResponseGrade(
            score=0,
            feedback="You did not provide an answer, so no understanding could be assessed.",
            missed_points=list(question.expected_points),
        )

    if _is_too_short(student_answer):
        return OpenResponseGrade(
            score=0,
            feedback=(
                f'Your answer ("{student_answer.strip()}") is too short to demonstrate understanding. '
                "Try explaining your reasoning in a full sentence or two."
            ),
            missed_points=list(question.expected_points),
        )

    if _is_copied_from_question(student_answer, question.question):
        return OpenResponseGrade(
            score=0,
            feedback="Your answer restates the question rather than answering it. Try explaining the reasoning behind an answer.",
            missed_points=list(question.expected_points),
        )

    if _is_irrelevant(student_answer, question):
        return OpenResponseGrade(
            score=0,
            feedback=f'Your answer ("{student_answer.strip()}") does not appear to address the question asked.',
            missed_points=list(question.expected_points),
        )

    return None


def _build_grading_prompt(question: OpenResponseQuestion, student_answer: str) -> str:
    expected_points_block = "\n".join(f"- {p}" for p in question.expected_points)
    return (
        f"Question: {question.question}\n\n"
        f"Expected points (grading checklist):\n{expected_points_block}\n\n"
        f"Relevant bill sections: {', '.join(question.section_ids)}\n"
        f"Bill evidence excerpt:\n{question.context_excerpt}\n\n"
        f'Student\'s answer:\n"""\n{student_answer}\n"""\n\n'
        f"{_GRADING_JSON_SCHEMA_INSTRUCTIONS}"
    )


def ground_grade_draft(raw_text: str, known_section_ids: set) -> OpenResponseGrade:
    """Parse and validate the grading model's JSON response, dropping any
    section_id it cites that wasn't actually part of the question."""
    try:
        data = extract_json_object(raw_text)
        draft = _GradeDraft.model_validate(data)
    except (ValidationError, ValueError) as e:
        raise OpenResponseGradingError(f"Model output failed schema validation: {e}") from e

    filtered_section_ids = [sid for sid in draft.section_ids if sid in known_section_ids]
    return OpenResponseGrade(
        score=draft.score,
        feedback=draft.feedback,
        missed_points=draft.missed_points,
        accurate_points=draft.accurate_points,
        section_ids=filtered_section_ids,
    )


class OpenResponseGradingService:
    """Grades a student's open-response answer against its question."""

    def __init__(self, llm_call: Optional[LLMCallable] = None):
        self._llm_call = llm_call or _default_grading_llm_call

    async def grade_answer(
        self,
        question: OpenResponseQuestion,
        student_answer: str,
        model: str = DEFAULT_LESSON_MODEL,
        max_attempts: int = 2,
    ) -> OpenResponseGrade:
        precheck = local_precheck(question, student_answer)
        if precheck is not None:
            logger.info(
                "open_response_grading precheck_fired question_id=%s score=%d",
                question.question_id, precheck.score,
            )
            return precheck

        known_section_ids = set(question.section_ids)
        prompt = _build_grading_prompt(question, student_answer)

        last_error: Optional[Exception] = None
        for attempt in range(1, max_attempts + 1):
            raw_text = await self._llm_call(GRADING_SYSTEM_PROMPT, prompt, model)
            try:
                grade = ground_grade_draft(raw_text, known_section_ids)
                logger.info(
                    "open_response_grading question_id=%s attempt=%d score=%d",
                    question.question_id, attempt, grade.score,
                )
                return grade
            except OpenResponseGradingError as e:
                last_error = e
                logger.warning(
                    "open_response_grading question_id=%s attempt=%d failed: %s",
                    question.question_id, attempt, e,
                )

        raise OpenResponseGradingError(
            f"Could not produce a valid grade after {max_attempts} attempt(s): {last_error}"
        )
