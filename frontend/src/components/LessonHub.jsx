import React, { useState } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { ArrowLeft, BookOpen } from 'lucide-react';
import { generateLesson } from '../api';
import { saveLessonBillText } from '../utils/lessonSession';
import './LessonHub.css';

function slugify(text) {
  return (text || '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/(^-|-$)/g, '')
    .slice(0, 60);
}

// Lesson Mode entry point -- maps to the core lesson-generation service
// (POST /lesson/generate). A student arrives here either directly (paste a
// bill) or via a "Start Lesson" action from Legislation.jsx, which passes
// billText/billTitle through router state.
function LessonHub() {
  const navigate = useNavigate();
  const location = useLocation();
  const incoming = location.state || {};

  const [billTitle, setBillTitle] = useState(incoming.billTitle || '');
  const [billText, setBillText] = useState(incoming.billText || '');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const handleGenerate = async () => {
    if (loading || !billText.trim()) return;
    setLoading(true);
    setError('');
    try {
      const billId = incoming.billId || slugify(billTitle) || `bill-${Date.now()}`;
      const lesson = await generateLesson(billId, billText, {
        includeVocabulary: true,
        includeQuiz: true,
        includeOpenResponse: true,
      });
      saveLessonBillText(lesson.lesson_id, billText, billTitle);
      navigate(`/lesson/${lesson.lesson_id}`);
    } catch (err) {
      setError(err?.response?.data?.detail || err.message || 'Failed to generate the lesson.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="lesson-hub-page">
      <Link to="/" className="lesson-hub-back-link">
        <ArrowLeft size={18} />
        <span>Back to Home</span>
      </Link>

      <div className="lesson-hub-card">
        <div className="lesson-hub-icon">
          <BookOpen size={28} />
        </div>
        <h1 className="lesson-hub-title">Start a Lesson</h1>
        <p className="lesson-hub-intro">
          Turn a bill into a guided lesson: a grounded summary, vocabulary flashcards, a quiz,
          an open-response question, a personalized impact narrative, and a debate opponent
          shaped by the bill itself.
        </p>

        {error && <div className="lesson-hub-error" role="alert">{error}</div>}

        <label className="lesson-hub-label" htmlFor="lesson-hub-title">
          Bill title
        </label>
        <input
          id="lesson-hub-title"
          className="lesson-hub-input"
          type="text"
          value={billTitle}
          onChange={(e) => setBillTitle(e.target.value)}
          placeholder="e.g. Early Childhood Educator Tax Credit Act"
          data-testid="lesson-hub-title-input"
        />

        <label className="lesson-hub-label" htmlFor="lesson-hub-text">
          Bill text
        </label>
        <textarea
          id="lesson-hub-text"
          className="lesson-hub-textarea"
          rows={10}
          value={billText}
          onChange={(e) => setBillText(e.target.value)}
          placeholder="Paste the full bill text here..."
          data-testid="lesson-hub-text-input"
        />

        <button
          className="lesson-hub-generate-btn"
          onClick={handleGenerate}
          disabled={loading || !billText.trim()}
          data-testid="lesson-hub-generate"
        >
          {loading ? 'Building your lesson…' : 'Generate Lesson'}
        </button>

        <p className="lesson-hub-persona-note">
          Want a personalized impact narrative later? <Link to="/lesson/persona">Build a persona</Link>{' '}
          (optional, and can be fictional).
        </p>
      </div>
    </div>
  );
}

export default LessonHub;
