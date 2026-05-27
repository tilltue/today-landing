#!/usr/bin/env node
'use strict';

const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');
const SRC = path.join(ROOT, 'src');
const DIST = path.join(ROOT, 'dist');

const DEFAULT_LOCALE = 'ko';
const LOCALES = ['ko', 'en', 'ja', 'zh-Hant', 'de', 'fr', 'es'];
const PAGES = ['index', 'privacy', 'support'];
const SITE_URL = 'https://today.sb-corporation.com';

// -------- helpers --------

function loadJson(rel) {
  return JSON.parse(fs.readFileSync(path.join(SRC, rel), 'utf8'));
}

function loadText(rel) {
  return fs.readFileSync(path.join(SRC, rel), 'utf8');
}

function ensureDir(filePath) {
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
}

function copyDir(src, dst) {
  if (!fs.existsSync(src)) return;
  fs.mkdirSync(dst, { recursive: true });
  for (const entry of fs.readdirSync(src, { withFileTypes: true })) {
    const sp = path.join(src, entry.name);
    const dp = path.join(dst, entry.name);
    if (entry.isDirectory()) copyDir(sp, dp);
    else fs.copyFileSync(sp, dp);
  }
}

function copyFileIfExists(src, dst) {
  if (fs.existsSync(src)) {
    ensureDir(dst);
    fs.copyFileSync(src, dst);
  }
}

// Collect all dot-notation paths from nested object (excluding arrays/leaves of objects)
function collectKeys(obj, prefix = '') {
  const keys = [];
  for (const k of Object.keys(obj)) {
    const next = prefix ? `${prefix}.${k}` : k;
    const v = obj[k];
    if (v && typeof v === 'object' && !Array.isArray(v)) {
      keys.push(...collectKeys(v, next));
    } else {
      keys.push(next);
    }
  }
  return keys;
}

// Render {{ key.path }} and {{ screenshot:name }}
function render(template, data, locale) {
  return template.replace(/\{\{\s*([^}]+?)\s*\}\}/g, (match, raw) => {
    const expr = raw.trim();

    // {{ screenshot:name }} → locale-specific path or ko fallback
    if (expr.startsWith('screenshot:')) {
      const name = expr.slice('screenshot:'.length).trim();
      const localePath = path.join(SRC, 'assets', 'images', 'screenshots', locale, `${name}.png`);
      const koPath = path.join(SRC, 'assets', 'images', 'screenshots', DEFAULT_LOCALE, `${name}.png`);
      if (fs.existsSync(localePath)) {
        return `/assets/images/screenshots/${locale}/${name}.png`;
      }
      if (fs.existsSync(koPath)) {
        if (locale !== DEFAULT_LOCALE) {
          console.log(`  [fallback] ${locale}/${name} → ${DEFAULT_LOCALE}`);
        }
        return `/assets/images/screenshots/${DEFAULT_LOCALE}/${name}.png`;
      }
      console.warn(`  [warn] missing screenshot: ${name} (no ${locale}, no ${DEFAULT_LOCALE})`);
      return `/assets/images/screenshots/${DEFAULT_LOCALE}/${name}.png`;
    }

    // Normal dot-notation lookup
    const parts = expr.split('.');
    let v = data;
    for (const p of parts) {
      if (v == null || typeof v !== 'object') return match;
      v = v[p];
    }
    if (v == null) return match;
    return String(v);
  });
}

function pageHref(page, locale, absolute) {
  const base = absolute ? SITE_URL : '';
  const prefix = locale === DEFAULT_LOCALE ? '' : `/${locale}`;
  const tail = page === 'index' ? '/' : `/${page}/`;
  return `${base}${prefix}${tail}`;
}

function outputPath(page, locale) {
  const localeDir = locale === DEFAULT_LOCALE ? '' : locale;
  const segments = [DIST];
  if (localeDir) segments.push(localeDir);
  if (page === 'index') segments.push('index.html');
  else segments.push(page, 'index.html');
  return path.join(...segments);
}

function hreflangLinks(page) {
  const lines = LOCALES.map(l =>
    `<link rel="alternate" hreflang="${l}" href="${pageHref(page, l, true)}" />`
  );
  lines.push(`<link rel="alternate" hreflang="x-default" href="${pageHref(page, DEFAULT_LOCALE, true)}" />`);
  return lines.join('\n  ');
}

// -------- validation --------

function checkLocaleConsistency() {
  const ref = loadJson(path.join('locales', `${DEFAULT_LOCALE}.json`));
  const refKeys = collectKeys(ref);
  let failed = false;
  for (const locale of LOCALES) {
    if (locale === DEFAULT_LOCALE) continue;
    const data = loadJson(path.join('locales', `${locale}.json`));
    const keys = collectKeys(data);
    const missing = refKeys.filter(k => !keys.includes(k));
    const extra = keys.filter(k => !refKeys.includes(k));
    if (missing.length > 0) {
      console.error(`[FAIL] ${locale}.json missing ${missing.length} key(s):`);
      missing.forEach(k => console.error(`  - ${k}`));
      failed = true;
    }
    if (extra.length > 0) {
      console.warn(`[WARN] ${locale}.json has ${extra.length} extra key(s) (unused):`);
      extra.forEach(k => console.warn(`  + ${k}`));
    }
  }
  if (failed) process.exit(1);
}

// -------- build --------

function build() {
  console.log('-- today-landing build --');

  // 1. Validate locale key consistency
  checkLocaleConsistency();
  console.log('[OK] locale key consistency');

  // 2. Clean dist
  if (fs.existsSync(DIST)) fs.rmSync(DIST, { recursive: true });
  fs.mkdirSync(DIST, { recursive: true });

  // 3. Load shared templates
  const base = loadText('layouts/base.html');
  const header = loadText('layouts/partials/header.html');
  const footer = loadText('layouts/partials/footer.html');

  // 4. Generate pages
  let generated = 0;
  for (const locale of LOCALES) {
    const data = loadJson(path.join('locales', `${locale}.json`));
    for (const page of PAGES) {
      const pageTpl = loadText(path.join('pages', `${page}.html`));

      // First pass: render partials with locale data + page-level extras.
      // __locale / __page must be available here because base render() does
      // not recurse into substituted content — anything left literal in the
      // page after this pass survives into the final HTML unresolved.
      const pageData = { ...data, __locale: locale, __page: page };
      const renderedHeader = render(header, pageData, locale);
      const renderedFooter = render(footer, pageData, locale);
      const renderedPage = render(pageTpl, pageData, locale);

      // Compose final html
      const extra = {
        ...data,
        __content: renderedPage,
        __header: renderedHeader,
        __footer: renderedFooter,
        __hreflangs: hreflangLinks(page),
        __canonical: pageHref(page, locale, true),
        __lang_html: locale,
        __locale: locale,
        __page: page
      };
      const html = render(base, extra, locale);

      // Verify no unresolved placeholders
      const unresolved = html.match(/\{\{[^}]+\}\}/g);
      if (unresolved) {
        console.error(`[FAIL] unresolved placeholders in ${locale}/${page}:`);
        [...new Set(unresolved)].forEach(u => console.error(`  ${u}`));
        process.exit(1);
      }

      const out = outputPath(page, locale);
      ensureDir(out);
      fs.writeFileSync(out, html);
      generated++;
    }
  }

  // 5. Copy static assets
  copyDir(path.join(SRC, 'styles'), path.join(DIST, 'styles'));
  copyDir(path.join(SRC, 'assets'), path.join(DIST, 'assets'));

  // 6. Copy Cloudflare config files
  copyFileIfExists(path.join(ROOT, '_headers'), path.join(DIST, '_headers'));
  copyFileIfExists(path.join(ROOT, '_redirects'), path.join(DIST, '_redirects'));
  copyFileIfExists(path.join(ROOT, 'CNAME'), path.join(DIST, 'CNAME'));

  // Cloudflare Pages Functions — wrangler direct-upload requires functions/
  // to be inside the deploy dir; CF Dashboard Git mode also picks it up here.
  copyDir(path.join(ROOT, 'functions'), path.join(DIST, 'functions'));

  // 7. File count check
  const expected = LOCALES.length * PAGES.length;
  if (generated !== expected) {
    console.error(`[FAIL] generated ${generated} files, expected ${expected}`);
    process.exit(1);
  }
  console.log(`[OK] generated ${generated} HTML files (${LOCALES.length} locales × ${PAGES.length} pages)`);
}

build();
