import React from 'react';
import { Link, useParams } from 'react-router-dom';
import { ArrowLeft } from 'lucide-react';
import LessonPersonalImpact from './LessonPersonalImpact';
import LessonModeNav from './LessonModeNav';
import { getLessonBillText } from '../utils/lessonSession';
import './LessonSubPage.css';

// Personalized bill-impact service page: hosts the persona-driven impact
// narrative component. Reuses the bill text saved to sessionStorage by
// LessonHub, so this still works after a page refresh even if the
// backend's in-memory RAG cache was cleared by a process restart.
function LessonPersonalImpactPage() {
  const { lessonId } = useParams();
  const { billText } = getLessonBillText(lessonId);

  return (
    <div className="lesson-subpage">
      <Link to={`/lesson/${lessonId}`} className="lesson-subpage-back-link">
        <ArrowLeft size={18} />
        <span>Back to Lesson</span>
      </Link>
      <LessonModeNav lessonId={lessonId} />
      <LessonPersonalImpact lessonId={lessonId} billText={billText} />
    </div>
  );
}

export default LessonPersonalImpactPage;
