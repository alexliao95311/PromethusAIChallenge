import React, { useCallback, useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { ArrowLeft, RefreshCw } from 'lucide-react';
import { getLesson } from '../api';
import LessonModeNav from './LessonModeNav';
import LessonFlowProgress from './LessonFlowProgress';
import LessonFlowNextButton from './LessonFlowNextButton';
import { markFlowStepComplete } from '../utils/lessonFlow';
import { trackEvent, FLOW_EVENTS } from '../utils/analytics';
import './LessonOverview.css';

function GroundedClaimList({ items, testId }) {
  if (!items || items.length === 0) return null;
  return (
    <ul className="lesson-claim-list" data-testid={testId}>
      {items.map((item, i) => (
        <li key={i} className="lesson-claim">
          <span>{item.claim}</span>
          {item.section_ids?.length > 0 && (
            <span className="lesson-claim-sources"> ({item.section_ids.join(', ')})</span>
          )}
        </li>
      ))}
    </ul>
  );
}

// The lesson-generation service's display page: title, plain-language
// summary, learning objectives, major provisions, stakeholders, and
// pro/con arguments -- every claim traceable to a cited bill section.
function LessonOverview() {
  const { lessonId } = useParams();
  const [lesson, setLesson] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const data = await getLesson(lessonId);
      setLesson(data);
      markFlowStepComplete(lessonId, 'lesson');
      trackEvent(FLOW_EVENTS.LESSON_VIEWED, { lessonId, success: true });
    } catch (err) {
      setError(err?.response?.data?.detail || err.message || 'Failed to load the lesson.');
      trackEvent(FLOW_EVENTS.LESSON_VIEWED, { lessonId, success: false });
    } finally {
      setLoading(false);
    }
  }, [lessonId]);

  useEffect(() => {
    load();
  }, [load]);

  if (loading) {
    return <div className="lesson-overview-page" data-testid="lesson-overview-loading">Loading lesson…</div>;
  }

  if (error) {
    return (
      <div className="lesson-overview-page">
        <Link to="/lesson" className="lesson-overview-back-link">
          <ArrowLeft size={18} />
          <span>Back to Lesson Mode</span>
        </Link>
        <div className="lesson-overview-error" role="alert">{error}</div>
        <button
          type="button"
          className="lesson-overview-retry-btn"
          onClick={load}
          data-testid="lesson-overview-retry"
        >
          <RefreshCw size={16} />
          <span>Retry</span>
        </button>
      </div>
    );
  }

  if (!lesson) return null;

  return (
    <div className="lesson-overview-page lesson-scope">
      <Link to="/lesson" className="lesson-overview-back-link">
        <ArrowLeft size={18} />
        <span>Back to Lesson Mode</span>
      </Link>

      <div className="lm-sticky-header">
        <LessonFlowProgress lessonId={lessonId} currentStepKey="lesson" />
        <LessonModeNav lessonId={lessonId} />
      </div>

      <div className="lesson-overview-card">
        <h1 className="lesson-overview-title" data-testid="lesson-overview-title">
          {lesson.lesson_title}
        </h1>
        <p className="lesson-overview-summary" data-testid="lesson-overview-summary">
          {lesson.plain_language_summary}
        </p>

        {lesson.learning_objectives?.length > 0 && (
          <div className="lesson-overview-section">
            <h2>Learning objectives</h2>
            <ul>
              {lesson.learning_objectives.map((obj, i) => <li key={i}>{obj}</li>)}
            </ul>
          </div>
        )}

        <div className="lesson-overview-provisions-stakeholders">
          <div className="lesson-overview-section">
            <h2>Major provisions</h2>
            <GroundedClaimList items={lesson.major_provisions} testId="lesson-overview-provisions" />
          </div>

          <div className="lesson-overview-section">
            <h2>Stakeholders</h2>
            <GroundedClaimList items={lesson.stakeholders} testId="lesson-overview-stakeholders" />
          </div>
        </div>

        <div className="lesson-overview-pro-con">
          <div className="lesson-overview-section lesson-overview-pro">
            <h2>Pro arguments</h2>
            <GroundedClaimList items={lesson.pro_arguments} testId="lesson-overview-pro" />
          </div>
          <div className="lesson-overview-section lesson-overview-con">
            <h2>Con arguments</h2>
            <GroundedClaimList items={lesson.con_arguments} testId="lesson-overview-con" />
          </div>
        </div>

        <LessonFlowNextButton lessonId={lessonId} currentStepKey="lesson" />
      </div>
    </div>
  );
}

export default LessonOverview;
