import React, { useState } from 'react';
import { MessageCircleQuestion, Sparkles } from 'lucide-react';
import { generateDebatePersona, getPersonaOptions, getSocraticHint } from '../api';
import './LessonDebatePersona.css';

const EMPTY_CONTEXT = { occupation: '', state: '', age_range: '', income_bracket: '' };

// Dynamic opposing debate persona service page (Increment 9): generates a
// bill-grounded stakeholder with a meaningfully different perspective to
// use as an AI debate opponent, and an optional Socratic hint for learning
// mode. This is intentionally self-contained rather than auto-launching a
// live debate -- Debate.jsx doesn't yet accept a persona_prompt from
// Lesson Mode (see docs/LESSON_MODE_ARCHITECTURE.md Non-goals), so the
// generated prompt is surfaced for the student/teacher to copy into Debate
// Mode's persona field today.
function LessonDebatePersona({ lessonId }) {
  const [showContextForm, setShowContextForm] = useState(false);
  const [context, setContext] = useState(EMPTY_CONTEXT);
  const [options, setOptions] = useState(null);

  const [persona, setPersona] = useState(null);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState('');
  const [copied, setCopied] = useState(false);

  const [transcript, setTranscript] = useState('');
  const [hint, setHint] = useState('');
  const [hintLoading, setHintLoading] = useState(false);
  const [hintError, setHintError] = useState('');

  const loadOptionsOnce = async () => {
    if (options) return;
    try {
      const opts = await getPersonaOptions();
      setOptions(opts);
    } catch {
      // Options are a nice-to-have for the dropdowns; the form still works
      // as free text/selects with no options loaded.
    }
  };

  const handleToggleContextForm = () => {
    setShowContextForm((prev) => !prev);
    loadOptionsOnce();
  };

  const handleGenerate = async () => {
    if (generating) return;
    setGenerating(true);
    setError('');
    try {
      const hasContext = Object.values(context).some((v) => v);
      const studentPersona = hasContext
        ? {
            occupation: context.occupation || null,
            state: context.state || null,
            age_range: context.age_range || null,
            income_bracket: context.income_bracket || null,
          }
        : undefined;
      const data = await generateDebatePersona(lessonId, { studentPersona });
      setPersona(data);
      setHint('');
    } catch (err) {
      setError(err?.response?.data?.detail || err.message || 'Failed to generate an opposing persona.');
    } finally {
      setGenerating(false);
    }
  };

  const handleCopyPrompt = async () => {
    if (!persona) return;
    try {
      await navigator.clipboard.writeText(persona.persona_prompt);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Clipboard API unavailable -- the text is still visible to select manually.
    }
  };

  const handleGetHint = async () => {
    if (hintLoading || !persona) return;
    setHintLoading(true);
    setHintError('');
    try {
      const data = await getSocraticHint(lessonId, persona.persona_id, transcript);
      setHint(data.hint);
    } catch (err) {
      setHintError(err?.response?.data?.detail || err.message || 'Failed to get a hint.');
    } finally {
      setHintLoading(false);
    }
  };

  return (
    <section className="debate-persona-container" aria-labelledby="debate-persona-heading">
      <h2 id="debate-persona-heading" className="debate-persona-title">
        Your Debate Opponent
      </h2>
      <p className="debate-persona-intro">
        Generate a bill-grounded stakeholder with a genuinely different perspective from your
        own to argue against in a practice debate.
      </p>

      {error && <div className="debate-persona-error" role="alert">{error}</div>}

      {!persona ? (
        <>
          <button
            type="button"
            className="debate-persona-toggle-context-btn"
            onClick={handleToggleContextForm}
            data-testid="debate-persona-toggle-context"
          >
            {showContextForm ? 'Hide my context' : 'Add your context (optional)'}
          </button>

          {showContextForm && (
            <div className="debate-persona-context-form" data-testid="debate-persona-context-form">
              <p className="debate-persona-context-note">
                Optional and can be skipped entirely -- used only to help pick a meaningfully
                different opposing perspective, never to shape the opponent's traits.
              </p>
              <input
                type="text"
                className="debate-persona-context-input"
                placeholder="Occupation or role"
                value={context.occupation}
                onChange={(e) => setContext((c) => ({ ...c, occupation: e.target.value }))}
                data-testid="debate-persona-context-occupation"
              />
              <select
                className="debate-persona-context-input"
                value={context.state}
                onChange={(e) => setContext((c) => ({ ...c, state: e.target.value }))}
                data-testid="debate-persona-context-state"
              >
                <option value="">State (prefer not to say)</option>
                {(options?.states || []).map((s) => (
                  <option key={s.code} value={s.code}>{s.name}</option>
                ))}
              </select>
              <select
                className="debate-persona-context-input"
                value={context.age_range}
                onChange={(e) => setContext((c) => ({ ...c, age_range: e.target.value }))}
                data-testid="debate-persona-context-age"
              >
                <option value="">Age range (prefer not to say)</option>
                {(options?.age_ranges || []).map((a) => (
                  <option key={a} value={a}>{a}</option>
                ))}
              </select>
            </div>
          )}

          <button
            type="button"
            className="debate-persona-generate-btn"
            onClick={handleGenerate}
            disabled={generating}
            data-testid="debate-persona-generate"
          >
            {generating ? 'Finding an opposing voice…' : 'Generate Opposing Persona'}
          </button>
        </>
      ) : (
        <div className="debate-persona-result" data-testid="debate-persona-result">
          <div className="debate-persona-role-card">
            <h3 className="debate-persona-role" data-testid="debate-persona-role">{persona.role}</h3>
            <p className="debate-persona-location">{persona.location_context}</p>
            <p className="debate-persona-position"><strong>Position:</strong> {persona.position}</p>

            {persona.interests?.length > 0 && (
              <div className="debate-persona-list-group">
                <h4>Interests</h4>
                <ul>{persona.interests.map((i, idx) => <li key={idx}>{i}</li>)}</ul>
              </div>
            )}

            {persona.likely_concerns?.length > 0 && (
              <div className="debate-persona-list-group">
                <h4>Likely concerns</h4>
                <ul>{persona.likely_concerns.map((c, idx) => <li key={idx}>{c}</li>)}</ul>
              </div>
            )}

            <p className="debate-persona-sources">
              Grounded in: {persona.section_ids.join(', ')}
            </p>
          </div>

          <div className="debate-persona-why" data-testid="debate-persona-reason">
            <Sparkles size={16} />
            <span><strong>Why this stakeholder:</strong> {persona.reason_for_selection}</span>
          </div>

          <div className="debate-persona-prompt-box">
            <div className="debate-persona-prompt-head">
              <span>Debate persona instructions</span>
              <button
                type="button"
                className="debate-persona-copy-btn"
                onClick={handleCopyPrompt}
                data-testid="debate-persona-copy"
              >
                {copied ? 'Copied!' : 'Copy'}
              </button>
            </div>
            <pre className="debate-persona-prompt-text" data-testid="debate-persona-prompt">
              {persona.persona_prompt}
            </pre>
            <p className="debate-persona-prompt-help">
              Paste this into Debate Mode's persona field to debate against this stakeholder.
            </p>
          </div>

          <div className="debate-persona-hint-box">
            <h3 className="debate-persona-hint-heading">
              <MessageCircleQuestion size={18} />
              Need a Socratic hint? (Learning mode)
            </h3>
            <p className="debate-persona-hint-intro">
              Paste your debate transcript so far for one thought-provoking question -- not an
              answer -- to help you notice a gap in your own reasoning.
            </p>
            <textarea
              className="debate-persona-hint-textarea"
              rows={5}
              value={transcript}
              onChange={(e) => setTranscript(e.target.value)}
              placeholder="Paste the debate transcript so far..."
              data-testid="debate-persona-hint-textarea"
            />
            {hintError && <div className="debate-persona-error" role="alert">{hintError}</div>}
            <button
              type="button"
              className="debate-persona-hint-btn"
              onClick={handleGetHint}
              disabled={hintLoading}
              data-testid="debate-persona-hint-button"
            >
              {hintLoading ? 'Thinking of a question…' : 'Get a Hint'}
            </button>
            {hint && (
              <div className="debate-persona-hint-result" data-testid="debate-persona-hint-result">
                {hint}
              </div>
            )}
          </div>

          <button
            type="button"
            className="debate-persona-regenerate-btn"
            onClick={() => setPersona(null)}
            data-testid="debate-persona-regenerate"
          >
            Generate a different opponent
          </button>
        </div>
      )}
    </section>
  );
}

export default LessonDebatePersona;
