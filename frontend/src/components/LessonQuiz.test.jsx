import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';

import LessonQuiz from './LessonQuiz';
import { getQuizQuestions, submitQuizAnswers } from '../api';

vi.mock('../api', () => ({
  getQuizQuestions: vi.fn(),
  submitQuizAnswers: vi.fn(),
}));

const QUESTION_1 = {
  question_id: 'q1',
  question: "What does 'eligible household' mean in this bill?",
  answer_choices: ['A household below the income threshold.', 'A wrong answer A.', 'A wrong answer B.', 'A wrong answer C.'],
  section_ids: ['section-2'],
  difficulty: 'beginner',
  question_type: 'vocabulary',
};

const QUESTION_2 = {
  question_id: 'q2',
  question: 'Who is authorized to issue regulations under this bill?',
  answer_choices: ['The Secretary.', 'The Governor.', 'The mayor.', 'The court.'],
  section_ids: ['section-5'],
  difficulty: 'intermediate',
  question_type: 'implementation',
};

beforeEach(() => {
  vi.clearAllMocks();
});

describe('LessonQuiz', () => {
  it('renders all questions with their answer choices', async () => {
    getQuizQuestions.mockResolvedValue([QUESTION_1, QUESTION_2]);
    render(<LessonQuiz lessonId="lesson-1" />);

    expect(await screen.findByText(QUESTION_1.question)).toBeInTheDocument();
    expect(screen.getByText(QUESTION_2.question)).toBeInTheDocument();
    expect(screen.getByTestId('quiz-choice-q1-0')).toBeInTheDocument();
    expect(screen.getByTestId('quiz-choice-q2-3')).toBeInTheDocument();
  });

  it('disables submit until every question has an answer selected', async () => {
    getQuizQuestions.mockResolvedValue([QUESTION_1, QUESTION_2]);
    render(<LessonQuiz lessonId="lesson-1" />);

    await screen.findByText(QUESTION_1.question);
    expect(screen.getByTestId('submit-quiz')).toBeDisabled();

    fireEvent.click(screen.getByTestId('quiz-choice-q1-0'));
    expect(screen.getByTestId('submit-quiz')).toBeDisabled();

    fireEvent.click(screen.getByTestId('quiz-choice-q2-0'));
    expect(screen.getByTestId('submit-quiz')).not.toBeDisabled();
  });

  it('submits selected answers and shows the score', async () => {
    getQuizQuestions.mockResolvedValue([QUESTION_1, QUESTION_2]);
    submitQuizAnswers.mockResolvedValue({
      attempt_id: 'attempt-1',
      score: 100.0,
      results: [
        { question_id: 'q1', selected_index: 0, correct: true, correct_answer_index: 0, explanation: 'Correct because of section-2.' },
        { question_id: 'q2', selected_index: 0, correct: true, correct_answer_index: 0, explanation: 'Correct because of section-5.' },
      ],
    });

    render(<LessonQuiz lessonId="lesson-1" />);
    await screen.findByText(QUESTION_1.question);

    fireEvent.click(screen.getByTestId('quiz-choice-q1-0'));
    fireEvent.click(screen.getByTestId('quiz-choice-q2-0'));
    fireEvent.click(screen.getByTestId('submit-quiz'));

    await waitFor(() => {
      expect(submitQuizAnswers).toHaveBeenCalledWith('lesson-1', [
        { question_id: 'q1', selected_index: 0 },
        { question_id: 'q2', selected_index: 0 },
      ]);
    });

    expect(await screen.findByTestId('quiz-score')).toHaveTextContent('Score: 100');
  });

  it('shows immediate explanations for each question after submission', async () => {
    getQuizQuestions.mockResolvedValue([QUESTION_1]);
    submitQuizAnswers.mockResolvedValue({
      attempt_id: 'attempt-1',
      score: 0.0,
      results: [
        { question_id: 'q1', selected_index: 1, correct: false, correct_answer_index: 0, explanation: 'The correct answer relates to section-2.' },
      ],
    });

    render(<LessonQuiz lessonId="lesson-1" />);
    await screen.findByText(QUESTION_1.question);

    fireEvent.click(screen.getByTestId('quiz-choice-q1-1'));
    fireEvent.click(screen.getByTestId('submit-quiz'));

    expect(await screen.findByTestId('quiz-explanation-q1')).toHaveTextContent(
      'The correct answer relates to section-2.'
    );
  });

  it('locks answer selection after submission', async () => {
    getQuizQuestions.mockResolvedValue([QUESTION_1]);
    submitQuizAnswers.mockResolvedValue({
      attempt_id: 'attempt-1',
      score: 100.0,
      results: [
        { question_id: 'q1', selected_index: 0, correct: true, correct_answer_index: 0, explanation: 'Correct.' },
      ],
    });

    render(<LessonQuiz lessonId="lesson-1" />);
    await screen.findByText(QUESTION_1.question);

    fireEvent.click(screen.getByTestId('quiz-choice-q1-0'));
    fireEvent.click(screen.getByTestId('submit-quiz'));

    await screen.findByTestId('quiz-score');
    expect(screen.getByTestId('quiz-choice-q1-0')).toBeDisabled();
  });

  it('shows an error message when loading fails', async () => {
    getQuizQuestions.mockRejectedValue(new Error('network error'));
    render(<LessonQuiz lessonId="lesson-1" />);

    expect(await screen.findByText('network error')).toBeInTheDocument();
  });

  it('shows a message when no quiz is available', async () => {
    getQuizQuestions.mockResolvedValue([]);
    render(<LessonQuiz lessonId="lesson-1" />);

    expect(await screen.findByText('No quiz is available for this lesson yet.')).toBeInTheDocument();
  });
});
