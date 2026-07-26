import React from 'react';
import { Link, useParams } from 'react-router-dom';
import { ArrowLeft } from 'lucide-react';
import LessonQuiz from './LessonQuiz';
import LessonModeNav from './LessonModeNav';
import LessonFlowProgress from './LessonFlowProgress';
import LessonFlowNextButton from './LessonFlowNextButton';
import './LessonSubPage.css';

// Quiz service page: hosts the multiple-choice quiz component.
function LessonQuizPage() {
  const { lessonId } = useParams();

  return (
    <div className="lesson-subpage">
      <Link to={`/lesson/${lessonId}`} className="lesson-subpage-back-link">
        <ArrowLeft size={18} />
        <span>Back to Lesson</span>
      </Link>
      <LessonFlowProgress lessonId={lessonId} currentStepKey="quiz" />
      <LessonModeNav lessonId={lessonId} />
      <LessonQuiz lessonId={lessonId} />
      <LessonFlowNextButton lessonId={lessonId} currentStepKey="quiz" />
    </div>
  );
}

export default LessonQuizPage;
