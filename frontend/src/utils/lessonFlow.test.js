import { describe, it, expect, beforeEach } from 'vitest';
import { FLOW_STEPS, markFlowStepComplete, isFlowStepComplete, getNextStep } from './lessonFlow';

beforeEach(() => {
  localStorage.clear();
});

describe('lessonFlow', () => {
  it('starts with every step incomplete', () => {
    expect(isFlowStepComplete('lesson-1', 'quiz')).toBe(false);
  });

  it('marks a step complete and persists it', () => {
    markFlowStepComplete('lesson-1', 'quiz');
    expect(isFlowStepComplete('lesson-1', 'quiz')).toBe(true);
  });

  it('scopes completion per lesson', () => {
    markFlowStepComplete('lesson-1', 'quiz');
    expect(isFlowStepComplete('lesson-2', 'quiz')).toBe(false);
  });

  it('does not throw when lessonId is missing', () => {
    expect(() => markFlowStepComplete(null, 'quiz')).not.toThrow();
    expect(isFlowStepComplete(null, 'quiz')).toBe(false);
  });

  it('walks the fixed step order via getNextStep', () => {
    expect(getNextStep('lesson', 'lesson-1')).toEqual({
      key: 'vocabulary', label: 'Vocabulary', path: '/lesson/lesson-1/vocabulary',
    });
    expect(getNextStep('debate-persona', 'lesson-1').key).toBe('reflection');
  });

  it('returns null after the last step', () => {
    expect(getNextStep('mastery-dashboard', null)).toBeNull();
  });

  it('returns null for an unknown current step rather than throwing', () => {
    expect(getNextStep('not-a-real-step', 'lesson-1')).toBeNull();
  });

  it('every step resolves to a lesson-scoped or global path without crashing', () => {
    for (const step of FLOW_STEPS) {
      expect(() => step.path('lesson-1')).not.toThrow();
    }
  });
});
