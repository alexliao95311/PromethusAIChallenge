"""Lesson Mode API routes.

Increment 1 added bill-section retrieval; Increment 2 added grounded lesson
generation; Increment 3 added optional vocabulary generation; Increment 4
added the adaptive (Leitner-box) flashcard review endpoints; Increment 5
added grounded multiple-choice quiz generation; Increment 6 added the
open-response question and its grading; Increment 9 adds dynamic opposing
debate personas -- see docs/LESSON_MODE_ARCHITECTURE.md.
"""

import logging
import uuid
from datetime import datetime
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, ValidationError

from models.lesson_models import (
    Flashcard,
    Lesson,
    OpenResponseAttempt,
    PersonaProfile,
    PersonalImpact,
    QuizAnswer,
    QuizAttempt,
)
from services.auth import get_current_user_id
from services.dynamic_persona_generation import (
    DynamicPersonaGenerationError,
    DynamicPersonaGenerationService,
    generate_socratic_hint,
)
from services.flashcard_review import (
    CardNotInLessonError,
    FlashcardReviewService,
    LessonNotFoundError,
    ReviewState,
)
from services.lesson_generation import (
    DEFAULT_LESSON_MODEL,
    LessonGenerationError,
    LessonGenerationService,
)
from services.open_response_generation import (
    OpenResponseGenerationError,
    OpenResponseGenerationService,
)
from services.open_response_grading import OpenResponseGradingError, OpenResponseGradingService
from services.persona_impact_generation import (
    PersonaImpactGenerationError,
    PersonaImpactGenerationService,
)
from services.mastery_dashboard import MasteryDashboard, MasteryDashboardService
from services.persona_service import PersonaService, PersonaValidationError
from services.quiz_generation import QuizGenerationError, QuizGenerationService
from services.rag.retrieval_service import BillNotCachedError, BillRagService, RetrievedSection
from services.reflection_generation import ReflectionGenerationError, ReflectionGenerationService
from services.vocabulary_generation import VocabularyGenerationError, VocabularyGenerationService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/lesson", tags=["lesson"])

# Shared service instances so the in-memory RAG embedding cache persists
# across requests within a running process.
_rag_service = BillRagService()
_lesson_generation_service = LessonGenerationService(rag_service=_rag_service)
_vocabulary_generation_service = VocabularyGenerationService(rag_service=_rag_service)
_flashcard_review_service = FlashcardReviewService(repository=_lesson_generation_service.repository)
_quiz_generation_service = QuizGenerationService(repository=_lesson_generation_service.repository)
_open_response_generation_service = OpenResponseGenerationService(
    repository=_lesson_generation_service.repository
)
_open_response_grading_service = OpenResponseGradingService()
_persona_service = PersonaService(repository=_lesson_generation_service.repository)
_persona_impact_service = PersonaImpactGenerationService(
    rag_service=_rag_service, repository=_lesson_generation_service.repository
)
_dynamic_persona_generation_service = DynamicPersonaGenerationService(
    repository=_lesson_generation_service.repository
)
_reflection_generation_service = ReflectionGenerationService(
    repository=_lesson_generation_service.repository
)
_mastery_dashboard_service = MasteryDashboardService(repository=_lesson_generation_service.repository)


# ---------------------------------------------------------------------------
# Analytics (Increment 12)
#
# A structured logging hook for the end-to-end Lesson Mode flow, not a full
# analytics pipeline (no GA4/Mixpanel/etc. integration -- out of scope).
# `event_type` is a closed enum and every other field is a bounded primitive
# -- there is no freeform string field anywhere in this model, so bill text,
# quiz answers, debate transcripts, or any other student-authored content can
# never reach this endpoint or the server logs it writes to, by construction
# rather than by convention. No auth required: some flow stages (choosing a
# bill, viewing a generated lesson) happen before/without sign-in.
# ---------------------------------------------------------------------------

FlowEventType = Literal[
    "bill_selected", "persona_step_viewed", "impact_generated", "lesson_viewed",
    "vocabulary_reviewed", "quiz_completed", "open_response_completed",
    "debate_started", "debate_ended", "reflection_submitted", "dashboard_viewed",
]


class AnalyticsEventRequest(BaseModel):
    event_type: FlowEventType
    lesson_id: Optional[str] = Field(default=None, max_length=200)
    step_index: Optional[int] = Field(default=None, ge=0, le=20)
    success: Optional[bool] = None


@router.post("/analytics/event")
async def log_analytics_event(request: AnalyticsEventRequest):
    logger.info(
        "lesson_flow_event event_type=%s lesson_id=%s step_index=%s success=%s",
        request.event_type, request.lesson_id, request.step_index, request.success,
    )
    return {"logged": True}


class RetrieveSectionsRequest(BaseModel):
    bill_id: str = Field(..., min_length=1)
    query: str = Field(..., min_length=1)
    top_k: int = Field(default=5, gt=0, le=50)
    bill_text: Optional[str] = None


class RetrieveSectionsResponse(BaseModel):
    bill_id: str
    query: str
    sections: List[RetrievedSection]


@router.post("/retrieve-sections", response_model=RetrieveSectionsResponse)
async def retrieve_sections(request: RetrieveSectionsRequest):
    logger.info(
        "POST /lesson/retrieve-sections bill_id=%s top_k=%d has_bill_text=%s",
        request.bill_id, request.top_k, request.bill_text is not None,
    )
    try:
        sections = _rag_service.retrieve_relevant_sections(
            bill_id=request.bill_id,
            query=request.query,
            top_k=request.top_k,
            bill_text=request.bill_text,
        )
    except BillNotCachedError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.error(f"Error in /lesson/retrieve-sections: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Error retrieving bill sections")

    return RetrieveSectionsResponse(
        bill_id=request.bill_id, query=request.query, sections=sections
    )


class GenerateLessonRequest(BaseModel):
    bill_id: str = Field(..., min_length=1)
    bill_text: str = Field(..., min_length=1)
    model: str = DEFAULT_LESSON_MODEL
    include_vocabulary: bool = False
    include_quiz: bool = False
    include_open_response: bool = False


class QuizQuestionPublic(BaseModel):
    """A quiz question without its correct_answer_index/explanation -- the
    shape shown to a student taking the quiz, before they submit answers."""

    question_id: str
    question: str
    answer_choices: List[str]
    section_ids: List[str]
    difficulty: str
    question_type: str


class OpenResponseQuestionPublic(BaseModel):
    """An open-response question without `expected_points`/`context_excerpt`
    -- the shape shown to a student before they answer."""

    question_id: str
    question: str
    question_type: str
    section_ids: List[str]


class GenerateLessonResponse(Lesson):
    vocabulary: Optional[List[Flashcard]] = None
    quiz: Optional[List[QuizQuestionPublic]] = None
    open_response_question: Optional[OpenResponseQuestionPublic] = None


def _merge_ids(existing_ids: List[str], new_ids: List[str]) -> List[str]:
    return existing_ids + [i for i in new_ids if i not in existing_ids]


@router.post("/generate", response_model=GenerateLessonResponse)
async def generate_lesson(request: GenerateLessonRequest):
    logger.info(
        "POST /lesson/generate bill_id=%s model=%s include_vocabulary=%s include_quiz=%s include_open_response=%s",
        request.bill_id, request.model, request.include_vocabulary, request.include_quiz,
        request.include_open_response,
    )
    try:
        lesson = await _lesson_generation_service.generate_lesson(
            bill_id=request.bill_id, bill_text=request.bill_text, model=request.model
        )

        vocabulary = None
        if request.include_vocabulary:
            vocabulary = await _vocabulary_generation_service.generate_vocabulary(
                bill_id=request.bill_id,
                lesson_id=lesson.lesson_id,
                bill_text=request.bill_text,
                model=request.model,
            )
            merged_ids = _merge_ids(lesson.vocabulary_card_ids, [c.card_id for c in vocabulary])
            if merged_ids != lesson.vocabulary_card_ids:
                lesson = lesson.model_copy(update={"vocabulary_card_ids": merged_ids})
                _lesson_generation_service.repository.create_lesson(lesson)

        quiz = None
        if request.include_quiz:
            quiz_questions = await _quiz_generation_service.generate_quiz(
                lesson_id=lesson.lesson_id, model=request.model
            )
            merged_ids = _merge_ids(lesson.quiz_question_ids, [q.question_id for q in quiz_questions])
            if merged_ids != lesson.quiz_question_ids:
                lesson = lesson.model_copy(update={"quiz_question_ids": merged_ids})
                _lesson_generation_service.repository.create_lesson(lesson)
            quiz = [
                QuizQuestionPublic(**q.model_dump(exclude={"lesson_id", "correct_answer_index", "explanation"}))
                for q in quiz_questions
            ]

        open_response_question = None
        if request.include_open_response:
            or_question = await _open_response_generation_service.generate_question(
                lesson_id=lesson.lesson_id, model=request.model
            )
            if lesson.open_response_question_id != or_question.question_id:
                lesson = lesson.model_copy(update={"open_response_question_id": or_question.question_id})
                _lesson_generation_service.repository.create_lesson(lesson)
            open_response_question = OpenResponseQuestionPublic(
                **or_question.model_dump(exclude={"lesson_id", "expected_points", "context_excerpt"})
            )
    except (LessonGenerationError, VocabularyGenerationError, QuizGenerationError, OpenResponseGenerationError) as e:
        raise HTTPException(status_code=502, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.error(f"Error in /lesson/generate: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Error generating lesson")

    return GenerateLessonResponse(
        **lesson.model_dump(), vocabulary=vocabulary, quiz=quiz, open_response_question=open_response_question
    )


class StartSessionResponse(BaseModel):
    session: int


class AnswerCardRequest(BaseModel):
    card_id: str = Field(..., min_length=1)
    correct: bool


class AnswerCardResponse(BaseModel):
    card_id: str
    leitner_box: int
    correct_count: int
    incorrect_count: int
    last_reviewed_session: int
    next_due_session: int


@router.post("/{lesson_id}/review/start-session", response_model=StartSessionResponse)
async def start_review_session(lesson_id: str, user_id: str = Depends(get_current_user_id)):
    logger.info("POST /lesson/%s/review/start-session user_id=%s", lesson_id, user_id)
    session = _flashcard_review_service.start_session(user_id=user_id, lesson_id=lesson_id)
    return StartSessionResponse(session=session)


@router.get("/{lesson_id}/review/state", response_model=ReviewState)
async def get_review_state(lesson_id: str, user_id: str = Depends(get_current_user_id)):
    logger.info("GET /lesson/%s/review/state user_id=%s", lesson_id, user_id)
    try:
        return _flashcard_review_service.get_review_state(user_id=user_id, lesson_id=lesson_id)
    except LessonNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error in /lesson/{lesson_id}/review/state: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Error fetching review state")


@router.post("/{lesson_id}/review/answer", response_model=AnswerCardResponse)
async def submit_review_answer(
    lesson_id: str, request: AnswerCardRequest, user_id: str = Depends(get_current_user_id)
):
    logger.info(
        "POST /lesson/%s/review/answer user_id=%s card_id=%s correct=%s",
        lesson_id, user_id, request.card_id, request.correct,
    )
    try:
        updated = _flashcard_review_service.submit_answer(
            user_id=user_id, lesson_id=lesson_id, card_id=request.card_id, correct=request.correct
        )
    except LessonNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except CardNotInLessonError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error in /lesson/{lesson_id}/review/answer: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Error submitting answer")

    return AnswerCardResponse(
        card_id=updated.card_id,
        leitner_box=updated.leitner_box,
        correct_count=updated.correct_count,
        incorrect_count=updated.incorrect_count,
        last_reviewed_session=updated.last_reviewed_session,
        next_due_session=updated.next_due_session,
    )


def _get_lesson_or_404(lesson_id: str) -> Lesson:
    lesson = _lesson_generation_service.repository.get_lesson(lesson_id)
    if lesson is None:
        raise HTTPException(status_code=404, detail=f"No lesson found for lesson_id={lesson_id!r}")
    return lesson


@router.get("/{lesson_id}/quiz", response_model=List[QuizQuestionPublic])
async def get_quiz(lesson_id: str):
    logger.info("GET /lesson/%s/quiz", lesson_id)
    lesson = _get_lesson_or_404(lesson_id)

    questions = [
        q for q in (
            _lesson_generation_service.repository.get_quiz_question(qid)
            for qid in lesson.quiz_question_ids
        ) if q is not None
    ]
    if not questions:
        raise HTTPException(status_code=404, detail=f"No quiz generated yet for lesson_id={lesson_id!r}")

    return [
        QuizQuestionPublic(**q.model_dump(exclude={"lesson_id", "correct_answer_index", "explanation"}))
        for q in questions
    ]


class QuizAnswerSubmission(BaseModel):
    question_id: str = Field(..., min_length=1)
    selected_index: int = Field(ge=0)


class SubmitQuizRequest(BaseModel):
    answers: List[QuizAnswerSubmission] = Field(min_length=1)


class QuestionResult(BaseModel):
    question_id: str
    selected_index: int
    correct: bool
    correct_answer_index: int
    explanation: str


class SubmitQuizResponse(BaseModel):
    attempt_id: str
    score: float
    results: List[QuestionResult]


@router.post("/{lesson_id}/quiz/submit", response_model=SubmitQuizResponse)
async def submit_quiz(
    lesson_id: str, request: SubmitQuizRequest, user_id: str = Depends(get_current_user_id)
):
    logger.info(
        "POST /lesson/%s/quiz/submit user_id=%s answers=%d",
        lesson_id, user_id, len(request.answers),
    )
    lesson = _get_lesson_or_404(lesson_id)

    questions_by_id = {
        qid: q for qid in lesson.quiz_question_ids
        if (q := _lesson_generation_service.repository.get_quiz_question(qid)) is not None
    }
    if not questions_by_id:
        raise HTTPException(status_code=404, detail=f"No quiz generated yet for lesson_id={lesson_id!r}")

    results: List[QuestionResult] = []
    quiz_answers: List[QuizAnswer] = []
    correct_count = 0

    for submitted in request.answers:
        question = questions_by_id.get(submitted.question_id)
        if question is None:
            raise HTTPException(
                status_code=400,
                detail=f"question_id={submitted.question_id!r} does not belong to lesson_id={lesson_id!r}",
            )

        is_correct = submitted.selected_index == question.correct_answer_index
        if is_correct:
            correct_count += 1

        results.append(
            QuestionResult(
                question_id=question.question_id,
                selected_index=submitted.selected_index,
                correct=is_correct,
                correct_answer_index=question.correct_answer_index,
                explanation=question.explanation,
            )
        )
        quiz_answers.append(
            QuizAnswer(
                question_id=question.question_id,
                response=str(submitted.selected_index),
                is_correct=is_correct,
            )
        )

    score = round(100 * correct_count / len(request.answers), 1)
    attempt = QuizAttempt(
        attempt_id=str(uuid.uuid4()),
        user_id=user_id,
        lesson_id=lesson_id,
        score=score,
        answers=quiz_answers,
    )
    _lesson_generation_service.repository.create_quiz_attempt(attempt)

    return SubmitQuizResponse(attempt_id=attempt.attempt_id, score=score, results=results)


@router.get("/{lesson_id}/open-response", response_model=OpenResponseQuestionPublic)
async def get_open_response_question(lesson_id: str):
    logger.info("GET /lesson/%s/open-response", lesson_id)
    lesson = _get_lesson_or_404(lesson_id)

    if not lesson.open_response_question_id:
        raise HTTPException(
            status_code=404, detail=f"No open-response question generated yet for lesson_id={lesson_id!r}"
        )
    question = _lesson_generation_service.repository.get_open_response_question(
        lesson.open_response_question_id
    )
    if question is None:
        raise HTTPException(
            status_code=404, detail=f"No open-response question generated yet for lesson_id={lesson_id!r}"
        )

    return OpenResponseQuestionPublic(
        **question.model_dump(exclude={"lesson_id", "expected_points", "context_excerpt"})
    )


class SubmitOpenResponseRequest(BaseModel):
    student_answer: str = Field(..., min_length=0)


class SubmitOpenResponseResponse(BaseModel):
    attempt_id: str
    score: int
    feedback: str
    missed_points: List[str]
    accurate_points: List[str]
    section_ids: List[str]


@router.post("/{lesson_id}/open-response/submit", response_model=SubmitOpenResponseResponse)
async def submit_open_response(
    lesson_id: str, request: SubmitOpenResponseRequest, user_id: str = Depends(get_current_user_id)
):
    logger.info(
        "POST /lesson/%s/open-response/submit user_id=%s answer_length=%d",
        lesson_id, user_id, len(request.student_answer),
    )
    lesson = _get_lesson_or_404(lesson_id)

    if not lesson.open_response_question_id:
        raise HTTPException(
            status_code=404, detail=f"No open-response question generated yet for lesson_id={lesson_id!r}"
        )
    question = _lesson_generation_service.repository.get_open_response_question(
        lesson.open_response_question_id
    )
    if question is None:
        raise HTTPException(
            status_code=404, detail=f"No open-response question generated yet for lesson_id={lesson_id!r}"
        )

    try:
        grade = await _open_response_grading_service.grade_answer(question, request.student_answer)
    except OpenResponseGradingError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        logger.error(f"Error in /lesson/{lesson_id}/open-response/submit: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Error grading answer")

    attempt = OpenResponseAttempt(
        attempt_id=str(uuid.uuid4()),
        user_id=user_id,
        lesson_id=lesson_id,
        question_id=question.question_id,
        student_answer=request.student_answer,
        score=grade.score,
        feedback=grade.feedback,
        missed_points=grade.missed_points,
        accurate_points=grade.accurate_points,
        section_ids=grade.section_ids,
    )
    _lesson_generation_service.repository.create_open_response_attempt(attempt)

    return SubmitOpenResponseResponse(
        attempt_id=attempt.attempt_id,
        score=grade.score,
        feedback=grade.feedback,
        missed_points=grade.missed_points,
        accurate_points=grade.accurate_points,
        section_ids=grade.section_ids,
    )


# ---------------------------------------------------------------------------
# Student persona builder (Increment 7)
#
# The persona is optional, may be fictional, and collects only broad
# attributes. Reading/saving/deleting a persona is per-user, so those routes
# require an authenticated caller and derive the uid from the verified token
# (never from the request body). The `occupation` field is an
# "occupation or role" -- a current job, an intended future occupation, or a
# broad category. No impact narrative is generated here (that is Increment 8).
# ---------------------------------------------------------------------------

class PersonaFieldOptionsResponse(BaseModel):
    occupation_suggestions: List[str]
    occupation_allows_custom: bool
    occupation_max_length: int
    states: List[dict]
    age_ranges: List[str]
    income_brackets: List[str]
    all_fields_optional: bool
    persona_may_be_fictional: bool
    not_collected: List[str]


class SavePersonaRequest(BaseModel):
    """All fields optional so a student can save just one, or leave any blank
    (blank/omitted == skipped). An empty string is treated as "skip"."""

    occupation: Optional[str] = Field(default=None, description="Occupation or intended role")
    state: Optional[str] = None
    age_range: Optional[str] = None
    income_bracket: Optional[str] = None


class PersonaResponse(BaseModel):
    has_persona: bool
    occupation: Optional[str] = None
    state: Optional[str] = None
    age_range: Optional[str] = None
    income_bracket: Optional[str] = None
    # Representation the (future) personal-impact generator consumes.
    impact_representation: Optional[dict] = None


def _persona_response(profile) -> PersonaResponse:
    if profile is None:
        return PersonaResponse(has_persona=False)
    return PersonaResponse(
        has_persona=True,
        occupation=profile.occupation,
        state=profile.state,
        age_range=profile.age_range,
        income_bracket=profile.income_bracket,
        impact_representation=profile.to_impact_representation(),
    )


@router.get("/persona/options", response_model=PersonaFieldOptionsResponse)
async def get_persona_options():
    """Public: the choice sets + privacy disclaimer the builder UI needs.

    Contains no user data, so it needs no authentication."""
    logger.info("GET /lesson/persona/options")
    return PersonaFieldOptionsResponse(**_persona_service.field_options())


@router.get("/persona", response_model=PersonaResponse)
async def get_persona(user_id: str = Depends(get_current_user_id)):
    logger.info("GET /lesson/persona user_id=%s", user_id)
    try:
        profile = _persona_service.get_persona(user_id)
    except Exception as e:
        logger.error(f"Error in GET /lesson/persona: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Error loading persona")
    return _persona_response(profile)


@router.put("/persona", response_model=PersonaResponse)
async def save_persona(request: SavePersonaRequest, user_id: str = Depends(get_current_user_id)):
    """Create or edit the authenticated user's persona (upsert by uid).

    Saving happens only on this explicit, authenticated call -- there is no
    implicit persistence anywhere else."""
    logger.info("PUT /lesson/persona user_id=%s", user_id)
    try:
        profile = _persona_service.save_persona(
            user_id,
            occupation=request.occupation,
            state=request.state,
            age_range=request.age_range,
            income_bracket=request.income_bracket,
        )
    except PersonaValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.error(f"Error in PUT /lesson/persona: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Error saving persona")
    return _persona_response(profile)


@router.delete("/persona")
async def delete_persona(user_id: str = Depends(get_current_user_id)):
    logger.info("DELETE /lesson/persona user_id=%s", user_id)
    try:
        deleted = _persona_service.delete_persona(user_id)
    except Exception as e:
        logger.error(f"Error in DELETE /lesson/persona: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Error deleting persona")
    return {"deleted": deleted}


# ---------------------------------------------------------------------------
# Personalized bill-impact narrative (Increment 8)
#
# Grounded, persona-specific explanation of how a bill could affect a student.
# Auth is required: the narrative is built from the caller's persona (their
# saved one, or an inline possibly-fictional override) and persisted under
# their uid. The lesson must already have been generated.
# ---------------------------------------------------------------------------

class PersonaOverride(BaseModel):
    """An inline, possibly-fictional persona so a student can explore impacts
    without first saving one. Same broad, optional fields as PersonaProfile.

    Increment 9's dynamic opposing-persona endpoint reuses this same shape
    (as `request.student_persona`) rather than introducing a duplicate
    input model -- both features need the same optional
    occupation/state/age_range/income_bracket context."""

    occupation: Optional[str] = None
    state: Optional[str] = None
    age_range: Optional[str] = None
    income_bracket: Optional[str] = None


class PersonalImpactRequest(BaseModel):
    lesson_id: str = Field(..., min_length=1)
    # Supplied when the bill isn't already cached in this process's RAG store.
    bill_text: Optional[str] = None
    # If omitted, the caller's saved persona (Increment 7) is used.
    persona: Optional[PersonaOverride] = None
    model: str = DEFAULT_LESSON_MODEL


class PersonalImpactResponse(BaseModel):
    impact_id: str
    lesson_id: str
    bill_id: str
    persona: dict
    narrative: str
    direct_impacts: List[PersonalImpact]
    possible_indirect_impacts: List[PersonalImpact]
    uncertainties: List[str]
    questions_to_consider: List[str]
    confidence: str
    section_ids: List[str]


@router.post("/personal-impact", response_model=PersonalImpactResponse)
async def personal_impact(
    request: PersonalImpactRequest, user_id: str = Depends(get_current_user_id)
):
    logger.info(
        "POST /lesson/personal-impact user_id=%s lesson_id=%s inline_persona=%s",
        user_id, request.lesson_id, request.persona is not None,
    )
    lesson = _get_lesson_or_404(request.lesson_id)

    # Resolve the persona: an inline (possibly fictional) override wins;
    # otherwise fall back to the caller's saved persona. Either way the uid
    # comes from the verified token, never the request body.
    if request.persona is not None:
        try:
            persona = PersonaProfile(user_id=user_id, **request.persona.model_dump())
        except ValidationError as e:
            raise HTTPException(status_code=422, detail=str(e))
    else:
        persona = _persona_service.get_persona(user_id)
        if persona is None:
            raise HTTPException(
                status_code=400,
                detail="No persona found. Save a persona first, or supply one in the request.",
            )

    try:
        narrative = await _persona_impact_service.generate_impact(
            persona=persona, lesson=lesson, bill_text=request.bill_text, model=request.model
        )
    except PersonaImpactGenerationError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.error(f"Error in /lesson/personal-impact: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Error generating personal impact")

    return PersonalImpactResponse(
        impact_id=narrative.impact_id,
        lesson_id=narrative.lesson_id,
        bill_id=narrative.bill_id,
        persona=narrative.persona,
        narrative=narrative.narrative,
        direct_impacts=narrative.direct_impacts,
        possible_indirect_impacts=narrative.possible_indirect_impacts,
        uncertainties=narrative.uncertainties,
        questions_to_consider=narrative.questions_to_consider,
        confidence=narrative.confidence,
        section_ids=narrative.section_ids,
    )


# ---------------------------------------------------------------------------
# Mastery dashboard (Increment 11)
#
# A read-only aggregation over data every other Lesson Mode endpoint already
# persists -- nothing here is generated or written. Auth required, since
# it's entirely the authenticated user's own progress. `mastery-dashboard`
# is a single path segment (a hyphen, not a `/`), so it is the SAME shape as
# `{lesson_id}` below and MUST be declared first, exactly like `/persona` /
# `/personal-impact` above -- otherwise a request to `/lesson/mastery-dashboard`
# would incorrectly match `GET /{lesson_id}` with lesson_id="mastery-dashboard"
# (this is not hypothetical: it's exactly the bug the Increment 1 GET
# /{lesson_id} route itself was originally added with and had to be fixed).
# ---------------------------------------------------------------------------

@router.get("/mastery-dashboard", response_model=MasteryDashboard)
async def get_mastery_dashboard(user_id: str = Depends(get_current_user_id)):
    logger.info("GET /lesson/mastery-dashboard user_id=%s", user_id)
    return _mastery_dashboard_service.get_dashboard(user_id)


@router.get("/{lesson_id}", response_model=Lesson)
async def get_lesson(lesson_id: str):
    """Re-fetch an already-generated lesson by id.

    Lets a page refresh or a direct link work without re-POSTing to
    `/lesson/generate` (which itself is idempotent per bill text, but still
    requires the caller to have the full bill_text on hand). Declared after
    every single-segment literal-path route above (`/generate`,
    `/retrieve-sections`, `/persona`, `/persona/options`, `/personal-impact`,
    `/mastery-dashboard`) -- FastAPI matches routes in declaration order, so
    those literal paths must come first or a request to e.g. `/lesson/persona`
    would incorrectly match this `{lesson_id}` route with `lesson_id="persona"`.
    Routes with additional path segments (`/{lesson_id}/quiz`, `/{lesson_id}/review/...`,
    the debate-persona routes below, etc.) are a different, more specific
    template and are never shadowed by this one regardless of order.
    """
    logger.info("GET /lesson/%s", lesson_id)
    return _get_lesson_or_404(lesson_id)


# ---------------------------------------------------------------------------
# Dynamic opposing debate persona (Increment 9)
#
# Distinct from Increment 8's personal-impact narrative above: this
# generates the AI's *debate opponent* -- a bill-grounded stakeholder with a
# meaningfully different perspective -- not an explanation of impact on the
# student. No auth required: a generated persona is lesson-scoped, reusable
# content (like a quiz question), not per-user state.
# ---------------------------------------------------------------------------

class GeneratePersonaRequest(BaseModel):
    student_persona: Optional[PersonaOverride] = None
    model: str = DEFAULT_LESSON_MODEL


class DynamicPersonaResponse(BaseModel):
    persona_id: str
    role: str
    location_context: str
    interests: List[str]
    likely_concerns: List[str]
    position: str
    section_ids: List[str]
    reason_for_selection: str
    persona_prompt: str


@router.post("/{lesson_id}/debate-persona/generate", response_model=DynamicPersonaResponse)
async def generate_debate_persona(lesson_id: str, request: GeneratePersonaRequest):
    logger.info(
        "POST /lesson/%s/debate-persona/generate has_student_persona=%s",
        lesson_id, request.student_persona is not None,
    )
    student_persona = None
    if request.student_persona is not None:
        student_persona = PersonaProfile(user_id="anonymous", **request.student_persona.model_dump())

    try:
        persona = await _dynamic_persona_generation_service.generate_persona(
            lesson_id=lesson_id, student_persona=student_persona, model=request.model
        )
    except DynamicPersonaGenerationError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        logger.error(f"Error in /lesson/{lesson_id}/debate-persona/generate: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Error generating debate persona")

    return DynamicPersonaResponse(**persona.model_dump(exclude={"lesson_id", "created_at"}))


class SocraticHintRequest(BaseModel):
    persona_id: str = Field(..., min_length=1)
    full_transcript: str = Field(default="")


class SocraticHintResponse(BaseModel):
    hint: str


@router.post("/{lesson_id}/debate-persona/hint", response_model=SocraticHintResponse)
async def get_socratic_hint(lesson_id: str, request: SocraticHintRequest):
    """Learning-mode only: an optional Socratic hint for the student,
    generated on demand (competition mode simply never calls this
    endpoint -- it's additive, not a mode switch on the debate engine
    itself)."""
    logger.info("POST /lesson/%s/debate-persona/hint persona_id=%s", lesson_id, request.persona_id)
    persona = _lesson_generation_service.repository.get_dynamic_persona(request.persona_id)
    if persona is None or persona.lesson_id != lesson_id:
        raise HTTPException(
            status_code=404, detail=f"No debate persona found for persona_id={request.persona_id!r}"
        )

    try:
        hint = await generate_socratic_hint(persona, request.full_transcript)
    except Exception as e:
        logger.error(f"Error in /lesson/{lesson_id}/debate-persona/hint: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Error generating hint")

    return SocraticHintResponse(hint=hint)


# ---------------------------------------------------------------------------
# Post-debate reflection and feedback (Increment 10)
#
# After a Lesson Mode debate (Increment 9's dynamic opposing persona), the
# student self-reports whether their view changed, and this generates a
# grounded educational judge analysis of the same transcript -- reusing
# `OpenRouterChat` from `chains/judge_chain.py` with a rubric that is
# separate from winner-determination and never infers belief change from
# debate performance. Auth is required: reflections are per-user state, and
# the progress endpoint below reads them back across every lesson.
# ---------------------------------------------------------------------------

class SubmitReflectionRequest(BaseModel):
    transcript: str = Field(..., min_length=1)
    view_changed: Literal["yes", "somewhat", "no", "less_certain"]
    explanation: Optional[str] = None
    persona_id: Optional[str] = None
    model: str = DEFAULT_LESSON_MODEL


class ReflectionFeedbackItemResponse(BaseModel):
    feedback: str
    transcript_excerpt: Optional[str] = None


class ReflectionResponse(BaseModel):
    reflection_id: str
    lesson_id: str
    view_changed: str
    explanation: Optional[str] = None
    strongest_student_argument: ReflectionFeedbackItemResponse
    weakest_reasoning_step: ReflectionFeedbackItemResponse
    evidence_use_feedback: ReflectionFeedbackItemResponse
    missed_opponent_point: ReflectionFeedbackItemResponse
    perspective_understanding: ReflectionFeedbackItemResponse
    recommended_skill: str
    recommended_next_activity: str
    created_at: datetime


def _reflection_response(reflection) -> ReflectionResponse:
    return ReflectionResponse(
        reflection_id=reflection.reflection_id,
        lesson_id=reflection.lesson_id,
        view_changed=reflection.view_changed,
        explanation=reflection.explanation,
        strongest_student_argument=ReflectionFeedbackItemResponse(
            **reflection.strongest_student_argument.model_dump()
        ),
        weakest_reasoning_step=ReflectionFeedbackItemResponse(
            **reflection.weakest_reasoning_step.model_dump()
        ),
        evidence_use_feedback=ReflectionFeedbackItemResponse(
            **reflection.evidence_use_feedback.model_dump()
        ),
        missed_opponent_point=ReflectionFeedbackItemResponse(
            **reflection.missed_opponent_point.model_dump()
        ),
        perspective_understanding=ReflectionFeedbackItemResponse(
            **reflection.perspective_understanding.model_dump()
        ),
        recommended_skill=reflection.recommended_skill,
        recommended_next_activity=reflection.recommended_next_activity,
        created_at=reflection.created_at,
    )


@router.post("/{lesson_id}/reflection", response_model=ReflectionResponse)
async def submit_reflection(
    lesson_id: str, request: SubmitReflectionRequest, user_id: str = Depends(get_current_user_id)
):
    logger.info(
        "POST /lesson/%s/reflection user_id=%s view_changed=%s",
        lesson_id, user_id, request.view_changed,
    )
    _get_lesson_or_404(lesson_id)

    try:
        reflection = await _reflection_generation_service.generate_reflection(
            reflection_id=str(uuid.uuid4()),
            lesson_id=lesson_id,
            user_id=user_id,
            transcript=request.transcript,
            view_changed=request.view_changed,
            explanation=request.explanation,
            persona_id=request.persona_id,
            model=request.model,
        )
    except ReflectionGenerationError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.error(f"Error in /lesson/{lesson_id}/reflection: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Error generating reflection")

    return _reflection_response(reflection)


class ReflectionProgressResponse(BaseModel):
    reflections: List[ReflectionResponse]


@router.get("/reflection/progress", response_model=ReflectionProgressResponse)
async def get_reflection_progress(user_id: str = Depends(get_current_user_id)):
    """Every reflection the authenticated user has submitted, across every
    lesson debate they've done -- oldest first. A 2-segment literal path
    (`reflection/progress`), so it is never shadowed by the 1-segment
    `/{lesson_id}` route above or by any `/{lesson_id}/<literal>` route
    below, regardless of declaration order."""
    logger.info("GET /lesson/reflection/progress user_id=%s", user_id)
    reflections = _reflection_generation_service.get_progress(user_id)
    return ReflectionProgressResponse(reflections=[_reflection_response(r) for r in reflections])
