import { mkdir, writeFile } from 'node:fs/promises';
import { spawn } from 'node:child_process';
import process from 'node:process';
import { fileURLToPath } from 'node:url';

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

const defaultThemeConfig = {
  colorBg: '#F8FAFC',
  colorPrimary: '#1E3A8A',
  palette: ['#1E3A8A', '#0F766E', '#475569'],
  base: {
    text: { fill: '#0F172A' },
  },
  title: { fill: '#0F172A' },
  desc: { fill: '#475569' },
};

function escapeXml(value) {
  return String(value)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&apos;');
}

function extractVisibleValues(syntax) {
  const listItems = [...syntax.matchAll(/^\s*-\s+label\s+(.+)\r?\n\s+desc\s+(.+)$/gim)]
    .map((match) => ({ label: match[1].trim(), desc: match[2].trim() }));
  if (listItems.length) {
    const title = listItems[0]?.desc || listItems[0]?.label;
    const cards = listItems.slice(1).flatMap(({ label, desc }) => [label, desc]);
    return [title, ...cards].filter(Boolean);
  }

  return [...syntax.matchAll(/(?:text|title|label|desc|footer|subtitle):\s*['"]([^'"\n]{3,220})['"]/gi)]
    .map((match) => match[1].trim())
    .filter((value) => !/^#[0-9a-f]{3,8}$/i.test(value))
    .filter((value, index, all) => all.indexOf(value) === index);
}

function wrapText(value, maxChars) {
  // Naive word-wrap for safe SVG <tspan> lines (no HTML).
  const words = String(value).split(/\s+/);
  const lines = [];
  let line = '';
  for (const word of words) {
    if ((line + ' ' + word).trim().length > maxChars) {
      if (line) lines.push(line);
      line = word;
    } else {
      line = (line ? line + ' ' : '') + word;
    }
  }
  if (line) lines.push(line);
  return lines.slice(0, 3); // cap at 3 lines per card
}

function fallbackSvg(syntax, width, height) {
  const values = extractVisibleValues(syntax).slice(0, 10);
  const title = values.shift() || 'Sudarshan Infographic Draft';
  const cards = values.length ? values : ['No visible text was available in the supplied specification.'];
  const cols = Math.min(cards.length, 3);
  const cardWidth = (width - 96) / cols;
  const cardMarkup = cards.map((value, index) => {
    const column = index % 3;
    const row = Math.floor(index / 3);
    const x = 24 + column * cardWidth;
    const y = 170 + row * 142;
    const lines = wrapText(value, Math.floor((cardWidth - 52) / 8));
    const labelLines = lines.map((l, li) =>
      `<tspan x="${x + 18}" dy="${li === 0 ? '1.2em' : '1.35em'}">${escapeXml(l)}</tspan>`
    ).join('');
    return `<g><rect x="${x}" y="${y}" width="${cardWidth - 16}" height="112" rx="12" fill="#F8FAFC" stroke="#CBD5E1"/><text x="${x + 18}" y="${y + 30}" font-family="Arial, sans-serif" font-size="14" font-weight="700" fill="#1E3A8A">${escapeXml(`Observation ${index + 1}`)}</text><text x="${x + 18}" y="${y + 44}" font-family="Arial, sans-serif" font-size="13" fill="#334155">${labelLines}</text></g>`;
  }).join('');
  const caveat = syntax.match(/This is synthetic test data only and must not be treated as operational intelligence\.?/i)?.[0];
  return `<svg xmlns="http://www.w3.org/2000/svg" role="img" aria-labelledby="infographic-title infographic-desc" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}"><title id="infographic-title">${escapeXml(title)}</title><desc id="infographic-desc">Sudarshan local infographic preview rendered from the supplied specification.</desc><rect width="100%" height="100%" fill="#F8FAFC"/><rect x="24" y="24" width="${width - 48}" height="116" rx="14" fill="#FFFFFF" stroke="#1E3A8A" stroke-width="2"/><text x="48" y="70" font-family="Arial, sans-serif" font-size="28" font-weight="700" fill="#0F172A">${escapeXml(title)}</text><text x="48" y="106" font-family="Arial, sans-serif" font-size="15" fill="#475569">Sudarshan local preview - rendered from the supplied specification</text>${cardMarkup}<text x="32" y="${height - 22}" font-family="Arial, sans-serif" font-size="12" fill="#475569">${escapeXml(caveat || 'Draft preview - review the quality notice before operational use.')}</text></svg>`;
}

function runAntvWorker(workerPayload, timeoutMs) {
  return new Promise((resolve, reject) => {
    const workerPath = fileURLToPath(new URL('./render_worker.mjs', import.meta.url));
    const child = spawn(process.execPath, [workerPath], { stdio: ['pipe', 'pipe', 'pipe'] });
    const stdout = [];
    const stderr = [];
    let settled = false;
    const timer = setTimeout(() => {
      if (settled) return;
      settled = true;
      child.kill('SIGKILL');
      reject(new Error(`AntV SSR timed out after ${timeoutMs}ms`));
    }, timeoutMs);
    timer.unref?.();
    child.stdout.on('data', (chunk) => stdout.push(chunk));
    child.stderr.on('data', (chunk) => stderr.push(chunk));
    child.on('error', (error) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      reject(error);
    });
    child.on('close', (code) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      if (code === 0) return resolve(Buffer.concat(stdout).toString('utf8'));
      reject(new Error(Buffer.concat(stderr).toString('utf8').trim() || `AntV worker exited with code ${code}`));
    });
    child.stdin.end(JSON.stringify(workerPayload));
  });
}

let svg;
let renderer = 'antv';
let warning = null;
const ssrTimeoutMs = Number(payload.ssrTimeoutMs || 30000);
try {
  svg = await runAntvWorker({
    syntax: payload.syntax,
    width: payload.width || 1200,
    height: payload.height || 675,
    themeConfig: payload.themeConfig || defaultThemeConfig,
  }, ssrTimeoutMs);
} catch (error) {
  // A separate child process makes this fallback a real cancellation boundary:
  // a stuck parser or renderer cannot keep the request process alive.
  renderer = 'fallback';
  warning = String(error?.message || error);
  svg = fallbackSvg(payload.syntax, payload.width || 1200, payload.height || 675);
}
if (/<foreignObject\b/i.test(svg)) {
  renderer = 'fallback';
  warning = 'AntV output contained forbidden foreignObject content; safe fallback was used.';
  svg = fallbackSvg(payload.syntax, payload.width || 1200, payload.height || 675);
}
const path = `${outputDir}/${artifactName}.svg`;
await writeFile(path, svg, 'utf8');
process.stdout.write(JSON.stringify({ path, format: 'svg', renderer, warning }));
