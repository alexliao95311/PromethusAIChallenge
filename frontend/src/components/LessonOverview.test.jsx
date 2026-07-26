import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';

import LessonOverview from './LessonOverview';
import { getLesson } from '../api';

vi.mock('../api', () => ({
  getLesson: vi.fn(),
}));

const LESSON = {
  lesson_id: 'lesson-abc',
  lesson_title: 'Understanding the Test Act',
  plain_language_summary: 'A summary of the test act.',
  learning_objectives: ['Explain the purpose of the bill.'],
  major_provisions: [{ claim: 'Provision one.', section_ids: ['section-3'] }],
  stakeholders: [{ claim: 'Affects students.', section_ids: ['section-4'] }],
  pro_arguments: [{ claim: 'Funding is guaranteed.', section_ids: ['section-6'] }],
  con_arguments: [{ claim: 'Costs may rise.', section_ids: ['section-7'] }],
};

beforeEach(() => {
  vi.clearAllMocks();
});

function renderOverview() {
  return render(
    <MemoryRouter initialEntries={['/lesson/lesson-abc']}>
      <Routes>
        <Route path="/lesson/:lessonId" element={<LessonOverview />} />
      </Routes>
    </MemoryRouter>
  );
}

describe('LessonOverview', () => {
  it('fetches and renders the lesson content', async () => {
    getLesson.mockResolvedValue(LESSON);
    renderOverview();

    expect(await screen.findByTestId('lesson-overview-title')).toHaveTextContent('Understanding the Test Act');
    expect(screen.getByTestId('lesson-overview-summary')).toHaveTextContent('A summary of the test act.');
    expect(getLesson).toHaveBeenCalledWith('lesson-abc');
  });

  it('renders grounded claims with their section ids', async () => {
    getLesson.mockResolvedValue(LESSON);
    renderOverview();

    await screen.findByTestId('lesson-overview-title');
    expect(screen.getByTestId('lesson-overview-provisions')).toHaveTextContent('Provision one.');
    expect(screen.getByTestId('lesson-overview-provisions')).toHaveTextContent('section-3');
    expect(screen.getByTestId('lesson-overview-pro')).toHaveTextContent('Funding is guaranteed.');
    expect(screen.getByTestId('lesson-overview-con')).toHaveTextContent('Costs may rise.');
  });

  it('renders the lesson-mode nav with links scoped to this lesson', async () => {
    getLesson.mockResolvedValue(LESSON);
    renderOverview();

    await screen.findByTestId('lesson-overview-title');
    expect(screen.getByTestId('lesson-nav-vocabulary')).toHaveAttribute('href', '/lesson/lesson-abc/vocabulary');
    expect(screen.getByTestId('lesson-nav-quiz')).toHaveAttribute('href', '/lesson/lesson-abc/quiz');
    expect(screen.getByTestId('lesson-nav-debate-persona')).toHaveAttribute('href', '/lesson/lesson-abc/debate-persona');
  });

  it('shows an error message when the lesson cannot be loaded', async () => {
    getLesson.mockRejectedValue(new Error('not found'));
    renderOverview();

    expect(await screen.findByText('not found')).toBeInTheDocument();
  });
});
