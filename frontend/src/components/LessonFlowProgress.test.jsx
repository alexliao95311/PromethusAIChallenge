import React from 'react';
import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

import LessonFlowProgress from './LessonFlowProgress';
import { markFlowStepComplete } from '../utils/lessonFlow';

beforeEach(() => {
  localStorage.clear();
});

function renderProgress(props) {
  return render(
    <MemoryRouter>
      <LessonFlowProgress lessonId="lesson-1" {...props} />
    </MemoryRouter>
  );
}

describe('LessonFlowProgress', () => {
  it('renders every step in the workflow', () => {
    renderProgress({ currentStepKey: 'quiz' });
    expect(screen.getByTestId('lesson-flow-step-persona')).toBeInTheDocument();
    expect(screen.getByTestId('lesson-flow-step-lesson')).toBeInTheDocument();
    expect(screen.getByTestId('lesson-flow-step-quiz')).toBeInTheDocument();
    expect(screen.getByTestId('lesson-flow-step-reflection')).toBeInTheDocument();
    expect(screen.getByTestId('lesson-flow-step-mastery-dashboard')).toBeInTheDocument();
  });

  it('highlights the current step', () => {
    renderProgress({ currentStepKey: 'quiz' });
    expect(screen.getByTestId('lesson-flow-step-quiz').className).toContain('lesson-flow-step-current');
  });

  it('marks a step complete from the local flow flag', () => {
    markFlowStepComplete('lesson-1', 'vocabulary');
    renderProgress({ currentStepKey: 'quiz' });
    expect(screen.getByTestId('lesson-flow-step-vocabulary').className).toContain('lesson-flow-step-complete');
    expect(screen.getByTestId('lesson-flow-step-quiz').className).not.toContain('lesson-flow-step-complete');
  });

  it('lets a page override completion with authoritative backend data', () => {
    // No local flag set for "quiz", but the caller knows from the backend
    // (mastery dashboard) that the student already has a quiz attempt.
    renderProgress({ currentStepKey: 'open-response', completedOverride: { quiz: true } });
    expect(screen.getByTestId('lesson-flow-step-quiz').className).toContain('lesson-flow-step-complete');
  });

  it('links each step to its correct lesson-scoped or global path', () => {
    renderProgress({ currentStepKey: 'lesson' });
    expect(screen.getByTestId('lesson-flow-step-quiz')).toHaveAttribute('href', '/lesson/lesson-1/quiz');
    expect(screen.getByTestId('lesson-flow-step-persona')).toHaveAttribute('href', '/lesson/persona');
    expect(screen.getByTestId('lesson-flow-step-mastery-dashboard')).toHaveAttribute('href', '/lesson/mastery-dashboard');
  });
});
