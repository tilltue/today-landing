#!/usr/bin/env node
'use strict';

const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');
const SRC = path.join(ROOT, 'src');
const DIST = path.join(ROOT, 'dist');

const DEFAULT_LOCALE = 'ko';
const LOCALES = ['ko', 'en', 'ja', 'zh-Hant', 'de', 'fr', 'es'];
const PAGES = ['index', 'privacy', 'privacy-android', 'support'];
// 스토리(콘텐츠)는 ko/en/ja 만 발행 — locales/*.json 패리티 검사와 무관하게
// src/stories/strings.json 의 문자열을 쓴다.
const STORY_LOCALES = ['ko', 'en', 'ja'];
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

// -------- stories --------

function parseFrontMatter(text) {
  const m = text.match(/^---\n([\s\S]*?)\n---\n?/);
  if (!m) throw new Error('front matter missing');
  const meta = {};
  for (const line of m[1].split('\n')) {
    const i = line.indexOf(':');
    if (i > 0) meta[line.slice(0, i).trim()] = line.slice(i + 1).trim();
  }
  for (const k of ['title', 'summary', 'date']) {
    if (!meta[k]) throw new Error(`front matter key missing: ${k}`);
  }
  return { meta, body: text.slice(m[0].length) };
}

function escapeHtml(s) {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function inlineMd(s) {
  return escapeHtml(s)
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2">$1</a>');
}

// 최소 마크다운 렌더러 (zero-dep): h2/h3, p, ul, strong, link, image 만 지원.
function renderMarkdown(md) {
  const out = [];
  let list = false;
  let para = [];
  const flush = () => {
    if (para.length) { out.push(`<p>${inlineMd(para.join(' '))}</p>`); para = []; }
  };
  const closeList = () => { if (list) { out.push('</ul>'); list = false; } };
  for (const raw of md.split('\n')) {
    const line = raw.trimEnd();
    if (!line.trim()) { flush(); closeList(); continue; }
    if (line.startsWith('### ')) { flush(); closeList(); out.push(`<h3>${inlineMd(line.slice(4))}</h3>`); }
    else if (line.startsWith('## ')) { flush(); closeList(); out.push(`<h2>${inlineMd(line.slice(3))}</h2>`); }
    else if (line.startsWith('- ')) {
      flush();
      if (!list) { out.push('<ul>'); list = true; }
      out.push(`<li>${inlineMd(line.slice(2))}</li>`);
    } else if (line.startsWith('![')) {
      flush(); closeList();
      const im = line.match(/^!\[([^\]]*)\]\(([^)]+)\)$/);
      if (im) {
        const alt = escapeHtml(im[1]);
        const caption = im[1] ? `\n  <figcaption>${alt}</figcaption>` : '';
        out.push(`<figure class="story__figure">\n  <img src="${im[2]}" alt="${alt}" loading="lazy">${caption}\n</figure>`);
      }
    } else {
      para.push(line);
    }
  }
  flush(); closeList();
  return out.join('\n');
}

// 스토리 헤더 이미지 — src/assets/images/stories/<slug>.jpg 가 있으면 자동 사용.
// 없으면 빈 문자열이라 이미지 없는 글도 그대로 빌드된다 (front matter 강제 안 함).
function storyHeroSrc(slug) {
  const rel = path.join('assets', 'images', 'stories', `${slug}.jpg`);
  return fs.existsSync(path.join(SRC, rel)) ? `/${rel.split(path.sep).join('/')}` : null;
}

// 공유 카드(og:image) 전용 — 히어로가 없는 글도 <slug>-og.jpg 를 두면
// 페이지에는 표시하지 않고 공유/링크 카드에만 쓴다 (앱 아이콘 폴백은 맥락을 해침).
function storyOgSrc(slug) {
  const hero = storyHeroSrc(slug);
  if (hero) return hero;
  const rel = path.join('assets', 'images', 'stories', `${slug}-og.jpg`);
  return fs.existsSync(path.join(SRC, rel)) ? `/${rel.split(path.sep).join('/')}` : null;
}

function storiesIndexHref(locale, absolute) {
  const base = absolute ? SITE_URL : '';
  const prefix = locale === DEFAULT_LOCALE ? '' : `/${locale}`;
  return `${base}${prefix}/stories/`;
}

function storyHref(slug, locale, absolute) {
  return `${storiesIndexHref(locale, absolute)}${slug}/`;
}

function storyHreflangs(hrefOf) {
  const lines = STORY_LOCALES.map(l =>
    `<link rel="alternate" hreflang="${l}" href="${hrefOf(l)}" />`
  );
  lines.push(`<link rel="alternate" hreflang="x-default" href="${hrefOf(DEFAULT_LOCALE)}" />`);
  return lines.join('\n  ');
}

// src/stories/<slug>/{ko,en,ja}.md 스캔. 로케일 누락 slug 는 빌드 실패 (부분 번역 방지).
function loadStories() {
  const dir = path.join(SRC, 'stories');
  if (!fs.existsSync(dir)) return [];
  const slugs = fs.readdirSync(dir, { withFileTypes: true })
    .filter(e => e.isDirectory())
    .map(e => e.name)
    .sort();
  const stories = [];
  for (const slug of slugs) {
    const locales = {};
    for (const locale of STORY_LOCALES) {
      const p = path.join(dir, slug, `${locale}.md`);
      if (!fs.existsSync(p)) {
        console.error(`[FAIL] story '${slug}' missing ${locale}.md`);
        process.exit(1);
      }
      try {
        locales[locale] = parseFrontMatter(fs.readFileSync(p, 'utf8'));
      } catch (e) {
        console.error(`[FAIL] story '${slug}' ${locale}.md: ${e.message}`);
        process.exit(1);
      }
    }
    stories.push({ slug, locales });
  }
  // 최신 글 먼저 (date 내림차순, 같은 날짜는 slug 역순으로 안정 정렬)
  stories.sort((a, b) => {
    const d = b.locales[DEFAULT_LOCALE].meta.date.localeCompare(a.locales[DEFAULT_LOCALE].meta.date);
    return d !== 0 ? d : b.slug.localeCompare(a.slug);
  });
  return stories;
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

  // 3.5 Load stories (ko/en/ja) — nav 링크 노출 판단에 페이지 생성보다 먼저 필요
  const stories = loadStories();
  const storyStrings = fs.existsSync(path.join(SRC, 'stories', 'strings.json'))
    ? loadJson(path.join('stories', 'strings.json'))
    : null;
  const storiesNavFor = locale =>
    stories.length > 0 && STORY_LOCALES.includes(locale) && storyStrings
      ? `<a href="${storiesIndexHref(locale)}">${storyStrings[locale].navLabel}</a>`
      : '';

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
      const pageData = {
        ...data,
        __locale: locale,
        __page: page,
        __storiesNav: storiesNavFor(locale)
      };
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
        __ogImage: `${SITE_URL}/assets/images/icon-1024.png`,
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

  // 4.5 Generate story pages + per-locale index (stories 가 있을 때만)
  let storyGenerated = 0;
  if (stories.length > 0) {
    if (!storyStrings) {
      console.error('[FAIL] src/stories/strings.json missing');
      process.exit(1);
    }
    const storyTpl = loadText(path.join('layouts', 'story.html'));
    const indexTpl = loadText(path.join('layouts', 'stories-index.html'));

    for (const locale of STORY_LOCALES) {
      const data = loadJson(path.join('locales', `${locale}.json`));
      const strings = storyStrings[locale];
      const common = {
        ...data,
        __strings: strings,
        __locale: locale,
        __storiesNav: storiesNavFor(locale),
        __storiesIndexHref: storiesIndexHref(locale)
      };
      const renderedHeader = render(loadText('layouts/partials/header.html'), common, locale);
      const renderedFooter = render(loadText('layouts/partials/footer.html'), common, locale);

      const writeOut = (relDir, html, label) => {
        const unresolved = html.match(/\{\{[^}]+\}\}/g);
        if (unresolved) {
          console.error(`[FAIL] unresolved placeholders in ${label}:`);
          [...new Set(unresolved)].forEach(u => console.error(`  ${u}`));
          process.exit(1);
        }
        const out = path.join(DIST, relDir, 'index.html');
        ensureDir(out);
        fs.writeFileSync(out, html);
        storyGenerated++;
      };

      // 상세 페이지
      for (const story of stories) {
        const { meta, body } = story.locales[locale];
        const hero = storyHeroSrc(story.slug);
        // 무드 이미지라 정보를 담지 않는다 → heroAlt 가 없으면 alt="" (장식용, 스크린리더 건너뜀)
        const heroHtml = hero
          ? `  <figure class="story__hero"><img src="${hero}" alt="${escapeHtml(meta.heroAlt || '')}" width="1600" height="1000" /></figure>`
          : '';
        const content = render(storyTpl, {
          ...common,
          __storyTitle: meta.title,
          __storySummary: meta.summary,
          __storyDate: meta.date,
          __storyHero: heroHtml,
          __storyBody: renderMarkdown(body)
        }, locale);
        const html = render(base, {
          ...common,
          meta: { title: `${meta.title} — ${data.app.name}`, description: meta.summary },
          __content: content,
          __header: renderedHeader,
          __footer: renderedFooter,
          __hreflangs: storyHreflangs(l => storyHref(story.slug, l, true)),
          __canonical: storyHref(story.slug, locale, true),
          // 공유 카드 — 히어로 → og 전용(<slug>-og.jpg) → 앱 아이콘 순 폴백
          __ogImage: `${SITE_URL}${storyOgSrc(story.slug) || '/assets/images/icon-1024.png'}`,
          __lang_html: locale,
          __page: 'story'
        }, locale);
        const rel = locale === DEFAULT_LOCALE
          ? path.join('stories', story.slug)
          : path.join(locale, 'stories', story.slug);
        writeOut(rel, html, `${locale}/stories/${story.slug}`);
      }

      // 인덱스 페이지
      const cards = stories.map(story => {
        const { meta } = story.locales[locale];
        const hero = storyHeroSrc(story.slug);
        return [
          `<a class="stories__card" href="${storyHref(story.slug, locale)}">`,
          hero ? `  <img class="stories__card-thumb" src="${hero}" alt="" loading="lazy" width="1600" height="1000" />` : '',
          `  <div class="stories__card-text">`,
          `    <p class="stories__card-date">${escapeHtml(meta.date)}</p>`,
          `    <h2 class="stories__card-title">${escapeHtml(meta.title)}</h2>`,
          `    <p class="stories__card-summary">${escapeHtml(meta.summary)}</p>`,
          `  </div>`,
          '</a>'
        ].filter(Boolean).join('\n');
      }).join('\n');
      const indexContent = render(indexTpl, { ...common, __storyCards: cards }, locale);
      const indexHtml = render(base, {
        ...common,
        meta: { title: `${strings.indexTitle} — ${data.app.name}`, description: strings.indexDescription },
        __content: indexContent,
        __header: renderedHeader,
        __footer: renderedFooter,
        __hreflangs: storyHreflangs(l => storiesIndexHref(l, true)),
        __canonical: storiesIndexHref(locale, true),
        __ogImage: `${SITE_URL}/assets/images/icon-1024.png`,
        __lang_html: locale,
        __page: 'stories'
      }, locale);
      const relIndex = locale === DEFAULT_LOCALE ? 'stories' : path.join(locale, 'stories');
      writeOut(relIndex, indexHtml, `${locale}/stories`);
    }
    console.log(`[OK] generated ${storyGenerated} story files (${stories.length} stories × ${STORY_LOCALES.length} locales + ${STORY_LOCALES.length} index)`);
  }

  // 4.6 sitemap.xml — 기본 페이지 + 스토리
  const urls = [];
  for (const locale of LOCALES) {
    for (const page of PAGES) urls.push(pageHref(page, locale, true));
  }
  if (stories.length > 0) {
    for (const locale of STORY_LOCALES) {
      urls.push(storiesIndexHref(locale, true));
      for (const story of stories) urls.push(storyHref(story.slug, locale, true));
    }
  }
  const sitemap = [
    '<?xml version="1.0" encoding="UTF-8"?>',
    '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ...urls.map(u => `  <url><loc>${u}</loc></url>`),
    '</urlset>'
  ].join('\n');
  fs.writeFileSync(path.join(DIST, 'sitemap.xml'), sitemap);

  // 5. Copy static assets
  copyDir(path.join(SRC, 'styles'), path.join(DIST, 'styles'));
  copyDir(path.join(SRC, 'assets'), path.join(DIST, 'assets'));
  // Threads 홍보용 공개 이미지 — repo 루트 promo-assets/ 를 URL 그대로 노출
  if (fs.existsSync(path.join(ROOT, 'promo-assets'))) {
    copyDir(path.join(ROOT, 'promo-assets'), path.join(DIST, 'promo-assets'));
  }

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
  const expectedStories = stories.length > 0 ? STORY_LOCALES.length * (stories.length + 1) : 0;
  if (storyGenerated !== expectedStories) {
    console.error(`[FAIL] generated ${storyGenerated} story files, expected ${expectedStories}`);
    process.exit(1);
  }
  console.log(`[OK] generated ${generated} HTML files (${LOCALES.length} locales × ${PAGES.length} pages)`);
}

build();
