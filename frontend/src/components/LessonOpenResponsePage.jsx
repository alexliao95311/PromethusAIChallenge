import React from 'react';
import { Link, useParams } from 'react-router-dom';
import { ArrowLeft } from 'lucide-react';
import LessonOpenResponse from './LessonOpenResponse';
import LessonModeNav from './LessonModeNav';
import './LessonSubPage.css';

// Open-response service page: hosts the open-ended question + AI grading component.
function LessonOpenResponsePage() {
  const { lessonId } = useParams();

  return (
    <div className="lesson-subpage">
      <Link to={`/lesson/${lessonId}`} className="lesson-subpage-back-link">
        <ArrowLeft size={18} />
        <span>Back to Lesson</span>
      </Link>
      <LessonModeNav lessonId={lessonId} />
      <LessonOpenResponse lessonId={lessonId} />
    </div>
  );
}

export default LessonOpenResponsePage;
