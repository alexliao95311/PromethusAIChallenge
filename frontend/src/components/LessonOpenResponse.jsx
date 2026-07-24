import React, { useCallback, useEffect, useState } from 'react';
import { getOpenResponseQuestion, submitOpenResponseAnswer } from '../api';
import './LessonOpenResponse.css';

const SCORE_LABELS = {
  0: 'Incorrect or irrelevant',
  1: 'Partial understanding',
  2: 'Mostly correct, missing reasoning',
  3: 'Complete and well explained',
};

function LessonOpenResponse({ lessonId }) {
  const [question, setQuestion] = useState(null);
  const [answer, setAnswer] = useState('');
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState(null);

  const loadQuestion = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const data = await getOpenResponseQuestion(lessonId);
      setQuestion(data);
      setResult(null);
      setAnswer('');
    } catch (err) {
      setError(err?.response?.data?.detail || err.message || 'Failed to load the question.');
    } finally {
      setLoading(false);
    }
  }, [lessonId]);

  useEffect(() => {
    loadQuestion();
  }, [loadQuestion]);

  const handleSubmit = async () => {
    if (submitting) return;
    setSubmitting(true);
    setError('');
    try {
      const data = await submitOpenResponseAnswer(lessonId, answer);
      setResult(data);
    } catch (err) {
      setError(err?.response?.data?.detail || err.message || 'Failed to submit your answer.');
    } finally {
      setSubmitting(false);
    }
  };

  const handleTryAgain = () => {
    setResult(null);
    setAnswer('');
  };

  if (loading) {
    return <div className="open-response-container" data-testid="open-response-loading">Loading question…</div>;
  }

  if (error && !question) {
    return <div className="open-response-container open-response-error">{error}</div>;
  }

  if (!question) {
    return (
      <div className="open-response-container">
        <p>No open-response question is available for this lesson yet.</p>
      </div>
    );
  }

  return (
    <div className="open-response-container">
      <div className="open-response-question-card">
        <span className="open-response-type-badge">{question.question_type.replace(/_/g, ' ')}</span>
        <p className="open-response-question-text" data-testid="open-response-question">
          {question.question}
        </p>

        {error && <div className="open-response-error-inline">{error}</div>}

        {!result ? (
          <>
            <textarea
              className="open-response-textarea"
              value={answer}
              onChange={(e) => setAnswer(e.target.value)}
              placeholder="Write your answer here..."
              rows={6}
              data-testid="open-response-textarea"
            />
            <button
              className="open-response-submit-btn"
              onClick={handleSubmit}
              disabled={submitting}
              data-testid="open-response-submit"
            >
              {submitting ? 'Submitting…' : 'Submit Answer'}
            </button>
          </>
        ) : (
          <div className="open-response-feedback" data-testid="open-response-feedback">
            <div className={`open-response-score-badge open-response-score-${result.score}`}>
              Score: {result.score} / 3 &mdash; {SCORE_LABELS[result.score]}
            </div>

            <p className="open-response-feedback-text" data-testid="open-response-feedback-text">
              {result.feedback}
            </p>

            {result.accurate_points.length > 0 && (
              <div className="open-response-points open-response-points-accurate">
                <strong>What you got right:</strong>
                <ul>
                  {result.accurate_points.map((point, i) => (
                    <li key={i}>{point}</li>
                  ))}
                </ul>
              </div>
            )}

            {result.missed_points.length > 0 && (
              <div className="open-response-points open-response-points-missed">
                <strong>What you missed:</strong>
                <ul>
                  {result.missed_points.map((point, i) => (
                    <li key={i}>{point}</li>
                  ))}
                </ul>
              </div>
            )}

            {result.section_ids.length > 0 && (
              <p className="open-response-sources">
                Relevant sections: {result.section_ids.join(', ')}
              </p>
            )}

            <button
              className="open-response-submit-btn open-response-try-again-btn"
              onClick={handleTryAgain}
              data-testid="open-response-try-again"
            >
              Try Again
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

export default LessonOpenResponse;
