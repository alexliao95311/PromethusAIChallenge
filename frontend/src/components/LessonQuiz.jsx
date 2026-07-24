import React, { useCallback, useEffect, useState } from 'react';
import { CheckCircle2, XCircle } from 'lucide-react';
import { getQuizQuestions, submitQuizAnswers } from '../api';
import './LessonQuiz.css';

function LessonQuiz({ lessonId }) {
  const [questions, setQuestions] = useState([]);
  const [selections, setSelections] = useState({});
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState(null);

  const loadQuestions = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const data = await getQuizQuestions(lessonId);
      setQuestions(data);
      setSelections({});
      setResult(null);
    } catch (err) {
      setError(err?.response?.data?.detail || err.message || 'Failed to load the quiz.');
    } finally {
      setLoading(false);
    }
  }, [lessonId]);

  useEffect(() => {
    loadQuestions();
  }, [loadQuestions]);

  const handleSelect = (questionId, index) => {
    if (result) return; // locked once submitted
    setSelections((prev) => ({ ...prev, [questionId]: index }));
  };

  const allAnswered = questions.length > 0 && questions.every((q) => selections[q.question_id] !== undefined);

  const handleSubmit = async () => {
    if (!allAnswered || submitting) return;
    setSubmitting(true);
    setError('');
    try {
      const answers = questions.map((q) => ({
        question_id: q.question_id,
        selected_index: selections[q.question_id],
      }));
      const data = await submitQuizAnswers(lessonId, answers);
      setResult(data);
    } catch (err) {
      setError(err?.response?.data?.detail || err.message || 'Failed to submit the quiz.');
    } finally {
      setSubmitting(false);
    }
  };

  const resultByQuestionId = {};
  if (result) {
    for (const r of result.results) {
      resultByQuestionId[r.question_id] = r;
    }
  }

  if (loading) {
    return <div className="lesson-quiz-container" data-testid="quiz-loading">Loading quiz…</div>;
  }

  if (error && questions.length === 0) {
    return <div className="lesson-quiz-container lesson-quiz-error">{error}</div>;
  }

  if (questions.length === 0) {
    return (
      <div className="lesson-quiz-container">
        <p>No quiz is available for this lesson yet.</p>
      </div>
    );
  }

  return (
    <div className="lesson-quiz-container">
      {result && (
        <div className="quiz-score-banner" data-testid="quiz-score">
          Score: {result.score}% ({result.results.filter((r) => r.correct).length} / {result.results.length} correct)
        </div>
      )}

      {error && <div className="lesson-quiz-error-inline">{error}</div>}

      <div className="quiz-questions-list">
        {questions.map((q, qIndex) => {
          const questionResult = resultByQuestionId[q.question_id];
          return (
            <div className="quiz-question-card" key={q.question_id} data-testid={`quiz-question-${q.question_id}`}>
              <div className="quiz-question-heading">
                <span className="quiz-question-number">Question {qIndex + 1}</span>
                <span className={`quiz-difficulty-badge quiz-difficulty-${q.difficulty}`}>{q.difficulty}</span>
              </div>
              <p className="quiz-question-text">{q.question}</p>

              <div className="quiz-answer-choices">
                {q.answer_choices.map((choice, choiceIndex) => {
                  const isSelected = selections[q.question_id] === choiceIndex;
                  let choiceClass = 'quiz-answer-choice';
                  if (isSelected) choiceClass += ' quiz-answer-choice-selected';
                  if (questionResult) {
                    if (choiceIndex === questionResult.correct_answer_index) {
                      choiceClass += ' quiz-answer-choice-correct';
                    } else if (isSelected && !questionResult.correct) {
                      choiceClass += ' quiz-answer-choice-incorrect';
                    }
                  }
                  return (
                    <button
                      key={choiceIndex}
                      type="button"
                      className={choiceClass}
                      onClick={() => handleSelect(q.question_id, choiceIndex)}
                      disabled={!!result}
                      data-testid={`quiz-choice-${q.question_id}-${choiceIndex}`}
                    >
                      {choice}
                    </button>
                  );
                })}
              </div>

              {questionResult && (
                <div
                  className={`quiz-explanation ${questionResult.correct ? 'quiz-explanation-correct' : 'quiz-explanation-incorrect'}`}
                  data-testid={`quiz-explanation-${q.question_id}`}
                >
                  {questionResult.correct ? <CheckCircle2 size={16} /> : <XCircle size={16} />}
                  <span>{questionResult.explanation}</span>
                </div>
              )}
            </div>
          );
        })}
      </div>

      {!result && (
        <button
          className="quiz-submit-btn"
          onClick={handleSubmit}
          disabled={!allAnswered || submitting}
          data-testid="submit-quiz"
        >
          {submitting ? 'Submitting…' : 'Submit Quiz'}
        </button>
      )}
    </div>
  );
}

export default LessonQuiz;
