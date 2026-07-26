import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { trackEvent, FLOW_EVENTS } from './analytics';

describe('analytics trackEvent', () => {
  let fetchSpy;

  beforeEach(() => {
    vi.stubEnv('VITE_API_URL', 'http://localhost:5050');
    fetchSpy = vi.spyOn(global, 'fetch').mockResolvedValue({ ok: true });
    vi.spyOn(console, 'info').mockImplementation(() => {});
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllEnvs();
  });

  it('never throws even when fetch is unavailable', () => {
    fetchSpy.mockRestore();
    // Simulate an environment where fetch is not a function at all.
    const original = global.fetch;
    global.fetch = undefined;
    expect(() => trackEvent(FLOW_EVENTS.QUIZ_COMPLETED, { lessonId: 'lesson-1' })).not.toThrow();
    global.fetch = original;
  });

  it('sends only whitelisted, non-text fields -- never raw student content', () => {
    trackEvent(FLOW_EVENTS.DEBATE_STARTED, { lessonId: 'lesson-1', stepIndex: 7, success: true });
    expect(fetchSpy).toHaveBeenCalled();
    const [, options] = fetchSpy.mock.calls[0];
    const body = JSON.parse(options.body);
    expect(Object.keys(body).sort()).toEqual(['event_type', 'lesson_id', 'step_index', 'success']);
    expect(body.event_type).toBe('debate_started');
  });

  it('does not reject or throw when the network call fails', async () => {
    fetchSpy.mockRejectedValue(new Error('network down'));
    expect(() => trackEvent(FLOW_EVENTS.REFLECTION_SUBMITTED, { lessonId: 'lesson-1' })).not.toThrow();
  });

  it('defaults lessonId/stepIndex/success to null rather than undefined', () => {
    trackEvent(FLOW_EVENTS.DASHBOARD_VIEWED);
    const [, options] = fetchSpy.mock.calls[0];
    const body = JSON.parse(options.body);
    expect(body.lesson_id).toBeNull();
    expect(body.step_index).toBeNull();
    expect(body.success).toBeNull();
  });
});
