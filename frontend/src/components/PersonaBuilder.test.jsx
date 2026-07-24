import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';

import PersonaBuilder from './PersonaBuilder';
import { getPersona, getPersonaOptions, savePersona, deletePersona } from '../api';

vi.mock('../api', () => ({
  getPersonaOptions: vi.fn(),
  getPersona: vi.fn(),
  savePersona: vi.fn(),
  deletePersona: vi.fn(),
}));

const OPTIONS = {
  occupation_suggestions: ['Student', 'Educator', 'Healthcare'],
  occupation_allows_custom: true,
  occupation_max_length: 80,
  states: [
    { code: 'CA', name: 'California' },
    { code: 'NY', name: 'New York' },
    { code: 'TX', name: 'Texas' },
  ],
  age_ranges: ['Under 18', '18-24', '25-34'],
  income_brackets: ['Under $25,000', '$25,000-$49,999'],
  all_fields_optional: true,
  persona_may_be_fictional: true,
  not_collected: ['exact age', 'exact income', 'home address'],
};

beforeEach(() => {
  vi.clearAllMocks();
  getPersonaOptions.mockResolvedValue(OPTIONS);
  getPersona.mockResolvedValue({ has_persona: false });
});

describe('PersonaBuilder', () => {
  it('explains the persona is optional and may be fictional', async () => {
    render(<PersonaBuilder isAuthenticated />);
    expect(await screen.findByText(/fictional/i)).toBeInTheDocument();
    expect(screen.getByText(/can be skipped/i)).toBeInTheDocument();
  });

  it('shows the privacy note listing what is never collected', async () => {
    render(<PersonaBuilder isAuthenticated />);
    const note = await screen.findByTestId('persona-privacy-note');
    expect(note).toHaveTextContent('exact age');
    expect(note).toHaveTextContent('exact income');
    expect(note).toHaveTextContent('home address');
  });

  it('renders accessible labels for every field', async () => {
    render(<PersonaBuilder isAuthenticated />);
    await screen.findByTestId('persona-occupation');
    expect(screen.getByLabelText(/occupation or role/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/^state$/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/age range/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/household income bracket/i)).toBeInTheDocument();
  });

  it('offers "Prefer not to say" so any field can be skipped', async () => {
    render(<PersonaBuilder isAuthenticated />);
    await screen.findByTestId('persona-state');
    // Every select defaults to the skip option (empty value).
    expect(screen.getByTestId('persona-state')).toHaveValue('');
    expect(screen.getByTestId('persona-age-range')).toHaveValue('');
    expect(screen.getByTestId('persona-income')).toHaveValue('');
  });

  it('saves a complete persona and converts blanks to null', async () => {
    savePersona.mockResolvedValue({ has_persona: true, occupation: 'Nurse', state: 'CA' });
    render(<PersonaBuilder isAuthenticated />);
    await screen.findByTestId('persona-occupation');

    fireEvent.change(screen.getByTestId('persona-occupation'), { target: { value: 'Nurse' } });
    fireEvent.change(screen.getByTestId('persona-state'), { target: { value: 'CA' } });
    fireEvent.change(screen.getByTestId('persona-age-range'), { target: { value: '25-34' } });
    fireEvent.click(screen.getByTestId('persona-save'));

    await waitFor(() => {
      expect(savePersona).toHaveBeenCalledWith({
        occupation: 'Nurse',
        state: 'CA',
        age_range: '25-34',
        income_bracket: null, // left as "Prefer not to say"
      });
    });
    expect(await screen.findByTestId('persona-status')).toHaveTextContent('Persona saved.');
  });

  it('saves a persona with only one field filled in', async () => {
    savePersona.mockResolvedValue({ has_persona: true, state: 'NY' });
    render(<PersonaBuilder isAuthenticated />);
    await screen.findByTestId('persona-state');

    fireEvent.change(screen.getByTestId('persona-state'), { target: { value: 'NY' } });
    fireEvent.click(screen.getByTestId('persona-save'));

    await waitFor(() => {
      expect(savePersona).toHaveBeenCalledWith({
        occupation: null,
        state: 'NY',
        age_range: null,
        income_bracket: null,
      });
    });
  });

  it('disables saving and prompts sign-in when unauthenticated', async () => {
    render(<PersonaBuilder isAuthenticated={false} />);
    await screen.findByTestId('persona-occupation');
    expect(screen.getByTestId('persona-save')).toBeDisabled();
    expect(screen.getByTestId('persona-signin-note')).toBeInTheDocument();
    // Options load without auth; the saved persona is never fetched.
    expect(getPersona).not.toHaveBeenCalled();
  });

  it('calls onSkip when the student skips persona creation', async () => {
    const onSkip = vi.fn();
    render(<PersonaBuilder isAuthenticated onSkip={onSkip} />);
    await screen.findByTestId('persona-skip');
    fireEvent.click(screen.getByTestId('persona-skip'));
    expect(onSkip).toHaveBeenCalled();
    expect(savePersona).not.toHaveBeenCalled();
  });

  it('prefills the form from a saved persona for editing', async () => {
    getPersona.mockResolvedValue({
      has_persona: true,
      occupation: 'Teacher',
      state: 'TX',
      age_range: '25-34',
      income_bracket: null,
    });
    savePersona.mockResolvedValue({ has_persona: true });
    render(<PersonaBuilder isAuthenticated />);

    await waitFor(() => expect(screen.getByTestId('persona-occupation')).toHaveValue('Teacher'));
    expect(screen.getByTestId('persona-state')).toHaveValue('TX');

    // Editing: change occupation and update.
    fireEvent.change(screen.getByTestId('persona-occupation'), { target: { value: 'Principal' } });
    expect(screen.getByTestId('persona-save')).toHaveTextContent(/update persona/i);
    fireEvent.click(screen.getByTestId('persona-save'));

    await waitFor(() => {
      expect(savePersona).toHaveBeenCalledWith(
        expect.objectContaining({ occupation: 'Principal', state: 'TX' })
      );
    });
  });

  it('deletes a saved persona and clears the form', async () => {
    getPersona.mockResolvedValue({ has_persona: true, occupation: 'Teacher', state: 'TX' });
    deletePersona.mockResolvedValue({ deleted: true });
    render(<PersonaBuilder isAuthenticated />);

    await waitFor(() => expect(screen.getByTestId('persona-occupation')).toHaveValue('Teacher'));
    fireEvent.click(screen.getByTestId('persona-delete'));

    await waitFor(() => expect(deletePersona).toHaveBeenCalled());
    expect(screen.getByTestId('persona-occupation')).toHaveValue('');
    expect(await screen.findByTestId('persona-status')).toHaveTextContent('Persona deleted.');
    // Delete button disappears once there is no saved persona.
    expect(screen.queryByTestId('persona-delete')).not.toBeInTheDocument();
  });

  it('shows an error when saving fails', async () => {
    savePersona.mockRejectedValue(new Error('network error'));
    render(<PersonaBuilder isAuthenticated />);
    await screen.findByTestId('persona-save');
    fireEvent.click(screen.getByTestId('persona-save'));
    expect(await screen.findByText('network error')).toBeInTheDocument();
  });

  it('does not offer a delete button before anything is saved', async () => {
    render(<PersonaBuilder isAuthenticated />);
    await screen.findByTestId('persona-save');
    expect(screen.queryByTestId('persona-delete')).not.toBeInTheDocument();
  });
});
