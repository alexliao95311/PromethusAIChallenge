"""Bill-specific vocabulary card generation for Lesson Mode (Increment 3).

Flow: retrieve the same relevant bill sections used for lesson generation
(via `BillRagService`) -> prompt the model for 6-12 vocabulary cards ->
validate/ground/dedupe/cap -> regenerate once for any invalid card ->
persist alongside the lesson.
"""

import logging
import re
from typing import List, Optional, Set, Tuple

from pydantic import BaseModel, Field, ValidationError

from models.lesson_models import Flashcard
from services.json_utils import extract_json_object
from services.lesson_generation import (
    DEFAULT_LESSON_MODEL,
    RETRIEVAL_QUERIES,
    LLMCallable,
    _default_llm_call,
)
from services.lesson_repository import LessonRepository
from services.rag.retrieval_service import BillRagService, RetrievedSection

logger = logging.getLogger(__name__)

MIN_CARDS = 6
MAX_CARDS = 12
MAX_DEFINITION_LENGTH = 300
_VALID_DIFFICULTIES = {"beginner", "intermediate", "advanced"}
_GENERIC_TERM_PATTERN = re.compile(r"^(SEC(?:TION)?\.?\s*\d+[A-Za-z]?)\.?$", re.IGNORECASE)

VOCAB_SYSTEM_PROMPT = """Select the most educationally important terms from the provided bill sections.

A good term is:
- necessary to understand the bill
- potentially unfamiliar to a high-school student
- used meaningfully in the bill

For each term:
- define it in plain language
- explain how it is used in this specific bill
- provide a short example
- cite exactly one primary source section_id

Do not invent terms that do not appear in or directly explain the provided sections.
Do not select generic words, people's names, or section numbers as terms unless they
are themselves educationally important to understanding the bill.
Return only structured JSON."""

_VOCAB_JSON_SCHEMA_INSTRUCTIONS = """Return ONLY a single JSON object (no markdown fences, no commentary) with exactly this shape:

{
  "vocabulary": [
    {
      "term": "string",
      "simple_definition": "string (a sentence or two, plain language)",
      "bill_context": "string explaining how this term is used in THIS bill",
      "example": "string, a short concrete example",
      "section_id": "one section_id from the Available sections list",
      "difficulty": "beginner" | "intermediate" | "advanced"
    },
    ...
  ]
}

Produce between 6 and 12 cards if enough distinct, meaningful terms exist in the sections;
fewer is fine if the sections do not contain that many. Every section_id MUST come from the
"Available sections" list below -- never invent one. Do not repeat the same term twice."""


class VocabularyGenerationError(Exception):
    """Raised when the model's vocabulary response cannot be parsed at all."""


class _VocabCardDraft(BaseModel):
    term: str = Field(min_length=1)
    simple_definition: str = Field(min_length=1)
    bill_context: str = Field(min_length=1)
    example: str = Field(min_length=1)
    section_id: str = Field(min_length=1)
    difficulty: str = Field(default="intermediate")


class _VocabDraft(BaseModel):
    vocabulary: List[_VocabCardDraft] = Field(default_factory=list)


def _is_educationally_valid_term(term: str) -> bool:
    t = term.strip()
    if not (2 <= len(t) <= 60):
        return False
    if t.isdigit():
        return False
    if _GENERIC_TERM_PATTERN.match(t):
        return False
    return True


def _normalize_difficulty(raw_difficulty: str) -> str:
    normalized = raw_difficulty.strip().lower()
    return normalized if normalized in _VALID_DIFFICULTIES else "intermediate"


def _truncate_definition(definition: str) -> str:
    text = definition.strip()
    if len(text) <= MAX_DEFINITION_LENGTH:
        return text
    return text[: MAX_DEFINITION_LENGTH - 1].rstrip() + "…"


def ground_vocabulary_draft(
    raw_text: str,
    known_section_ids: Set[str],
    lesson_id: str,
    *,
    existing_terms_lower: Optional[Set[str]] = None,
    start_index: int = 1,
    max_cards: int = MAX_CARDS,
) -> Tuple[List[Flashcard], List[str]]:
    """Parse the model's raw vocabulary JSON into validated `Flashcard`s.

    Applies, per card: term-quality filtering (drops names/section
    numbers/pure numbers per requirement #2), case-insensitive
    deduplication against both this batch and `existing_terms_lower`,
    section_id grounding against `known_section_ids`, difficulty
    normalization, and a definition length cap. Returns the accepted cards
    (capped at `max_cards`) plus the terms that were rejected as invalid
    (ungrounded or failing the term-quality filter) so a caller can attempt
    regeneration for just those terms.
    """
    try:
        data = extract_json_object(raw_text)
        draft = _VocabDraft.model_validate(data)
    except (ValidationError, ValueError) as e:
        raise VocabularyGenerationError(f"Model output failed schema validation: {e}") from e

    seen_terms = set(existing_terms_lower or set())
    cards: List[Flashcard] = []
    invalid_terms: List[str] = []
    index = start_index

    for raw_card in draft.vocabulary:
        term = raw_card.term.strip()
        term_key = term.lower()

        if not _is_educationally_valid_term(term):
            invalid_terms.append(term)
            continue
        if raw_card.section_id not in known_section_ids:
            invalid_terms.append(term)
            continue
        if term_key in seen_terms:
            continue  # duplicate (case-insensitive) -- silently skip, not "invalid"
        if len(cards) >= max_cards:
            break

        cards.append(
            Flashcard(
                card_id=f"{lesson_id}-vocab-{index}",
                lesson_id=lesson_id,
                term=term,
                simple_definition=_truncate_definition(raw_card.simple_definition),
                bill_context=raw_card.bill_context.strip(),
                example=raw_card.example.strip(),
                section_id=raw_card.section_id,
                difficulty=_normalize_difficulty(raw_card.difficulty),
            )
        )
        seen_terms.add(term_key)
        index += 1

    return cards, invalid_terms


def _build_vocab_prompt(bill_id: str, sections: List[RetrievedSection]) -> str:
    section_blocks = "\n\n".join(f"[{s.section_id}] {s.heading}\n{s.text}" for s in sections)
    return (
        f"Bill ID: {bill_id}\n\n"
        f"Available sections (cite ONLY these section_ids):\n\n{section_blocks}\n\n"
        f"{_VOCAB_JSON_SCHEMA_INSTRUCTIONS}"
    )


def _build_regeneration_prompt(
    bill_id: str, sections: List[RetrievedSection], invalid_terms: List[str]
) -> str:
    return (
        _build_vocab_prompt(bill_id, sections)
        + "\n\nYour previous response included these terms with an invalid or "
        f"unrecognized section_id, a name/section-number instead of a real term, "
        f"or a duplicate: {invalid_terms}. Provide replacement vocabulary cards for "
        "different, genuinely important terms from the sections above, each citing a "
        "real section_id from the Available sections list."
    )


class VocabularyGenerationService:
    """Generates and persists bill-specific vocabulary cards for a lesson."""

    def __init__(
        self,
        rag_service: Optional[BillRagService] = None,
        repository: Optional[LessonRepository] = None,
        llm_call: Optional[LLMCallable] = None,
    ):
        self._rag_service = rag_service or BillRagService()
        self._repository = repository or LessonRepository()
        self._llm_call = llm_call or _default_llm_call

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

    async def regenerate_invalid_cards(
        self,
        bill_id: str,
        lesson_id: str,
        context_sections: List[RetrievedSection],
        known_section_ids: Set[str],
        invalid_terms: List[str],
        existing_terms_lower: Set[str],
        model: str,
        start_index: int,
        max_cards: int,
    ) -> List[Flashcard]:
        """Ask the model for replacement cards for terms that failed
        validation (ungrounded section_id or a name/section-number
        masquerading as a term). Returns only newly-produced, already
        grounded/deduped cards -- callers merge these into their running
        list."""
        prompt = _build_regeneration_prompt(bill_id, context_sections, invalid_terms)
        raw_text = await self._llm_call(VOCAB_SYSTEM_PROMPT, prompt, model)
        new_cards, _ = ground_vocabulary_draft(
            raw_text,
            known_section_ids,
            lesson_id,
            existing_terms_lower=existing_terms_lower,
            start_index=start_index,
            max_cards=max_cards,
        )
        return new_cards

    async def generate_vocabulary(
        self,
        bill_id: str,
        lesson_id: str,
        bill_text: str,
        model: str = DEFAULT_LESSON_MODEL,
        min_cards: int = MIN_CARDS,
        max_cards: int = MAX_CARDS,
    ) -> List[Flashcard]:
        """Generate, ground, and persist 0-`max_cards` vocabulary cards for
        `lesson_id`. Fewer than `min_cards` is not an error -- a bill with
        little jargon may legitimately need fewer (or zero) cards."""
        if not bill_text or not bill_text.strip():
            raise ValueError("bill_text must not be empty")

        context_sections = self._retrieve_context_sections(bill_id, bill_text)
        known_section_ids = {s.section_id for s in context_sections}
        if not context_sections:
            logger.warning("vocabulary_generation no_sections bill_id=%s", bill_id)
            return []

        prompt = _build_vocab_prompt(bill_id, context_sections)
        raw_text = await self._llm_call(VOCAB_SYSTEM_PROMPT, prompt, model)
        cards, invalid_terms = ground_vocabulary_draft(
            raw_text, known_section_ids, lesson_id, max_cards=max_cards
        )

        if invalid_terms and len(cards) < max_cards:
            logger.info(
                "vocabulary_generation regenerating bill_id=%s invalid_terms=%s",
                bill_id, invalid_terms,
            )
            replacement_cards = await self.regenerate_invalid_cards(
                bill_id=bill_id,
                lesson_id=lesson_id,
                context_sections=context_sections,
                known_section_ids=known_section_ids,
                invalid_terms=invalid_terms,
                existing_terms_lower={c.term.lower() for c in cards},
                model=model,
                start_index=len(cards) + 1,
                max_cards=max_cards - len(cards),
            )
            cards.extend(replacement_cards)

        if len(cards) < min_cards:
            logger.info(
                "vocabulary_generation bill_id=%s produced_fewer_than_min cards=%d min=%d",
                bill_id, len(cards), min_cards,
            )

        for card in cards:
            self._repository.create_flashcard(card)

        logger.info("vocabulary_generation bill_id=%s lesson_id=%s cards=%d", bill_id, lesson_id, len(cards))
        return cards
