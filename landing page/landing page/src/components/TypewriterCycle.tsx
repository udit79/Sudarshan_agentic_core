import { useState, useEffect } from 'react';

const PHRASES = [
  "Sudarshan",
  "understands your request",
  "retrieves the right context",
  "coordinates specialized agents",
  "executes complex workflows",
  "remembers what matters"
];

export function TypewriterCycle() {
  const [phraseIndex, setPhraseIndex] = useState(0);
  const [charIndex, setCharIndex] = useState(0);
  const [isDeleting, setIsDeleting] = useState(false);
  const [prefersReducedMotion, setPrefersReducedMotion] = useState(false);

  useEffect(() => {
    const mediaQuery = window.matchMedia('(prefers-reduced-motion: reduce)');
    setPrefersReducedMotion(mediaQuery.matches);
    const handler = (e: MediaQueryListEvent) => setPrefersReducedMotion(e.matches);
    mediaQuery.addEventListener('change', handler);
    return () => mediaQuery.removeEventListener('change', handler);
  }, []);

  useEffect(() => {
    if (prefersReducedMotion) return;

    let timer: number;
    const currentPhrase = PHRASES[phraseIndex];

    if (!isDeleting && charIndex === currentPhrase.length) {
      timer = window.setTimeout(() => setIsDeleting(true), 1200 + Math.random() * 600);
    } else if (isDeleting && charIndex === 0) {
      setIsDeleting(false);
      setPhraseIndex((prev) => (prev + 1) % PHRASES.length);
    } else {
      const typeSpeed = isDeleting ? 30 + Math.random() * 10 : 60 + Math.random() * 30;
      timer = window.setTimeout(() => {
        setCharIndex((prev) => prev + (isDeleting ? -1 : 1));
      }, typeSpeed);
    }

    return () => clearTimeout(timer);
  }, [charIndex, isDeleting, phraseIndex, prefersReducedMotion]);

  useEffect(() => {
    if (!prefersReducedMotion) return;
    const timer = setInterval(() => {
      setPhraseIndex((prev) => (prev + 1) % PHRASES.length);
    }, 3000);
    return () => clearInterval(timer);
  }, [prefersReducedMotion]);

  if (prefersReducedMotion) {
    return (
      <span className="inline-block transition-opacity duration-500 min-h-[1.5em] text-text-primary">
        {PHRASES[phraseIndex]}
      </span>
    );
  }

  return (
    <span className="inline-block min-h-[1.5em] text-text-primary">
      {PHRASES[phraseIndex].substring(0, charIndex)}
      <span className="inline-block w-[3px] h-[1.2em] bg-cyan-highlight ml-[2px] align-middle animate-pulse"></span>
    </span>
  );
}
