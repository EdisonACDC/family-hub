/* Family Hub guest web app: works offline (read only) and shows notifications.
 * Only the app's own files are kept; the API is never cached here (the page keeps its own
 * last copy of the appointments). */
"use strict";

var CACHE = "family-hub-guest-v3";
var BASE = "/api/family_hub/guest/";
var SHELL = [
  BASE,
  BASE + "app.js",
  BASE + "app.css",
  BASE + "manifest.json",
  BASE + "icon-192.png",
  BASE + "apple-touch-icon.png"
];

self.addEventListener("install", function (event) {
  event.waitUntil(
    caches.open(CACHE).then(function (cache) { return cache.addAll(SHELL); }).then(function () {
      return self.skipWaiting();
    })
  );
});

self.addEventListener("activate", function (event) {
  event.waitUntil(
    caches.keys().then(function (names) {
      return Promise.all(names.filter(function (name) {
        return name.indexOf("family-hub-guest-") === 0 && name !== CACHE;
      }).map(function (name) { return caches.delete(name); }));
    }).then(function () { return self.clients.claim(); })
  );
});

self.addEventListener("fetch", function (event) {
  var request = event.request;
  if (request.method !== "GET") return;
  var url = new URL(request.url);
  if (url.origin !== self.location.origin || url.pathname.indexOf(BASE) !== 0) return;
  if (url.pathname.indexOf(BASE + "api/") === 0) return;
  // Pages are kept by their address without the query: the simple app (and its invite in
  // ?i=) under BASE, "Completa" under full.html.
  var key = request.mode === "navigate" && url.pathname !== BASE + "full.html" ? BASE : url.pathname;
  // The network first, so an update arrives at once; the saved copy when offline.
  event.respondWith(
    fetch(request).then(function (response) {
      if (response.ok) {
        var copy = response.clone();
        caches.open(CACHE).then(function (cache) { cache.put(key, copy); });
        return response;
      }
      return caches.match(key).then(function (saved) { return saved || response; });
    }).catch(function () {
      return caches.match(key).then(function (saved) {
        return saved || new Response("", { status: 503 });
      });
    })
  );
});

self.addEventListener("push", function (event) {
  var data = {};
  try { data = event.data ? event.data.json() : {}; } catch (e) { data = {}; }
  event.waitUntil(
    self.registration.showNotification(String(data.title || "Family Hub"), {
      body: String(data.body || ""),
      tag: data.tag ? String(data.tag) : undefined,
      renotify: !!data.tag,
      icon: BASE + "icon-192.png",
      badge: BASE + "icon-192.png",
      // Web notifications cannot ring like an alarm: they vibrate, and stay on screen until
      // touched where the system allows it.
      vibrate: [300, 150, 300, 150, 600],
      requireInteraction: data.tag !== "test",
      // What a tap opens: one appointment (new appointments).
      data: { open: data.open ? String(data.open) : "", day: data.day ? String(data.day) : "" }
    })
  );
});

self.addEventListener("notificationclick", function (event) {
  event.notification.close();
  var info = event.notification.data || {};
  var open = /^[0-9a-f]{32}$/.test(info.open || "") && /^\d{4}-\d{2}-\d{2}$/.test(info.day || "")
    ? { type: "open", id: info.open, day: info.day } : null;
  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then(function (list) {
      for (var i = 0; i < list.length; i++) {
        if (list[i].url.indexOf(BASE) !== -1 && "focus" in list[i]) {
          if (open) list[i].postMessage(open);
          return list[i].focus();
        }
      }
      return self.clients.openWindow(open ? BASE + "#e=" + open.id + "." + open.day : BASE);
    })
  );
});
