import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { prefersReducedMotion, staggerFadeUp, animateCountUp, animateBarFill, popIn } from './animations';

function mockMatchMedia(reduced) {
  window.matchMedia = vi.fn().mockImplementation((query) => ({
    matches: reduced,
    media: query,
    addEventListener: () => {},
    removeEventListener: () => {},
  }));
}

describe('animations', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('prefersReducedMotion reflects the media query', () => {
    mockMatchMedia(true);
    expect(prefersReducedMotion()).toBe(true);
    mockMatchMedia(false);
    expect(prefersReducedMotion()).toBe(false);
  });

  it('prefersReducedMotion never throws when matchMedia is unavailable (this project\'s default jsdom test env)', () => {
    const original = window.matchMedia;
    // eslint-disable-next-line no-undefined
    window.matchMedia = undefined;
    expect(() => prefersReducedMotion()).not.toThrow();
    expect(prefersReducedMotion()).toBe(false);
    window.matchMedia = original;
  });

  it('animateCountUp snaps straight to the final value when motion is reduced', () => {
    mockMatchMedia(true);
    const el = document.createElement('span');
    animateCountUp(el, 42, { suffix: '%' });
    expect(el.textContent).toBe('42%');
  });

  it('animateCountUp formats decimals correctly when reduced', () => {
    mockMatchMedia(true);
    const el = document.createElement('span');
    animateCountUp(el, 62.5, { decimals: 1, suffix: '%' });
    expect(el.textContent).toBe('62.5%');
  });

  it('animateBarFill snaps the width directly when motion is reduced', () => {
    mockMatchMedia(true);
    const el = document.createElement('div');
    animateBarFill(el, 75);
    expect(el.style.width).toBe('75%');
  });

  it('animateBarFill clamps out-of-range percentages', () => {
    mockMatchMedia(true);
    const el = document.createElement('div');
    animateBarFill(el, 150);
    expect(el.style.width).toBe('100%');
    animateBarFill(el, -20);
    expect(el.style.width).toBe('0%');
  });

  it('none of the helpers throw when called on null/empty targets', () => {
    mockMatchMedia(true);
    expect(() => staggerFadeUp(null)).not.toThrow();
    expect(() => staggerFadeUp([])).not.toThrow();
    expect(() => animateCountUp(null, 5)).not.toThrow();
    expect(() => animateBarFill(null, 5)).not.toThrow();
    expect(() => popIn(null)).not.toThrow();
  });

  it('does not throw when motion is not reduced (real anime.js path)', () => {
    mockMatchMedia(false);
    const el = document.createElement('div');
    document.body.appendChild(el);
    expect(() => animateBarFill(el, 60)).not.toThrow();
    expect(() => popIn(el)).not.toThrow();
    const span = document.createElement('span');
    expect(() => animateCountUp(span, 10)).not.toThrow();
  });
});
