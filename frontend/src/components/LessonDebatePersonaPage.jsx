import React from 'react';
import { Link, useParams } from 'react-router-dom';
import { ArrowLeft } from 'lucide-react';
import LessonDebatePersona from './LessonDebatePersona';
import LessonModeNav from './LessonModeNav';
import LessonFlowProgress from './LessonFlowProgress';
import './LessonSubPage.css';

// Dynamic opposing debate persona service page (Increment 9). No
// LessonFlowNextButton here -- Increment 12 wires "Start Debate" itself to
// navigate onward into Debate.jsx, which is the actual next step.
function LessonDebatePersonaPage() {
  const { lessonId } = useParams();

  return (
    <div className="lesson-subpage lesson-scope">
      <Link to={`/lesson/${lessonId}`} className="lesson-subpage-back-link">
        <ArrowLeft size={18} />
        <span>Back to Lesson</span>
      </Link>
      <div className="lm-sticky-header">
        <LessonFlowProgress lessonId={lessonId} currentStepKey="debate-persona" />
        <LessonModeNav lessonId={lessonId} />
      </div>
      <LessonDebatePersona lessonId={lessonId} />
    </div>
  );
}

export default LessonDebatePersonaPage;
