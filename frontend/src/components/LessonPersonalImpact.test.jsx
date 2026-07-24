import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';

import LessonPersonalImpact from './LessonPersonalImpact';
import { getPersonalImpact } from '../api';

vi.mock('../api', () => ({
  getPersonalImpact: vi.fn(),
}));

const RESULT = {
  impact_id: 'imp-1',
  lesson_id: 'lesson-1',
  bill_id: 'hr1',
  persona: { attributes: { occupation: 'Nurse', state: 'CA' }, is_fictional: true },
  narrative: 'This bill could affect you in a few grounded ways.',
  direct_impacts: [
    { impact: 'You may qualify for benefits.', reasoning: 'Eligibility is income-based.',
      section_ids: ['section-3'], confidence: 'high' },
  ],
  possible_indirect_impacts: [
    { impact: 'Your local clinic may change services.', reasoning: 'Depends on clinic behavior.',
      section_ids: ['section-4'], confidence: 'medium' },
  ],
  uncertainties: ['Your exact eligibility depends on details not provided.'],
  questions_to_consider: ['Do you rely on a local clinic?'],
  confidence: 'medium',
};

beforeEach(() => {
  vi.clearAllMocks();
});

describe('LessonPersonalImpact', () => {
  it('shows a generate prompt before any result', () => {
    render(<LessonPersonalImpact lessonId="lesson-1" />);
    expect(screen.getByTestId('personal-impact-generate')).toBeInTheDocument();
    expect(screen.queryByTestId('personal-impact-result')).not.toBeInTheDocument();
  });

  it('generates and shows the narrative with overall confidence', async () => {
    getPersonalImpact.mockResolvedValue(RESULT);
    render(<LessonPersonalImpact lessonId="lesson-1" persona={{ occupation: 'Nurse' }} />);

    fireEvent.click(screen.getByTestId('personal-impact-generate'));

    await waitFor(() =>
      expect(getPersonalImpact).toHaveBeenCalledWith('lesson-1', {
        billText: undefined,
        persona: { occupation: 'Nurse' },
      })
    );
    expect(await screen.findByTestId('personal-impact-narrative')).toHaveTextContent(RESULT.narrative);
  });

  it('separates direct, indirect, uncertainty, and questions sections', async () => {
    getPersonalImpact.mockResolvedValue(RESULT);
    render(<LessonPersonalImpact lessonId="lesson-1" />);
    fireEvent.click(screen.getByTestId('personal-impact-generate'));

    await screen.findByTestId('personal-impact-result');
    expect(screen.getByTestId('personal-impact-direct')).toHaveTextContent('You may qualify for benefits.');
    expect(screen.getByTestId('personal-impact-indirect')).toHaveTextContent('Your local clinic may change services.');
    expect(screen.getByTestId('personal-impact-uncertainties')).toHaveTextContent('exact eligibility');
    expect(screen.getByTestId('personal-impact-questions')).toHaveTextContent('local clinic');
  });

  it('shows the source section and confidence on each impact', async () => {
    getPersonalImpact.mockResolvedValue(RESULT);
    render(<LessonPersonalImpact lessonId="lesson-1" />);
    fireEvent.click(screen.getByTestId('personal-impact-generate'));

    await screen.findByTestId('personal-impact-result');
    expect(screen.getByTestId('personal-impact-direct')).toHaveTextContent('section-3');
    // Multiple confidence badges render (per-impact + overall).
    expect(screen.getAllByTestId('impact-confidence').length).toBeGreaterThanOrEqual(3);
  });

  it('shows a grounded empty state when there are no direct impacts', async () => {
    getPersonalImpact.mockResolvedValue({ ...RESULT, direct_impacts: [], confidence: 'low' });
    render(<LessonPersonalImpact lessonId="lesson-1" />);
    fireEvent.click(screen.getByTestId('personal-impact-generate'));

    await screen.findByTestId('personal-impact-result');
    expect(screen.getByTestId('personal-impact-direct')).toHaveTextContent(
      /doesn't clearly establish a direct effect/i
    );
  });

  it('shows an error when generation fails', async () => {
    getPersonalImpact.mockRejectedValue(new Error('network error'));
    render(<LessonPersonalImpact lessonId="lesson-1" />);
    fireEvent.click(screen.getByTestId('personal-impact-generate'));

    expect(await screen.findByText('network error')).toBeInTheDocument();
    expect(screen.queryByTestId('personal-impact-result')).not.toBeInTheDocument();
  });

  it('passes billText through when provided', async () => {
    getPersonalImpact.mockResolvedValue(RESULT);
    render(<LessonPersonalImpact lessonId="lesson-1" billText="SECTION 1..." />);
    fireEvent.click(screen.getByTestId('personal-impact-generate'));

    await waitFor(() =>
      expect(getPersonalImpact).toHaveBeenCalledWith('lesson-1', {
        billText: 'SECTION 1...',
        persona: undefined,
      })
    );
  });
});
