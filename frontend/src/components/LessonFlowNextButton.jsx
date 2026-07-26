import React from 'react';
import { Link } from 'react-router-dom';
import { ArrowRight } from 'lucide-react';
import { getNextStep } from '../utils/lessonFlow';
import './LessonFlowNextButton.css';

// Chains one Lesson Mode step to the next (Increment 12) -- e.g. shown at
// the bottom of the vocabulary page, it links to the quiz; at the bottom of
// reflection, it links to the mastery dashboard. Renders nothing past the
// last step (there is no "next" after the dashboard).
function LessonFlowNextButton({ lessonId, currentStepKey }) {
  const next = getNextStep(currentStepKey, lessonId);
  if (!next) return null;

  return (
    <Link to={next.path} className="lesson-flow-next-btn" data-testid="lesson-flow-next-button">
      <span>Continue to {next.label}</span>
      <ArrowRight size={16} />
    </Link>
  );
}

export default LessonFlowNextButton;
