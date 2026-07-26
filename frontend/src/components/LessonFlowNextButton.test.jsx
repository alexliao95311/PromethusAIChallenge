import React from 'react';
import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

import LessonFlowNextButton from './LessonFlowNextButton';

function renderButton(currentStepKey) {
  return render(
    <MemoryRouter>
      <LessonFlowNextButton lessonId="lesson-1" currentStepKey={currentStepKey} />
    </MemoryRouter>
  );
}

describe('LessonFlowNextButton', () => {
  it('links to the next step in the fixed workflow order', () => {
    renderButton('vocabulary');
    const link = screen.getByTestId('lesson-flow-next-button');
    expect(link).toHaveTextContent('Continue to Quiz');
    expect(link).toHaveAttribute('href', '/lesson/lesson-1/quiz');
  });

  it('links from debate to reflection', () => {
    renderButton('debate-persona');
    expect(screen.getByTestId('lesson-flow-next-button')).toHaveAttribute(
      'href', '/lesson/lesson-1/reflection'
    );
  });

  it('renders nothing after the final step', () => {
    renderButton('mastery-dashboard');
    expect(screen.queryByTestId('lesson-flow-next-button')).not.toBeInTheDocument();
  });
});
