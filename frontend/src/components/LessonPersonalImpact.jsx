import React, { useState } from 'react';
import { getPersonalImpact } from '../api';
import { trackEvent, FLOW_EVENTS } from '../utils/analytics';
import { markFlowStepComplete } from '../utils/lessonFlow';
import './LessonPersonalImpact.css';

const CONFIDENCE_LABELS = {
  high: 'High confidence',
  medium: 'Medium confidence',
  low: 'Low confidence',
};

function ConfidenceBadge({ level }) {
  const known = CONFIDENCE_LABELS[level] ? level : 'low';
  return (
    <span className={`impact-confidence impact-confidence-${known}`} data-testid="impact-confidence">
      {CONFIDENCE_LABELS[known]}
    </span>
  );
}

function ImpactCard({ impact }) {
  return (
    <li className="impact-card">
      <div className="impact-card-head">
        <span className="impact-what">{impact.impact}</span>
        <ConfidenceBadge level={impact.confidence} />
      </div>
      <p className="impact-why"><strong>Why:</strong> {impact.reasoning}</p>
      {impact.section_ids?.length > 0 && (
        <p className="impact-sources">
          Relevant bill section{impact.section_ids.length > 1 ? 's' : ''}: {impact.section_ids.join(', ')}
        </p>
      )}
    </li>
  );
}

// Shows the personalized, grounded bill-impact narrative prominently. Generation
// is an explicit action (a model call), so results appear after the student asks.
function LessonPersonalImpact({ lessonId, billText, persona }) {
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const handleGenerate = async () => {
    if (loading) return;
    setLoading(true);
    setError('');
    try {
      const data = await getPersonalImpact(lessonId, { billText, persona });
      setResult(data);
      markFlowStepComplete(lessonId, 'personal-impact');
      trackEvent(FLOW_EVENTS.IMPACT_GENERATED, { lessonId, success: true });
    } catch (err) {
      setError(err?.response?.data?.detail || err.message || 'Failed to generate your personal impact.');
      trackEvent(FLOW_EVENTS.IMPACT_GENERATED, { lessonId, success: false });
    } finally {
      setLoading(false);
    }
  };

  return (
    <section className="personal-impact" aria-labelledby="personal-impact-heading">
      <h2 id="personal-impact-heading" className="personal-impact-title">
        How could this bill affect you?
      </h2>

      {!result && (
        <p className="personal-impact-intro">
          Get a grounded, plain-language look at how this bill could affect someone with your
          persona. It separates effects the bill clearly establishes from possible knock-on
          effects and what stays uncertain — every point cites the bill section it comes from.
        </p>
      )}

      {error && <div className="personal-impact-error" role="alert">{error}</div>}

      {!result ? (
        <button
          className="personal-impact-generate-btn"
          onClick={handleGenerate}
          disabled={loading}
          data-testid="personal-impact-generate"
        >
          {loading ? 'Analyzing the bill for you…' : 'See how this bill could affect you'}
        </button>
      ) : (
        <div className="personal-impact-result" data-testid="personal-impact-result">
          <div className="personal-impact-summary-row">
            <p className="personal-impact-narrative" data-testid="personal-impact-narrative">
              {result.narrative}
            </p>
            <div className="personal-impact-overall">
              <span className="personal-impact-overall-label">Overall</span>
              <ConfidenceBadge level={result.confidence} />
            </div>
          </div>

          <div className="personal-impact-group personal-impact-direct" data-testid="personal-impact-direct">
            <h3>What could affect you directly</h3>
            {result.direct_impacts?.length > 0 ? (
              <ul className="impact-list">
                {result.direct_impacts.map((imp, i) => <ImpactCard key={i} impact={imp} />)}
              </ul>
            ) : (
              <p className="personal-impact-empty">
                The bill text doesn't clearly establish a direct effect on someone with this persona.
              </p>
            )}
          </div>

          <div className="personal-impact-group personal-impact-indirect" data-testid="personal-impact-indirect">
            <h3>Possible indirect effects</h3>
            {result.possible_indirect_impacts?.length > 0 ? (
              <ul className="impact-list">
                {result.possible_indirect_impacts.map((imp, i) => <ImpactCard key={i} impact={imp} />)}
              </ul>
            ) : (
              <p className="personal-impact-empty">No likely indirect effects were identified.</p>
            )}
          </div>

          {result.uncertainties?.length > 0 && (
            <div className="personal-impact-group personal-impact-uncertain" data-testid="personal-impact-uncertainties">
              <h3>What stays uncertain</h3>
              <ul>
                {result.uncertainties.map((u, i) => <li key={i}>{u}</li>)}
              </ul>
            </div>
          )}

          {result.questions_to_consider?.length > 0 && (
            <div className="personal-impact-group personal-impact-questions" data-testid="personal-impact-questions">
              <h3>Questions to consider</h3>
              <ul>
                {result.questions_to_consider.map((q, i) => <li key={i}>{q}</li>)}
              </ul>
            </div>
          )}

          <button
            className="personal-impact-regenerate-btn"
            onClick={handleGenerate}
            disabled={loading}
            data-testid="personal-impact-regenerate"
          >
            {loading ? 'Refreshing…' : 'Regenerate'}
          </button>
        </div>
      )}
    </section>
  );
}

export default LessonPersonalImpact;
