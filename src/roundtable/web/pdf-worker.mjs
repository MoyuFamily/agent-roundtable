/** Isolated PDF renderer. No package lookup/download is performed at request time. */
import { createRequire } from 'node:module';
import { existsSync, readFileSync } from 'node:fs';

const require = createRequire(import.meta.url);

try {
  const rendererRequire = createRequire(require.resolve('md-to-pdf'));
  const { mdToPdf } = require('md-to-pdf');
  const { Renderer } = rendererRequire('marked');
  const puppeteer = rendererRequire('puppeteer');
  const executablePath = process.env.PUPPETEER_EXECUTABLE_PATH || puppeteer.executablePath();
  if (!existsSync(executablePath)) throw new Error('Chromium is unavailable; configure PUPPETEER_EXECUTABLE_PATH.');

  if (process.argv[2] === '--check') {
    process.stdout.write(JSON.stringify({ available: true }) + '\n');
  } else {
    const escape = (value) => String(value || '').replace(/[&<>"]/g, (c) => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;',
    })[c]);
    const renderer = new Renderer();
    // Discussion content is evidence, never executable HTML or a remote resource request.
    renderer.html = (html) => escape(html);
    renderer.image = (_href, _title, text) => escape(text);
    renderer.link = (_href, _title, text) => text;
    const result = await mdToPdf({ content: readFileSync(process.argv[2], 'utf8') }, {
      basedir: process.cwd(),
      dest: process.argv[3],
      document_title: 'Roundtable review',
      marked_options: { renderer },
      launch_options: {
        executablePath,
        args: process.env.ROUNDTABLE_PDF_NO_SANDBOX === '1' ? ['--no-sandbox'] : [],
      },
      pdf_options: { format: 'A4', margin: '20mm', printBackground: true },
    });
    if (!result?.content?.length) throw new Error('Renderer produced an empty PDF.');
  }
} catch (error) {
  process.stderr.write(String(error?.message || error) + '\n');
  process.exit(1);
}
