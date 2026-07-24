import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';

import LessonOpenResponse from './LessonOpenResponse';
import { getOpenResponseQuestion, submitOpenResponseAnswer } from '../api';

vi.mock('../api', () => ({
  getOpenResponseQuestion: vi.fn(),
  submitOpenResponseAnswer: vi.fn(),
}));

const QUESTION = {
  question_id: 'q1-open-response',
  question: 'Why might a small-business owner oppose this bill?',
  question_type: 'stakeholder_perspective',
  section_ids: ['section-8'],
};

beforeEach(() => {
  vi.clearAllMocks();
});

describe('LessonOpenResponse', () => {
  it('renders the question and an empty textarea', async () => {
    getOpenResponseQuestion.mockResolvedValue(QUESTION);
    render(<LessonOpenResponse lessonId="lesson-1" />);

    expect(await screen.findByTestId('open-response-question')).toHaveTextContent(QUESTION.question);
    expect(screen.getByTestId('open-response-textarea')).toHaveValue('');
  });

  it('submits the typed answer and shows the score and feedback', async () => {
    getOpenResponseQuestion.mockResolvedValue(QUESTION);
    submitOpenResponseAnswer.mockResolvedValue({
      attempt_id: 'attempt-1',
      score: 2,
      feedback: 'You identified the compliance cost but did not explain how it could affect hiring.',
      missed_points: ['Possible effect on hiring'],
      accurate_points: ['Administrative burden'],
      section_ids: ['section-8'],
    });

    render(<LessonOpenResponse lessonId="lesson-1" />);
    await screen.findByTestId('open-response-question');

    fireEvent.change(screen.getByTestId('open-response-textarea'), {
      target: { value: 'It costs them money to comply with the new quarterly reports.' },
    });
    fireEvent.click(screen.getByTestId('open-response-submit'));

    await waitFor(() => {
      expect(submitOpenResponseAnswer).toHaveBeenCalledWith(
        'lesson-1',
        'It costs them money to comply with the new quarterly reports.'
      );
    });

    expect(await screen.findByTestId('open-response-feedback')).toBeInTheDocument();
    expect(screen.getByText(/Score: 2 \/ 3/)).toBeInTheDocument();
    expect(screen.getByTestId('open-response-feedback-text')).toHaveTextContent(
      'You identified the compliance cost but did not explain how it could affect hiring.'
    );
  });

  it('shows both accurate and missed points after submission', async () => {
    getOpenResponseQuestion.mockResolvedValue(QUESTION);
    submitOpenResponseAnswer.mockResolvedValue({
      attempt_id: 'attempt-1',
      score: 2,
      feedback: 'Good but incomplete.',
      missed_points: ['Possible effect on hiring'],
      accurate_points: ['Administrative burden'],
      section_ids: ['section-8'],
    });

    render(<LessonOpenResponse lessonId="lesson-1" />);
    await screen.findByTestId('open-response-question');
    fireEvent.change(screen.getByTestId('open-response-textarea'), { target: { value: 'some answer here' } });
    fireEvent.click(screen.getByTestId('open-response-submit'));

    await screen.findByTestId('open-response-feedback');
    expect(screen.getByText('Administrative burden')).toBeInTheDocument();
    expect(screen.getByText('Possible effect on hiring')).toBeInTheDocument();
  });

  it('allows trying again after submission', async () => {
    getOpenResponseQuestion.mockResolvedValue(QUESTION);
    submitOpenResponseAnswer.mockResolvedValue({
      attempt_id: 'attempt-1',
      score: 0,
      feedback: 'Your answer is too short.',
      missed_points: [],
      accurate_points: [],
      section_ids: [],
    });

    render(<LessonOpenResponse lessonId="lesson-1" />);
    await screen.findByTestId('open-response-question');
    fireEvent.change(screen.getByTestId('open-response-textarea'), { target: { value: 'idk' } });
    fireEvent.click(screen.getByTestId('open-response-submit'));

    await screen.findByTestId('open-response-feedback');
    fireEvent.click(screen.getByTestId('open-response-try-again'));

    expect(screen.queryByTestId('open-response-feedback')).not.toBeInTheDocument();
    expect(screen.getByTestId('open-response-textarea')).toHaveValue('');
  });

  it('shows an error message when loading fails', async () => {
    getOpenResponseQuestion.mockRejectedValue(new Error('network error'));
    render(<LessonOpenResponse lessonId="lesson-1" />);

    expect(await screen.findByText('network error')).toBeInTheDocument();
  });

  it('shows a message when no question is available', async () => {
    getOpenResponseQuestion.mockResolvedValue(null);
    render(<LessonOpenResponse lessonId="lesson-1" />);

    expect(await screen.findByText('No open-response question is available for this lesson yet.')).toBeInTheDocument();
  });
});
