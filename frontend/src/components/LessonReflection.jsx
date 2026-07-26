import React, { useState } from 'react';
import { useLocation } from 'react-router-dom';
import { Sparkles } from 'lucide-react';
import { submitReflection } from '../api';
import { trackEvent, FLOW_EVENTS } from '../utils/analytics';
import { markFlowStepComplete } from '../utils/lessonFlow';
import './LessonReflection.css';

const VIEW_CHANGE_OPTIONS = [
  { value: 'yes', label: 'Yes, it changed' },
  { value: 'somewhat', label: 'Somewhat' },
  { value: 'no', label: 'No, it did not change' },
  { value: 'less_certain', label: "I'm less certain now" },
];

const FEEDBACK_FIELDS = [
  { key: 'strongest_student_argument', label: 'Your strongest argument' },
  { key: 'weakest_reasoning_step', label: 'Where your reasoning was weakest' },
  { key: 'evidence_use_feedback', label: 'How you used evidence' },
  { key: 'missed_opponent_point', label: "A point you didn't address" },
  { key: 'perspective_understanding', label: 'Understanding the opposing perspective' },
];

// Post-debate reflection service page (Increment 10): the student
// self-reports whether their view of the bill changed, then gets a
// grounded educational analysis of their own debate transcript -- a
// separate rubric from winner-determination judging, never used to infer
// belief change. This is self-contained rather than auto-capturing a live
// debate transcript, mirroring Increment 9's LessonDebatePersona (Debate.jsx
// doesn't yet pass its transcript back into Lesson Mode).
function LessonReflection({ lessonId }) {
  const location = useLocation();
  // Increment 12: when arriving straight from a Lesson Mode debate
  // (Debate.jsx's "End Debate" navigates here with the transcript), prefill
  // it so the student doesn't have to paste it in manually. Falls back to
  // an empty field, same as before, when arriving directly (e.g. a refresh).
  const [transcript, setTranscript] = useState(location.state?.transcript || '');
  const [viewChanged, setViewChanged] = useState('');
  const [explanation, setExplanation] = useState('');

  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');
  const [reflection, setReflection] = useState(null);

  const canSubmit = transcript.trim() && viewChanged && !submitting;

  const handleSubmit = async () => {
    if (!canSubmit) return;
    setSubmitting(true);
    setError('');
    try {
      const data = await submitReflection(lessonId, {
        transcript,
        viewChanged,
        explanation: explanation.trim() || undefined,
      });
      setReflection(data);
      markFlowStepComplete(lessonId, 'reflection');
      trackEvent(FLOW_EVENTS.REFLECTION_SUBMITTED, { lessonId, success: true });
    } catch (err) {
      setError(err?.response?.data?.detail || err.message || 'Failed to generate your reflection.');
      trackEvent(FLOW_EVENTS.REFLECTION_SUBMITTED, { lessonId, success: false });
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <section className="lesson-reflection-container" aria-labelledby="lesson-reflection-heading">
      <h2 id="lesson-reflection-heading" className="lesson-reflection-title">
        Post-Debate Reflection
      </h2>
      <p className="lesson-reflection-intro">
        Paste the transcript from your practice debate to get feedback on your own performance --
        this does not judge who won.
      </p>

      {error && <div className="lesson-reflection-error" role="alert">{error}</div>}

      {!reflection ? (
        <div className="lesson-reflection-form">
          <label className="lesson-reflection-label" htmlFor="lesson-reflection-transcript">
            Debate transcript
          </label>
          <textarea
            id="lesson-reflection-transcript"
            className="lesson-reflection-textarea"
            rows={8}
            value={transcript}
            onChange={(e) => setTranscript(e.target.value)}
            placeholder="Paste your full debate transcript here..."
            data-testid="reflection-transcript"
          />

          <fieldset className="lesson-reflection-view-changed">
            <legend className="lesson-reflection-label">Did your view of the bill change?</legend>
            {VIEW_CHANGE_OPTIONS.map((opt) => (
              <label key={opt.value} className="lesson-reflection-radio-label">
                <input
                  type="radio"
                  name="view_changed"
                  value={opt.value}
                  checked={viewChanged === opt.value}
                  onChange={() => setViewChanged(opt.value)}
                  data-testid={`reflection-view-changed-${opt.value}`}
                />
                {opt.label}
              </label>
            ))}
          </fieldset>

          <label className="lesson-reflection-label" htmlFor="lesson-reflection-explanation">
            Why? (optional)
          </label>
          <textarea
            id="lesson-reflection-explanation"
            className="lesson-reflection-textarea lesson-reflection-explanation"
            rows={3}
            value={explanation}
            onChange={(e) => setExplanation(e.target.value)}
            placeholder="What, if anything, changed your thinking?"
            data-testid="reflection-explanation"
          />

          <button
            type="button"
            className="lesson-reflection-submit-btn"
            onClick={handleSubmit}
            disabled={!canSubmit}
            data-testid="reflection-submit"
          >
            {submitting ? 'Analyzing your debate…' : 'Get Feedback'}
          </button>
        </div>
      ) : (
        <div className="lesson-reflection-result" data-testid="reflection-result">
          <div className="lesson-reflection-self-report">
            <Sparkles size={16} />
            <span>
              <strong>Your view:</strong>{' '}
              {VIEW_CHANGE_OPTIONS.find((o) => o.value === reflection.view_changed)?.label
                || reflection.view_changed}
              {reflection.explanation ? ` -- ${reflection.explanation}` : ''}
            </span>
          </div>

          {FEEDBACK_FIELDS.map((field) => {
            const item = reflection[field.key];
            if (!item) return null;
            return (
              <div
                key={field.key}
                className="lesson-reflection-feedback-card"
                data-testid={`reflection-${field.key.replace(/_/g, '-')}`}
              >
                <h3 className="lesson-reflection-feedback-heading">{field.label}</h3>
                <p className="lesson-reflection-feedback-text">{item.feedback}</p>
                {item.transcript_excerpt && (
                  <blockquote className="lesson-reflection-excerpt">
                    "{item.transcript_excerpt}"
                  </blockquote>
                )}
              </div>
            );
          })}

          <div className="lesson-reflection-next-steps">
            <h3 className="lesson-reflection-feedback-heading">Next steps</h3>
            <p data-testid="reflection-recommended-skill">
              <strong>Practice:</strong> {reflection.recommended_skill}
            </p>
            <p data-testid="reflection-recommended-activity">
              <strong>Try next:</strong> {reflection.recommended_next_activity}
            </p>
          </div>

          <button
            type="button"
            className="lesson-reflection-regenerate-btn"
            onClick={() => setReflection(null)}
            data-testid="reflection-reset"
          >
            Reflect on another debate
          </button>
        </div>
      )}
    </section>
  );
}

export default LessonReflection;
