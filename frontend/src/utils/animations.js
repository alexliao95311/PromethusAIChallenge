// Shared anime.js (v4) motion helpers for Lesson Mode.
//
// Used deliberately in a few places that mark real progress -- the mastery
// dashboard's numbers/bars, the flow stepper's steps, the lesson hub's
// entrance, and the reflection page's feedback reveal -- not scattered
// across every element. Every helper respects `prefers-reduced-motion` by
// snapping straight to the end state instead of animating.

import { animate, stagger } from 'animejs';

export function prefersReducedMotion() {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return false;
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

// Staggered fade-up entrance for a list of elements (a NodeList, an array
// of refs, or a CSS selector string).
export function staggerFadeUp(targets, { delay = 0, staggerMs = 60 } = {}) {
  if (!targets || (typeof targets !== 'string' && targets.length === 0)) return;
  if (prefersReducedMotion()) {
    animate(targets, { opacity: 1, translateY: 0, duration: 1 });
    return;
  }
  animate(targets, {
    opacity: [0, 1],
    translateY: [14, 0],
    delay: stagger(staggerMs, { start: delay }),
    duration: 520,
    ease: 'outQuart',
  });
}

// Animates a number from 0 (or `from`) up to `value`, writing the
// formatted result into the element's textContent on every frame.
export function animateCountUp(el, value, { from = 0, duration = 900, suffix = '', decimals = 0 } = {}) {
  if (!el) return;
  if (prefersReducedMotion() || !Number.isFinite(value)) {
    el.textContent = `${value.toFixed(decimals)}${suffix}`;
    return;
  }
  const counter = { value: from };
  animate(counter, {
    value,
    duration,
    ease: 'outCubic',
    onUpdate: () => {
      el.textContent = `${counter.value.toFixed(decimals)}${suffix}`;
    },
  });
}

// Animates a mastery/progress bar's fill width from 0 to `percent`.
export function animateBarFill(el, percent, { duration = 900, delay = 0 } = {}) {
  if (!el) return;
  const clamped = Math.max(0, Math.min(100, percent));
  if (prefersReducedMotion()) {
    el.style.width = `${clamped}%`;
    return;
  }
  animate(el, {
    width: [`0%`, `${clamped}%`],
    duration,
    delay,
    ease: 'outExpo',
  });
}

// A small "pop" for a marker that just became complete/active (e.g. a
// stepper checkmark).
export function popIn(el) {
  if (!el || prefersReducedMotion()) return;
  animate(el, {
    scale: [0.6, 1.15, 1],
    duration: 420,
    ease: 'outBack',
  });
}

// A 3D card-flip reveal: the card turns from edge-on to face-on, so
// whatever content is already in the DOM when this runs (React has already
// swapped it) appears to have been "turned to". Needs `perspective` set on
// an ancestor for the rotation to read as 3D rather than a flat squish.
export function flipCard(el, { direction = 1 } = {}) {
  if (!el) return;
  if (prefersReducedMotion()) {
    el.style.transform = '';
    return;
  }
  animate(el, {
    rotateY: [90 * direction, 0],
    duration: 480,
    ease: 'outQuint',
  });
}
