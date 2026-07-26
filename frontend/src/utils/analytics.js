// End-to-end Lesson Mode flow analytics (Increment 12).
//
// A structured logging hook, not a full analytics pipeline (no GA4/Mixpanel
// integration -- out of scope). Deliberately does NOT import from '../api':
// it reads import.meta.env.VITE_API_URL directly and no-ops when it's
// missing, so this module is safe to import unmocked in any component test
// (unlike api.js, which throws at module load if the env var is absent).
// Every call is fire-and-forget -- a failed analytics beacon must never
// block or break the student's flow.

export const FLOW_EVENTS = {
  BILL_SELECTED: 'bill_selected',
  PERSONA_STEP_VIEWED: 'persona_step_viewed',
  IMPACT_GENERATED: 'impact_generated',
  LESSON_VIEWED: 'lesson_viewed',
  VOCABULARY_REVIEWED: 'vocabulary_reviewed',
  QUIZ_COMPLETED: 'quiz_completed',
  OPEN_RESPONSE_COMPLETED: 'open_response_completed',
  DEBATE_STARTED: 'debate_started',
  DEBATE_ENDED: 'debate_ended',
  REFLECTION_SUBMITTED: 'reflection_submitted',
  DASHBOARD_VIEWED: 'dashboard_viewed',
};

// Only bounded, non-text fields are ever sent -- never bill text, answers,
// or transcripts. Matches routes/lesson_routes.py's AnalyticsEventRequest.
export function trackEvent(eventType, { lessonId, stepIndex, success } = {}) {
  const payload = { event_type: eventType, lesson_id: lessonId ?? null, step_index: stepIndex ?? null, success: success ?? null };

  if (typeof console !== 'undefined') {
    console.info('[lesson-flow]', eventType, payload);
  }

  const apiUrl = typeof import.meta !== 'undefined' ? import.meta.env?.VITE_API_URL : undefined;
  if (!apiUrl || typeof fetch !== 'function') return;

  try {
    fetch(`${apiUrl}/lesson/analytics/event`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }).catch(() => {
      // Analytics is best-effort; a network failure here must never
      // surface to the student or interrupt their flow.
    });
  } catch {
    // Synchronous failures (e.g. fetch unavailable in some test/SSR
    // environments) are equally non-fatal.
  }
}
