/* Family Hub guest web app. No library, no inline code (strict Content-Security-Policy).
 *
 * The invite token comes in the link's fragment (#i=...), so it never reaches a server log.
 * It is sent once, in the body of POST api/activate. The device token that comes back is kept
 * on the phone and sent in the Authorization header, never in a URL.
 */
(function () {
  "use strict";

  var BASE = "/api/family_hub/guest/";
  var API = BASE + "api/";
  var KEY_TOKEN = "fh_guest_token";
  var KEY_ME = "fh_guest_me";
  var KEY_CACHE = "fh_guest_cache";
  var REFRESH_MS = 30000;
  var PENDING_POLL_MS = 10000;

  var TEXT = {
    it: {
      loading: "Un momento…",
      hello: "Ciao, {name}",
      offline: "Non aggiornato – senza connessione",
      upcoming: "Prossimi giorni",
      week: "Settimana",
      today: "Oggi",
      tomorrow: "Domani",
      nothingDays: "Nessun impegno nei prossimi giorni.",
      nothingDay: "—",
      allDay: "Tutto il giorno",
      pending: "In attesa",
      addedBy: "aggiunto da {name}",
      add: "+ Aggiungi",
      addTitle: "Nuovo appuntamento",
      editTitle: "Modifica appuntamento",
      fTitle: "Che cosa",
      fPerson: "Per chi",
      fCalendar: "Calendario",
      fDate: "Giorno",
      fAllDay: "Tutto il giorno",
      fStart: "Inizio",
      fEnd: "Fine",
      fLocation: "Dove (facoltativo)",
      fNote: "Nota (facoltativa)",
      save: "Salva",
      cancel: "Annulla",
      close: "Chiudi",
      edit: "Modifica",
      remove: "Elimina",
      removeAsk: "Eliminare questo appuntamento?",
      sentPending: "Inviato. La famiglia lo deve approvare.",
      added: "Aggiunto.",
      saved: "Salvato.",
      removed: "Eliminato.",
      errTitle: "Scrivi che cosa.",
      errTime: "La fine deve essere dopo l'inizio.",
      errSave: "Non è stato possibile salvare. Riprova.",
      errForbidden: "Questo non è permesso.",
      errSlow: "Troppe richieste. Riprova tra un minuto.",
      waitingTitle: "In attesa",
      waitingText: "In attesa della conferma della famiglia.",
      offTitle: "Accesso disattivato",
      offText: "Questo telefono non può più vedere il calendario. Se serve, chiedi un nuovo invito alla famiglia.",
      invalidTitle: "Invito non valido",
      invalidText: "Questo invito è già stato usato o è scaduto. Chiedi un nuovo invito alla famiglia.",
      noInviteTitle: "Serve un invito",
      noInviteText: "Apri il link dell'invito che ti ha mandato la famiglia.",
      netTitle: "Senza connessione",
      netText: "Il telefono non riesce a raggiungere Family Hub. Controlla la connessione.",
      retry: "Riprova",
      installTitle: "Benvenuto in Family Hub",
      installIntro: "Metti Family Hub sulla schermata Home: lo apri come un'app, con un tocco.",
      iosStep1: "Apri questo link in Safari.",
      iosStep2: "Tocca il pulsante Condividi (il quadrato con la freccia in su).",
      iosStep3: "Scorri e tocca «Aggiungi alla schermata Home», poi «Aggiungi».",
      iosStep4: "Apri Family Hub dalla schermata Home.",
      androidStep1: "Tocca il menu ⋮ in alto a destra.",
      androidStep2: "Tocca «Installa app» (oppure «Aggiungi a schermata Home»).",
      installButton: "Installa app",
      continueBrowser: "Continua nel browser",
      continueApp: "Continua",
      pushOn: "🔔 Attiva le notifiche",
      pushOff: "Disattiva le notifiche",
      pushActive: "Le notifiche sono attive.",
      pushDenied: "Le notifiche sono bloccate nelle impostazioni del telefono.",
      pushIos: "Su iPhone le notifiche funzionano solo con iOS 16.4 o più recente e con Family Hub aggiunto alla schermata Home da Safari.",
      pushNone: "Questo browser non può ricevere notifiche.",
      pushError: "Non è stato possibile attivare le notifiche.",
      installAgain: "Come installare l'app"
    },
    en: {
      loading: "One moment…",
      hello: "Hello, {name}",
      offline: "Not up to date – no connection",
      upcoming: "Next days",
      week: "Week",
      today: "Today",
      tomorrow: "Tomorrow",
      nothingDays: "Nothing in the next days.",
      nothingDay: "—",
      allDay: "All day",
      pending: "Waiting",
      addedBy: "added by {name}",
      add: "+ Add",
      addTitle: "New appointment",
      editTitle: "Change appointment",
      fTitle: "What",
      fPerson: "For whom",
      fCalendar: "Calendar",
      fDate: "Day",
      fAllDay: "All day",
      fStart: "Start",
      fEnd: "End",
      fLocation: "Where (optional)",
      fNote: "Note (optional)",
      save: "Save",
      cancel: "Cancel",
      close: "Close",
      edit: "Change",
      remove: "Delete",
      removeAsk: "Delete this appointment?",
      sentPending: "Sent. The family needs to approve it.",
      added: "Added.",
      saved: "Saved.",
      removed: "Deleted.",
      errTitle: "Write what it is.",
      errTime: "The end must be after the start.",
      errSave: "It could not be saved. Please try again.",
      errForbidden: "This is not allowed.",
      errSlow: "Too many requests. Try again in a minute.",
      waitingTitle: "Waiting",
      waitingText: "Waiting for the family to confirm.",
      offTitle: "Access turned off",
      offText: "This phone can no longer see the calendar. If needed, ask the family for a new invite.",
      invalidTitle: "Invite not valid",
      invalidText: "This invite has been used already or has expired. Ask the family for a new invite.",
      noInviteTitle: "An invite is needed",
      noInviteText: "Open the invite link the family sent you.",
      netTitle: "No connection",
      netText: "The phone cannot reach Family Hub. Check the connection.",
      retry: "Try again",
      installTitle: "Welcome to Family Hub",
      installIntro: "Put Family Hub on the Home Screen: it opens like an app, with one tap.",
      iosStep1: "Open this link in Safari.",
      iosStep2: "Tap the Share button (the square with the arrow pointing up).",
      iosStep3: "Scroll down and tap “Add to Home Screen”, then “Add”.",
      iosStep4: "Open Family Hub from the Home Screen.",
      androidStep1: "Tap the ⋮ menu at the top right.",
      androidStep2: "Tap “Install app” (or “Add to Home screen”).",
      installButton: "Install app",
      continueBrowser: "Continue in the browser",
      continueApp: "Continue",
      pushOn: "🔔 Turn on notifications",
      pushOff: "Turn off notifications",
      pushActive: "Notifications are on.",
      pushDenied: "Notifications are blocked in the phone's settings.",
      pushIos: "On iPhone, notifications work only with iOS 16.4 or later, with Family Hub added to the Home Screen from Safari.",
      pushNone: "This browser cannot receive notifications.",
      pushError: "Notifications could not be turned on.",
      installAgain: "How to install the app"
    },
    de: {
      loading: "Einen Moment…",
      hello: "Hallo, {name}",
      offline: "Nicht aktuell – keine Verbindung",
      upcoming: "Nächste Tage",
      week: "Woche",
      today: "Heute",
      tomorrow: "Morgen",
      nothingDays: "Keine Termine in den nächsten Tagen.",
      nothingDay: "—",
      allDay: "Ganztägig",
      pending: "Wartet",
      addedBy: "eingetragen von {name}",
      add: "+ Eintragen",
      addTitle: "Neuer Termin",
      editTitle: "Termin ändern",
      fTitle: "Was",
      fPerson: "Für wen",
      fCalendar: "Kalender",
      fDate: "Tag",
      fAllDay: "Ganztägig",
      fStart: "Beginn",
      fEnd: "Ende",
      fLocation: "Wo (freiwillig)",
      fNote: "Notiz (freiwillig)",
      save: "Speichern",
      cancel: "Abbrechen",
      close: "Schließen",
      edit: "Ändern",
      remove: "Löschen",
      removeAsk: "Diesen Termin löschen?",
      sentPending: "Gesendet. Die Familie muss ihn annehmen.",
      added: "Eingetragen.",
      saved: "Gespeichert.",
      removed: "Gelöscht.",
      errTitle: "Bitte schreiben, was es ist.",
      errTime: "Das Ende muss nach dem Beginn liegen.",
      errSave: "Speichern war nicht möglich. Bitte noch einmal versuchen.",
      errForbidden: "Das ist nicht erlaubt.",
      errSlow: "Zu viele Anfragen. In einer Minute noch einmal versuchen.",
      waitingTitle: "Warten",
      waitingText: "Warten auf die Bestätigung der Familie.",
      offTitle: "Zugang ausgeschaltet",
      offText: "Dieses Telefon kann den Kalender nicht mehr sehen. Bei Bedarf eine neue Einladung bei der Familie erbitten.",
      invalidTitle: "Einladung ungültig",
      invalidText: "Diese Einladung wurde schon benutzt oder ist abgelaufen. Bitte eine neue Einladung bei der Familie erbitten.",
      noInviteTitle: "Eine Einladung wird gebraucht",
      noInviteText: "Den Einladungslink öffnen, den die Familie geschickt hat.",
      netTitle: "Keine Verbindung",
      netText: "Das Telefon erreicht Family Hub nicht. Bitte die Verbindung prüfen.",
      retry: "Noch einmal",
      installTitle: "Willkommen bei Family Hub",
      installIntro: "Family Hub auf den Home-Bildschirm legen: es öffnet sich wie eine App, mit einem Tipp.",
      iosStep1: "Diesen Link in Safari öffnen.",
      iosStep2: "Auf Teilen tippen (das Quadrat mit dem Pfeil nach oben).",
      iosStep3: "Nach unten scrollen, auf „Zum Home-Bildschirm“ tippen, dann auf „Hinzufügen“.",
      iosStep4: "Family Hub vom Home-Bildschirm öffnen.",
      androidStep1: "Oben rechts auf das Menü ⋮ tippen.",
      androidStep2: "Auf „App installieren“ (oder „Zum Startbildschirm hinzufügen“) tippen.",
      installButton: "App installieren",
      continueBrowser: "Im Browser weiter",
      continueApp: "Weiter",
      pushOn: "🔔 Mitteilungen einschalten",
      pushOff: "Mitteilungen ausschalten",
      pushActive: "Mitteilungen sind eingeschaltet.",
      pushDenied: "Mitteilungen sind in den Einstellungen des Telefons gesperrt.",
      pushIos: "Auf dem iPhone gehen Mitteilungen nur ab iOS 16.4 und wenn Family Hub über Safari zum Home-Bildschirm hinzugefügt wurde.",
      pushNone: "Dieser Browser kann keine Mitteilungen empfangen.",
      pushError: "Mitteilungen konnten nicht eingeschaltet werden.",
      installAgain: "So wird die App installiert"
    }
  };

  var state = {
    lang: pickLanguage(),
    token: read(KEY_TOKEN),
    invite: null,
    me: readJSON(KEY_ME),
    view: "list",
    weekStart: null,
    events: [],
    offline: false,
    installPrompt: null,
    refreshTimer: null,
    pendingTimer: null
  };

  // ----- small helpers --------------------------------------------------------

  function $(id) { return document.getElementById(id); }

  function read(key) {
    try { return window.localStorage.getItem(key); } catch (e) { return null; }
  }
  function write(key, value) {
    try {
      if (value === null) window.localStorage.removeItem(key);
      else window.localStorage.setItem(key, value);
    } catch (e) { /* private mode: the app still works for this visit */ }
  }
  function readJSON(key) {
    try { return JSON.parse(read(key) || "null"); } catch (e) { return null; }
  }

  function pickLanguage(code) {
    var lang = String(code || navigator.language || "en").slice(0, 2).toLowerCase();
    return TEXT[lang] ? lang : "en";
  }

  function t(key, values) {
    var text = (TEXT[state.lang] || TEXT.en)[key] || TEXT.en[key] || key;
    Object.keys(values || {}).forEach(function (name) {
      text = text.split("{" + name + "}").join(values[name]);
    });
    return text;
  }

  function el(tag, attrs, children) {
    var node = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (name) {
      var value = attrs[name];
      if (value === null || value === undefined || value === false) return;
      if (name === "text") node.textContent = value;
      else if (name.slice(0, 2) === "on") node.addEventListener(name.slice(2), value);
      else node.setAttribute(name, value === true ? "" : String(value));
    });
    (children || []).forEach(function (child) {
      if (child) node.appendChild(typeof child === "string" ? document.createTextNode(child) : child);
    });
    return node;
  }

  function isIOS() {
    var ua = navigator.userAgent || "";
    return /iPhone|iPad|iPod/.test(ua) || (/Macintosh/.test(ua) && navigator.maxTouchPoints > 1);
  }
  function standalone() {
    return window.navigator.standalone === true ||
      (window.matchMedia && window.matchMedia("(display-mode: standalone)").matches);
  }

  function pad(n) { return (n < 10 ? "0" : "") + n; }
  function dayKey(d) { return d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate()); }
  function fromKey(key) {
    var p = key.split("-");
    return new Date(Number(p[0]), Number(p[1]) - 1, Number(p[2]));
  }
  function addDays(d, n) { var c = new Date(d.getTime()); c.setDate(c.getDate() + n); return c; }
  function today() { var d = new Date(); d.setHours(0, 0, 0, 0); return d; }

  function clock(date) {
    var twelve = state.me && state.me.time_format === "12h";
    return new Intl.DateTimeFormat(state.lang, {
      hour: "2-digit", minute: "2-digit", hour12: twelve
    }).format(date);
  }
  function dayTitle(d) {
    var diff = Math.round((d - today()) / 86400000);
    var long = new Intl.DateTimeFormat(state.lang, { weekday: "long", day: "numeric", month: "long" }).format(d);
    if (diff === 0) return t("today") + " · " + long;
    if (diff === 1) return t("tomorrow") + " · " + long;
    return long;
  }

  function startDate(item) {
    return item.all_day ? fromKey(item.start.slice(0, 10)) : new Date(item.start);
  }
  // The local days an appointment covers (an all-day end is the day after).
  function daysOf(item) {
    var first = startDate(item);
    var last;
    if (item.all_day) last = addDays(fromKey(item.end.slice(0, 10)), -1);
    else last = new Date(new Date(item.end).getTime() - 1);
    var keys = [];
    var d = new Date(first.getFullYear(), first.getMonth(), first.getDate());
    var guard = 0;
    while (d <= last && guard < 62) { keys.push(dayKey(d)); d = addDays(d, 1); guard++; }
    if (!keys.length) keys.push(dayKey(first));
    return keys;
  }

  function show(id) {
    ["screen-loading", "screen-message", "screen-install", "screen-main"].forEach(function (name) {
      $(name).hidden = name !== id;
    });
    $("add-button").hidden = !(id === "screen-main" && canAdd());
  }

  function toast(text) {
    var box = $("toast");
    box.textContent = text;
    box.hidden = false;
    window.clearTimeout(toast.timer);
    toast.timer = window.setTimeout(function () { box.hidden = true; }, 3500);
  }

  function canAdd() {
    return !!(state.me && (state.me.permission === "add" || state.me.permission === "edit_own"));
  }
  function canEdit(item) {
    return !!(state.me && state.me.permission === "edit_own" && item.mine);
  }

  // ----- talking to Family Hub -----------------------------------------------

  function api(method, path, body) {
    var headers = { "Accept": "application/json" };
    if (state.token) headers.Authorization = "Bearer " + state.token;
    if (body !== undefined) headers["Content-Type"] = "application/json";
    return fetch(API + path, {
      method: method,
      headers: headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      cache: "no-store",
      credentials: "omit",
      referrerPolicy: "no-referrer"
    }).then(function (response) {
      return response.json().catch(function () { return {}; }).then(function (data) {
        if (!response.ok) {
          var err = new Error(data.error || "http_" + response.status);
          err.status = response.status;
          err.code = data.error || "";
          throw err;
        }
        return data;
      });
    });
  }

  function isNetwork(err) { return !err || !err.status; }

  // ----- screens ----------------------------------------------------------------

  function message(icon, title, text, retry) {
    stopTimers();
    $("message-icon").textContent = icon;
    $("message-title").textContent = title;
    $("message-text").textContent = text;
    var button = $("message-retry");
    button.hidden = !retry;
    button.textContent = t("retry");
    button.onclick = retry || null;
    $("hello").hidden = true;
    show("screen-message");
  }

  function accessOff() {
    // Nothing of the family stays on a phone that may no longer see it.
    write(KEY_CACHE, null);
    write(KEY_ME, null);
    state.me = null;
    state.events = [];
    message("🔒", t("offTitle"), t("offText"));
    unsubscribeQuietly();
  }

  function waiting() {
    message("⏳", t("waitingTitle"), t("waitingText"));
    state.pendingTimer = window.setTimeout(loadMe, PENDING_POLL_MS);
  }

  function stopTimers() {
    window.clearTimeout(state.pendingTimer);
    window.clearTimeout(state.refreshTimer);
  }

  function installScreen(onContinue) {
    $("install-title").textContent = t("installTitle");
    $("install-intro").textContent = t("installIntro");
    ["iosStep1", "iosStep2", "iosStep3", "iosStep4", "androidStep1", "androidStep2"].forEach(function (key) {
      $(key.replace(/Step/, "-step")).textContent = t(key);
    });
    var ios = isIOS();
    $("install-ios").hidden = !ios;
    $("install-android").hidden = ios;
    $("install-button").textContent = t("installButton");
    $("install-button").hidden = !state.installPrompt;
    $("install-continue").textContent = ios && !standalone() ? t("continueBrowser") : t("continueApp");
    $("install-continue").onclick = onContinue;
    show("screen-install");
  }

  // ----- start --------------------------------------------------------------------

  function readInvite() {
    var match = /[#&]i=([A-Za-z0-9_-]{20,128})/.exec(window.location.hash || "");
    return match ? match[1] : null;
  }

  function forgetInviteInUrl() {
    if (window.location.hash && window.history && window.history.replaceState) {
      window.history.replaceState(null, "", BASE);
    }
  }

  function start() {
    applyStaticTexts();
    registerWorker();
    state.invite = readInvite();
    if (state.token) {
      forgetInviteInUrl();
      loadMe();
      return;
    }
    if (!state.invite) {
      message("✉️", t("noInviteTitle"), t("noInviteText"));
      return;
    }
    if (isIOS() && !standalone()) {
      // On iPhone the app on the Home Screen keeps its own storage: the invite must be used
      // there, not in Safari. Without the manifest, Safari keeps this whole link (with the
      // invite) for the Home Screen icon.
      var link = $("manifest-link");
      if (link) link.parentNode.removeChild(link);
      installScreen(activate);
      return;
    }
    activate();
  }

  function activate() {
    show("screen-loading");
    api("POST", "activate", { token: state.invite }).then(function (data) {
      state.token = data.token;
      write(KEY_TOKEN, data.token);
      state.invite = null;
      forgetInviteInUrl();
      if (!standalone() && !isIOS()) {
        installScreen(loadMe);
      } else {
        loadMe();
      }
    }).catch(function (err) {
      if (isNetwork(err)) {
        message("📶", t("netTitle"), t("netText"), activate);
      } else if (err.status === 429) {
        message("⏱️", t("netTitle"), t("errSlow"), activate);
      } else {
        forgetInviteInUrl();
        message("✉️", t("invalidTitle"), t("invalidText"));
      }
    });
  }

  function loadMe() {
    stopTimers();
    api("GET", "me").then(function (me) {
      if (me.token) {
        state.token = me.token;
        write(KEY_TOKEN, me.token);
      }
      if (me.status === "pending") {
        waiting();
        return;
      }
      if (me.status !== "active") {
        accessOff();
        return;
      }
      state.me = me;
      write(KEY_ME, JSON.stringify(me));
      state.lang = pickLanguage(me.language);
      applyStaticTexts();
      state.offline = false;
      openMain();
    }).catch(function (err) {
      if (isNetwork(err)) {
        if (state.me) {
          state.lang = pickLanguage(state.me.language);
          applyStaticTexts();
          state.offline = true;
          openMain();
        } else {
          message("📶", t("netTitle"), t("netText"), loadMe);
        }
        return;
      }
      if (err.status === 429) {
        state.refreshTimer = window.setTimeout(loadMe, REFRESH_MS);
        return;
      }
      // 401, 403 (disabled, rejected) and 404 (sharing turned off): no more access.
      accessOff();
    });
  }

  // ----- main screen --------------------------------------------------------

  function weekStartOf(d) {
    var first = state.me && state.me.first_weekday === "sunday" ? 0 : 1;
    var day = d.getDay();
    var back = (day - first + 7) % 7;
    return addDays(d, -back);
  }

  function openMain() {
    $("hello").textContent = t("hello", { name: state.me.name || "" });
    $("hello").hidden = false;
    if (!state.weekStart) state.weekStart = weekStartOf(today());
    show("screen-main");
    renderPush();
    $("install-again").hidden = standalone();
    loadEvents();
  }

  function range() {
    if (state.view === "week") return { from: state.weekStart, days: 7 };
    return { from: today(), days: 14 };
  }

  function loadEvents() {
    window.clearTimeout(state.refreshTimer);
    var r = range();
    var key = state.view + ":" + dayKey(r.from);
    api("GET", "events?from=" + dayKey(r.from) + "&days=" + r.days).then(function (data) {
      state.events = data.events || [];
      state.offline = false;
      var cache = readJSON(KEY_CACHE) || {};
      cache[key] = { at: Date.now(), events: state.events };
      // Only the last few views are kept.
      Object.keys(cache).sort(function (a, b) { return cache[b].at - cache[a].at; })
        .slice(6).forEach(function (old) { delete cache[old]; });
      write(KEY_CACHE, JSON.stringify(cache));
      render();
    }).catch(function (err) {
      if (isNetwork(err)) {
        var cache = readJSON(KEY_CACHE) || {};
        state.events = cache[key] ? cache[key].events : [];
        state.offline = true;
        render();
      } else if (err.status !== 429) {
        accessOff();
        return;
      }
    }).then(function () {
      if (!$("screen-main").hidden) state.refreshTimer = window.setTimeout(loadEvents, REFRESH_MS);
    });
  }

  function personOf(id) {
    return (state.me.persons || []).filter(function (p) { return p.id === id; })[0];
  }
  function categoryOf(id) {
    return (state.me.categories || []).filter(function (c) { return c.id === id; })[0];
  }
  function colorOf(item) {
    var person = personOf((item.persons || [])[0]);
    if (person && person.color) return person.color;
    var category = categoryOf(item.category);
    return category && category.color ? category.color : "";
  }

  function render() {
    $("offline").textContent = t("offline");
    $("offline").hidden = !state.offline;
    $("tab-list").setAttribute("aria-selected", state.view === "list" ? "true" : "false");
    $("tab-week").setAttribute("aria-selected", state.view === "week" ? "true" : "false");
    $("week-nav").hidden = state.view !== "week";
    var r = range();
    if (state.view === "week") {
      var fmt = new Intl.DateTimeFormat(state.lang, { day: "numeric", month: "short" });
      $("week-range").textContent = fmt.format(r.from) + " – " + fmt.format(addDays(r.from, 6));
    }
    var byDay = {};
    state.events.forEach(function (item) {
      daysOf(item).forEach(function (key) { (byDay[key] = byDay[key] || []).push(item); });
    });
    var box = $("days");
    box.textContent = "";
    var todayKey = dayKey(today());
    var shown = 0;
    for (var i = 0; i < r.days; i++) {
      var d = addDays(r.from, i);
      var key = dayKey(d);
      var items = byDay[key] || [];
      if (state.view === "list" && !items.length) continue;
      shown += items.length;
      var section = el("section", { class: "day" + (key === todayKey ? " today" : "") }, [
        el("h3", { text: dayTitle(d) })
      ]);
      if (!items.length) section.appendChild(el("p", { class: "empty", text: t("nothingDay") }));
      items.forEach(function (item) { section.appendChild(eventCard(item)); });
      box.appendChild(section);
    }
    if (state.view === "list" && !shown) box.appendChild(el("p", { class: "big-note", text: t("nothingDays") }));
  }

  function whenText(item) {
    if (item.all_day) return t("allDay");
    return clock(new Date(item.start)) + " – " + clock(new Date(item.end));
  }

  function personChips(item) {
    return el("div", { class: "persons" }, (item.persons || []).map(function (id) {
      var person = personOf(id);
      if (!person) return null;
      var dot = el("span", { class: "dot" });
      if (person.color) dot.style.background = person.color;
      return el("span", { class: "person" }, [dot, person.name]);
    }));
  }

  function eventCard(item) {
    var card = el("button", { type: "button", class: "event", onclick: function () { openDetail(item); } }, [
      el("div", { class: "event-time" }, [whenText(item),
        item.status === "pending" ? el("span", { class: "badge", text: t("pending") }) : null]),
      el("div", { class: "event-title", text: item.title }),
      personChips(item),
      item.location ? el("div", { class: "event-meta", text: "📍 " + item.location }) : null,
      item.added_by ? el("div", { class: "event-meta", text: t("addedBy", { name: item.added_by }) }) : null
    ]);
    var color = colorOf(item);
    if (color) card.style.borderLeftColor = color;
    return card;
  }

  // ----- sheets ------------------------------------------------------------------

  function openSheet(title, body, actions) {
    $("sheet-title").textContent = title;
    var box = $("sheet-body");
    box.textContent = "";
    box.appendChild(body);
    $("sheet-error").hidden = true;
    var foot = $("sheet-actions");
    foot.textContent = "";
    actions.forEach(function (a) { foot.appendChild(a); });
    $("sheet").hidden = false;
    $("add-button").hidden = true;
    var first = box.querySelector("input, button") || foot.querySelector("button");
    if (first) first.focus();
  }
  function closeSheet() {
    $("sheet").hidden = true;
    $("add-button").hidden = !canAdd() || $("screen-main").hidden;
  }
  function sheetError(text) {
    $("sheet-error").textContent = text;
    $("sheet-error").hidden = false;
  }

  function openDetail(item) {
    var category = categoryOf(item.category);
    var day = new Intl.DateTimeFormat(state.lang, { weekday: "long", day: "numeric", month: "long" })
      .format(startDate(item));
    var body = el("div", { class: "detail" }, [
      el("p", {}, [day + " · " + whenText(item),
        item.status === "pending" ? el("span", { class: "badge", text: t("pending") }) : null]),
      personChips(item),
      category ? el("p", { text: "🗂️ " + category.name }) : null,
      item.location ? el("p", { text: "📍 " + item.location }) : null,
      item.note ? el("p", { text: "📝 " + item.note }) : null,
      item.added_by ? el("p", { class: "event-meta", text: t("addedBy", { name: item.added_by }) }) : null
    ]);
    var actions = [];
    if (canEdit(item) && !state.offline) {
      actions.push(el("button", { type: "button", class: "btn btn-primary", text: t("edit"),
        onclick: function () { openForm(item); } }));
      actions.push(el("button", { type: "button", class: "btn btn-danger", text: t("remove"),
        onclick: function () { removeItem(item); } }));
    }
    actions.push(el("button", { type: "button", class: "btn", text: t("close"), onclick: closeSheet }));
    openSheet(item.title, body, actions);
  }

  function chips(name, options, chosen) {
    var group = el("div", { class: "chips", role: "group", "data-name": name });
    options.forEach(function (option) {
      var dot = el("span", { class: "dot" });
      if (option.color) dot.style.background = option.color;
      var chip = el("button", {
        type: "button", class: "chip", "data-value": option.id,
        "aria-pressed": option.id === chosen ? "true" : "false",
        onclick: function () {
          Array.prototype.forEach.call(group.children, function (c) { c.setAttribute("aria-pressed", "false"); });
          chip.setAttribute("aria-pressed", "true");
        }
      }, [dot, option.name]);
      group.appendChild(chip);
    });
    return group;
  }
  function chosenChip(group) {
    var on = group.querySelector('[aria-pressed="true"]');
    return on ? on.getAttribute("data-value") : "";
  }

  function hhmm(date) { return pad(date.getHours()) + ":" + pad(date.getMinutes()); }

  function openForm(item) {
    var persons = state.me.persons || [];
    var categories = state.me.categories || [];
    var start = item ? startDate(item) : null;
    var now = new Date();
    var defaultStart = pad(Math.min(now.getHours() + 1, 23)) + ":00";
    var title = el("input", { type: "text", id: "f-title", maxlength: "80", value: item ? item.title : "",
      autocomplete: "off" });
    var personGroup = chips("person", persons, item ? (item.persons || [])[0] : (persons.length === 1 ? persons[0].id : ""));
    var categoryGroup = chips("category", categories, item ? item.category : (categories.length === 1 ? categories[0].id : ""));
    var dateInput = el("input", { type: "date", id: "f-date", value: dayKey(start || today()) });
    var allDay = el("input", { type: "checkbox", id: "f-allday" });
    allDay.checked = !!(item && item.all_day);
    var startInput = el("input", { type: "time", id: "f-start",
      value: item && !item.all_day ? hhmm(start) : defaultStart });
    var endInput = el("input", { type: "time", id: "f-end",
      value: item && !item.all_day ? hhmm(new Date(item.end)) : pad(Math.min(Number(defaultStart.slice(0, 2)) + 1, 23)) + ":" + (defaultStart.slice(0, 2) === "23" ? "59" : "00") });
    var times = el("div", { class: "row" }, [
      el("label", { class: "field" }, [el("span", { text: t("fStart") }), startInput]),
      el("label", { class: "field" }, [el("span", { text: t("fEnd") }), endInput])
    ]);
    times.hidden = allDay.checked;
    allDay.addEventListener("change", function () { times.hidden = allDay.checked; });
    var location = el("input", { type: "text", id: "f-location", maxlength: "100", value: item ? item.location : "" });
    var note = el("textarea", { id: "f-note", maxlength: "500" });
    note.value = item && item.note ? item.note : "";
    var body = el("div", {}, [
      el("label", { class: "field" }, [el("span", { text: t("fTitle") }), title]),
      el("div", { class: "field" }, [el("span", { text: t("fPerson") }), personGroup]),
      el("div", { class: "field" }, [el("span", { text: t("fCalendar") }), categoryGroup]),
      el("label", { class: "field" }, [el("span", { text: t("fDate") }), dateInput]),
      el("label", { class: "check" }, [allDay, t("fAllDay")]),
      times,
      el("label", { class: "field" }, [el("span", { text: t("fLocation") }), location]),
      el("label", { class: "field" }, [el("span", { text: t("fNote") }), note])
    ]);
    var save = el("button", { type: "button", class: "btn btn-primary", id: "f-save", text: t("save") });
    save.addEventListener("click", function () {
      var data = {
        title: title.value.trim(),
        person: chosenChip(personGroup),
        category: chosenChip(categoryGroup),
        date: dateInput.value,
        all_day: allDay.checked,
        location: location.value.trim(),
        note: note.value.trim()
      };
      if (!data.all_day) { data.start = startInput.value; data.end = endInput.value; }
      if (!data.title) { sheetError(t("errTitle")); return; }
      if (!data.person || !data.category || !data.date) { sheetError(t("errSave")); return; }
      if (!data.all_day && !(data.start && data.end && data.end > data.start)) { sheetError(t("errTime")); return; }
      save.disabled = true;
      var call = item ? api("PUT", "events/" + item.id, data) : api("POST", "events", data);
      call.then(function (answer) {
        closeSheet();
        var pending = answer.event && answer.event.status === "pending";
        toast(item ? t("saved") : (pending ? t("sentPending") : t("added")));
        loadEvents();
      }).catch(function (err) {
        save.disabled = false;
        if (err.status === 403 && /disabled|rejected|unknown/.test(err.code)) { closeSheet(); accessOff(); return; }
        sheetError(err.status === 403 ? t("errForbidden") : err.status === 429 ? t("errSlow") : t("errSave"));
      });
    });
    openSheet(item ? t("editTitle") : t("addTitle"), body, [
      save,
      el("button", { type: "button", class: "btn", text: t("cancel"), onclick: closeSheet })
    ]);
  }

  function removeItem(item) {
    if (!window.confirm(t("removeAsk"))) return;
    api("DELETE", "events/" + item.id).then(function () {
      closeSheet();
      toast(t("removed"));
      loadEvents();
    }).catch(function (err) {
      sheetError(err.status === 403 ? t("errForbidden") : t("errSave"));
    });
  }

  // ----- notifications --------------------------------------------------------

  function pushSupported() {
    return "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;
  }

  function keyBytes(text) {
    var padded = (text + "===".slice((text.length + 3) % 4)).replace(/-/g, "+").replace(/_/g, "/");
    var raw = window.atob(padded);
    var bytes = new Uint8Array(raw.length);
    for (var i = 0; i < raw.length; i++) bytes[i] = raw.charCodeAt(i);
    return bytes;
  }

  function renderPush() {
    var box = $("push-box");
    box.textContent = "";
    if (!state.me || !state.me.notify || !state.me.vapid) return;
    if (!pushSupported()) {
      box.appendChild(el("p", { class: "note-box", text: isIOS() ? t("pushIos") : t("pushNone") }));
      return;
    }
    if (window.Notification.permission === "denied") {
      box.appendChild(el("p", { class: "note-box", text: t("pushDenied") }));
      return;
    }
    if (state.me.push) {
      box.appendChild(el("p", { class: "note-box", text: t("pushActive") }));
      box.appendChild(el("button", { type: "button", class: "btn", id: "push-off", text: t("pushOff"), onclick: pushOff }));
      return;
    }
    box.appendChild(el("button", { type: "button", class: "btn btn-primary", id: "push-on", text: t("pushOn"), onclick: pushOn }));
    if (isIOS()) box.appendChild(el("p", { class: "note-box", text: t("pushIos") }));
  }

  function pushOn() {
    // Asked only here, after a tap: never when the app opens.
    window.Notification.requestPermission().then(function (answer) {
      if (answer !== "granted") { renderPush(); throw new Error("denied"); }
      return navigator.serviceWorker.ready;
    }).then(function (registration) {
      return registration.pushManager.subscribe({
        userVisibleOnly: true, applicationServerKey: keyBytes(state.me.vapid)
      });
    }).then(function (subscription) {
      return api("POST", "push", { subscription: subscription.toJSON() });
    }).then(function (answer) {
      state.me.push = !!answer.push;
      write(KEY_ME, JSON.stringify(state.me));
      renderPush();
    }).catch(function (err) {
      if (err && err.message !== "denied") toast(t("pushError"));
    });
  }

  function unsubscribeQuietly() {
    if (!("serviceWorker" in navigator)) return;
    navigator.serviceWorker.getRegistration(BASE).then(function (registration) {
      if (!registration || !registration.pushManager) return null;
      return registration.pushManager.getSubscription();
    }).then(function (subscription) {
      if (subscription) return subscription.unsubscribe();
      return null;
    }).catch(function () { /* nothing to undo */ });
  }

  function pushOff() {
    api("DELETE", "push").then(function () {
      unsubscribeQuietly();
      state.me.push = false;
      write(KEY_ME, JSON.stringify(state.me));
      renderPush();
    }).catch(function () { toast(t("pushError")); });
  }

  // ----- installing ------------------------------------------------------------

  function registerWorker() {
    if (!("serviceWorker" in navigator)) return;
    navigator.serviceWorker.register(BASE + "sw.js", { scope: BASE }).catch(function () {
      /* without it the app still works, only not offline */
    });
  }

  window.addEventListener("beforeinstallprompt", function (event) {
    event.preventDefault();
    state.installPrompt = event;
    $("install-button").hidden = false;
  });

  function install() {
    if (!state.installPrompt) return;
    state.installPrompt.prompt();
    state.installPrompt.userChoice.then(function () {
      state.installPrompt = null;
      $("install-button").hidden = true;
    });
  }

  // ----- fixed texts and buttons ------------------------------------------------

  function applyStaticTexts() {
    document.documentElement.lang = state.lang;
    $("loading-text").textContent = t("loading");
    $("tab-list").textContent = t("upcoming");
    $("tab-week").textContent = t("week");
    $("add-button").textContent = t("add");
    $("install-again").textContent = t("installAgain");
  }

  $("tab-list").addEventListener("click", function () { state.view = "list"; render(); loadEvents(); });
  $("tab-week").addEventListener("click", function () { state.view = "week"; render(); loadEvents(); });
  $("week-prev").addEventListener("click", function () { state.weekStart = addDays(state.weekStart, -7); render(); loadEvents(); });
  $("week-next").addEventListener("click", function () { state.weekStart = addDays(state.weekStart, 7); render(); loadEvents(); });
  $("add-button").addEventListener("click", function () { openForm(null); });
  $("install-button").addEventListener("click", install);
  $("install-again").addEventListener("click", function () { installScreen(openMain); });
  $("sheet").addEventListener("click", function (event) { if (event.target === $("sheet")) closeSheet(); });
  document.addEventListener("keydown", function (event) { if (event.key === "Escape" && !$("sheet").hidden) closeSheet(); });
  document.addEventListener("visibilitychange", function () {
    // Back on screen: ask at once, so a disabled phone shows it without waiting.
    if (document.visibilityState === "visible" && state.token && !$("screen-main").hidden) loadMe();
  });
  window.addEventListener("online", function () { if (state.token) loadMe(); });

  start();
})();
