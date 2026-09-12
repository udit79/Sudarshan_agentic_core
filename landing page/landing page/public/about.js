(function () {
  const revealItems = document.querySelectorAll('.about-reveal');
  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  if (reducedMotion || !('IntersectionObserver' in window)) {
    revealItems.forEach((item) => item.classList.add('is-visible'));
  } else {
    const observer = new IntersectionObserver((entries, currentObserver) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return;
        entry.target.classList.add('is-visible');
        currentObserver.unobserve(entry.target);
      });
    }, { threshold: 0.14 });

    revealItems.forEach((item) => observer.observe(item));
  }

  const photo = document.querySelector('.team-photo');
  const modal = document.querySelector('#team-modal');
  const closeButton = modal?.querySelector('.team-modal-close');
  const backdrop = modal?.querySelector('.team-modal-backdrop');
  let lastFocusedElement = null;

  if (!photo || !modal || !closeButton || !backdrop) return;

  const closeModal = () => {
    modal.hidden = true;
    photo.setAttribute('aria-expanded', 'false');
    document.body.classList.remove('team-modal-open');
    lastFocusedElement?.focus();
  };

  const openModal = () => {
    lastFocusedElement = document.activeElement;
    modal.hidden = false;
    photo.setAttribute('aria-expanded', 'true');
    document.body.classList.add('team-modal-open');
    closeButton.focus();
  };

  photo.addEventListener('click', openModal);
  closeButton.addEventListener('click', closeModal);
  backdrop.addEventListener('click', closeModal);
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && !modal.hidden) closeModal();
  });
})();
