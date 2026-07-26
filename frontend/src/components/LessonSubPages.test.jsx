import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';

import LessonVocabularyPage from './LessonVocabularyPage';
import LessonQuizPage from './LessonQuizPage';
import LessonOpenResponsePage from './LessonOpenResponsePage';
import LessonPersonalImpactPage from './LessonPersonalImpactPage';
import { getReviewState, getQuizQuestions, getOpenResponseQuestion } from '../api';

// Each wrapper page just adds a back-link + LessonModeNav around an
// already-tested component; these tests confirm the wiring (lessonId
// threaded through, nav rendered) rather than re-testing the components.
vi.mock('../api', () => ({
  getReviewState: vi.fn(() => new Promise(() => {})),
  startReviewSession: vi.fn(),
  submitReviewAnswer: vi.fn(),
  getQuizQuestions: vi.fn(() => new Promise(() => {})),
  submitQuizAnswers: vi.fn(),
  getOpenResponseQuestion: vi.fn(() => new Promise(() => {})),
  submitOpenResponseAnswer: vi.fn(),
  getPersonalImpact: vi.fn(),
}));

beforeEach(() => {
  vi.clearAllMocks();
});

function renderAt(path, element, routePath) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path={routePath} element={element} />
      </Routes>
    </MemoryRouter>
  );
}

describe('Lesson Mode sub-pages', () => {
  it('LessonVocabularyPage threads lessonId to LessonFlashcards and renders the nav', () => {
    renderAt('/lesson/lesson-1/vocabulary', <LessonVocabularyPage />, '/lesson/:lessonId/vocabulary');
    expect(getReviewState).toHaveBeenCalledWith('lesson-1');
    expect(screen.getByTestId('lesson-nav-vocabulary')).toBeInTheDocument();
  });

  it('LessonQuizPage threads lessonId to LessonQuiz and renders the nav', () => {
    renderAt('/lesson/lesson-1/quiz', <LessonQuizPage />, '/lesson/:lessonId/quiz');
    expect(getQuizQuestions).toHaveBeenCalledWith('lesson-1');
    expect(screen.getByTestId('lesson-nav-quiz')).toBeInTheDocument();
  });

  it('LessonOpenResponsePage threads lessonId to LessonOpenResponse and renders the nav', () => {
    renderAt('/lesson/lesson-1/open-response', <LessonOpenResponsePage />, '/lesson/:lessonId/open-response');
    expect(getOpenResponseQuestion).toHaveBeenCalledWith('lesson-1');
    expect(screen.getByTestId('lesson-nav-open-response')).toBeInTheDocument();
  });

  it('LessonPersonalImpactPage threads lessonId to LessonPersonalImpact and renders the nav', () => {
    renderAt('/lesson/lesson-1/personal-impact', <LessonPersonalImpactPage />, '/lesson/:lessonId/personal-impact');
    expect(screen.getByTestId('lesson-nav-personal-impact')).toBeInTheDocument();
    expect(screen.getByTestId('personal-impact-generate')).toBeInTheDocument();
  });
});
