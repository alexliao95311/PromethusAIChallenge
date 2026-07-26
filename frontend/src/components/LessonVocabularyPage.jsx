import React from 'react';
import { Link, useParams } from 'react-router-dom';
import { ArrowLeft } from 'lucide-react';
import LessonFlashcards from './LessonFlashcards';
import LessonModeNav from './LessonModeNav';
import LessonFlowProgress from './LessonFlowProgress';
import LessonFlowNextButton from './LessonFlowNextButton';
import './LessonSubPage.css';

// Vocabulary-review service page: hosts the flashcard/Leitner-box component.
function LessonVocabularyPage() {
  const { lessonId } = useParams();

  return (
    <div className="lesson-subpage">
      <Link to={`/lesson/${lessonId}`} className="lesson-subpage-back-link">
        <ArrowLeft size={18} />
        <span>Back to Lesson</span>
      </Link>
      <LessonFlowProgress lessonId={lessonId} currentStepKey="vocabulary" />
      <LessonModeNav lessonId={lessonId} />
      <LessonFlashcards lessonId={lessonId} />
      <LessonFlowNextButton lessonId={lessonId} currentStepKey="vocabulary" />
    </div>
  );
}

export default LessonVocabularyPage;
