import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';

import LessonPersona from './LessonPersona';
import { generateLesson, getPersona, getPersonaOptions, savePersona, deletePersona } from '../api';

vi.mock('../api', () => ({
  generateLesson: vi.fn(),
  getPersonaOptions: vi.fn(),
  getPersona: vi.fn(),
  savePersona: vi.fn(),
  deletePersona: vi.fn(),
}));

const OPTIONS = {
  occupation_suggestions: ['Student', 'Educator'],
  occupation_max_length: 80,
  states: [{ code: 'CA', name: 'California' }],
  age_ranges: ['18-24'],
  income_brackets: ['Under $25,000'],
  not_collected: ['exact age'],
};

beforeEach(() => {
  vi.clearAllMocks();
  sessionStorage.clear();
  getPersonaOptions.mockResolvedValue(OPTIONS);
  getPersona.mockResolvedValue({ has_persona: false });
});

function renderPersonaPage(initialState, { user } = { user: { uid: 'u1' } }) {
  return render(
    <MemoryRouter initialEntries={[{ pathname: '/lesson/persona', state: initialState }]}>
      <Routes>
        <Route path="/lesson/persona" element={<LessonPersona user={user} />} />
        <Route path="/lesson" element={<div>Lesson hub page</div>} />
        <Route path="/lesson/:lessonId/personal-impact" element={<div>Personal impact page</div>} />
      </Routes>
    </MemoryRouter>
  );
}

describe('LessonPersona', () => {
  it('links back to the Lesson Hub, not Home', async () => {
    renderPersonaPage();
    const backLink = await screen.findByText('Back to Lesson');
    expect(backLink.closest('a')).toHaveAttribute('href', '/lesson');
  });

  it('shows no bill-in-progress banner or skip button when accessed standalone', async () => {
    renderPersonaPage();
    await screen.findByTestId('persona-save');
    expect(screen.queryByTestId('lesson-persona-bill-context')).not.toBeInTheDocument();
    expect(screen.queryByTestId('persona-skip')).not.toBeInTheDocument();
  });

  it('saves a standalone persona in place without forcing navigation away', async () => {
    savePersona.mockResolvedValue({ occupation: 'Student' });
    renderPersonaPage();

    fireEvent.click(await screen.findByTestId('persona-save'));

    expect(await screen.findByTestId('persona-status')).toHaveTextContent('Persona saved.');
    expect(screen.queryByText('Lesson hub page')).not.toBeInTheDocument();
  });

  it('shows the bill-in-progress banner and a skip button when arriving mid-flow', async () => {
    renderPersonaPage({ billTitle: 'Test Bill', billText: 'Some bill text' });
    expect(await screen.findByTestId('lesson-persona-bill-context')).toHaveTextContent('Test Bill');
    expect(await screen.findByTestId('persona-skip')).toBeInTheDocument();
  });

  it('generates the lesson and advances to personal impact after saving a persona mid-flow', async () => {
    savePersona.mockResolvedValue({ occupation: 'Student' });
    generateLesson.mockResolvedValue({ lesson_id: 'lesson-abc' });
    renderPersonaPage({ billTitle: 'Test Bill', billText: 'Some bill text' });

    fireEvent.click(await screen.findByTestId('persona-save'));

    await waitFor(() => {
      expect(generateLesson).toHaveBeenCalledWith(
        'test-bill',
        'Some bill text',
        expect.objectContaining({ includeVocabulary: true, includeQuiz: true, includeOpenResponse: true })
      );
    });
    expect(await screen.findByText('Personal impact page')).toBeInTheDocument();
  });

  it('generates the lesson and advances to personal impact when skipping the persona', async () => {
    generateLesson.mockResolvedValue({ lesson_id: 'lesson-xyz' });
    renderPersonaPage({ billTitle: 'Test Bill', billText: 'Some bill text' });

    fireEvent.click(await screen.findByTestId('persona-skip'));

    expect(await screen.findByText('Personal impact page')).toBeInTheDocument();
  });

  it('shows an error and stays on the page when lesson generation fails', async () => {
    generateLesson.mockRejectedValue(new Error('generation failed'));
    renderPersonaPage({ billTitle: 'Test Bill', billText: 'Some bill text' });

    fireEvent.click(await screen.findByTestId('persona-skip'));

    expect(await screen.findByText('generation failed')).toBeInTheDocument();
  });
});
