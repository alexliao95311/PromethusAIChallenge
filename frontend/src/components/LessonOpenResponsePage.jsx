import React from 'react';
import { Link, useParams } from 'react-router-dom';
import { ArrowLeft } from 'lucide-react';
import LessonOpenResponse from './LessonOpenResponse';
import LessonModeNav from './LessonModeNav';
import LessonFlowProgress from './LessonFlowProgress';
import LessonFlowNextButton from './LessonFlowNextButton';
import './LessonSubPage.css';

// Open-response service page: hosts the open-ended question + AI grading component.
function LessonOpenResponsePage() {
  const { lessonId } = useParams();

  return (
    <div className="lesson-subpage lesson-scope">
      <Link to={`/lesson/${lessonId}`} className="lesson-subpage-back-link">
        <ArrowLeft size={18} />
        <span>Back to Lesson</span>
      </Link>
      <div className="lm-sticky-header">
        <LessonFlowProgress lessonId={lessonId} currentStepKey="open-response" />
        <LessonModeNav lessonId={lessonId} />
      </div>
      <LessonOpenResponse lessonId={lessonId} />
      <LessonFlowNextButton lessonId={lessonId} currentStepKey="open-response" />
    </div>
  );
}

export default LessonOpenResponsePage;
