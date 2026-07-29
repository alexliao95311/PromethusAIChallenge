import React from 'react';
import { Link } from 'react-router-dom';
import { ArrowLeft } from 'lucide-react';
import MasteryDashboard from './MasteryDashboard';
import './LessonSubPage.css';

// Cross-lesson mastery dashboard (Increment 11) -- not scoped to a single
// lesson, so like LessonReflectionProgress it lives outside the per-lesson
// :lessonId route tree.
function MasteryDashboardPage() {
  return (
    <div className="lesson-subpage lesson-scope">
      <Link to="/lesson" className="lesson-subpage-back-link">
        <ArrowLeft size={18} />
        <span>Back to Lesson Mode</span>
      </Link>
      <MasteryDashboard />
    </div>
  );
}

export default MasteryDashboardPage;
