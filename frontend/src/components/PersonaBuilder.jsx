import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { getPersona, getPersonaOptions, savePersona, deletePersona } from '../api';
import './PersonaBuilder.css';

const EMPTY_FORM = { occupation: '', state: '', age_range: '', income_bracket: '' };

// The persona is deliberately broad and optional. This component collects only
// occupation-or-role, state, an age *range*, and an income *bracket* -- never
// an exact age, exact income, address, employer, or any protected attribute.
function PersonaBuilder({ isAuthenticated = false, onSaved, onDeleted, onSkip }) {
  const [options, setOptions] = useState(null);
  const [form, setForm] = useState(EMPTY_FORM);
  const [hasSavedPersona, setHasSavedPersona] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState('');
  const [status, setStatus] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const opts = await getPersonaOptions();
      setOptions(opts);

      // Prefill from the saved persona so an authenticated student can edit it.
      if (isAuthenticated) {
        try {
          const persona = await getPersona();
          if (persona && persona.has_persona) {
            setForm({
              occupation: persona.occupation || '',
              state: persona.state || '',
              age_range: persona.age_range || '',
              income_bracket: persona.income_bracket || '',
            });
            setHasSavedPersona(true);
          }
        } catch {
          // A missing/unauthorized persona is fine -- start from a blank form.
        }
      }
    } catch (err) {
      setError(err?.response?.data?.detail || err.message || 'Failed to load the persona builder.');
    } finally {
      setLoading(false);
    }
  }, [isAuthenticated]);

  useEffect(() => {
    load();
  }, [load]);

  const maxOccupationLength = options?.occupation_max_length ?? 80;

  const occupationTooLong = form.occupation.trim().length > maxOccupationLength;
  const isFormValid = !occupationTooLong;

  const handleChange = (field) => (e) => {
    setStatus('');
    setForm((prev) => ({ ...prev, [field]: e.target.value }));
  };

  // Convert the form into the API shape: trimmed values, blanks -> null (skip).
  const toPayload = useMemo(
    () => () => ({
      occupation: form.occupation.trim() || null,
      state: form.state || null,
      age_range: form.age_range || null,
      income_bracket: form.income_bracket || null,
    }),
    [form]
  );

  const handleSave = async () => {
    if (saving || !isFormValid) return;
    setSaving(true);
    setError('');
    setStatus('');
    try {
      const saved = await savePersona(toPayload());
      setHasSavedPersona(true);
      setStatus('Persona saved.');
      if (onSaved) onSaved(saved);
    } catch (err) {
      setError(err?.response?.data?.detail || err.message || 'Failed to save your persona.');
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async () => {
    if (deleting) return;
    setDeleting(true);
    setError('');
    setStatus('');
    try {
      await deletePersona();
      setForm(EMPTY_FORM);
      setHasSavedPersona(false);
      setStatus('Persona deleted.');
      if (onDeleted) onDeleted();
    } catch (err) {
      setError(err?.response?.data?.detail || err.message || 'Failed to delete your persona.');
    } finally {
      setDeleting(false);
    }
  };

  if (loading) {
    return (
      <div className="persona-builder" data-testid="persona-loading">
        Loading persona builder…
      </div>
    );
  }

  if (error && !options) {
    return <div className="persona-builder persona-error">{error}</div>;
  }

  return (
    <section className="persona-builder" aria-labelledby="persona-heading">
      <h2 id="persona-heading" className="persona-title">Build your persona</h2>

      <p className="persona-intro" id="persona-intro">
        This is optional and helps personalize the lesson. Every field can be
        skipped, and your persona can be completely <strong>fictional</strong>.
      </p>

      {options?.not_collected?.length > 0 && (
        <p className="persona-privacy-note" data-testid="persona-privacy-note">
          We never ask for your {options.not_collected.join(', ')}.
        </p>
      )}

      <form
        className="persona-form"
        aria-describedby="persona-intro"
        onSubmit={(e) => {
          e.preventDefault();
          handleSave();
        }}
      >
        <div className="persona-field">
          <label htmlFor="persona-occupation">Occupation or role (current or intended)</label>
          <input
            id="persona-occupation"
            type="text"
            list="persona-occupation-suggestions"
            value={form.occupation}
            onChange={handleChange('occupation')}
            maxLength={maxOccupationLength}
            placeholder="e.g. Student, Nurse, Small-business owner"
            aria-describedby="persona-occupation-help"
            aria-invalid={occupationTooLong}
            data-testid="persona-occupation"
          />
          <datalist id="persona-occupation-suggestions">
            {(options?.occupation_suggestions || []).map((o) => (
              <option key={o} value={o} />
            ))}
          </datalist>
          <span id="persona-occupation-help" className="persona-help">
            Pick a suggestion or type your own. Optional.
          </span>
          {occupationTooLong && (
            <span className="persona-field-error" data-testid="persona-occupation-error" role="alert">
              Keep this under {maxOccupationLength} characters.
            </span>
          )}
        </div>

        <div className="persona-field">
          <label htmlFor="persona-state">State</label>
          <select
            id="persona-state"
            value={form.state}
            onChange={handleChange('state')}
            data-testid="persona-state"
          >
            <option value="">Prefer not to say</option>
            {(options?.states || []).map((s) => (
              <option key={s.code} value={s.code}>{s.name}</option>
            ))}
          </select>
        </div>

        <div className="persona-field">
          <label htmlFor="persona-age-range">Age range</label>
          <select
            id="persona-age-range"
            value={form.age_range}
            onChange={handleChange('age_range')}
            data-testid="persona-age-range"
          >
            <option value="">Prefer not to say</option>
            {(options?.age_ranges || []).map((a) => (
              <option key={a} value={a}>{a}</option>
            ))}
          </select>
        </div>

        <div className="persona-field">
          <label htmlFor="persona-income">Household income bracket</label>
          <select
            id="persona-income"
            value={form.income_bracket}
            onChange={handleChange('income_bracket')}
            data-testid="persona-income"
          >
            <option value="">Prefer not to say</option>
            {(options?.income_brackets || []).map((b) => (
              <option key={b} value={b}>{b}</option>
            ))}
          </select>
        </div>

        {error && <div className="persona-error-inline" role="alert">{error}</div>}
        {status && <div className="persona-status" role="status" data-testid="persona-status">{status}</div>}

        {!isAuthenticated && (
          <p className="persona-signin-note" data-testid="persona-signin-note">
            Sign in to save your persona.
          </p>
        )}

        <div className="persona-actions">
          <button
            type="submit"
            className="persona-btn persona-save-btn"
            disabled={!isAuthenticated || saving || !isFormValid}
            data-testid="persona-save"
          >
            {saving ? 'Saving…' : hasSavedPersona ? 'Update persona' : 'Save persona'}
          </button>

          {onSkip && (
            <button
              type="button"
              className="persona-btn persona-skip-btn"
              onClick={onSkip}
              data-testid="persona-skip"
            >
              Skip for now
            </button>
          )}

          {hasSavedPersona && (
            <button
              type="button"
              className="persona-btn persona-delete-btn"
              onClick={handleDelete}
              disabled={deleting}
              data-testid="persona-delete"
            >
              {deleting ? 'Deleting…' : 'Delete persona'}
            </button>
          )}
        </div>
      </form>
    </section>
  );
}

export default PersonaBuilder;
