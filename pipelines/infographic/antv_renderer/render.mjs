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

function fallbackSvg(syntax, width, height) {
  const values = extractVisibleValues(syntax).slice(0, 10);
  const title = values.shift() || 'Sudarshan Infographic Draft';
  const cards = values.length ? values : ['No visible text was available in the supplied specification.'];
  const cardWidth = (width - 96) / Math.min(cards.length, 3);
  const cardMarkup = cards.map((value, index) => {
    const column = index % 3;
    const row = Math.floor(index / 3);
    const x = 24 + column * cardWidth;
    const y = 170 + row * 142;
    return `<g><rect x="${x}" y="${y}" width="${cardWidth - 16}" height="112" rx="12" fill="#F8FAFC" stroke="#CBD5E1"/><text x="${x + 18}" y="${y + 30}" font-family="Arial, sans-serif" font-size="14" font-weight="700" fill="#1E3A8A">${escapeXml(`Observation ${index + 1}`)}</text><foreignObject x="${x + 18}" y="${y + 44}" width="${cardWidth - 52}" height="58"><div xmlns="http://www.w3.org/1999/xhtml" style="font: 16px Arial,sans-serif;line-height:1.35;color:#334155;">${escapeXml(value)}</div></foreignObject></g>`;
  }).join('');
  const caveat = syntax.match(/This is synthetic test data only and must not be treated as operational intelligence\.?/i)?.[0];
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}"><rect width="100%" height="100%" fill="#F8FAFC"/><rect x="24" y="24" width="${width - 48}" height="116" rx="14" fill="#FFFFFF" stroke="#1E3A8A" stroke-width="2"/><text x="48" y="70" font-family="Arial, sans-serif" font-size="28" font-weight="700" fill="#0F172A">${escapeXml(title)}</text><text x="48" y="106" font-family="Arial, sans-serif" font-size="15" fill="#475569">Sudarshan local preview - rendered from the supplied specification</text>${cardMarkup}<text x="32" y="${height - 22}" font-family="Arial, sans-serif" font-size="12" fill="#475569">${escapeXml(caveat || 'Draft preview - review the quality notice before operational use.')}</text></svg>`;
}

let svg;
try {
  svg = await renderToString(payload.syntax, {
    width: payload.width || 1200,
    height: payload.height || 675,
  });
} catch {
  // Keep local demos usable when a generated AntV layout exceeds SSR's
  // parser/render timeout. This fallback is deterministic and contains no
  // generated claims beyond text already present in the supplied syntax.
  svg = fallbackSvg(payload.syntax, payload.width || 1200, payload.height || 675);
}
const path = `${outputDir}/${artifactName}.svg`;
await writeFile(path, svg, 'utf8');
process.stdout.write(JSON.stringify({ path, format: 'svg' }));
