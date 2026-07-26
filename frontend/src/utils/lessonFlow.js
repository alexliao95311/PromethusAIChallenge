// End-to-end Lesson Mode flow state (Increment 12).
//
// The ordered sequence connecting every increment's page into one guided
// workflow: bill -> persona (optional) -> personalized impact (optional) ->
// lesson -> vocabulary -> quiz -> open response -> debate -> reflection ->
// mastery dashboard.
//
// Step-completion for lesson/vocabulary/quiz/open-response/reflection is
// authoritatively derivable from the backend (quiz attempts, open-response
// attempts, vocabulary mastery, reflections -- see MasteryDashboard and
// getReflectionProgress). Persona and personal-impact have no per-lesson
// "have you done this" backend check (persona is a global per-user profile;
// impact generation is idempotent/cached but has no cheap existence check),
// so those two are tracked as a lightweight, best-effort LOCAL hint via
// localStorage, namespaced per lesson_id.
//
// This local state is a UX nicety only, never a source of truth: it
// persists across a page refresh (satisfying "preserve work on refresh")
// and across browser sessions on the SAME device/browser ("leave and
// resume"), but is correctly and gracefully absent on a different device --
// falling back to "not yet marked", never a false claim of completion.

const PREFIX = 'lesson-flow:';

export const FLOW_STEPS = [
  { key: 'persona', label: 'Persona', path: () => '/lesson/persona', optional: true },
  { key: 'personal-impact', label: 'Personal Impact', path: (lessonId) => `/lesson/${lessonId}/personal-impact`, optional: true },
  { key: 'lesson', label: 'Lesson', path: (lessonId) => `/lesson/${lessonId}` },
  { key: 'vocabulary', label: 'Vocabulary', path: (lessonId) => `/lesson/${lessonId}/vocabulary` },
  { key: 'quiz', label: 'Quiz', path: (lessonId) => `/lesson/${lessonId}/quiz` },
  { key: 'open-response', label: 'Open Response', path: (lessonId) => `/lesson/${lessonId}/open-response` },
  { key: 'debate-persona', label: 'Debate', path: (lessonId) => `/lesson/${lessonId}/debate-persona` },
  { key: 'reflection', label: 'Reflection', path: (lessonId) => `/lesson/${lessonId}/reflection` },
  { key: 'mastery-dashboard', label: 'Dashboard', path: () => '/lesson/mastery-dashboard' },
];

function readFlags(lessonId) {
  try {
    const raw = localStorage.getItem(`${PREFIX}${lessonId}`);
    return raw ? JSON.parse(raw) : {};
  } catch {
    return {};
  }
}

export function markFlowStepComplete(lessonId, stepKey) {
  if (!lessonId) return;
  try {
    const flags = readFlags(lessonId);
    flags[stepKey] = true;
    localStorage.setItem(`${PREFIX}${lessonId}`, JSON.stringify(flags));
  } catch {
    // localStorage unavailable (private browsing, etc.) -- non-fatal; the
    // step just won't show as complete until backend-derived data catches up.
  }
}

export function isFlowStepComplete(lessonId, stepKey) {
  if (!lessonId) return false;
  return Boolean(readFlags(lessonId)[stepKey]);
}

// Returns the next step's { key, label, path } after `currentStepKey`, or
// null if `currentStepKey` is the last step. `lessonId` may be null for the
// two non-lesson-scoped steps (persona and mastery-dashboard paths).
export function getNextStep(currentStepKey, lessonId) {
  const idx = FLOW_STEPS.findIndex((s) => s.key === currentStepKey);
  if (idx === -1 || idx === FLOW_STEPS.length - 1) return null;
  const next = FLOW_STEPS[idx + 1];
  return { key: next.key, label: next.label, path: next.path(lessonId) };
}
