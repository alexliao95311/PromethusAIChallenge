import React from 'react';
import { Link, useLocation } from 'react-router-dom';
import './LessonModeNav.css';

const TABS = [
  { key: 'overview', label: 'Overview', suffix: '' },
  { key: 'vocabulary', label: 'Vocabulary', suffix: '/vocabulary' },
  { key: 'quiz', label: 'Quiz', suffix: '/quiz' },
  { key: 'open-response', label: 'Open Response', suffix: '/open-response' },
  { key: 'personal-impact', label: 'Personal Impact', suffix: '/personal-impact' },
  { key: 'debate-persona', label: 'Debate Opponent', suffix: '/debate-persona' },
];

// A consistent tab bar shown at the top of every Lesson Mode sub-page, so
// the six backend services (lesson, vocabulary, quiz, open-response,
// personal-impact, dynamic debate persona) read as one visually cohesive
// experience rather than disconnected pages.
function LessonModeNav({ lessonId }) {
  const location = useLocation();
  const basePath = `/lesson/${lessonId}`;

  return (
    <nav className="lesson-mode-nav" aria-label="Lesson Mode sections">
      {TABS.map((tab) => {
        const path = `${basePath}${tab.suffix}`;
        const isActive = location.pathname === path;
        return (
          <Link
            key={tab.key}
            to={path}
            className={`lesson-mode-nav-tab ${isActive ? 'lesson-mode-nav-tab-active' : ''}`}
            data-testid={`lesson-nav-${tab.key}`}
          >
            {tab.label}
          </Link>
        );
      })}
    </nav>
  );
}

export default LessonModeNav;
