import { mkdir, writeFile, readFile, stat } from 'node:fs/promises';
import { existsSync } from 'node:fs';
import path from 'node:path';

const BASE = 'https://www.klayout.de';
const ROOT = '/doc-qt5/';
const START_PATHS = [
  '/doc-qt5/programming/index.html',
  '/doc-qt5/code/index.html',
];

const OUT_DIR = path.resolve('klayout-python/references/docs_html');
const MAX_PAGES = 5000; // safety
const CONCURRENCY = 6;

function normalizeUrl(u) {
  try {
    const url = new URL(u, BASE);
    // stay on same host
    if (url.origin !== BASE) return null;
    if (!url.pathname.startsWith(ROOT)) return null;

    // keep only programming/* and code/*
    if (!(url.pathname.startsWith('/doc-qt5/programming/') || url.pathname.startsWith('/doc-qt5/code/'))) {
      return null;
    }

    // only html pages
    if (!url.pathname.endsWith('.html')) return null;

    // drop fragments
    url.hash = '';
    return url.toString();
  } catch {
    return null;
  }
}

function urlToLocalPath(urlStr) {
  const url = new URL(urlStr);
  const p = url.pathname.replace(/^\/doc-qt5\//, '');
  return path.join(OUT_DIR, p);
}

function extractLinks(html, baseUrl) {
  // naive but effective for href="..." / href='...'
  const links = new Set();
  const re = /href\s*=\s*("([^"]+)"|'([^']+)')/gi;
  let m;
  while ((m = re.exec(html))) {
    const href = m[2] ?? m[3];
    if (!href) continue;
    const abs = normalizeUrl(new URL(href, baseUrl).toString());
    if (abs) links.add(abs);
  }
  return [...links];
}

async function ensureDirFor(filePath) {
  await mkdir(path.dirname(filePath), { recursive: true });
}

async function alreadyHave(filePath) {
  if (!existsSync(filePath)) return false;
  try {
    const s = await stat(filePath);
    return s.size > 0;
  } catch {
    return false;
  }
}

async function fetchOne(url) {
  const outPath = urlToLocalPath(url);
  if (await alreadyHave(outPath)) {
    const html = await readFile(outPath, 'utf8');
    return { url, outPath, html, fromCache: true };
  }

  const res = await fetch(url, {
    headers: {
      'user-agent': 'openclaw-doc-mirror/1.0 (+offline skill build)'
    }
  });
  if (!res.ok) throw new Error(`HTTP ${res.status} for ${url}`);
  const html = await res.text();
  await ensureDirFor(outPath);
  await writeFile(outPath, html, 'utf8');
  return { url, outPath, html, fromCache: false };
}

async function main() {
  await mkdir(OUT_DIR, { recursive: true });

  const queue = [];
  const seen = new Set();
  for (const p of START_PATHS) {
    const u = normalizeUrl(BASE + p);
    if (u) {
      queue.push(u);
      seen.add(u);
    }
  }

  const errors = [];
  let done = 0;

  async function worker() {
    while (queue.length && done < MAX_PAGES) {
      const url = queue.shift();
      if (!url) return;
      try {
        const { html } = await fetchOne(url);
        done++;
        const links = extractLinks(html, url);
        for (const l of links) {
          if (!seen.has(l)) {
            seen.add(l);
            queue.push(l);
          }
        }
        if (done % 100 === 0) {
          console.log(`mirrored ${done} pages (queue ${queue.length}, seen ${seen.size})`);
        }
      } catch (e) {
        errors.push({ url, error: String(e) });
      }
    }
  }

  const workers = Array.from({ length: CONCURRENCY }, () => worker());
  await Promise.all(workers);

  await writeFile(
    path.resolve('klayout-python/references/docs_html/manifest.json'),
    JSON.stringify({
      base: BASE,
      root: ROOT,
      start: START_PATHS,
      pages: [...seen].length,
      done,
      errors,
      generatedAt: new Date().toISOString(),
    }, null, 2),
    'utf8'
  );

  console.log(`Done. mirrored=${done}, discovered=${seen.size}, errors=${errors.length}`);
  if (errors.length) {
    console.log('First errors:', errors.slice(0, 10));
  }
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
