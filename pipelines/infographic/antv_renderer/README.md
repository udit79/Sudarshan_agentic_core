# AntV renderer setup

Install the pinned renderer dependency from this directory:

```bash
npm install
```

The Python `AntVInfographicRenderer` invokes `render.mjs`, which calls
`@antv/infographic/ssr.renderToString()` and writes an SVG artifact. The
renderer receives only validated AntV syntax from the Python pipeline.
