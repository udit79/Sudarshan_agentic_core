import React, { useEffect, useMemo, useRef, useState } from "react";
import chakraImg from "./assets/chakra.png";
import smokeBg from "./assets/smoke-bg.png";

/**
 * Scene layout (back to front):
 *  1. Nebula/smoke background — slow Ken Burns drift (pan + zoom).
 *  2. Two soft "wisp" blobs drifting on their own paths.
 *  3. A scatter of twinkling stars.
 *  4. A pulsing glow behind the chakra.
 *  5. The chakra artwork, right-aligned, rotating slowly.
 *
 * All of the above lives in <SceneLayers>, which gets rendered TWICE:
 * once normally, and once again — mirrored, distorted, tinted and
 * clipped into a strip at the bottom — as a live water reflection with
 * animated waves. Moving the mouse also stirs the fog: a soft light
 * follows the cursor and little energy ripples bloom where it moves.
 */
export default function App() {
  const stars = useMemo(() => generateStars(45), []);
  const waterHeight = 30; // vh — how tall the water strip is

  return (
    <div className="stage">
      <WaterFilter />

      <div className="scene-real">
        <SceneLayers stars={stars} smokeBg={smokeBg} chakraImg={chakraImg} />
      </div>

      <div className="pool-clip" style={{ height: `${waterHeight}vh` }}>
        <div
          className="reflection-inner"
          style={{
            top: `calc(${waterHeight}vh - 100vh)`,
            transformOrigin: `50% calc(100% - ${waterHeight}vh)`,
          }}
        >
          <SceneLayers stars={stars} smokeBg={smokeBg} chakraImg={chakraImg} />
        </div>
        <div className="water-tint" />
        <div className="water-highlight" />
        <WaveRings />
      </div>

      <div className="vignette" />
      <CursorEffects />
    </div>
  );
}

function SceneLayers({ stars, smokeBg, chakraImg }) {
  return (
    <>
      <div className="smoke-layer" style={{ backgroundImage: `url(${smokeBg})` }} />
      <div className="wisp wisp--one" />
      <div className="wisp wisp--two" />
      <div className="stars">
        {stars.map((s) => (
          <span
            key={s.id}
            className="star"
            style={{
              left: `${s.x}%`,
              top: `${s.y}%`,
              width: s.size,
              height: s.size,
              animationDelay: `${s.delay}s`,
              animationDuration: `${s.duration}s`,
            }}
          />
        ))}
      </div>
      <div className="chakra-wrap">
        <div className="chakra-glow" />
        <img src={chakraImg} alt="" className="chakra" />
      </div>
    </>
  );
}

/** A few concentric rings that periodically expand across the water's
 * top edge, like slow waves rolling in — separate from the fine
 * turbulence distortion so the motion reads clearly. */
function WaveRings() {
  const rings = [0, 1, 2];
  return (
    <div className="wave-rings">
      {rings.map((i) => (
        <span key={i} className="wave-ring" style={{ animationDelay: `${i * 2.6}s` }} />
      ))}
    </div>
  );
}

/** Hidden SVG filter that gently warps the reflection to look like it's
 * sitting on rippling water. */
function WaterFilter() {
  return (
    <svg width="0" height="0" style={{ position: "absolute" }} aria-hidden="true">
      <filter id="water-wave">
        <feTurbulence
          type="fractalNoise"
          baseFrequency="0.012 0.04"
          numOctaves="2"
          seed="7"
          result="noise"
        >
          <animate
            attributeName="baseFrequency"
            values="0.010 0.035;0.016 0.045;0.010 0.035"
            dur="9s"
            repeatCount="indefinite"
          />
        </feTurbulence>
        <feDisplacementMap in="SourceGraphic" in2="noise" scale="22" xChannelSelector="R" yChannelSelector="G" />
      </filter>
    </svg>
  );
}

/** A soft light that eases toward the cursor, plus small ripple bursts
 * spawned as the mouse moves — makes the whole background feel alive
 * and responsive without replacing the real cursor. */
function CursorEffects() {
  const glowRef = useRef(null);
  const [ripples, setRipples] = useState([]);
  const target = useRef({ x: -9999, y: -9999 });
  const eased = useRef({ x: -9999, y: -9999 });
  const lastSpawn = useRef(0);

  useEffect(() => {
    const handleMove = (e) => {
      target.current = { x: e.clientX, y: e.clientY };
      const now = performance.now();
      if (now - lastSpawn.current > 130) {
        lastSpawn.current = now;
        const id = now + Math.random();
        setRipples((cur) => [...cur.slice(-11), { id, x: e.clientX, y: e.clientY }]);
      }
    };
    window.addEventListener("mousemove", handleMove);

    let raf;
    const tick = () => {
      eased.current.x += (target.current.x - eased.current.x) * 0.08;
      eased.current.y += (target.current.y - eased.current.y) * 0.08;
      if (glowRef.current) {
        glowRef.current.style.transform = `translate(${eased.current.x}px, ${eased.current.y}px) translate(-50%, -50%)`;
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);

    return () => {
      window.removeEventListener("mousemove", handleMove);
      cancelAnimationFrame(raf);
    };
  }, []);

  return (
    <div className="cursor-fx-layer">
      <div ref={glowRef} className="cursor-glow-follow" />
      {ripples.map((r) => (
        <span
          key={r.id}
          className="cursor-ripple"
          style={{ left: r.x, top: r.y }}
          onAnimationEnd={() => setRipples((cur) => cur.filter((x) => x.id !== r.id))}
        />
      ))}
    </div>
  );
}

function generateStars(count) {
  return Array.from({ length: count }).map((_, i) => ({
    id: i,
    x: Math.random() * 100,
    y: Math.random() * 65,
    size: `${(Math.random() * 2 + 1).toFixed(1)}px`,
    delay: (Math.random() * 6).toFixed(2),
    duration: (Math.random() * 3 + 2.5).toFixed(2),
  }));
}
