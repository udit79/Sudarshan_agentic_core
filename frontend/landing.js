(() => {
  const backdrop = document.querySelector('.landing-backdrop');
  if (!backdrop) return;

  let frame;
  window.addEventListener('pointermove', (event) => {
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    cancelAnimationFrame(frame);
    frame = requestAnimationFrame(() => {
      const x = (event.clientX / window.innerWidth - 0.5) * 2;
      const y = (event.clientY / window.innerHeight - 0.5) * 2;
      backdrop.style.transform = `translate3d(${x * -4}px, ${y * -3}px, 0)`;
    });
  }, { passive: true });

  const revealItems = document.querySelectorAll('.capability-card, .workflow-panel');
  if (!('IntersectionObserver' in window)) return;
  const observer = new IntersectionObserver((entries, currentObserver) => {
    entries.forEach((entry) => {
      if (!entry.isIntersecting) return;
      entry.target.classList.add('reveal');
      currentObserver.unobserve(entry.target);
    });
  }, { threshold: 0.12 });
  revealItems.forEach((item) => observer.observe(item));
})();
