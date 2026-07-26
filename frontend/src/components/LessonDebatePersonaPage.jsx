import React from 'react';
import { Link, useParams } from 'react-router-dom';
import { ArrowLeft } from 'lucide-react';
import LessonDebatePersona from './LessonDebatePersona';
import LessonModeNav from './LessonModeNav';
import './LessonSubPage.css';

// Dynamic opposing debate persona service page (Increment 9).
function LessonDebatePersonaPage() {
  const { lessonId } = useParams();

  return (
    <div className="lesson-subpage">
      <Link to={`/lesson/${lessonId}`} className="lesson-subpage-back-link">
        <ArrowLeft size={18} />
        <span>Back to Lesson</span>
      </Link>
      <LessonModeNav lessonId={lessonId} />
      <LessonDebatePersona lessonId={lessonId} />
    </div>
  );
}

export default LessonDebatePersonaPage;
