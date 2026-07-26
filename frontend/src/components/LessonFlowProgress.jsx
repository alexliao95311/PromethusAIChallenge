import React from 'react';
import { Link } from 'react-router-dom';
import { Check } from 'lucide-react';
import { FLOW_STEPS, isFlowStepComplete } from '../utils/lessonFlow';
import './LessonFlowProgress.css';

// End-to-end Lesson Mode progress stepper (Increment 12): shows every step
// of the connected workflow (persona -> personal impact -> lesson ->
// vocabulary -> quiz -> open response -> debate -> reflection -> mastery
// dashboard) with a checkmark for steps this browser has already completed.
// `completedOverride` lets a page pass in authoritative backend-derived
// completion (e.g. LessonOverview knows quiz/open-response attempts from
// the mastery dashboard) for steps where the local flag alone would be
// incomplete/stale; steps without an override fall back to the local flag.
function LessonFlowProgress({ lessonId, currentStepKey, completedOverride = {} }) {
  return (
    <nav className="lesson-flow-progress" aria-label="Lesson Mode workflow progress" data-testid="lesson-flow-progress">
      {FLOW_STEPS.map((step, idx) => {
        const isCurrent = step.key === currentStepKey;
        const isComplete = completedOverride[step.key] ?? isFlowStepComplete(lessonId, step.key);
        return (
          <React.Fragment key={step.key}>
            <Link
              to={step.path(lessonId)}
              className={[
                'lesson-flow-step',
                isCurrent ? 'lesson-flow-step-current' : '',
                isComplete ? 'lesson-flow-step-complete' : '',
              ].join(' ').trim()}
              data-testid={`lesson-flow-step-${step.key}`}
            >
              <span className="lesson-flow-step-marker">
                {isComplete ? <Check size={12} /> : idx + 1}
              </span>
              <span className="lesson-flow-step-label">
                {step.label}
                {step.optional && <span className="lesson-flow-step-optional"> (optional)</span>}
              </span>
            </Link>
            {idx < FLOW_STEPS.length - 1 && <span className="lesson-flow-connector" />}
          </React.Fragment>
        );
      })}
    </nav>
  );
}

export default LessonFlowProgress;
