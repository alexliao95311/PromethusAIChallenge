import React, { useCallback, useEffect, useState } from 'react';
import { CheckCircle2, XCircle, Sparkles } from 'lucide-react';
import { getReviewState, startReviewSession, submitReviewAnswer } from '../api';
import './LessonFlashcards.css';

const BOX_LABELS = { 1: 'Needs review', 2: 'Learning', 3: 'Mastered' };

function nextBox(currentBox, correct) {
  if (!correct) return 1;
  return Math.min(currentBox + 1, 3);
}

function LessonFlashcards({ lessonId }) {
  const [reviewState, setReviewState] = useState(null);
  const [dueQueue, setDueQueue] = useState([]);
  const [currentIndex, setCurrentIndex] = useState(0);
  const [revealed, setRevealed] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const loadState = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const state = await getReviewState(lessonId);
      setReviewState(state);
      setDueQueue(state.due_cards);
      setCurrentIndex(0);
      setRevealed(false);
    } catch (err) {
      setError(err?.response?.data?.detail || err.message || 'Failed to load flashcards.');
    } finally {
      setLoading(false);
    }
  }, [lessonId]);

  useEffect(() => {
    loadState();
  }, [loadState]);

  const handleReveal = () => setRevealed(true);

  const handleAnswer = async (correct) => {
    const card = dueQueue[currentIndex];
    if (!card || submitting) return;
    setSubmitting(true);
    setError('');
    try {
      await submitReviewAnswer(lessonId, card.card_id, correct);

      setReviewState((prev) => {
        if (!prev) return prev;
        const oldBox = card.leitner_box;
        const newBox = nextBox(oldBox, correct);
        const boxDistribution = { ...prev.box_distribution };
        boxDistribution[String(oldBox)] = Math.max(0, (boxDistribution[String(oldBox)] || 0) - 1);
        boxDistribution[String(newBox)] = (boxDistribution[String(newBox)] || 0) + 1;
        const masteredCount = boxDistribution['3'] || 0;
        const masteryPercent = prev.total_cards
          ? Math.round((1000 * masteredCount) / prev.total_cards) / 10
          : 0;
        return {
          ...prev,
          due_count: Math.max(0, prev.due_count - 1),
          box_distribution: boxDistribution,
          mastery_percent: masteryPercent,
        };
      });

      setCurrentIndex((i) => i + 1);
      setRevealed(false);
    } catch (err) {
      setError(err?.response?.data?.detail || err.message || 'Failed to submit answer.');
    } finally {
      setSubmitting(false);
    }
  };

  const handleStartNextSession = async () => {
    setLoading(true);
    setError('');
    try {
      await startReviewSession(lessonId);
      await loadState();
    } catch (err) {
      setError(err?.response?.data?.detail || err.message || 'Failed to start next session.');
      setLoading(false);
    }
  };

  if (loading) {
    return <div className="lesson-flashcards-container" data-testid="flashcards-loading">Loading flashcards…</div>;
  }

  if (error && !reviewState) {
    return <div className="lesson-flashcards-container lesson-flashcards-error">{error}</div>;
  }

  if (!reviewState || reviewState.total_cards === 0) {
    return (
      <div className="lesson-flashcards-container">
        <p>No vocabulary cards are available for this lesson yet.</p>
      </div>
    );
  }

  const boxCounts = reviewState.box_distribution || {};
  const sessionDone = currentIndex >= dueQueue.length;
  const currentCard = !sessionDone ? dueQueue[currentIndex] : null;

  return (
    <div className="lesson-flashcards-container">
      <div className="flashcards-summary" data-testid="flashcards-summary">
        <div className="mastery-bar-wrapper">
          <div className="mastery-bar-label">
            <span>Mastery</span>
            <span data-testid="mastery-percent">{reviewState.mastery_percent}%</span>
          </div>
          <div className="mastery-bar-track">
            <div
              className="mastery-bar-fill"
              style={{ width: `${reviewState.mastery_percent}%` }}
              data-testid="mastery-bar-fill"
            />
          </div>
        </div>

        <div className="flashcards-stats-row">
          <span className="due-count-badge" data-testid="due-count">
            {reviewState.due_count} due this session
          </span>
          <span className="box-count box-count-1">Box 1: {boxCounts['1'] || 0}</span>
          <span className="box-count box-count-2">Box 2: {boxCounts['2'] || 0}</span>
          <span className="box-count box-count-3">Box 3: {boxCounts['3'] || 0}</span>
        </div>
      </div>

      {error && <div className="lesson-flashcards-error-inline">{error}</div>}

      {sessionDone ? (
        <div className="flashcards-complete" data-testid="session-complete">
          <Sparkles size={32} />
          <h3>All caught up!</h3>
          <p>You&apos;ve completed every due card for this session.</p>
          <button
            className="flashcards-primary-btn"
            onClick={handleStartNextSession}
            data-testid="start-next-session"
          >
            Start Next Session
          </button>
        </div>
      ) : (
        <div className="flashcard-review-card" data-testid="flashcard-card">
          <div className="flashcard-progress" data-testid="flashcard-progress">
            Card {currentIndex + 1} of {dueQueue.length}
          </div>

          <span className={`needs-review-label needs-review-box-${currentCard.leitner_box}`}>
            {BOX_LABELS[currentCard.leitner_box]}
          </span>

          <h2 className="flashcard-term" data-testid="flashcard-term">
            {currentCard.term}
          </h2>

          {!revealed ? (
            <button
              className="flashcards-primary-btn"
              onClick={handleReveal}
              data-testid="reveal-answer"
            >
              Reveal Answer
            </button>
          ) : (
            <div className="flashcard-answer" data-testid="flashcard-answer">
              <p className="flashcard-definition">{currentCard.simple_definition}</p>
              <p className="flashcard-context">
                <strong>Why it matters in this bill:</strong> {currentCard.bill_context}
              </p>
              <p className="flashcard-example">
                <strong>Example:</strong> {currentCard.example}
              </p>
              <p className="flashcard-source">Source: {currentCard.section_id}</p>

              <div className="flashcard-answer-buttons">
                <button
                  className="flashcards-answer-btn flashcards-answer-correct"
                  onClick={() => handleAnswer(true)}
                  disabled={submitting}
                  data-testid="mark-correct"
                >
                  <CheckCircle2 size={18} /> Got it right
                </button>
                <button
                  className="flashcards-answer-btn flashcards-answer-incorrect"
                  onClick={() => handleAnswer(false)}
                  disabled={submitting}
                  data-testid="mark-incorrect"
                >
                  <XCircle size={18} /> Missed it
                </button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default LessonFlashcards;
