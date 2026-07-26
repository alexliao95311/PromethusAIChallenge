import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';

import LessonDebatePersona from './LessonDebatePersona';
import { generateDebatePersona, getPersonaOptions, getSocraticHint } from '../api';

vi.mock('../api', () => ({
  generateDebatePersona: vi.fn(),
  getPersonaOptions: vi.fn(),
  getSocraticHint: vi.fn(),
}));

const PERSONA = {
  persona_id: 'lesson-1-persona-skipped',
  role: 'School district budget director',
  location_context: 'overseeing a rural county health-services budget',
  interests: ['Predictable funding'],
  likely_concerns: ['Compliance reporting could strain limited staff time'],
  position: 'Cautiously supportive but concerned about implementation costs',
  section_ids: ['section-8'],
  reason_for_selection: 'A different lens on cost vs. benefit than a student focused on access.',
  persona_prompt: 'PERSONA INSTRUCTIONS:\nYou are role-playing as School district budget director...',
};

beforeEach(() => {
  vi.clearAllMocks();
  Object.assign(navigator, { clipboard: { writeText: vi.fn().mockResolvedValue() } });
});

describe('LessonDebatePersona', () => {
  it('generates and displays the opposing persona', async () => {
    generateDebatePersona.mockResolvedValue(PERSONA);
    render(<LessonDebatePersona lessonId="lesson-1" />);

    fireEvent.click(screen.getByTestId('debate-persona-generate'));

    expect(await screen.findByTestId('debate-persona-role')).toHaveTextContent(
      'School district budget director'
    );
    expect(generateDebatePersona).toHaveBeenCalledWith('lesson-1', { studentPersona: undefined });
  });

  it('shows the reason the stakeholder was selected', async () => {
    generateDebatePersona.mockResolvedValue(PERSONA);
    render(<LessonDebatePersona lessonId="lesson-1" />);
    fireEvent.click(screen.getByTestId('debate-persona-generate'));

    expect(await screen.findByTestId('debate-persona-reason')).toHaveTextContent(
      'A different lens on cost vs. benefit than a student focused on access.'
    );
  });

  it('sends optional student context when the form is filled in', async () => {
    getPersonaOptions.mockResolvedValue({ states: [], age_ranges: [] });
    generateDebatePersona.mockResolvedValue(PERSONA);
    render(<LessonDebatePersona lessonId="lesson-1" />);

    fireEvent.click(screen.getByTestId('debate-persona-toggle-context'));
    await screen.findByTestId('debate-persona-context-form');
    fireEvent.change(screen.getByTestId('debate-persona-context-occupation'), {
      target: { value: 'Student' },
    });

    fireEvent.click(screen.getByTestId('debate-persona-generate'));

    await waitFor(() => {
      expect(generateDebatePersona).toHaveBeenCalledWith('lesson-1', {
        studentPersona: { occupation: 'Student', state: null, age_range: null, income_bracket: null },
      });
    });
  });

  it('shows the persona_prompt for copying into Debate Mode', async () => {
    generateDebatePersona.mockResolvedValue(PERSONA);
    render(<LessonDebatePersona lessonId="lesson-1" />);
    fireEvent.click(screen.getByTestId('debate-persona-generate'));

    expect(await screen.findByTestId('debate-persona-prompt')).toHaveTextContent('PERSONA INSTRUCTIONS:');

    fireEvent.click(screen.getByTestId('debate-persona-copy'));
    await waitFor(() => {
      expect(navigator.clipboard.writeText).toHaveBeenCalledWith(PERSONA.persona_prompt);
    });
  });

  it('requests and displays a Socratic hint', async () => {
    generateDebatePersona.mockResolvedValue(PERSONA);
    getSocraticHint.mockResolvedValue({ hint: 'What assumption is your argument relying on?' });
    render(<LessonDebatePersona lessonId="lesson-1" />);

    fireEvent.click(screen.getByTestId('debate-persona-generate'));
    await screen.findByTestId('debate-persona-role');

    fireEvent.change(screen.getByTestId('debate-persona-hint-textarea'), {
      target: { value: 'Pro: funding is good. Con: costs too much.' },
    });
    fireEvent.click(screen.getByTestId('debate-persona-hint-button'));

    await waitFor(() => {
      expect(getSocraticHint).toHaveBeenCalledWith(
        'lesson-1',
        PERSONA.persona_id,
        'Pro: funding is good. Con: costs too much.'
      );
    });
    expect(await screen.findByTestId('debate-persona-hint-result')).toHaveTextContent(
      'What assumption is your argument relying on?'
    );
  });

  it('allows generating a different opponent', async () => {
    generateDebatePersona.mockResolvedValue(PERSONA);
    render(<LessonDebatePersona lessonId="lesson-1" />);
    fireEvent.click(screen.getByTestId('debate-persona-generate'));
    await screen.findByTestId('debate-persona-role');

    fireEvent.click(screen.getByTestId('debate-persona-regenerate'));
    expect(screen.getByTestId('debate-persona-generate')).toBeInTheDocument();
  });

  it('shows an error message when generation fails', async () => {
    generateDebatePersona.mockRejectedValue(new Error('generation failed'));
    render(<LessonDebatePersona lessonId="lesson-1" />);
    fireEvent.click(screen.getByTestId('debate-persona-generate'));

    expect(await screen.findByText('generation failed')).toBeInTheDocument();
  });
});
