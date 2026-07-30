import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { RefreshCw, Sparkles, TrendingUp } from 'lucide-react';
import { getMasteryDashboard } from '../api';
import { trackEvent, FLOW_EVENTS } from '../utils/analytics';
import { animateBarFill, animateCountUp, staggerFadeUp } from '../utils/animations';
import './MasteryDashboard.css';

const ACTIVITY_LINKS = {
  generate_lesson: () => '/lesson',
  review_flashcards: (lessonId) => `/lesson/${lessonId}/vocabulary`,
  take_quiz: (lessonId) => `/lesson/${lessonId}/quiz`,
  open_response: (lessonId) => `/lesson/${lessonId}/open-response`,
  retake_quiz: (lessonId) => `/lesson/${lessonId}/quiz`,
  debate_and_reflect: (lessonId) => `/lesson/${lessonId}/debate-persona`,
  explore_new_bill: () => '/lesson',
};

function activityLink(activity) {
  const build = ACTIVITY_LINKS[activity.activity_type] || ACTIVITY_LINKS.explore_new_bill;
  return build(activity.lesson_id);
}

function MasteryBar({ percent, testId, delay = 0 }) {
  const clamped = Math.max(0, Math.min(100, percent));
  const fillRef = useRef(null);

  useEffect(() => {
    animateBarFill(fillRef.current, clamped, { delay });
    // Only re-run when the underlying percent changes -- not on every parent re-render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [clamped]);

  return (
    <div className="dashboard-mastery-bar-track" data-testid={testId}>
      <div ref={fillRef} className="dashboard-mastery-bar-fill" style={{ width: 0 }} />
      <span className="dashboard-mastery-bar-label">{clamped}%</span>
    </div>
  );
}

// Lesson Mode mastery dashboard (Increment 11): a read-only aggregation
// view over vocabulary mastery (Leitner boxes), quiz/open-response scores,
// and debate reflection feedback across every lesson the student has
// touched. Deliberately never combines these into one overall score --
// each is a different kind of measurement, shown in its own section, and
// the debate skill section is explicitly labeled an AI estimate rather
// than a precise measurement.
function MasteryDashboard() {
  const [dashboard, setDashboard] = useState(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const overviewRef = useRef(null);
  const lessonListRef = useRef(null);
  const cardsDueRef = useRef(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const data = await getMasteryDashboard();
      setDashboard(data);
      trackEvent(FLOW_EVENTS.DASHBOARD_VIEWED, { success: true });
    } catch (err) {
      setError(err?.response?.data?.detail || err.message || 'Failed to load your dashboard.');
      trackEvent(FLOW_EVENTS.DASHBOARD_VIEWED, { success: false });
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  // The dashboard's signature moment: once real progress data lands, the
  // overview stats and per-bill cards stagger in together, and the "cards
  // due" count ticks up -- everything else on the page stays quiet.
  useEffect(() => {
    if (!dashboard?.has_activity) return;
    if (overviewRef.current) staggerFadeUp(overviewRef.current.children, { staggerMs: 90 });
    if (lessonListRef.current) staggerFadeUp(lessonListRef.current.children, { delay: 120, staggerMs: 70 });
    animateCountUp(cardsDueRef.current, dashboard.overall_cards_due, { duration: 700 });
  }, [dashboard]);

  if (loading) {
    return (
      <div className="mastery-dashboard" data-testid="mastery-dashboard-loading">
        <p>Loading your progress…</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="mastery-dashboard">
        <div className="mastery-dashboard-error" role="alert" data-testid="mastery-dashboard-error">
          {error}
        </div>
        <button
          type="button"
          className="mastery-recommendation-btn"
          onClick={load}
          data-testid="mastery-dashboard-retry"
        >
          <RefreshCw size={16} />
          <span>Retry</span>
        </button>
      </div>
    );
  }

  if (!dashboard) return null;

  const {
    has_activity: hasActivity,
    total_lessons_started: totalLessonsStarted,
    completed_lesson_count: completedLessonCount,
    overall_vocabulary_mastery_percent: overallVocabPercent,
    overall_cards_due: overallCardsDue,
    lessons,
    recent_quiz_scores: recentQuizScores,
    recent_open_response_scores: recentOpenResponseScores,
    debate_skill: debateSkill,
    recommended_activity: recommendedActivity,
  } = dashboard;

  return (
    <div className="mastery-dashboard" data-testid="mastery-dashboard">
      <h1 className="mastery-dashboard-title">Your Mastery Dashboard</h1>

      <div className="mastery-recommendation-banner" data-testid="mastery-recommendation">
        <TrendingUp size={22} />
        <div className="mastery-recommendation-text">
          <span className="mastery-recommendation-label">Recommended next step</span>
          <span className="mastery-recommendation-title" data-testid="mastery-recommendation-title">
            {recommendedActivity.label}
          </span>
          <span className="mastery-recommendation-reason">{recommendedActivity.reason}</span>
        </div>
        <Link to={activityLink(recommendedActivity)} className="mastery-recommendation-btn">
          Go
        </Link>
      </div>

      {!hasActivity ? (
        <div className="mastery-empty-state" data-testid="mastery-empty-state">
          <p>
            You haven't started a Lesson Mode activity yet. Generate a lesson from a bill to begin
            tracking your vocabulary mastery, quiz scores, and debate feedback here.
          </p>
          <Link to="/lesson" className="mastery-empty-cta">Start your first lesson</Link>
        </div>
      ) : (
        <>
          <section className="mastery-overview-grid" ref={overviewRef}>
            <div className="mastery-stat-card">
              <span className="mastery-stat-value" data-testid="mastery-completed-count">
                {completedLessonCount} / {totalLessonsStarted}
              </span>
              <span className="mastery-stat-label">Lessons completed</span>
            </div>
            <div className="mastery-stat-card">
              <span className="mastery-stat-value" data-testid="mastery-overall-vocab">
                {overallVocabPercent}%
              </span>
              <span className="mastery-stat-label">Vocabulary mastered (all bills)</span>
              <MasteryBar percent={overallVocabPercent} testId="mastery-overall-vocab-bar" />
            </div>
            <div className="mastery-stat-card">
              <span
                ref={cardsDueRef}
                className="mastery-stat-value"
                data-testid="mastery-cards-due"
              >
                {overallCardsDue}
                {/* Overwritten on mount by animateCountUp (or immediately, unchanged, when
                    prefers-reduced-motion is set) -- this static value is the no-JS/first-paint fallback. */}
              </span>
              <span className="mastery-stat-label">Flashcards due for review</span>
            </div>
          </section>

          <section className="mastery-section">
            <h2 className="mastery-section-title">Progress by Bill</h2>
            <div className="lm-scroll-panel">
              <div className="mastery-lesson-list" data-testid="mastery-lesson-list" ref={lessonListRef}>
                {lessons.map((lesson) => (
                  <div key={lesson.lesson_id} className="mastery-lesson-card" data-testid={`mastery-lesson-${lesson.lesson_id}`}>
                    <div className="mastery-lesson-head">
                      <h3 className="mastery-lesson-title">{lesson.lesson_title}</h3>
                      {lesson.completed && <span className="mastery-completed-badge">Completed</span>}
                    </div>

                    <div className="mastery-lesson-row">
                      <span className="mastery-lesson-row-label">Vocabulary mastery</span>
                      <MasteryBar percent={lesson.vocabulary.mastery_percent} testId={`mastery-vocab-bar-${lesson.lesson_id}`} />
                    </div>
                    <p className="mastery-lesson-sub">
                      Learning: {lesson.vocabulary.box_distribution['1']} ·
                      Developing: {lesson.vocabulary.box_distribution['2']} ·
                      Mastered: {lesson.vocabulary.box_distribution['3']}
                      {lesson.vocabulary.cards_due > 0 && ` · ${lesson.vocabulary.cards_due} due`}
                    </p>

                    {lesson.has_quiz && (
                      <p className="mastery-lesson-sub">
                        Quiz: {lesson.quiz_attempts === 0
                          ? 'not attempted yet'
                          : `latest ${lesson.latest_quiz_score}% (best ${lesson.best_quiz_score}%)`}
                      </p>
                    )}
                    {lesson.has_open_response && (
                      <p className="mastery-lesson-sub">
                        Open response: {lesson.open_response_attempts === 0
                          ? 'not attempted yet'
                          : `latest score ${lesson.latest_open_response_score} / 3`}
                      </p>
                    )}
                  </div>
                ))}
              </div>
            </div>
          </section>

          {(recentQuizScores.length > 0 || recentOpenResponseScores.length > 0) && (
            <section className="mastery-section">
              <h2 className="mastery-section-title">Recent Scores</h2>
              <div className="mastery-recent-columns">
                {recentQuizScores.length > 0 && (
                  <div>
                    <h3 className="mastery-recent-heading">Quiz</h3>
                    <ul className="mastery-recent-list" data-testid="mastery-recent-quiz">
                      {recentQuizScores.map((entry, idx) => (
                        <li key={idx}>{entry.lesson_title}: {entry.score}%</li>
                      ))}
                    </ul>
                  </div>
                )}
                {recentOpenResponseScores.length > 0 && (
                  <div>
                    <h3 className="mastery-recent-heading">Open Response</h3>
                    <ul className="mastery-recent-list" data-testid="mastery-recent-open-response">
                      {recentOpenResponseScores.map((entry, idx) => (
                        <li key={idx}>{entry.lesson_title}: {entry.score} / 3</li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            </section>
          )}

          <section className="mastery-section">
            <h2 className="mastery-section-title">Debate Skill Profile</h2>
            {debateSkill ? (
              <div className="mastery-debate-card" data-testid="mastery-debate-skill">
                <div className="mastery-estimate-badge">
                  <Sparkles size={14} />
                  AI estimate -- not a precise measurement
                </div>
                <p>Based on {debateSkill.reflections_count} debate reflection(s).</p>
                {debateSkill.most_recent_recommended_skill && (
                  <p><strong>Focus area:</strong> {debateSkill.most_recent_recommended_skill}</p>
                )}
                {debateSkill.recent_recommended_skills.length > 1 && (
                  <div className="mastery-skill-chips">
                    {debateSkill.recent_recommended_skills.map((skill, idx) => (
                      <span key={idx} className="mastery-skill-chip">{skill}</span>
                    ))}
                  </div>
                )}
              </div>
            ) : (
              <p className="mastery-lesson-sub" data-testid="mastery-debate-skill-empty">
                No debate reflections yet -- debate your generated opponent and reflect afterward to
                see feedback here.
              </p>
            )}
          </section>
        </>
      )}
    </div>
  );
}

export default MasteryDashboard;
