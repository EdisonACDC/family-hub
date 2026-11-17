/* Family Hub guest web app, "Completa" (0.10.0b2): the panel of Home Assistant, unchanged
 * (panel-app.js, panel.css: copies of the add-on's files), talking to this bridge instead of the
 * add-on's WebSocket. The bridge answers the panel's requests with the guests' API only
 * (/api/family_hub/guest/api/...), with the phone's own token. Home Assistant checks every
 * request and filters everything (Regola Zero) on the server: what is not allowed never
 * reaches this page, and whatever the panel asks beyond that is refused here and there.
 * The phone never has a Home Assistant token. */
(function () {
  "use strict";

  var BASE = "/api/family_hub/guest/";
  var API = BASE + "api/";
  var DB_NAME = "family-hub-guest";
  var DB_STORE = "kv";
  var POLL = 60000;
  var CACHE_MS = 15000;
  var MAX_DAYS = 62;
  var WASTE_CAL = "family_hub_guest_waste";

  var db = null;
  var token = null;
  var me = null;
  var socket = null;
  var known = {};      // the guest's appointments seen last, by id (to change them)
  var cache = {};      // GET answers for a few seconds: the panel asks the same thing often
  var pollTimer = null;

  html().classList.add("fh-invited");

  function html() { return document.documentElement; }
  function f(key) { return window.FH_I18N ? window.FH_I18N.f(key) : key; }
  function pad(n) { return n < 10 ? "0" + n : "" + n; }
  function ymd(d) { return d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate()); }
  function day(text) {
    var p = String(text).slice(0, 10).split("-");
    return new Date(parseInt(p[0], 10), parseInt(p[1], 10) - 1, parseInt(p[2], 10));
  }
  function addDays(d, n) { var x = new Date(d.getTime()); x.setDate(x.getDate() + n); return x; }

  // ----- what the phone keeps (the same store as the simple web app) -----------------------

  function openDb() {
    return new Promise(function (resolve) {
      try {
        var request = window.indexedDB.open(DB_NAME, 1);
        request.onupgradeneeded = function () { request.result.createObjectStore(DB_STORE); };
        request.onsuccess = function () { db = request.result; resolve(); };
        request.onerror = function () { resolve(); };
        request.onblocked = function () { resolve(); };
      } catch (e) { resolve(); }
    });
  }

  function dbGet(key) {
    return new Promise(function (resolve) {
      if (!db) { resolve(null); return; }
      try {
        var request = db.transaction(DB_STORE, "readonly").objectStore(DB_STORE).get(key);
        request.onsuccess = function () { resolve(request.result === undefined ? null : request.result); };
        request.onerror = function () { resolve(null); };
      } catch (e) { resolve(null); }
    });
  }

  function dbPut(key, value) {
    if (!db) return;
    try { db.transaction(DB_STORE, "readwrite").objectStore(DB_STORE).put(value, key); } catch (e) { /* this visit only */ }
  }

  // Back to the simple web app: it says what is wrong (no access, waiting, offline...).
  function leave() {
    window.clearInterval(pollTimer);
    window.location.replace(BASE);
  }

  // ----- the guests' API ---------------------------------------------------------------------

  function api(method, path, body) {
    var headers = { "Accept": "application/json", "Authorization": "Bearer " + token };
    if (body !== undefined) headers["Content-Type"] = "application/json";
    return fetch(API + path, {
      method: method, headers: headers, cache: "no-store", credentials: "omit",
      referrerPolicy: "no-referrer",
      body: body === undefined ? undefined : JSON.stringify(body)
    }).then(function (response) {
      return response.json().catch(function () { return {}; }).then(function (data) {
        if (response.status === 401) leave();
        if (!response.ok) {
          var err = new Error(data.error || "http_" + response.status);
          err.code = response.status === 403 ? "forbidden" : data.error || "unknown";
          throw err;
        }
        return data;
      });
    });
  }

  function cachedGet(path) {
    var hit = cache[path];
    if (hit && Date.now() - hit.at < CACHE_MS) return hit.promise;
    var promise = api("GET", path);
    cache[path] = { at: Date.now(), promise: promise };
    promise.catch(function () { delete cache[path]; });
    return promise;
  }

  function forget() { cache = {}; }

  function refuse(code) {
    var err = new Error(code || "forbidden");
    err.code = code || "forbidden";
    return Promise.reject(err);
  }

  // ----- who this phone is, as the panel's "identity" and "theme" -------------------------

  function feature(name) { return !!(me && me.features && me.features[name]); }

  function caps() {
    var calendar = feature("calendar");
    return {
      calendar: calendar,
      add: calendar && (me.permission === "add" || me.permission === "edit_own"),
      edit: calendar && me.permission === "edit_own",
      lists: feature("lists") && (me.lists || []).length > 0,
      lists_edit: (me.lists || []).some(function (l) { return l.edit; }),
      waste: feature("waste"),
      weather: feature("weather"),
      shifts: !!me.has_shifts
    };
  }

  function identity() {
    return { type: "identity", role: "invited", caps: caps(), user_name: me.name || "",
      person_id: me.own_person || "" };
  }

  function theme() {
    return { type: "theme", theme: me.theme || "auto", language: me.language,
      time_format: me.time_format, first_weekday: me.first_weekday,
      week_from_today: me.week_from_today !== false };
  }

  // Only "Completa" with the calendar lives here; anything else is the simple web app.
  function belongsHere(data) {
    return data && data.status === "active" && data.mode === "full"
      && !!(data.features && data.features.calendar);
  }

  function loadMe() {
    return api("GET", "me").then(function (data) {
      if (data.token) { token = data.token; dbPut("token", token); }
      if (!belongsHere(data)) { leave(); throw new Error("elsewhere"); }
      var before = me ? JSON.stringify(caps()) + me.theme + me.language : "";
      me = data;
      dbPut("me", data);
      return before !== JSON.stringify(caps()) + me.theme + me.language;
    });
  }

  // ----- the panel's requests ----------------------------------------------------------------

  function persons() {
    return (me.persons || []).map(function (p) {
      var own = p.id === me.own_person;
      return { id: p.id, name: p.name, color: p.color, role: own ? "guest" : "", has_shifts: own && !!me.has_shifts };
    });
  }

  function calendars() {
    var found = [];
    if (feature("calendar")) {
      (me.categories || []).forEach(function (c) {
        found.push({ entity_id: "family_hub_guest_" + c.id, name: c.name, category_id: c.id,
          external: false, persons: persons(), shared_users: [] });
      });
    }
    if (feature("calendar")) {
      // External calendars allowed to this phone (school, Google, ICS): read only.
      (me.externals || []).forEach(function (x) {
        found.push({ entity_id: "family_hub_guest_" + x.id, name: x.name, category_id: "", external: true,
          type: x.type || "altro", color: x.color || "#64748B", persons: (x.persons || []).slice() });
      });
    }
    if (feature("waste")) {
      found.push({ entity_id: WASTE_CAL, name: f("invitedWaste"), category_id: "", external: true,
        type: "rifiuti", color: "#64748B", persons: [] });
    }
    return found;
  }

  function categoryName(id) {
    var c = (me.categories || []).filter(function (x) { return x.id === id; })[0];
    return c ? c.name : "";
  }

  function externalEvent(item) {
    return { summary: item.title, start: item.start, end: item.end, location: item.location || "",
      record_id: "", person_ids: (item.persons || []).slice(), external: true };
  }

  // One appointment of the guests' API as the panel draws it.
  function panelEvent(item) {
    known[item.id] = item;
    return {
      summary: item.status === "pending" ? item.title + " (" + f("invitedPending") + ")" : item.title,
      start: item.start,
      end: item.end,
      location: item.location || "",
      record_id: item.id,
      version: item.version || "",
      person_ids: (item.persons || []).slice(),
      shift_id: item.shift_id || "",
      description: item.note || "",
      category_id: item.category,
      calendar: categoryName(item.category),
      added_by: item.added_by || "",
      mine: !!item.mine,
      private: false
    };
  }

  function wasteEvents(days) {
    var list = [];
    days.forEach(function (d) {
      (d.items || []).forEach(function (w) {
        list.push({ summary: w.label, start: d.date, end: ymd(addDays(day(d.date), 1)), location: "",
          record_id: "", person_ids: [], external: true, waste: w.type || "altro",
          waste_label: w.label, waste_icon: w.icon || w.type || "", waste_color: w.color });
      });
    });
    return list;
  }

  function events(start, end) {
    var from = day(start);
    var days = Math.round((day(end) - from) / 86400000);
    days = Math.max(1, Math.min(MAX_DAYS, days));
    var query = "from=" + ymd(from) + "&days=" + days;
    var result = {};
    var jobs = [];
    if (feature("calendar")) {
      jobs.push(cachedGet("events?" + query).then(function (data) {
        (data.events || []).forEach(function (item) {
          var key = "family_hub_guest_" + item.category;
          (result[key] = result[key] || []).push(item.external ? externalEvent(item) : panelEvent(item));
        });
      }));
    }
    if (feature("waste")) {
      jobs.push(cachedGet("waste?" + query).then(function (data) {
        result[WASTE_CAL] = wasteEvents(data.days || []);
      }).catch(function () { result[WASTE_CAL] = []; }));
    }
    return Promise.all(jobs).then(function () { return result; });
  }

  // The panel's form, as the guests' API takes it: one person, one day.
  function guestEvent(data, current) {
    var people = data.persons || (current ? current.persons : []);
    if (people.length !== 1) return null;
    var start = String(data.start || (current && current.start) || "");
    var end = String(data.end || (current && current.end) || "");
    var allDay = start.length === 10;
    var body = {
      title: data.summary || (current && current.title) || "",
      person: people[0],
      category: data.category || (current && current.category) || "",
      date: start.slice(0, 10),
      all_day: allDay,
      location: current ? current.location || "" : "",
      note: current ? current.note || "" : ""
    };
    // The version the panel read: if the appointment is another by now, the change is refused.
    if (current && (data.version || current.version)) body.version = data.version || current.version;
    if (!allDay) {
      body.start = start.slice(11, 16);
      body.end = end.slice(11, 16);
    }
    return body;
  }

  function service(name, data) {
    data = data || {};
    if (name === "add_event") {
      var body = guestEvent(data, null);
      if (!body) return refuse("one_person");
      return api("POST", "events", body).then(function () { forget(); return null; });
    }
    if (name === "update_event") {
      var current = known[data.uid];
      if (!current) return refuse("not_found");
      var change = guestEvent(data, current);
      if (!change) return refuse("one_person");
      return api("PUT", "events/" + encodeURIComponent(data.uid), change).then(function () { forget(); return null; });
    }
    if (name === "delete_event") {
      var read = known[data.uid];
      var version = data.version || (read && read.version) || "";
      return api("DELETE", "events/" + encodeURIComponent(data.uid) + (version ? "?version=" + encodeURIComponent(version) : ""))
        .then(function () { forget(); return null; });
    }
    return refuse();
  }

  function todoLists() {
    return Promise.resolve((caps().lists ? me.lists : []).map(function (l) {
      return { entity_id: l.id, name: l.name };
    }));
  }

  function todoItems(data) {
    return data.items ? data.items.map(function (i) {
      return { uid: i.id, summary: i.summary, status: i.done ? "completed" : "needs_action" };
    }) : [];
  }

  function shifts() {
    return api("GET", "shifts?from=" + ymd(new Date()) + "&days=1").then(function (data) {
      var own = me.own_person;
      var name = ((me.persons || []).filter(function (p) { return p.id === own; })[0] || {}).name || me.name;
      var calendar = { id: "own", name: me.shifts_calendar || f("cardShift") };
      var models = {};
      models[own] = (data.types || []).map(function (s) {
        return { id: s.id, name: s.name, start: s.start, end: s.end, category: calendar.id };
      });
      return { shifts: models, categories: [calendar], persons: [{ id: own, name: name }],
        time_format: me.time_format };
    });
  }

  function answer(payload) {
    var op = payload.op;
    switch (op) {
      case "status": return Promise.resolve({});
      case "calendars": return Promise.resolve(calendars());
      case "events": return events(payload.start, payload.end);
      case "weather":
        if (!feature("weather")) return Promise.resolve(null);
        return cachedGet("weather").then(function (w) {
          return { condition: w.condition, temperature: w.temperature, unit: w.unit || "°C",
            forecast: w.forecast || [] };
        });
      case "service": return service(payload.service, payload.data);
      case "todo_lists": return todoLists();
      case "todo_items":
        return api("GET", "lists/" + encodeURIComponent(payload.entity_id)).then(todoItems);
      case "todo_add":
        return api("POST", "lists/" + encodeURIComponent(payload.entity_id), { add: payload.summary }).then(todoItems);
      case "todo_update":
        return api("POST", "lists/" + encodeURIComponent(payload.entity_id),
          { item: payload.item, done: !!payload.done }).then(todoItems);
      case "shifts": return shifts();
      case "shifts_save":
        return api("PUT", "shifts/types", { types: (payload.shifts || []).map(function (s) {
          return { id: s.id || "", name: s.name, start: s.start, end: s.end };
        }) }).then(function () { forget(); return {}; });
      case "shifts_apply":
        return api("POST", "shifts/apply", { days: payload.days, shift_id: payload.shift_id || "" })
          .then(function (r) { forget(); return { inserted: r.written || 0, removed: 0 }; });
      default:
        // Condivisione, the guide, external calendars, settings, Home Assistant: never here.
        return refuse();
    }
  }

  // ----- the socket the panel opens (window.FH_SOCKET) ---------------------------------------

  function BridgeSocket() {
    socket = this;
    this.readyState = 0;
    this.onopen = null;
    this.onclose = null;
    this.onmessage = null;
    var self = this;
    openDb().then(function () {
      return Promise.all([dbGet("token"), dbGet("me")]);
    }).then(function (stored) {
      token = stored[0];
      if (!token) { leave(); return; }
      if (!belongsHere(stored[1])) { leave(); return; }
      me = stored[1];
      return loadMe().then(function () {
        self.readyState = 1;
        self.emit(identity());
        self.emit(theme());
        if (self.onopen) self.onopen();
        addPushItem();
        pollTimer = window.setInterval(poll, POLL);
      }, function (err) {
        // No network: the simple web app shows the copy the phone keeps.
        if (err && err.message !== "elsewhere") leave();
      });
    });
  }

  BridgeSocket.OPEN = 1;
  BridgeSocket.prototype.emit = function (message) {
    if (this.onmessage) this.onmessage({ data: JSON.stringify(message) });
  };
  BridgeSocket.prototype.send = function (text) {
    var self = this;
    var payload = JSON.parse(text);
    answer(payload).then(function (result) {
      self.emit({ type: "result", id: payload.id, ok: true, result: result });
    }, function (err) {
      self.emit({ type: "result", id: payload.id, ok: false, error: (err && err.code) || "unknown" });
    });
  };
  BridgeSocket.prototype.close = function () { /* the page lives as long as the bridge */ };

  // What changed in Home Assistant (or in this guest's permissions) is shown at the next look.
  function poll() {
    if (document.hidden || !socket) return;
    loadMe().then(function (changed) {
      forget();
      if (changed) { socket.emit(identity()); socket.emit(theme()); addPushItem(); }
      socket.emit({ type: "state_changed" });
    }).catch(function () { /* offline for now: the next look tries again */ });
  }

  document.addEventListener("visibilitychange", function () { if (!document.hidden) poll(); });

  // ----- notifications on this phone (asked only after a tap, from the menu) -----------------

  function keyBytes(base64) {
    var padding = "=".repeat((4 - (base64.length % 4)) % 4);
    var raw = window.atob((base64 + padding).replace(/-/g, "+").replace(/_/g, "/"));
    var out = new Uint8Array(raw.length);
    for (var i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
    return out;
  }

  function pushSupported() {
    return "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;
  }

  function addPushItem() {
    var old = document.getElementById("menu-push");
    if (old) old.remove();
    if (!me || !me.vapid || me.push || !pushSupported() || window.Notification.permission === "denied") return;
    var menu = document.getElementById("menu");
    if (!menu) return;
    var item = document.createElement("button");
    item.type = "button";
    item.className = "btn";
    item.id = "menu-push";
    item.textContent = f("invitedPush");
    item.addEventListener("click", function () {
      window.Notification.requestPermission().then(function (granted) {
        if (granted !== "granted") throw new Error("denied");
        return navigator.serviceWorker.ready;
      }).then(function (registration) {
        return registration.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: keyBytes(me.vapid) });
      }).then(function (subscription) {
        return api("POST", "push", { subscription: subscription.toJSON() });
      }).then(function (result) {
        me.push = !!result.push;
        dbPut("me", me);
        addPushItem();
      }).catch(function () { addPushItem(); });
    });
    menu.insertBefore(item, menu.querySelector(".menu-switch"));
  }

  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register(BASE + "sw.js", { scope: BASE }).catch(function () { /* online only */ });
  }

  window.FH_SOCKET = BridgeSocket;
})();
