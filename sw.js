/* 绿茵数据台：上次访问优先（stale-while-revalidate），弱网也能秒开。
   页面是每日更新的数据台，页面内自带「数据截止」时间戳，
   因此导航直接返回缓存、后台再拉新版本，下一次访问即为最新。 */
const VERSION = "gyd-v2";
const HTML_CACHE = VERSION + "-html";
const STATIC_CACHE = VERSION + "-static";

self.addEventListener("install", () => {
  // 新版本立即接管，避免用户长时间停留在旧缓存
  self.skipWaiting();
});

self.addEventListener("activate", event => {
  event.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(keys.filter(k => !k.startsWith(VERSION)).map(k => caches.delete(k)));
    await self.clients.claim();
  })());
});

self.addEventListener("fetch", event => {
  const req = event.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;

  if (req.mode === "navigate") {
    event.respondWith(htmlStrategy(req));
    return;
  }
  const p = url.pathname;
  if (p.includes("/logos/") || p.includes("/fonts/") || /\.(png|jpe?g|webp|svg|woff2?|ico)$/i.test(p)) {
    event.respondWith(staticStrategy(req));
  }
});

async function htmlStrategy(req) {
  const cache = await caches.open(HTML_CACHE);
  const cached = await cache.match(req, { ignoreSearch: true });
  // 后台更新：不阻塞当前返回
  const refresh = fetch(req).then(res => {
    if (res && res.ok) cache.put(req, res.clone());
    return res;
  }).catch(() => null);
  if (cached) {
    refresh.catch(() => {});
    return cached;
  }
  const res = await refresh;
  return res || new Response("网络暂不可用，请稍后重试。", {
    status: 503,
    headers: { "Content-Type": "text/plain; charset=utf-8" }
  });
}

async function staticStrategy(req) {
  const cache = await caches.open(STATIC_CACHE);
  const cached = await cache.match(req);
  if (cached) return cached;
  try {
    const res = await fetch(req);
    if (res && res.ok) cache.put(req, res.clone());
    return res;
  } catch (e) {
    return cached || Response.error();
  }
}
