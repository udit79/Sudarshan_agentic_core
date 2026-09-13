import process from 'node:process';
import { renderToString } from '@antv/infographic/ssr';

const chunks = [];
for await (const chunk of process.stdin) chunks.push(chunk);
const payload = JSON.parse(Buffer.concat(chunks).toString('utf8'));
if (typeof payload.syntax !== 'string' || !payload.syntax.trim().startsWith('infographic')) {
  throw new Error('syntax must start with the AntV infographic directive');
}

try {
  const svg = await renderToString(payload.syntax, {
    width: payload.width || 1200,
    height: payload.height || 675,
    themeConfig: payload.themeConfig,
  });
  process.stdout.write(svg);
} catch (error) {
  process.stderr.write(String(error?.stack || error));
  process.exitCode = 1;
}
