import React, { useEffect, useState } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { ArrowLeft } from 'lucide-react';
import PersonaBuilder from './PersonaBuilder';
import { generateLesson } from '../api';
import { saveLessonBillText, slugifyBillTitle } from '../utils/lessonSession';
import { trackEvent, FLOW_EVENTS } from '../utils/analytics';
import './LessonPersona.css';

// Lesson Mode's entry page (Increment 7, reordered by Increment 12's flow:
// bill -> persona -> personal impact -> lesson). A student arrives here
// either mid-flow -- from Legislation.jsx's "Lesson" action card, carrying
// billTitle/billText in router state -- or standalone, e.g. via LessonHub's
// "Build a persona" link, with no bill in progress.
//
// Persona is optional (PersonaBuilder's "Skip for now" button), and when a
// bill is in progress, saving OR skipping both advance the flow the same
// way: generate the lesson, then continue to its personal-impact step.
// Personal impact itself is also optional -- its own page already has a
// "Continue to Lesson" link (LessonFlowNextButton) that works without
// generating an impact first.
function LessonPersona({ user }) {
  const navigate = useNavigate();
  const location = useLocation();
  const incoming = location.state || {};
  const billTitle = incoming.billTitle || '';
  const billText = incoming.billText || '';
  const hasBillInProgress = Boolean(billText.trim());

  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    if (hasBillInProgress) {
      trackEvent(FLOW_EVENTS.PERSONA_STEP_VIEWED, { lessonId: incoming.billId || null });
    }
    // Fire once per page load; re-running on every incoming-object identity
    // change would double-count within the same visit.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const advance = async () => {
    if (!hasBillInProgress) {
      navigate('/lesson');
      return;
    }

    setGenerating(true);
    setError('');
    try {
      const billId = incoming.billId || slugifyBillTitle(billTitle) || `bill-${Date.now()}`;
      trackEvent(FLOW_EVENTS.BILL_SELECTED, { lessonId: billId });
      const lesson = await generateLesson(billId, billText, {
        includeVocabulary: true,
        includeQuiz: true,
        includeOpenResponse: true,
      });
      saveLessonBillText(lesson.lesson_id, billText, billTitle);
      trackEvent(FLOW_EVENTS.LESSON_VIEWED, { lessonId: lesson.lesson_id, success: true });
      navigate(`/lesson/${lesson.lesson_id}/personal-impact`);
    } catch (err) {
      setError(err?.response?.data?.detail || err.message || 'Failed to generate the lesson.');
      trackEvent(FLOW_EVENTS.LESSON_VIEWED, { success: false });
      setGenerating(false);
    }
  };

  return (
    <div className="lesson-persona-page">
      <Link to="/lesson" className="lesson-persona-back-link">
        <ArrowLeft size={18} />
        <span>Back to Lesson</span>
      </Link>

      {hasBillInProgress && (
        <p className="lesson-persona-context" data-testid="lesson-persona-bill-context">
          Building a lesson for <strong>{billTitle || 'this bill'}</strong>. Add a persona
          below for a personalized impact narrative, or skip ahead.
        </p>
      )}

      {error && (
        <div className="lesson-persona-error" role="alert" data-testid="lesson-persona-error">
          {error}
        </div>
      )}

      {generating ? (
        <div className="lesson-persona-generating" data-testid="lesson-persona-generating">
          Building your lesson…
        </div>
      ) : (
        <PersonaBuilder
          isAuthenticated={!!user}
          onSaved={hasBillInProgress ? advance : undefined}
          onSkip={hasBillInProgress ? advance : undefined}
        />
      )}
    </div>
  );
}

export default LessonPersona;
