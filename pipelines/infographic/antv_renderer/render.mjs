import { mkdir, writeFile } from 'node:fs/promises';
import process from 'node:process';
import { renderToString } from '@antv/infographic/ssr';

const chunks = [];
for await (const chunk of process.stdin) chunks.push(chunk);
const input = Buffer.concat(chunks).toString('utf8');
const payload = JSON.parse(input);
if (typeof payload.syntax !== 'string' || !payload.syntax.trim().startsWith('infographic')) {
  throw new Error('syntax must start with the AntV infographic directive');
}

const outputDir = payload.outputDir;
const artifactName = String(payload.artifactName || 'infographic').replace(/[^A-Za-z0-9._-]/g, '-');
await mkdir(outputDir, { recursive: true });
const svg = await renderToString(payload.syntax, {
  width: payload.width || 1200,
  height: payload.height || 675,
});
const path = `${outputDir}/${artifactName}.svg`;
await writeFile(path, svg, 'utf8');
process.stdout.write(JSON.stringify({ path, format: 'svg' }));
