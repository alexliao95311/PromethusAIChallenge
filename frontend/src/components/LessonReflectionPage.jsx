import React from 'react';
import { Link, useParams } from 'react-router-dom';
import { ArrowLeft } from 'lucide-react';
import LessonReflection from './LessonReflection';
import LessonModeNav from './LessonModeNav';
import LessonFlowProgress from './LessonFlowProgress';
import LessonFlowNextButton from './LessonFlowNextButton';
import './LessonSubPage.css';

// Post-debate reflection service page (Increment 10).
function LessonReflectionPage() {
  const { lessonId } = useParams();

  return (
    <div className="lesson-subpage lesson-scope">
      <Link to={`/lesson/${lessonId}`} className="lesson-subpage-back-link">
        <ArrowLeft size={18} />
        <span>Back to Lesson</span>
      </Link>
      <div className="lm-sticky-header">
        <LessonFlowProgress lessonId={lessonId} currentStepKey="reflection" />
        <LessonModeNav lessonId={lessonId} />
      </div>
      <LessonReflection lessonId={lessonId} />
      <LessonFlowNextButton lessonId={lessonId} currentStepKey="reflection" />
      <Link to="/lesson/reflection-progress" className="lesson-subpage-back-link">
        See your progress across every lesson debate
      </Link>
    </div>
  );
}

export default LessonReflectionPage;
