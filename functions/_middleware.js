/**
 * Cloudflare Pages middleware — Accept-Language based locale routing.
 *
 * Only acts on the root path "/". Non-root paths (already locale-specific
 * or page-specific) pass through. ko + unknown → default (serve root).
 *
 * Cloudflare's `_redirects` file is path-based only and does not support
 * header conditions, so locale auto-redirect lives here instead.
 */
export async function onRequest(context) {
  const { request, next } = context;
  const url = new URL(request.url);

  if (url.pathname !== '/') {
    return next();
  }

  const al = (request.headers.get('accept-language') || '').toLowerCase();
  const firstTag = al.split(',')[0].trim();
  const [lang, region] = firstTag.split('-');

  // zh-TW / zh-HK / zh-Hant → /zh-Hant/
  if (lang === 'zh' && (region === 'tw' || region === 'hk' || region === 'hant')) {
    return Response.redirect(url.origin + '/zh-Hant/', 302);
  }

  const map = {
    en: '/en/',
    ja: '/ja/',
    de: '/de/',
    fr: '/fr/',
    es: '/es/'
  };

  if (map[lang]) {
    return Response.redirect(url.origin + map[lang], 302);
  }

  // ko or any unmapped language → serve default (root = ko).
  return next();
}
