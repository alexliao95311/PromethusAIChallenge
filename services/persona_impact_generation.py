"""Personalized bill-impact generation for Lesson Mode (Increment 8).

Given a student's (possibly fictional) persona and an already-generated,
grounded lesson, this produces a short persona-specific explanation of how
the bill could affect someone like them -- separated into effects the bill
text clearly establishes (`direct_impacts`), effects that depend on
implementation or behavior (`possible_indirect_impacts`), and what remains
uncertain (`uncertainties`, often because the persona omitted a detail).

Grounding discipline mirrors lesson/quiz/open-response generation:
- RAG (`BillRagService`) retrieves the bill sections most relevant to *this
  persona* (queries are built from the persona's own attributes), so two
  different personas are shown different provisions -- the source of the
  personalization -- rather than the same generic summary.
- The model may cite only those retrieved section_ids. Every cited id is
  validated against the retrieved set (`_ground_impact_draft`); an impact
  whose cited sections are all invalid is dropped, never stored uncited.
- Confidence is never inflated: if nothing is *directly* established, the
  overall confidence is capped so the narrative can't claim the bill
  definitely affects the student.

Reuses `_default_llm_call` / `DEFAULT_LESSON_MODEL` and the shared JSON
helper rather than introducing a second LLM client or parser.
"""

import json
import logging
from typing import List, Optional, Tuple

from pydantic import BaseModel, Field, ValidationError

from models.lesson_models import (
    ImpactConfidence,
    Lesson,
    PersonaProfile,
    PersonalImpact,
    PersonalImpactNarrative,
)
from services.json_utils import extract_json_object
from services.lesson_generation import DEFAULT_LESSON_MODEL, LLMCallable, _default_llm_call
from services.lesson_repository import LessonRepository
from services.rag.cache import compute_text_hash
from services.rag.retrieval_service import BillRagService, RetrievedSection

logger = logging.getLogger(__name__)

# Bumping this invalidates every cached narrative (the cache key includes it).
IMPACT_PROMPT_VERSION = "v1"

# Cap how many retrieved sections are handed to the model, to bound prompt size.
MAX_CITABLE_SECTIONS = 10
TOP_K_PER_QUERY = 4

_CONFIDENCE_RANK = {"low": 0, "medium": 1, "high": 2}


PERSONAL_IMPACT_SYSTEM_PROMPT = """You are a neutral civic-education assistant. Explain how a proposed bill could affect a
fictional person described by a persona, using ONLY the provided bill sections.

Separate your analysis into:
1. Direct effects that are clearly established by the bill text
2. Possible indirect effects that depend on implementation or on how people behave
3. Information that remains uncertain (for example, when the persona does not specify a needed detail)

For every direct or indirect impact:
- explain the reasoning in plain language
- cite the supporting section_ids (only from the provided sections)
- assign a confidence of high, medium, or low

Rules:
- Do NOT claim the bill definitely affects the person unless the bill text clearly establishes it.
  When in doubt, describe it as a possible indirect effect or an uncertainty, and lower the confidence.
- Do NOT assume the person's political beliefs, race, religion, health, or any sensitive trait
  beyond what the persona states. If a detail is missing, treat it as an uncertainty.
- Present BOTH potential benefits and potential costs when the text supports them.
- Keep the tone educational and non-partisan. Do not try to persuade the reader for or against the bill.

Return only structured JSON."""

_JSON_SCHEMA_INSTRUCTIONS = """Return ONLY a single JSON object (no markdown fences, no commentary) with exactly this shape:

{
  "narrative": "string (2-4 plain-language sentences addressed to the persona)",
  "direct_impacts": [{"impact": "string", "reasoning": "string", "section_ids": ["section-id", ...], "confidence": "high|medium|low"}, ...],
  "possible_indirect_impacts": [{"impact": "string", "reasoning": "string", "section_ids": ["section-id", ...], "confidence": "high|medium|low"}, ...],
  "uncertainties": ["string", ...],
  "questions_to_consider": ["string", ...],
  "confidence": "high|medium|low"
}

Every section_id in direct_impacts and possible_indirect_impacts MUST be drawn ONLY from the
"Available sections" list below. Never invent a section_id. Do not put section_ids in
uncertainties or questions_to_consider."""


class PersonaImpactGenerationError(Exception):
    """Raised when a personal-impact narrative cannot be produced (no bill
    sections could be retrieved, or the model output is unparseable)."""


class _ImpactItemDraft(BaseModel):
    impact: str = Field(min_length=1)
    reasoning: str = Field(min_length=1)
    section_ids: List[str] = Field(default_factory=list)
    confidence: str = "low"


class _PersonalImpactDraft(BaseModel):
    narrative: str = Field(min_length=1)
    direct_impacts: List[_ImpactItemDraft] = Field(default_factory=list)
    possible_indirect_impacts: List[_ImpactItemDraft] = Field(default_factory=list)
    uncertainties: List[str] = Field(default_factory=list)
    questions_to_consider: List[str] = Field(default_factory=list)
    confidence: str = "low"


def _normalize_confidence(value: str) -> ImpactConfidence:
    """Map any model-provided confidence to one of high/medium/low, defaulting
    to the most conservative ('low') for anything unrecognized."""
    v = (value or "").strip().lower()
    return v if v in _CONFIDENCE_RANK else "low"


class GroundedImpacts(BaseModel):
    """The result of validating a raw impact draft against the retrieved
    section_ids -- carrying only impacts whose citations survived."""

    narrative: str
    direct_impacts: List[PersonalImpact]
    possible_indirect_impacts: List[PersonalImpact]
    uncertainties: List[str]
    questions_to_consider: List[str]
    confidence: ImpactConfidence
    section_ids: List[str]
    dropped: List[str]


def _filter_impacts(
    items: List[_ImpactItemDraft], known_section_ids: set
) -> Tuple[List[PersonalImpact], List[str]]:
    """Keep only impacts that cite at least one *retrieved* section_id; trim
    away invalid ids and drop wholly-ungrounded impacts (mirrors
    lesson_generation.ground_lesson_draft)."""
    kept: List[PersonalImpact] = []
    dropped: List[str] = []
    for item in items:
        valid_ids = [sid for sid in item.section_ids if sid in known_section_ids]
        if not valid_ids:
            dropped.append(f"dropped ungrounded impact {item.impact!r}")
            continue
        if len(valid_ids) != len(item.section_ids):
            dropped.append(
                f"trimmed invalid section_ids on impact {item.impact!r}: "
                f"{set(item.section_ids) - known_section_ids}"
            )
        kept.append(
            PersonalImpact(
                impact=item.impact,
                reasoning=item.reasoning,
                section_ids=valid_ids,
                confidence=_normalize_confidence(item.confidence),
            )
        )
    return kept, dropped


def _ground_impact_draft(raw_text: str, known_section_ids: set) -> GroundedImpacts:
    """Parse + validate the model's JSON, drop ungrounded impacts, and cap
    overall confidence so an ungrounded narrative can't claim certainty."""
    try:
        data = extract_json_object(raw_text)
        draft = _PersonalImpactDraft.model_validate(data)
    except (ValidationError, ValueError) as e:
        raise PersonaImpactGenerationError(f"Model output failed schema validation: {e}") from e

    direct, dropped_direct = _filter_impacts(draft.direct_impacts, known_section_ids)
    indirect, dropped_indirect = _filter_impacts(draft.possible_indirect_impacts, known_section_ids)
    dropped = dropped_direct + dropped_indirect

    overall = _normalize_confidence(draft.confidence)
    # Requirement 2: never claim the bill definitely affects the student unless
    # the bill text clearly establishes it. With no surviving *direct* impact,
    # a "high" overall confidence would overstate certainty -> cap at medium.
    if not direct and _CONFIDENCE_RANK[overall] > _CONFIDENCE_RANK["medium"]:
        overall = "medium"

    section_ids = sorted(
        {sid for impact in (direct + indirect) for sid in impact.section_ids}
    )

    return GroundedImpacts(
        narrative=draft.narrative,
        direct_impacts=direct,
        possible_indirect_impacts=indirect,
        uncertainties=list(draft.uncertainties),
        questions_to_consider=list(draft.questions_to_consider),
        confidence=overall,
        section_ids=section_ids,
        dropped=dropped,
    )


def _build_persona_queries(persona: PersonaProfile) -> List[str]:
    """Build RAG queries from the persona's own attributes so retrieval --
    and therefore the resulting narrative -- actually varies by persona."""
    attrs = persona.to_impact_representation()["attributes"]
    queries = ["How could this bill affect an individual person and their household?"]
    if attrs.get("occupation"):
        queries.append(f"How could this bill affect someone who works in {attrs['occupation']}?")
    if attrs.get("state_name"):
        queries.append(
            f"How could this bill affect residents of {attrs['state_name']} "
            "or state and local governments?"
        )
    if attrs.get("income_bracket"):
        queries.append(
            f"How could this bill affect households with an income of {attrs['income_bracket']}?"
        )
    if attrs.get("age_range"):
        queries.append(
            f"How could this bill affect people in the {attrs['age_range']} age range?"
        )
    return queries


def _persona_hash(persona: PersonaProfile) -> str:
    """Stable hash of the persona attributes actually used, so the same
    persona reuses a cached narrative and a different one regenerates."""
    attrs = persona.to_impact_representation()["attributes"]
    canonical = json.dumps(attrs, sort_keys=True)
    return compute_text_hash(canonical)


def _build_user_prompt(
    persona: PersonaProfile, lesson: Lesson, sections: List[RetrievedSection]
) -> str:
    rep = persona.to_impact_representation()
    descriptor = rep["descriptor"] or "No persona details were provided."
    section_blocks = "\n\n".join(
        f"[{s.section_id}] {s.heading}\n{s.text}" for s in sections
    )
    return (
        "Persona (may be fictional; treat as given, do not infer anything beyond it):\n"
        f"{descriptor}\n\n"
        f"Lesson summary (for context only):\n{lesson.lesson_title}\n"
        f"{lesson.plain_language_summary}\n\n"
        f"Available sections (cite ONLY these section_ids):\n\n{section_blocks}\n\n"
        f"{_JSON_SCHEMA_INSTRUCTIONS}"
    )


class PersonaImpactGenerationService:
    """Generates and persists a persona-specific, grounded bill-impact narrative."""

    def __init__(
        self,
        rag_service: Optional[BillRagService] = None,
        repository: Optional[LessonRepository] = None,
        llm_call: Optional[LLMCallable] = None,
    ):
        self._rag_service = rag_service or BillRagService()
        self._repository = repository or LessonRepository()
        self._llm_call = llm_call or _default_llm_call

    @property
    def repository(self) -> LessonRepository:
        return self._repository

    @staticmethod
    def compute_impact_id(lesson_id: str, persona_hash: str) -> str:
        return f"{lesson_id}::impact::{IMPACT_PROMPT_VERSION}::{persona_hash[:16]}"

    def _retrieve_persona_sections(
        self, persona: PersonaProfile, lesson: Lesson, bill_text: Optional[str]
    ) -> List[RetrievedSection]:
        by_id = {}
        for query in _build_persona_queries(persona):
            for section in self._rag_service.retrieve_relevant_sections(
                bill_id=lesson.bill_id, query=query, top_k=TOP_K_PER_QUERY, bill_text=bill_text
            ):
                existing = by_id.get(section.section_id)
                if existing is None or section.similarity_score > existing.similarity_score:
                    by_id[section.section_id] = section
        ranked = sorted(by_id.values(), key=lambda s: s.similarity_score, reverse=True)
        return ranked[:MAX_CITABLE_SECTIONS]

    async def generate_impact(
        self,
        persona: PersonaProfile,
        lesson: Lesson,
        bill_text: Optional[str] = None,
        model: str = DEFAULT_LESSON_MODEL,
    ) -> PersonalImpactNarrative:
        """Generate (or reuse a cached) grounded personal-impact narrative for
        `persona` against `lesson`. Cached by lesson_id + persona hash +
        IMPACT_PROMPT_VERSION, so the same persona on the same bill is
        idempotent and a different persona regenerates."""
        persona_hash = _persona_hash(persona)
        impact_id = self.compute_impact_id(lesson.lesson_id, persona_hash)

        cached = self._repository.get_personal_impact_narrative(impact_id)
        if cached is not None:
            logger.info(
                "persona_impact cache_hit lesson_id=%s impact_id=%s", lesson.lesson_id, impact_id
            )
            return cached

        sections = self._retrieve_persona_sections(persona, lesson, bill_text)
        if not sections:
            raise PersonaImpactGenerationError(
                f"No bill sections could be retrieved for bill_id={lesson.bill_id!r}"
            )
        known_section_ids = {s.section_id for s in sections}

        prompt = _build_user_prompt(persona, lesson, sections)
        raw_text = await self._llm_call(PERSONAL_IMPACT_SYSTEM_PROMPT, prompt, model)
        grounded = _ground_impact_draft(raw_text, known_section_ids)

        if grounded.dropped:
            logger.info(
                "persona_impact lesson_id=%s dropped=%s", lesson.lesson_id, grounded.dropped
            )

        narrative = PersonalImpactNarrative(
            impact_id=impact_id,
            lesson_id=lesson.lesson_id,
            bill_id=lesson.bill_id,
            user_id=persona.user_id,
            prompt_version=IMPACT_PROMPT_VERSION,
            persona=persona.to_impact_representation(),
            narrative=grounded.narrative,
            direct_impacts=grounded.direct_impacts,
            possible_indirect_impacts=grounded.possible_indirect_impacts,
            uncertainties=grounded.uncertainties,
            questions_to_consider=grounded.questions_to_consider,
            confidence=grounded.confidence,
            section_ids=grounded.section_ids,
        )

        self._repository.create_personal_impact_narrative(narrative)
        logger.info(
            "persona_impact saved lesson_id=%s impact_id=%s direct=%d indirect=%d confidence=%s",
            lesson.lesson_id, impact_id, len(grounded.direct_impacts),
            len(grounded.possible_indirect_impacts), grounded.confidence,
        )
        return narrative
