import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';

import LessonHub from './LessonHub';
import { generateLesson } from '../api';

vi.mock('../api', () => ({
  generateLesson: vi.fn(),
}));

beforeEach(() => {
  vi.clearAllMocks();
  sessionStorage.clear();
});

function renderHub(initialState) {
  return render(
    <MemoryRouter initialEntries={[{ pathname: '/lesson', state: initialState }]}>
      <Routes>
        <Route path="/lesson" element={<LessonHub />} />
        <Route path="/lesson/:lessonId" element={<div>Overview page</div>} />
      </Routes>
    </MemoryRouter>
  );
}

describe('LessonHub', () => {
  it('renders empty bill title/text fields by default', () => {
    renderHub();
    expect(screen.getByTestId('lesson-hub-title-input')).toHaveValue('');
    expect(screen.getByTestId('lesson-hub-text-input')).toHaveValue('');
    expect(screen.getByTestId('lesson-hub-generate')).toBeDisabled();
  });

  it('prefills from router state (e.g. passed from Legislation.jsx)', () => {
    renderHub({ billTitle: 'Test Bill', billText: 'Some bill text' });
    expect(screen.getByTestId('lesson-hub-title-input')).toHaveValue('Test Bill');
    expect(screen.getByTestId('lesson-hub-text-input')).toHaveValue('Some bill text');
    expect(screen.getByTestId('lesson-hub-generate')).not.toBeDisabled();
  });

  it('generates a lesson and navigates to the overview page', async () => {
    generateLesson.mockResolvedValue({ lesson_id: 'lesson-abc' });
    renderHub({ billTitle: 'Test Bill', billText: 'Some bill text' });

    fireEvent.click(screen.getByTestId('lesson-hub-generate'));

    await waitFor(() => {
      expect(generateLesson).toHaveBeenCalledWith(
        'test-bill',
        'Some bill text',
        expect.objectContaining({ includeVocabulary: true, includeQuiz: true, includeOpenResponse: true })
      );
    });

    expect(await screen.findByText('Overview page')).toBeInTheDocument();
  });

  it('shows an error message when generation fails', async () => {
    generateLesson.mockRejectedValue(new Error('generation failed'));
    renderHub({ billTitle: 'Test Bill', billText: 'Some bill text' });

    fireEvent.click(screen.getByTestId('lesson-hub-generate'));

    expect(await screen.findByText('generation failed')).toBeInTheDocument();
  });
});
