// Lesson Mode: keeps a lesson's bill text/title in sessionStorage, keyed by
// lesson_id, so sub-pages routed independently by URL (vocabulary, quiz,
// personal impact, debate persona -- each its own route so refresh/direct
// links work) don't need the student to re-paste the bill, and so
// bill-text-dependent generation calls (personal impact, debate persona)
// still work after a backend process restart clears the in-memory RAG
// cache. Session-scoped, not persisted server-side -- purely a UX
// convenience, never a source of truth.

const PREFIX = 'lesson-mode:';

// Shared by every entry point that needs to turn a bill title into a bill_id
// before a lesson exists yet (LessonHub's paste form, LessonPersona when a
// bill arrives via router state from Legislation.jsx).
export function slugifyBillTitle(text) {
  return (text || '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/(^-|-$)/g, '')
    .slice(0, 60);
}

export function saveLessonBillText(lessonId, billText, billTitle) {
  try {
    sessionStorage.setItem(
      `${PREFIX}${lessonId}`,
      JSON.stringify({ billText: billText || '', billTitle: billTitle || '' })
    );
  } catch {
    // sessionStorage unavailable (private browsing, etc.) -- non-fatal.
  }
}

export function getLessonBillText(lessonId) {
  try {
    const raw = sessionStorage.getItem(`${PREFIX}${lessonId}`);
    if (!raw) return { billText: '', billTitle: '' };
    return JSON.parse(raw);
  } catch {
    return { billText: '', billTitle: '' };
  }
}
