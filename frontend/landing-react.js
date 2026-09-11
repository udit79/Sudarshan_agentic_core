(() => {
  const root = document.getElementById('robot-react-root');
  if (!root || !window.React || !window.ReactDOM) return;

  const { useEffect, useRef } = window.React;

  function RobotModel() {
    const modelRef = useRef(null);
    const pointerRef = useRef({ x: 0, y: 0 });
    const frameRef = useRef(null);

    useEffect(() => {
      const model = modelRef.current;
      if (!model) return undefined;

      const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
      const renderMotion = () => {
        frameRef.current = null;
        const { x, y } = pointerRef.current;
        model.style.setProperty('--robot-drift-x', `${x * 10}px`);
        model.style.setProperty('--robot-drift-y', `${y * 8}px`);
        model.style.setProperty('--robot-tilt-x', `${x * 4}deg`);
        model.style.setProperty('--robot-tilt-y', `${y * -4}deg`);
        model.style.setProperty('--robot-depth', `${Math.abs(x) * 4}px`);
      };
      const scheduleMotion = () => {
        if (frameRef.current === null) frameRef.current = window.requestAnimationFrame(renderMotion);
      };
      const update = (event) => {
        if (reduceMotion.matches) return;
        pointerRef.current = {
          x: (event.clientX / window.innerWidth - 0.5) * 2,
          y: (event.clientY / window.innerHeight - 0.5) * 2,
        };
        scheduleMotion();
      };
      const reset = () => {
        pointerRef.current = { x: 0, y: 0 };
        scheduleMotion();
      };

      window.addEventListener('pointermove', update, { passive: true });
      window.addEventListener('blur', reset);
      return () => {
        window.removeEventListener('pointermove', update);
        window.removeEventListener('blur', reset);
        if (frameRef.current !== null) window.cancelAnimationFrame(frameRef.current);
      };
    }, []);

    return window.React.createElement(
      'div',
      { ref: modelRef, className: 'robot-react-model', 'aria-hidden': 'true' },
      window.React.createElement('div', { className: 'robot-react-bloom' }),
      window.React.createElement('img', {
        src: 'assets/sudarshan-robot.png',
        alt: 'Sudarshan AI robot assistant',
        className: 'robot-image',
      }),
      window.React.createElement('span', { className: 'robot-react-spark' }),
    );
  }

  window.ReactDOM.createRoot(root).render(window.React.createElement(RobotModel));
})();
