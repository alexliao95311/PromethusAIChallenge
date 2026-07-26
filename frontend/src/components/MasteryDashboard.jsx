import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Sparkles, TrendingUp } from 'lucide-react';
import { getMasteryDashboard } from '../api';
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

function MasteryBar({ percent, testId }) {
  const clamped = Math.max(0, Math.min(100, percent));
  return (
    <div className="mastery-bar-track" data-testid={testId}>
      <div className="mastery-bar-fill" style={{ width: `${clamped}%` }} />
      <span className="mastery-bar-label">{clamped}%</span>
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

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await getMasteryDashboard();
        if (!cancelled) setDashboard(data);
      } catch (err) {
        if (!cancelled) {
          setError(err?.response?.data?.detail || err.message || 'Failed to load your dashboard.');
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

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
          <section className="mastery-overview-grid">
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
              <span className="mastery-stat-value" data-testid="mastery-cards-due">
                {overallCardsDue}
              </span>
              <span className="mastery-stat-label">Flashcards due for review</span>
            </div>
          </section>

          <section className="mastery-section">
            <h2 className="mastery-section-title">Progress by Bill</h2>
            <div className="mastery-lesson-list" data-testid="mastery-lesson-list">
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
