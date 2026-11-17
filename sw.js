/* 绿茵数据台：Service Worker 自毁脚本。
   早期版本用 SW 做离线缓存，但站点每 30 分钟构建，缓存会让用户看到旧数据。
   这里主动清空所有缓存、注销自己，并通知已打开的页面刷新。 */
const VERSION = "gyd-v7";

self.addEventListener("install", () => { self.skipWaiting(); });

self.addEventListener("activate", event => {
  event.waitUntil((async () => {
    try {
      const keys = await caches.keys();
      await Promise.all(keys.map(k => caches.delete(k)));
    } catch (e) {}
    try {
      const clients = await self.clients.matchAll({ type: "window" });
      clients.forEach(c => c.postMessage({ type: "force-reload" }));
    } catch (e) {}
    try { await self.registration.unregister(); } catch (e) {}
  })());
});

self.addEventListener("fetch", () => {});
