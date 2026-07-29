import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { ArrowLeft } from 'lucide-react';
import { getReflectionProgress } from '../api';
import './LessonSubPage.css';
import './LessonReflection.css';

// Cross-lesson progress view (Increment 10): every reflection the
// authenticated student has submitted, across every Lesson Mode debate
// they've done -- not scoped to a single lesson, so it lives outside the
// per-lesson :lessonId route tree.
function LessonReflectionProgress() {
  const [reflections, setReflections] = useState(null);
  const [error, setError] = useState('');

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await getReflectionProgress();
        if (!cancelled) setReflections(data.reflections || []);
      } catch (err) {
        if (!cancelled) {
          setError(err?.response?.data?.detail || err.message || 'Failed to load your progress.');
        }
      }
    })();
    return () => { cancelled = true; };
  }, []);

  return (
    <div className="lesson-subpage lesson-scope">
      <Link to="/lesson" className="lesson-subpage-back-link">
        <ArrowLeft size={18} />
        <span>Back to Lesson Mode</span>
      </Link>
      <section className="lesson-reflection-container" aria-labelledby="reflection-progress-heading">
        <h2 id="reflection-progress-heading" className="lesson-reflection-title">
          Your Reflection Progress
        </h2>
        <p className="lesson-reflection-intro">
          Every post-debate reflection you've submitted, across every lesson.
        </p>

        {error && <div className="lesson-reflection-error" role="alert">{error}</div>}

        {reflections === null && !error && <p>Loading…</p>}

        {reflections !== null && reflections.length === 0 && (
          <p data-testid="reflection-progress-empty">
            You haven't submitted a post-debate reflection yet.
          </p>
        )}

        {reflections && reflections.length > 0 && (
          <ul className="lesson-reflection-progress-list" data-testid="reflection-progress-list">
            {reflections.map((r) => (
              <li key={r.reflection_id} className="lesson-reflection-feedback-card">
                <p className="lesson-reflection-feedback-text">
                  <strong>Lesson:</strong> {r.lesson_id}
                </p>
                <p className="lesson-reflection-feedback-text">
                  <strong>View change:</strong> {r.view_changed}
                </p>
                <p className="lesson-reflection-feedback-text">
                  <strong>Recommended next:</strong> {r.recommended_next_activity}
                </p>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

export default LessonReflectionProgress;
