import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

import MasteryDashboard from './MasteryDashboard';
import { getMasteryDashboard } from '../api';

vi.mock('../api', () => ({
  getMasteryDashboard: vi.fn(),
}));

const EMPTY_DASHBOARD = {
  has_activity: false,
  total_lessons_started: 0,
  completed_lesson_count: 0,
  overall_vocabulary_mastery_percent: 0,
  overall_cards_due: 0,
  lessons: [],
  recent_quiz_scores: [],
  recent_open_response_scores: [],
  debate_skill: null,
  recommended_activity: {
    label: 'Generate your first lesson',
    reason: "You haven't started a Lesson Mode activity yet.",
    activity_type: 'generate_lesson',
    lesson_id: null,
  },
};

const POPULATED_DASHBOARD = {
  has_activity: true,
  total_lessons_started: 2,
  completed_lesson_count: 1,
  overall_vocabulary_mastery_percent: 62.5,
  overall_cards_due: 3,
  lessons: [
    {
      lesson_id: 'lesson-1',
      lesson_title: 'Community Health Access Act',
      completed: true,
      has_quiz: true,
      has_open_response: true,
      vocabulary: {
        total_cards: 8,
        mastery_percent: 75.0,
        box_distribution: { '1': 1, '2': 1, '3': 6 },
        cards_due: 0,
      },
      quiz_attempts: 2,
      best_quiz_score: 95.0,
      latest_quiz_score: 90.0,
      open_response_attempts: 1,
      latest_open_response_score: 3,
    },
    {
      lesson_id: 'lesson-2',
      lesson_title: 'Rural Broadband Expansion Act',
      completed: false,
      has_quiz: true,
      has_open_response: false,
      vocabulary: {
        total_cards: 4,
        mastery_percent: 25.0,
        box_distribution: { '1': 2, '2': 1, '3': 1 },
        cards_due: 3,
      },
      quiz_attempts: 0,
      best_quiz_score: null,
      latest_quiz_score: null,
      open_response_attempts: 0,
      latest_open_response_score: null,
    },
  ],
  recent_quiz_scores: [
    { lesson_id: 'lesson-1', lesson_title: 'Community Health Access Act', score: 90.0, created_at: '2026-01-01T00:00:00' },
  ],
  recent_open_response_scores: [
    { lesson_id: 'lesson-1', lesson_title: 'Community Health Access Act', score: 3, created_at: '2026-01-01T00:00:00' },
  ],
  debate_skill: {
    reflections_count: 2,
    most_recent_recommended_skill: 'Address counterarguments directly',
    most_recent_recommended_activity: 'Debate this bill again',
    most_recent_view_changed: 'somewhat',
    recent_recommended_skills: ['Address counterarguments directly', 'Use more evidence'],
    is_estimate: true,
  },
  recommended_activity: {
    label: 'Review 3 due flashcard(s) in "Rural Broadband Expansion Act"',
    reason: 'Spaced-repetition cards are ready for review.',
    activity_type: 'review_flashcards',
    lesson_id: 'lesson-2',
  },
};

function renderDashboard() {
  return render(
    <MemoryRouter>
      <MasteryDashboard />
    </MemoryRouter>
  );
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe('MasteryDashboard', () => {
  it('shows a loading state before data arrives', () => {
    getMasteryDashboard.mockReturnValue(new Promise(() => {}));
    renderDashboard();
    expect(screen.getByTestId('mastery-dashboard-loading')).toBeInTheDocument();
  });

  it('shows an error message when the fetch fails', async () => {
    getMasteryDashboard.mockRejectedValue(new Error('network error'));
    renderDashboard();
    expect(await screen.findByTestId('mastery-dashboard-error')).toHaveTextContent('network error');
  });

  it('shows a helpful empty state for a new user with no division-by-zero errors', async () => {
    getMasteryDashboard.mockResolvedValue(EMPTY_DASHBOARD);
    renderDashboard();

    expect(await screen.findByTestId('mastery-empty-state')).toBeInTheDocument();
    expect(screen.getByTestId('mastery-recommendation-title')).toHaveTextContent('Generate your first lesson');
    expect(screen.queryByTestId('mastery-lesson-list')).not.toBeInTheDocument();
    expect(screen.queryByText('NaN%')).not.toBeInTheDocument();
    expect(screen.queryByText('undefined')).not.toBeInTheDocument();
  });

  it('shows the recommended next step prominently at the top', async () => {
    getMasteryDashboard.mockResolvedValue(POPULATED_DASHBOARD);
    renderDashboard();

    const recommendation = await screen.findByTestId('mastery-recommendation');
    expect(recommendation).toHaveTextContent('Review 3 due flashcard(s)');
  });

  it('shows overall and per-bill vocabulary mastery from Leitner boxes', async () => {
    getMasteryDashboard.mockResolvedValue(POPULATED_DASHBOARD);
    renderDashboard();

    await screen.findByTestId('mastery-dashboard');
    expect(screen.getByTestId('mastery-overall-vocab')).toHaveTextContent('62.5%');
    expect(screen.getByTestId('mastery-vocab-bar-lesson-1')).toHaveTextContent('75%');
    expect(screen.getByTestId('mastery-lesson-lesson-1')).toHaveTextContent('Learning: 1');
    expect(screen.getByTestId('mastery-lesson-lesson-1')).toHaveTextContent('Mastered: 6');
  });

  it('shows progress by bill and marks completed lessons', async () => {
    getMasteryDashboard.mockResolvedValue(POPULATED_DASHBOARD);
    renderDashboard();

    await screen.findByTestId('mastery-dashboard');
    expect(screen.getByTestId('mastery-lesson-lesson-1')).toHaveTextContent('Completed');
    expect(screen.getByTestId('mastery-lesson-lesson-2')).not.toHaveTextContent('Completed');
    expect(screen.getByTestId('mastery-completed-count')).toHaveTextContent('1 / 2');
  });

  it('labels debate skill feedback as an AI estimate, never a combined score', async () => {
    getMasteryDashboard.mockResolvedValue(POPULATED_DASHBOARD);
    renderDashboard();

    const debateSection = await screen.findByTestId('mastery-debate-skill');
    expect(debateSection).toHaveTextContent('AI estimate');
    expect(debateSection).toHaveTextContent('Address counterarguments directly');
    // No combined/overall intelligence score is ever rendered anywhere.
    expect(screen.queryByText(/intelligence/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/overall score/i)).not.toBeInTheDocument();
  });

  it('shows an empty debate-skill state when there are no reflections yet', async () => {
    getMasteryDashboard.mockResolvedValue({ ...POPULATED_DASHBOARD, debate_skill: null });
    renderDashboard();

    expect(await screen.findByTestId('mastery-debate-skill-empty')).toBeInTheDocument();
  });

  it('shows recent quiz and open-response scores', async () => {
    getMasteryDashboard.mockResolvedValue(POPULATED_DASHBOARD);
    renderDashboard();

    await screen.findByTestId('mastery-dashboard');
    expect(screen.getByTestId('mastery-recent-quiz')).toHaveTextContent('90');
    expect(screen.getByTestId('mastery-recent-open-response')).toHaveTextContent('3 / 3');
  });

  it('lets the student retry after a failed load', async () => {
    getMasteryDashboard.mockRejectedValueOnce(new Error('network error'));
    renderDashboard();
    await screen.findByTestId('mastery-dashboard-retry');

    getMasteryDashboard.mockResolvedValueOnce(EMPTY_DASHBOARD);
    fireEvent.click(screen.getByTestId('mastery-dashboard-retry'));

    expect(await screen.findByTestId('mastery-empty-state')).toBeInTheDocument();
    expect(getMasteryDashboard).toHaveBeenCalledTimes(2);
  });
});
