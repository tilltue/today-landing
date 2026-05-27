# today-landing

Landing, privacy, and support pages for "오늘, 기록" iOS app.

Served at: https://today.sb-corporation.com

## Build

```bash
npm run build      # generates dist/
npm run serve      # build + python3 http.server on :4173
```

Requirements: Node 20+, Python 3 (for `serve` only).

## Structure

- `src/locales/ko.json` — canonical content (Korean). Other locales mirror its key structure.
- `src/pages/*.html` — page templates with `{{ key.path }}` placeholders.
- `src/layouts/base.html` — common HTML shell.
- `scripts/build.js` — pure Node, zero deps.

Build script enforces:
1. All non-default locales have the same keys as `ko.json` (missing → fail).
2. No unresolved `{{ }}` in output (→ fail).
3. Output file count = `locales × pages` (currently 7 × 3 = 21).

## Deploy

Cloudflare Pages auto-deploys on push to `main`. Build command: `node scripts/build.js`, output directory: `dist`.

## Add a new locale

1. Copy `src/locales/ko.json` → `src/locales/<lc>.json`.
2. Translate all values; keep the same keys.
3. Add `<lc>` to `LOCALES` array in `scripts/build.js`.
4. Add Accept-Language redirect rule in `_redirects`.
5. Run `npm run build` — check for errors.
