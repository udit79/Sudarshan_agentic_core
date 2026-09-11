import React from "react";
import chakraImg from "./assets/chakra-transparent.png";
import smokeBg from "./assets/smoke-bg.png";

/**
 * Scene layout (back to front):
 *  1. Nebula/smoke background — slow Ken Burns drift (pan + zoom) so the
 *     whole frame feels alive, not a static photo.
 *  2. Two extra soft "wisp" blobs, blurred and screen-blended, drifting
 *     on their own paths — reinforces the smoke actually moving rather
 *     than just the base image scaling.
 *  3. A scatter of twinkling star points for depth.
 *  4. A soft pulsing glow sitting behind the chakra.
 *  5. The chakra artwork itself, right-aligned, rotating slowly.
 *  6. A faint, blurred, upside-down reflection of the chakra sitting on
 *     the reflective floor already present in the background art, so
 *     the two images read as one integrated scene.
 *  7. A subtle vignette to blend the chakra's edges into the backdrop.
 */
export default function App() {
  const stars = React.useMemo(() => generateStars(45), []);

  return (
    <div className="scene">
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
        <img src={chakraImg} alt="" className="chakra chakra--main" />
        <img src={chakraImg} alt="" className="chakra chakra--reflection" aria-hidden="true" />
      </div>

      <div className="vignette" />
    </div>
  );
}

function generateStars(count) {
  return Array.from({ length: count }).map((_, i) => ({
    id: i,
    x: Math.random() * 100,
    y: Math.random() * 65, // keep stars out of the floor area
    size: `${(Math.random() * 2 + 1).toFixed(1)}px`,
    delay: (Math.random() * 6).toFixed(2),
    duration: (Math.random() * 3 + 2.5).toFixed(2),
  }));
}
