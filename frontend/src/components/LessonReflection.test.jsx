import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

import LessonReflection from './LessonReflection';
import { submitReflection } from '../api';

vi.mock('../api', () => ({
  submitReflection: vi.fn(),
}));

function renderComponent(initialState) {
  return render(
    <MemoryRouter initialEntries={[{ pathname: '/lesson/lesson-1/reflection', state: initialState }]}>
      <LessonReflection lessonId="lesson-1" />
    </MemoryRouter>
  );
}

const REFLECTION = {
  reflection_id: 'refl-1',
  lesson_id: 'lesson-1',
  view_changed: 'somewhat',
  explanation: 'The cost cap point was new to me.',
  strongest_student_argument: {
    feedback: 'Good point about guaranteed funding.',
    transcript_excerpt: 'The bill guarantees funding for rural clinics.',
  },
  weakest_reasoning_step: {
    feedback: 'Did not explain why the cap would not matter.',
    transcript_excerpt: null,
  },
  evidence_use_feedback: { feedback: 'No specific figures cited.', transcript_excerpt: null },
  missed_opponent_point: {
    feedback: 'Never addressed rising costs.',
    transcript_excerpt: 'The funding is capped and may not keep pace with rising costs.',
  },
  perspective_understanding: { feedback: 'Engaged with the opponent directly.', transcript_excerpt: null },
  recommended_skill: 'Address the opponent\'s strongest point directly',
  recommended_next_activity: 'Debate this bill again from the opposing side',
};

beforeEach(() => {
  vi.clearAllMocks();
});

function fillAndSubmit() {
  fireEvent.change(screen.getByTestId('reflection-transcript'), {
    target: { value: 'Pro: funding is good. Con: costs too much.' },
  });
  fireEvent.click(screen.getByTestId('reflection-view-changed-somewhat'));
  fireEvent.click(screen.getByTestId('reflection-submit'));
}

describe('LessonReflection', () => {
  it('disables submit until a transcript and a view-changed answer are given', () => {
    renderComponent();
    expect(screen.getByTestId('reflection-submit')).toBeDisabled();

    fireEvent.change(screen.getByTestId('reflection-transcript'), {
      target: { value: 'Some transcript text' },
    });
    expect(screen.getByTestId('reflection-submit')).toBeDisabled();

    fireEvent.click(screen.getByTestId('reflection-view-changed-yes'));
    expect(screen.getByTestId('reflection-submit')).not.toBeDisabled();
  });

  it('submits the transcript, self-reported view change, and optional explanation', async () => {
    submitReflection.mockResolvedValue(REFLECTION);
    renderComponent();

    fireEvent.change(screen.getByTestId('reflection-transcript'), {
      target: { value: 'Pro: funding is good. Con: costs too much.' },
    });
    fireEvent.click(screen.getByTestId('reflection-view-changed-somewhat'));
    fireEvent.change(screen.getByTestId('reflection-explanation'), {
      target: { value: 'The cost cap point was new to me.' },
    });
    fireEvent.click(screen.getByTestId('reflection-submit'));

    await waitFor(() => {
      expect(submitReflection).toHaveBeenCalledWith('lesson-1', {
        transcript: 'Pro: funding is good. Con: costs too much.',
        viewChanged: 'somewhat',
        explanation: 'The cost cap point was new to me.',
      });
    });
  });

  it('renders grounded feedback with transcript excerpts', async () => {
    submitReflection.mockResolvedValue(REFLECTION);
    renderComponent();
    fillAndSubmit();

    expect(await screen.findByTestId('reflection-result')).toBeInTheDocument();
    expect(screen.getByTestId('reflection-strongest-student-argument')).toHaveTextContent(
      'The bill guarantees funding for rural clinics.'
    );
    // A feedback item with no verified excerpt still shows its feedback text,
    // just without a quoted blockquote.
    expect(screen.getByTestId('reflection-evidence-use-feedback')).toHaveTextContent(
      'No specific figures cited.'
    );
  });

  it('shows the recommended skill and next activity', async () => {
    submitReflection.mockResolvedValue(REFLECTION);
    renderComponent();
    fillAndSubmit();

    expect(await screen.findByTestId('reflection-recommended-skill')).toHaveTextContent(
      "Address the opponent's strongest point directly"
    );
    expect(screen.getByTestId('reflection-recommended-activity')).toHaveTextContent(
      'Debate this bill again from the opposing side'
    );
  });

  it('never displays a winner/loser determination -- a separate rubric from judge_chain', async () => {
    submitReflection.mockResolvedValue(REFLECTION);
    renderComponent();
    fillAndSubmit();

    await screen.findByTestId('reflection-result');
    expect(screen.queryByText(/wins/i)).not.toBeInTheDocument();
  });

  it('lets the student reflect on another debate', async () => {
    submitReflection.mockResolvedValue(REFLECTION);
    renderComponent();
    fillAndSubmit();

    await screen.findByTestId('reflection-result');
    fireEvent.click(screen.getByTestId('reflection-reset'));
    expect(screen.getByTestId('reflection-submit')).toBeInTheDocument();
  });

  it('shows an error message when generation fails', async () => {
    submitReflection.mockRejectedValue(new Error('generation failed'));
    renderComponent();
    fillAndSubmit();

    expect(await screen.findByText('generation failed')).toBeInTheDocument();
  });

  it('prefills the transcript when arriving from a Lesson Mode debate (Debate.jsx handoff)', () => {
    renderComponent({ transcript: 'Pro: prefilled argument.\n\nCon: prefilled rebuttal.' });
    expect(screen.getByTestId('reflection-transcript')).toHaveValue(
      'Pro: prefilled argument.\n\nCon: prefilled rebuttal.'
    );
    // Only a view-changed answer is still needed once the transcript arrives prefilled.
    fireEvent.click(screen.getByTestId('reflection-view-changed-yes'));
    expect(screen.getByTestId('reflection-submit')).not.toBeDisabled();
  });

  it('leaves the transcript empty when arriving without router state (e.g. a direct refresh)', () => {
    renderComponent();
    expect(screen.getByTestId('reflection-transcript')).toHaveValue('');
  });
});
