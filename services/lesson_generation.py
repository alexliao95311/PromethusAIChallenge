"""Grounded lesson generation for Lesson Mode (Increment 2).

Flow: retrieve relevant bill sections (via `BillRagService`, not the full
bill) -> prompt the model for structured JSON -> validate with Pydantic ->
drop/regenerate any claim citing a section_id that wasn't actually
retrieved -> cache/persist the result.

Reuses `OpenRouterChat` from `chains.debater_chain` (DebateSim's existing
OpenRouter-backed chat model wrapper) for the underlying LLM call, rather
than building a second HTTP client. The multi-round, markdown-formatted
debate *template* in that module is not reused here -- it's built for a
live back-and-forth round structure with free-form prose output, which is
the wrong shape for a single-shot structured-JSON grounded claim; the pro/
con instructions below adapt its "weigh comparatively, engage with the
opponent's actual claims" reasoning style into that JSON shape instead.
"""

import logging
from typing import Awaitable, Callable, List, Optional, Set, Tuple

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field, ValidationError

from chains.debater_chain import OpenRouterChat
from models.lesson_models import GroundedClaim, Lesson
from services.json_utils import extract_json_object
from services.lesson_repository import LessonRepository
from services.rag.cache import compute_text_hash
from services.rag.retrieval_service import BillRagService, RetrievedSection

logger = logging.getLogger(__name__)

# Bumping this invalidates every cached lesson (cache key includes it), so
# a prompt-wording change doesn't silently serve stale-format lessons.
LESSON_PROMPT_VERSION = "v1"

DEFAULT_LESSON_MODEL = "openai/gpt-4o-mini"

RETRIEVAL_QUERIES = {
    "purpose": "What is the purpose of this bill and why was it proposed?",
    "requirements": "What are the major requirements and provisions of this bill?",
    "stakeholders": "Who are the stakeholders affected by this bill?",
    "benefits": "Who benefits from this bill and how?",
    "objections": "What are the costs, burdens, or objections to this bill?",
    "implementation": "How will this bill be implemented and by whom?",
}

CORE_LESSON_SYSTEM_PROMPT = """You are creating a neutral civic-education lesson for a high-school student.

Use only the provided bill sections. Do not introduce facts that are not supported by those sections.

For every factual claim, include the section_id or section_ids that support it.

Explain:
1. What the bill does
2. Why it was proposed
3. Who may benefit
4. Who may face costs or disadvantages
5. How the bill would be implemented
6. The strongest grounded argument supporting it
7. The strongest grounded argument opposing it

Use plain language. Define technical terms. Clearly separate facts from reasonable interpretations.

When writing the strongest supporting and opposing arguments, reason like a debater: only argue
points the bill text actually supports, weigh impact (who is affected, how much, how directly),
and engage with the substance of the provision rather than vague generalities. Keep both sides
fair and grounded -- do not strawman the opposing side.

Return only the required JSON structure."""

_JSON_SCHEMA_INSTRUCTIONS = """Return ONLY a single JSON object (no markdown fences, no commentary) with exactly this shape:

{
  "lesson_title": "string",
  "plain_language_summary": "string",
  "learning_objectives": ["string", ...],
  "major_provisions": [{"claim": "string", "section_ids": ["section-id", ...]}, ...],
  "stakeholders": [{"claim": "string", "section_ids": ["section-id", ...]}, ...],
  "pro_arguments": [{"claim": "string", "section_ids": ["section-id", ...]}, ...],
  "con_arguments": [{"claim": "string", "section_ids": ["section-id", ...]}, ...]
}

Every item in major_provisions, stakeholders, pro_arguments, and con_arguments MUST include at
least one section_id drawn ONLY from the "Available sections" list below. Never invent a
section_id. Include at least one pro_argument and at least one con_argument."""


class LessonGenerationError(Exception):
    """Raised when a grounded lesson cannot be produced (e.g. model output
    is unparseable, or no valid grounded pro/con arguments survive
    validation after all retry attempts)."""


class _LessonDraft(BaseModel):
    """The model's raw structured output, before section_id validation and
    before bookkeeping fields (lesson_id, bill_id, prompt_version, ...) are
    attached."""

    lesson_title: str = Field(min_length=1)
    plain_language_summary: str = Field(min_length=1)
    learning_objectives: List[str] = Field(default_factory=list)
    major_provisions: List[GroundedClaim] = Field(default_factory=list)
    stakeholders: List[GroundedClaim] = Field(default_factory=list)
    pro_arguments: List[GroundedClaim] = Field(default_factory=list)
    con_arguments: List[GroundedClaim] = Field(default_factory=list)


LLMCallable = Callable[[str, str, str], Awaitable[str]]


async def _default_llm_call(system_prompt: str, user_prompt: str, model: str) -> str:
    llm = OpenRouterChat(model_name=model, temperature=0.3)
    message = await llm.ainvoke(
        [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)]
    )
    return message.content


def ground_lesson_draft(
    raw_text: str, known_section_ids: Set[str]
) -> Tuple[_LessonDraft, List[str]]:
    """Parse the model's raw JSON response and drop any claim citing a
    section_id outside `known_section_ids`.

    Returns the grounded draft plus a list of human-readable descriptions of
    dropped/trimmed claims, for logging. A claim keeps only its valid
    section_ids; if none of its section_ids are valid, the whole claim is
    dropped rather than left uncited.
    """
    try:
        data = extract_json_object(raw_text)
        draft = _LessonDraft.model_validate(data)
    except (ValidationError, ValueError) as e:
        raise LessonGenerationError(f"Model output failed schema validation: {e}") from e

    dropped: List[str] = []

    def _filter(claims: List[GroundedClaim]) -> List[GroundedClaim]:
        kept = []
        for claim in claims:
            valid_ids = [sid for sid in claim.section_ids if sid in known_section_ids]
            if valid_ids:
                if len(valid_ids) != len(claim.section_ids):
                    dropped.append(
                        f"trimmed invalid section_ids on claim {claim.claim!r}: "
                        f"{set(claim.section_ids) - known_section_ids}"
                    )
                kept.append(GroundedClaim(claim=claim.claim, section_ids=valid_ids))
            else:
                dropped.append(f"dropped ungrounded claim {claim.claim!r}")
        return kept

    draft.major_provisions = _filter(draft.major_provisions)
    draft.stakeholders = _filter(draft.stakeholders)
    draft.pro_arguments = _filter(draft.pro_arguments)
    draft.con_arguments = _filter(draft.con_arguments)

    return draft, dropped


def _build_user_prompt(bill_id: str, sections: List[RetrievedSection]) -> str:
    section_blocks = "\n\n".join(
        f"[{s.section_id}] {s.heading}\n{s.text}" for s in sections
    )
    return (
        f"Bill ID: {bill_id}\n\n"
        f"Available sections (cite ONLY these section_ids):\n\n{section_blocks}\n\n"
        f"{_JSON_SCHEMA_INSTRUCTIONS}"
    )


class LessonGenerationService:
    """Generates a grounded, structured civic-education lesson for a bill."""

    def __init__(
        self,
        rag_service: Optional[BillRagService] = None,
        repository: Optional[LessonRepository] = None,
        llm_call: Optional[LLMCallable] = None,
    ):
        self._rag_service = rag_service or BillRagService()
        self._repository = repository or LessonRepository()
        self._llm_call = llm_call or _default_llm_call

    @staticmethod
    def compute_lesson_id(bill_id: str, bill_text_hash: str) -> str:
        return f"{bill_id}::{LESSON_PROMPT_VERSION}::{bill_text_hash[:16]}"

    def _retrieve_context_sections(
        self, bill_id: str, bill_text: str, top_k_per_query: int = 5
    ) -> List[RetrievedSection]:
        by_id = {}
        for query in RETRIEVAL_QUERIES.values():
            for section in self._rag_service.retrieve_relevant_sections(
                bill_id=bill_id, query=query, top_k=top_k_per_query, bill_text=bill_text
            ):
                existing = by_id.get(section.section_id)
                if existing is None or section.similarity_score > existing.similarity_score:
                    by_id[section.section_id] = section
        return list(by_id.values())

    async def generate_lesson(
        self,
        bill_id: str,
        bill_text: str,
        model: str = DEFAULT_LESSON_MODEL,
        max_attempts: int = 2,
    ) -> Lesson:
        """Generate (or reuse a cached) grounded lesson for `bill_id`.

        Cached by bill_id + bill_text_hash + LESSON_PROMPT_VERSION: an
        unchanged bill returns the same lesson without calling the model
        again; a changed bill or a bumped prompt version produces a fresh
        one.
        """
        if not bill_text or not bill_text.strip():
            raise ValueError("bill_text must not be empty")

        bill_text_hash = compute_text_hash(bill_text)
        lesson_id = self.compute_lesson_id(bill_id, bill_text_hash)

        cached = self._repository.get_lesson(lesson_id)
        if cached is not None:
            logger.info("lesson_generation cache_hit bill_id=%s lesson_id=%s", bill_id, lesson_id)
            return cached
        logger.info("lesson_generation cache_miss bill_id=%s lesson_id=%s", bill_id, lesson_id)

        context_sections = self._retrieve_context_sections(bill_id, bill_text)
        if not context_sections:
            raise LessonGenerationError(
                f"No bill sections could be retrieved for bill_id={bill_id!r}"
            )
        known_section_ids = {s.section_id for s in context_sections}

        user_prompt = _build_user_prompt(bill_id, context_sections)
        system_prompt = CORE_LESSON_SYSTEM_PROMPT

        draft: Optional[_LessonDraft] = None
        dropped_report: List[str] = []
        for attempt in range(1, max_attempts + 1):
            raw_text = await self._llm_call(system_prompt, user_prompt, model)
            draft, dropped_report = ground_lesson_draft(raw_text, known_section_ids)

            has_pro = len(draft.pro_arguments) > 0
            has_con = len(draft.con_arguments) > 0
            if has_pro and has_con:
                break

            logger.warning(
                "lesson_generation attempt=%d bill_id=%s missing_pro=%s missing_con=%s dropped=%s",
                attempt, bill_id, not has_pro, not has_con, dropped_report,
            )
            if attempt < max_attempts:
                user_prompt = (
                    _build_user_prompt(bill_id, context_sections)
                    + "\n\nYour previous response was missing a grounded pro_argument or "
                    "con_argument, or cited section_ids that do not exist. Every argument "
                    "must cite a real section_id from the list above. Include at least one "
                    "pro_argument and one con_argument."
                )

        if draft is None or not draft.pro_arguments or not draft.con_arguments:
            raise LessonGenerationError(
                "Could not produce a grounded lesson with both a pro and a con argument "
                f"after {max_attempts} attempt(s). Dropped: {dropped_report}"
            )

        if dropped_report:
            logger.info(
                "lesson_generation bill_id=%s dropped_ungrounded_claims=%s", bill_id, dropped_report
            )

        source_sections = sorted(
            {
                sid
                for claims in (
                    draft.major_provisions,
                    draft.stakeholders,
                    draft.pro_arguments,
                    draft.con_arguments,
                )
                for claim in claims
                for sid in claim.section_ids
            }
        )

        lesson = Lesson(
            lesson_id=lesson_id,
            bill_id=bill_id,
            prompt_version=LESSON_PROMPT_VERSION,
            bill_text_hash=bill_text_hash,
            lesson_title=draft.lesson_title,
            plain_language_summary=draft.plain_language_summary,
            learning_objectives=draft.learning_objectives,
            major_provisions=draft.major_provisions,
            stakeholders=draft.stakeholders,
            pro_arguments=draft.pro_arguments,
            con_arguments=draft.con_arguments,
            source_sections=source_sections,
        )

        self._repository.create_lesson(lesson)
        logger.info("lesson_generation saved bill_id=%s lesson_id=%s", bill_id, lesson_id)
        return lesson
