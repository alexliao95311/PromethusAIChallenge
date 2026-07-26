"""Post-debate reflection and educational feedback for Lesson Mode
(Increment 10).

After a student finishes a Lesson Mode debate (Increment 9's dynamic
opposing persona), they self-report whether their view of the bill changed
and optionally why. Separately, this module runs an *educational* judge
analysis of the same transcript -- reusing `OpenRouterChat`, the same
underlying model class `chains/judge_chain.py` already uses to judge
debates -- but with its own rubric that never determines a winner and never
infers belief change from debate performance. `view_changed` always comes
from the student's own self-report; the model is never asked for it and
never allowed to override it.

Grounding discipline mirrors the rest of Lesson Mode: every feedback item
the model attaches a `transcript_excerpt` to is verified as an actual
(whitespace-normalized) substring of the transcript. An excerpt that
doesn't verify is dropped -- the feedback text itself is kept, just without
an unverified quote -- rather than failing the whole response, since one
ungrounded excerpt shouldn't discard four grounded ones.
"""

import logging
import re
from typing import List, Optional

from pydantic import BaseModel, Field, ValidationError

from chains.judge_chain import OpenRouterChat
from langchain_core.messages import HumanMessage, SystemMessage

from models.lesson_models import DebateReflection, ReflectionFeedbackItem, ViewChangeResponse
from services.json_utils import extract_json_object
from services.lesson_generation import DEFAULT_LESSON_MODEL, LLMCallable
from services.lesson_repository import LessonRepository

logger = logging.getLogger(__name__)

REFLECTION_PROMPT_VERSION = "v1"

EDUCATIONAL_JUDGE_SYSTEM_PROMPT = """You are an educational debate coach analyzing a debate transcript for a
high-school student's learning -- you are NOT determining who won the debate.

This is a SEPARATE rubric from winner-determination: do not declare a winner and do not weigh which
side had the stronger overall case. Focus only on the STUDENT's individual growth.

Evaluate only what is actually present in the transcript. Do not invent or paraphrase-as-a-quote
anything the student or their opponent did not actually say.

You do NOT know whether the student's view changed as a result of this debate -- that is
self-reported separately by the student. Never infer or comment on belief change from debate
performance alone.

Identify:
1. strongest_student_argument -- the student's single best argument, with a short verbatim excerpt
2. weakest_reasoning_step -- a specific place the student's reasoning was weak or unsupported, with a short verbatim excerpt
3. evidence_use_feedback -- how well the student used evidence or examples, with a short verbatim excerpt if one exists
4. missed_opponent_point -- a substantive point the opponent made that the student never addressed, with a short verbatim excerpt from the opponent's side
5. perspective_understanding -- how well the student engaged with and accurately represented the opposing perspective, with a short verbatim excerpt
6. recommended_skill -- ONE specific debate or reasoning skill to practice next (a short phrase)
7. recommended_next_activity -- ONE concrete next step within this app (e.g. "retake the quiz", "debate this bill again from the opposing side", "review the vocabulary flashcards")

Keep excerpts short (under 200 characters) and copy them verbatim from the transcript. If no
excerpt genuinely supports a point, omit it (use null) rather than inventing one. Return only
structured JSON."""

_JSON_SCHEMA_INSTRUCTIONS = """Return ONLY a single JSON object (no markdown fences, no commentary) with exactly this shape:

{
  "strongest_student_argument": {"feedback": "string", "transcript_excerpt": "string or null"},
  "weakest_reasoning_step": {"feedback": "string", "transcript_excerpt": "string or null"},
  "evidence_use_feedback": {"feedback": "string", "transcript_excerpt": "string or null"},
  "missed_opponent_point": {"feedback": "string", "transcript_excerpt": "string or null"},
  "perspective_understanding": {"feedback": "string", "transcript_excerpt": "string or null"},
  "recommended_skill": "string",
  "recommended_next_activity": "string"
}

Every transcript_excerpt MUST be copied verbatim from the transcript below, or be null."""


class ReflectionGenerationError(Exception):
    """Raised when an educational judge analysis cannot be produced (empty
    transcript, or model output unparseable after all retry attempts)."""


class _ReflectionFeedbackItemDraft(BaseModel):
    feedback: str = Field(min_length=1)
    transcript_excerpt: Optional[str] = None


class _EducationalAnalysisDraft(BaseModel):
    strongest_student_argument: _ReflectionFeedbackItemDraft
    weakest_reasoning_step: _ReflectionFeedbackItemDraft
    evidence_use_feedback: _ReflectionFeedbackItemDraft
    missed_opponent_point: _ReflectionFeedbackItemDraft
    perspective_understanding: _ReflectionFeedbackItemDraft
    recommended_skill: str = Field(min_length=1)
    recommended_next_activity: str = Field(min_length=1)


async def _default_educational_judge_call(system_prompt: str, user_prompt: str, model: str) -> str:
    # Reuses the same OpenRouterChat model class chains/judge_chain.py's
    # winner-determination judge uses, rather than a second HTTP client.
    llm = OpenRouterChat(model_name=model, temperature=0.3)
    message = await llm.ainvoke(
        [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)]
    )
    return message.content


def _normalize_for_match(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def _verify_excerpt(excerpt: Optional[str], transcript: str) -> Optional[str]:
    """Keep an excerpt only if it's an actual (whitespace-normalized)
    substring of the transcript; otherwise drop it."""
    if not excerpt or not excerpt.strip():
        return None
    normalized_excerpt = _normalize_for_match(excerpt)
    if normalized_excerpt and normalized_excerpt in _normalize_for_match(transcript):
        return excerpt.strip()
    return None


def _build_prompt(transcript: str) -> str:
    return (
        f"DEBATE TRANSCRIPT:\n{transcript}\n\n{_JSON_SCHEMA_INSTRUCTIONS}"
    )


def _ground_analysis_draft(raw_text: str, transcript: str) -> tuple:
    """Parse + validate the model's JSON, then verify every transcript_excerpt
    against the actual transcript. Returns (grounded_items_dict, dropped)."""
    try:
        data = extract_json_object(raw_text)
        draft = _EducationalAnalysisDraft.model_validate(data)
    except (ValidationError, ValueError) as e:
        raise ReflectionGenerationError(f"Model output failed schema validation: {e}") from e

    dropped: List[str] = []

    def _grounded_item(field_name: str, item: _ReflectionFeedbackItemDraft) -> ReflectionFeedbackItem:
        verified = _verify_excerpt(item.transcript_excerpt, transcript)
        if item.transcript_excerpt and verified is None:
            dropped.append(f"ungrounded excerpt on {field_name}: {item.transcript_excerpt!r}")
        return ReflectionFeedbackItem(feedback=item.feedback, transcript_excerpt=verified)

    items = {
        "strongest_student_argument": _grounded_item(
            "strongest_student_argument", draft.strongest_student_argument
        ),
        "weakest_reasoning_step": _grounded_item(
            "weakest_reasoning_step", draft.weakest_reasoning_step
        ),
        "evidence_use_feedback": _grounded_item(
            "evidence_use_feedback", draft.evidence_use_feedback
        ),
        "missed_opponent_point": _grounded_item(
            "missed_opponent_point", draft.missed_opponent_point
        ),
        "perspective_understanding": _grounded_item(
            "perspective_understanding", draft.perspective_understanding
        ),
    }
    return items, draft.recommended_skill, draft.recommended_next_activity, dropped


class ReflectionGenerationService:
    """Generates and persists a post-debate reflection: the student's
    self-reported view-change response plus a grounded educational judge
    analysis of the debate transcript."""

    def __init__(
        self,
        repository: Optional[LessonRepository] = None,
        llm_call: Optional[LLMCallable] = None,
    ):
        self._repository = repository or LessonRepository()
        self._llm_call = llm_call or _default_educational_judge_call

    @property
    def repository(self) -> LessonRepository:
        return self._repository

    async def generate_reflection(
        self,
        reflection_id: str,
        lesson_id: str,
        user_id: str,
        transcript: str,
        view_changed: ViewChangeResponse,
        explanation: Optional[str] = None,
        persona_id: Optional[str] = None,
        model: str = DEFAULT_LESSON_MODEL,
        max_attempts: int = 2,
    ) -> DebateReflection:
        if not transcript or not transcript.strip():
            raise ValueError("transcript must not be empty")

        prompt = _build_prompt(transcript)

        last_error: Optional[Exception] = None
        items = recommended_skill = recommended_next_activity = None
        for attempt in range(1, max_attempts + 1):
            raw_text = await self._llm_call(EDUCATIONAL_JUDGE_SYSTEM_PROMPT, prompt, model)
            try:
                items, recommended_skill, recommended_next_activity, dropped = _ground_analysis_draft(
                    raw_text, transcript
                )
                if dropped:
                    logger.info(
                        "reflection_generation lesson_id=%s dropped=%s", lesson_id, dropped
                    )
                break
            except ReflectionGenerationError as e:
                last_error = e
                logger.warning(
                    "reflection_generation lesson_id=%s attempt=%d failed: %s",
                    lesson_id, attempt, e,
                )
        else:
            raise ReflectionGenerationError(
                f"Could not produce a valid educational analysis after {max_attempts} attempt(s): {last_error}"
            )

        reflection = DebateReflection(
            reflection_id=reflection_id,
            lesson_id=lesson_id,
            user_id=user_id,
            persona_id=persona_id,
            view_changed=view_changed,
            explanation=explanation,
            recommended_skill=recommended_skill,
            recommended_next_activity=recommended_next_activity,
            **items,
        )
        self._repository.create_debate_reflection(reflection)
        logger.info(
            "reflection_generation saved lesson_id=%s reflection_id=%s view_changed=%s",
            lesson_id, reflection_id, view_changed,
        )
        return reflection

    def get_progress(self, user_id: str) -> List[DebateReflection]:
        """Every reflection this user has submitted across every lesson
        debate, oldest first."""
        return self._repository.list_debate_reflections(user_id)
