/* 绿茵数据台：缓存优先 + 后台更新，弱网时优先保证能打开 */
const CACHE = "gyd-page-v1";
const TIMEOUT = 3500;

self.addEventListener("install", () => self.skipWaiting());

self.addEventListener("activate", event => {
  event.waitUntil(
    caches.keys()
      .then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", event => {
  const req = event.request;
  if (req.mode !== "navigate" || req.method !== "GET") return;

  event.respondWith((async () => {
    const cache = await caches.open(CACHE);
    const cached = await cache.match(req);

    const network = fetch(req).then(res => {
      if (res && res.ok) cache.put(req, res.clone());
      return res;
    }).catch(() => null);

    if (!cached) {
      const res = await network;
      return res || Response.error();
    }

    // 有缓存时不等待慢网络：最多等 3.5 秒，超时直接返回缓存，更新在后台继续
    const timeout = new Promise(resolve => setTimeout(() => resolve(cached), TIMEOUT));
    return Promise.race([network.then(res => res || cached), timeout]);
  })());
});
