import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';

import LessonFlashcards from './LessonFlashcards';
import { getReviewState, submitReviewAnswer, startReviewSession } from '../api';

vi.mock('../api', () => ({
  getReviewState: vi.fn(),
  submitReviewAnswer: vi.fn(),
  startReviewSession: vi.fn(),
}));

const CARD_A = {
  card_id: 'card-a',
  term: 'eligible household',
  simple_definition: 'A household at or below the income threshold.',
  bill_context: 'Defines who can receive benefits.',
  example: 'A family of four earning below the limit qualifies.',
  section_id: 'section-2',
  difficulty: 'beginner',
  leitner_box: 1,
  is_new: true,
  is_due: true,
};

const CARD_B = {
  ...CARD_A,
  card_id: 'card-b',
  term: 'appropriation',
};

function makeState(dueCards, overrides = {}) {
  return {
    session: 1,
    due_cards: dueCards,
    total_cards: 2,
    due_count: dueCards.length,
    box_distribution: { '1': 2, '2': 0, '3': 0 },
    mastery_percent: 0,
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe('LessonFlashcards', () => {
  it('shows the term first, without revealing the definition', async () => {
    getReviewState.mockResolvedValue(makeState([CARD_A]));
    render(<LessonFlashcards lessonId="lesson-1" />);

    expect(await screen.findByTestId('flashcard-term')).toHaveTextContent('eligible household');
    expect(screen.queryByTestId('flashcard-answer')).not.toBeInTheDocument();
    expect(screen.getByTestId('reveal-answer')).toBeInTheDocument();
  });

  it('reveals the definition, context, and example on click', async () => {
    getReviewState.mockResolvedValue(makeState([CARD_A]));
    render(<LessonFlashcards lessonId="lesson-1" />);

    await screen.findByTestId('flashcard-term');
    fireEvent.click(screen.getByTestId('reveal-answer'));

    expect(screen.getByTestId('flashcard-answer')).toBeInTheDocument();
    expect(screen.getByText(CARD_A.simple_definition)).toBeInTheDocument();
    expect(screen.getByText(/Defines who can receive benefits/)).toBeInTheDocument();
    expect(screen.getByText(/family of four/)).toBeInTheDocument();
  });

  it('submits a correct answer and advances to the next due card', async () => {
    getReviewState.mockResolvedValue(makeState([CARD_A, CARD_B]));
    submitReviewAnswer.mockResolvedValue({ card_id: 'card-a', leitner_box: 2 });
    render(<LessonFlashcards lessonId="lesson-1" />);

    await screen.findByTestId('flashcard-term');
    fireEvent.click(screen.getByTestId('reveal-answer'));
    fireEvent.click(screen.getByTestId('mark-correct'));

    await waitFor(() => {
      expect(submitReviewAnswer).toHaveBeenCalledWith('lesson-1', 'card-a', true);
    });
    expect(await screen.findByTestId('flashcard-term')).toHaveTextContent('appropriation');
    expect(screen.getByTestId('flashcard-progress')).toHaveTextContent('Card 2 of 2');
  });

  it('submits an incorrect answer', async () => {
    getReviewState.mockResolvedValue(makeState([CARD_A]));
    submitReviewAnswer.mockResolvedValue({ card_id: 'card-a', leitner_box: 1 });
    render(<LessonFlashcards lessonId="lesson-1" />);

    await screen.findByTestId('flashcard-term');
    fireEvent.click(screen.getByTestId('reveal-answer'));
    fireEvent.click(screen.getByTestId('mark-incorrect'));

    await waitFor(() => {
      expect(submitReviewAnswer).toHaveBeenCalledWith('lesson-1', 'card-a', false);
    });
  });

  it('updates the due count and mastery bar immediately after answering', async () => {
    getReviewState.mockResolvedValue(makeState([CARD_A]));
    submitReviewAnswer.mockResolvedValue({ card_id: 'card-a', leitner_box: 2 });
    render(<LessonFlashcards lessonId="lesson-1" />);

    await screen.findByTestId('flashcard-term');
    expect(screen.getByTestId('due-count')).toHaveTextContent('1 due this session');

    fireEvent.click(screen.getByTestId('reveal-answer'));
    fireEvent.click(screen.getByTestId('mark-correct'));

    await waitFor(() => {
      expect(screen.getByTestId('session-complete')).toBeInTheDocument();
    });
  });

  it('shows a completion state once all due cards are answered', async () => {
    getReviewState.mockResolvedValue(makeState([CARD_A]));
    submitReviewAnswer.mockResolvedValue({ card_id: 'card-a', leitner_box: 2 });
    render(<LessonFlashcards lessonId="lesson-1" />);

    await screen.findByTestId('flashcard-term');
    fireEvent.click(screen.getByTestId('reveal-answer'));
    fireEvent.click(screen.getByTestId('mark-correct'));

    expect(await screen.findByTestId('session-complete')).toBeInTheDocument();
    expect(screen.getByTestId('start-next-session')).toBeInTheDocument();
  });

  it('starts a new session and reloads state when "Start Next Session" is clicked', async () => {
    getReviewState
      .mockResolvedValueOnce(makeState([]))
      .mockResolvedValueOnce(makeState([CARD_B], { session: 2 }));
    startReviewSession.mockResolvedValue(2);

    render(<LessonFlashcards lessonId="lesson-1" />);

    expect(await screen.findByTestId('session-complete')).toBeInTheDocument();
    fireEvent.click(screen.getByTestId('start-next-session'));

    await waitFor(() => {
      expect(startReviewSession).toHaveBeenCalledWith('lesson-1');
    });
    expect(await screen.findByTestId('flashcard-term')).toHaveTextContent('appropriation');
  });

  it('shows a "Needs review" label for a Box 1 card', async () => {
    getReviewState.mockResolvedValue(makeState([{ ...CARD_A, leitner_box: 1 }]));
    render(<LessonFlashcards lessonId="lesson-1" />);

    await screen.findByTestId('flashcard-term');
    expect(screen.getByText('Needs review')).toBeInTheDocument();
  });

  it('renders an error message when loading fails', async () => {
    getReviewState.mockRejectedValue(new Error('network error'));
    render(<LessonFlashcards lessonId="lesson-1" />);

    expect(await screen.findByText('network error')).toBeInTheDocument();
  });
});
