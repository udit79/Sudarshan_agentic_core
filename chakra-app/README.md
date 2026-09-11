# Revolving Chakra Scene

A full React (Vite) app that layers your chakra artwork over the nebula
background and brings the whole frame to life:

- The nebula/smoke background slowly zooms and pans (Ken Burns style).
- Two extra blurred, colored "wisp" blobs drift independently on top of it,
  so the smoke reads as genuinely moving, not just the photo scaling.
- A scatter of small stars twinkle at random.
- The chakra sits on the right side of the frame, rotating slowly, with a
  soft pulsing glow behind it.
- A faint, blurred, upside-down reflection of the chakra sits near the
  bottom so it blends into the reflective floor already in the background
  art.

## Run it

```bash
npm install
npm run dev
```

Then open the local URL Vite prints (usually `http://localhost:5173`).

## Build for production

```bash
npm run build
npm run preview
```

## Files

```
chakra-app/
├── index.html
├── package.json
├── vite.config.js
├── README.md
└── src/
    ├── main.jsx
    ├── App.jsx
    ├── App.css
    └── assets/
        ├── chakra.png      # your mandala artwork (transparent PNG)
        └── smoke-bg.png    # the nebula/smoke floor background
```

## Tweaking

- **Rotation speed**: change `50s` in `.chakra--main` / `.chakra--reflection`
  in `App.css` (lower = faster).
- **Chakra size/position**: edit `.chakra-wrap` (`width`, `height`, `right`).
- **Smoke drift speed**: change the `34s` duration on `.smoke-layer`
  (`kenburns` animation).
- **Star count**: change `generateStars(45)` in `App.jsx`.
