import { useEffect, useRef, useState } from 'react';
export function useLandingMotion() {
  const root = useRef<HTMLDivElement>(null);
  const [reduced, setReduced] = useState(
    () => window.matchMedia('(prefers-reduced-motion: reduce)').matches
  );
  const [paused, setPaused] = useState(() => {
    try {
      return localStorage.getItem('conatus.motion') === 'paused';
    } catch {
      return false;
    }
  });
  const enabled = !reduced && !paused;
  useEffect(() => {
    const query = window.matchMedia('(prefers-reduced-motion: reduce)');
    const change = () => setReduced(query.matches);
    query.addEventListener('change', change);
    return () => query.removeEventListener('change', change);
  }, []);
  useEffect(() => {
    try {
      localStorage.setItem('conatus.motion', paused ? 'paused' : 'enabled');
    } catch {
      /* Session preference still applies. */
    }
  }, [paused]);
  useEffect(() => {
    const element = root.current;
    if (!element) return;
    const targets = Array.from(
      element.querySelectorAll<HTMLElement>('[data-reveal]')
    );
    if (!enabled) {
      targets.forEach((target) => target.classList.remove('reveal-pending'));
      return;
    }
    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            entry.target.classList.remove('reveal-pending');
            entry.target.classList.add('is-revealed');
            observer.unobserve(entry.target);
          }
        });
      },
      { threshold: 0.08 }
    );
    targets.forEach((target) => {
      if (target.getBoundingClientRect().top > window.innerHeight) {
        target.classList.add('reveal-pending');
        observer.observe(target);
      }
    });
    const hero = element.querySelector<HTMLElement>('.c-hero');
    const art = element.querySelector<HTMLElement>('.c-hero-art');
    let frame = 0;
    const move = (event: PointerEvent) => {
      if (event.pointerType !== 'mouse' || !hero || !art) return;
      const rect = hero.getBoundingClientRect();
      const x = (event.clientX - rect.left) / rect.width - 0.5,
        y = (event.clientY - rect.top) / rect.height - 0.5;
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        art.style.setProperty('--parallax-x', `${x * 16}px`);
        art.style.setProperty('--parallax-y', `${y * 12}px`);
      });
    };
    const reset = () => {
      cancelAnimationFrame(frame);
      art?.style.setProperty('--parallax-x', '0px');
      art?.style.setProperty('--parallax-y', '0px');
    };
    hero?.addEventListener('pointermove', move);
    hero?.addEventListener('pointerleave', reset);
    return () => {
      observer.disconnect();
      cancelAnimationFrame(frame);
      targets.forEach((target) => target.classList.remove('reveal-pending'));
      hero?.removeEventListener('pointermove', move);
      hero?.removeEventListener('pointerleave', reset);
      reset();
    };
  }, [enabled]);
  return {
    root,
    enabled,
    reduced,
    paused,
    toggle: () => setPaused((value) => !value),
  };
}
