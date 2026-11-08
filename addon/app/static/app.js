/* Family Hub tablet UI. Talks only to the add-on server (/ws), which relays to Home Assistant. */
(function () {
  "use strict";

  var I = window.FH_I18N;
  var t = I.t;
  var PALETTE = ["#2563EB", "#059669", "#DC2626", "#D97706", "#7C3AED", "#DB2777"];

  var state = {
    ws: null,
    pending: {},
    nextId: 1,
    reconnectDelay: 1000,
    connected: false,
    calendars: [],
    hidden: {},
    events: {},
    weekFromToday: true,
    weekStart: viewStart(new Date()),
    view: loadView(),
    monthLoaded: {},
    monthLoading: {},
    monthObserver: null,
    listWaste: false,
    monthStart: firstOfMonth(new Date()),
    monthPerson: "",
    popups: [],
    wizardStep: 0,
    mode: layoutMode(),
    upcoming: {},
    statusTimer: null,
    draft: null,
    dayOffset: 0,
    shiftData: null,
    shiftPerson: null,
    shiftMonth: new Date(new Date().getFullYear(), new Date().getMonth(), 1),
    shiftMarks: {},
    shiftSelected: {},
    shiftChoice: "",
    todoLists: [],
    role: null,
    refreshTimer: null,
    // The family's clock ("24h" or "12h"), sent by the server; every time on screen follows it.
    timeFormat: "24h",
    notifyData: null,
    notifyServices: { phone: [], alexa: [] },
    notifyUsers: [],
    weather: null,
    me: null,
    editing: null,
    cardItem: null
  };

  // ---- small helpers -------------------------------------------------------

  function pad(n) { return n < 10 ? "0" + n : "" + n; }

  function ymd(d) { return d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate()); }

  // Days from the first day of the week (the family's setting; Monday until it is known).
  // (state is not built yet when the first week is computed, hence the guard.)
  function weekdayOffset(d) {
    var sunday = !!state && state.firstWeekday === "sunday";
    return sunday ? d.getDay() : (d.getDay() + 6) % 7;
  }

  // The short day names (Monday first in the translations) in the order of the family's week.
  function orderedDays(names) {
    var offset = state.firstWeekday === "sunday" ? 6 : 0;
    return names.slice(offset).concat(names.slice(0, offset));
  }

  function mondayOf(d) {
    var x = new Date(d.getFullYear(), d.getMonth(), d.getDate());
    x.setDate(x.getDate() - weekdayOffset(x));
    return x;
  }

  // The first day of the grid: today on the tablet's "week starts today" setting (the default),
  // otherwise the family's first day. (state is not built yet when the first week is computed.)
  function viewStart(d) {
    if (!state || state.weekFromToday !== false) {
      return new Date(d.getFullYear(), d.getMonth(), d.getDate());
    }
    return mondayOf(d);
  }

  function addDays(d, n) {
    var x = new Date(d.getFullYear(), d.getMonth(), d.getDate());
    x.setDate(x.getDate() + n);
    return x;
  }

  function isAllDay(start) { return start.length === 10; }

  function dayKey(start) { return isAllDay(start) ? start : ymd(new Date(start)); }

  function timeOf(start) {
    if (isAllDay(start)) return t("allDay");
    var d = new Date(start);
    return showTime(pad(d.getHours()) + ":" + pad(d.getMinutes()), state.timeFormat);
  }

  // Dates are always day/month/year on screen; they are stored as yyyy-mm-dd.
  function showDate(isoDay) {
    var parts = isoDay.split("-");
    return parts[2] + "/" + parts[1] + "/" + parts[0];
  }

  function parseDate(text) {
    var m = /^\s*(\d{1,2})[./-](\d{1,2})[./-](\d{4})\s*$/.exec(text || "");
    if (!m) return null;
    var day = parseInt(m[1], 10);
    var month = parseInt(m[2], 10);
    var year = parseInt(m[3], 10);
    var check = new Date(year, month - 1, day);
    if (check.getFullYear() !== year || check.getMonth() !== month - 1 || check.getDate() !== day) {
      return null;
    }
    return year + "-" + pad(month) + "-" + pad(day);
  }

  function el(tag, attrs, text) {
    var node = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (key) { node.setAttribute(key, attrs[key]); });
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function $(id) { return document.getElementById(id); }


  // ---- connection to the add-on server ---------------------------------------

  function connect() {
    var url = new URL("ws", window.location.href);
    url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
    var ws = new WebSocket(url.href);
    state.ws = ws;
    ws.onopen = function () {
      state.reconnectDelay = 1000;
      setConnected(true);
      refreshCalendars();
    };
    ws.onclose = function () {
      setConnected(false);
      Object.keys(state.pending).forEach(function (id) {
        state.pending[id]({ ok: false, error: "offline" });
        delete state.pending[id];
      });
      window.setTimeout(connect, state.reconnectDelay);
      state.reconnectDelay = Math.min(state.reconnectDelay * 2, 30000);
    };
    ws.onmessage = function (message) { onMessage(JSON.parse(message.data)); };
  }

  function onMessage(msg) {
    if (msg.type === "result") {
      var done = state.pending[msg.id];
      delete state.pending[msg.id];
      if (done) done(msg);
    } else if (msg.type === "identity") {
      state.role = msg.role;
      state.me = msg;
      // Guests only read: no add button for them. Until Home Assistant answers (pending), the
      // tablet offers nothing either, and it is told again once the connection is there.
      var limited = msg.role === "guest" || msg.role === "pending";
      $("add-btn").hidden = limited;
      $("wizard-start").hidden = msg.role !== "adult";
      $("menu-wizard").hidden = msg.role !== "adult";
      $("menu-shifts").hidden = limited;
      $("menu-notify").hidden = limited;
      $("menu-ics").hidden = msg.role !== "adult";
      $("menu-btn").hidden = limited;
      if (msg.role === "adult") openGuideIfNeeded();
      // A guest is told why nothing can be changed; while waiting for Home Assistant, that.
      var guestNote = $("guest-note");
      guestNote.hidden = !limited;
      guestNote.textContent = msg.role === "pending"
        ? I.f("connecting")
        : msg.role === "guest"
          ? I.f("guestNote").replace("{name}", msg.user_name || "Home Assistant")
          : "";
    } else if (msg.type === "theme") {
      applyTheme(msg.theme);
      if (msg.time_format) state.timeFormat = msg.time_format;
      if (msg.first_weekday && msg.first_weekday !== state.firstWeekday) {
        state.firstWeekday = msg.first_weekday;
        state.weekStart = viewStart(new Date());
      }
      var fromToday = msg.week_from_today !== false;
      if (fromToday !== state.weekFromToday) {
        state.weekFromToday = fromToday;
        state.weekStart = viewStart(new Date());
      }
      if (state.events) renderWeek();
    } else if (msg.type === "connection") {
      setConnected(msg.connected);
      if (msg.connected) refreshCalendars();
    } else if (msg.type === "state_changed") {
      scheduleRefresh();
      loadWeather();
      if (!$("todo-overlay").hidden) loadTodos();
    } else if (msg.type === "event") {
      if (msg.event_type === "family_hub_reminder") showReminder(msg.data);
      if (msg.event_type === "family_hub_reminder_closed") closeReminder(msg.data.uid);
    }
  }

  function request(payload) {
    return new Promise(function (resolve, reject) {
      if (!state.ws || state.ws.readyState !== WebSocket.OPEN) {
        var offline = new Error("offline");
        offline.code = "offline";
        reject(offline);
        return;
      }
      var id = state.nextId++;
      state.pending[id] = function (msg) {
        if (msg.ok) {
          resolve(msg.result);
        } else {
          var failure = new Error(msg.detail || msg.error || "error");
          failure.code = msg.error || "unknown";
          reject(failure);
        }
      };
      state.ws.send(JSON.stringify(Object.assign({ id: id }, payload)));
    });
  }

  function openGuideIfNeeded() {
    request({ op: "config_get" }).then(function (config) {
      if (!config.configured) openWizard(0);
    }).catch(function () { /* no Family Hub entry yet: the status line says so */ });
  }

  function setConnected(on) {
    state.connected = on;
    $("conn-dot").className = "dot " + (on ? "ok" : "bad");
    $("conn-text").textContent = on ? t("connected") : t("offline");
  }

  // ---- data ----------------------------------------------------------------

  function refreshCalendars() {
    loadWeather();
    request({ op: "calendars" }).then(function (calendars) {
      state.calendars = calendars;
      calendars.forEach(function (cal, index) {
        cal.color = cal.external ? "#64748B" : PALETTE[index % PALETTE.length];
      });
      renderFilters();
      fillCategorySelect();
      if (calendars.length === 0) {
        $("empty-note").textContent = t("noCalendars");
        $("empty-note").hidden = false;
        // Opening the guide is decided by Home Assistant's "configured" flag (see openGuideIfNeeded).
      } else {
        $("empty-note").hidden = true;
      }
      refreshEvents();
    }).catch(function () { /* offline: the status line already says so */ });
  }

  function refreshEvents() {
    var now = new Date();
    var start, end;
    if (state.view === "month") {
      // Months are read as they come near the screen (see watchMonths).
      loadPickups();
      state.monthLoaded = {};
      state.monthLoading = {};
      renderWeek();
      return;
    }
    if (state.view === "list") {
      loadPickups();
      var from = new Date(now.getFullYear(), now.getMonth(), now.getDate());
      var to = new Date(from.getFullYear() + 1, from.getMonth(), from.getDate());
      request({ op: "events", start: ymd(from) + " 00:00:00", end: ymd(to) + " 00:00:00" })
        .then(function (events) { state.events = events; renderWeek(); })
        .catch(function () { renderWeek(); });
      return;
    }
    if (state.mode === "phone") {
      start = ymd(addDays(now, state.dayOffset)) + " 00:00:00";
      end = ymd(addDays(now, state.dayOffset + 2)) + " 00:00:00";
    } else {
      start = ymd(state.weekStart) + " 00:00:00";
      end = ymd(addDays(state.weekStart, 7)) + " 00:00:00";
    }
    loadPickups();
    request({ op: "events", start: start, end: end }).then(function (events) {
      state.events = events;
      if (state.mode === "pc") refreshUpcoming();
      else renderWeek();
    }).catch(function () { renderWeek(); });
  }

  // Rubbish pickups of the next seven days, as the TrashCard shows them.
  function loadPickups() {
    var today = new Date();
    var start = ymd(today) + " 00:00:00";
    var end = ymd(addDays(today, 7)) + " 00:00:00";
    request({ op: "events", start: start, end: end }).then(function (events) {
      var found = [];
      Object.keys(events).forEach(function (entity) {
        (events[entity] || []).forEach(function (ev) { if (ev.waste) found.push(ev); });
      });
      found.sort(function (a, b) { return String(a.start).localeCompare(String(b.start)); });
      renderPickups(found);
    }).catch(function () { renderPickups([]); });
  }

  function renderPickups(list) {
    var box = $("pickups");
    if (!box) return;
    box.textContent = "";
    box.hidden = list.length === 0;
    if (!list.length) return;
    box.appendChild(el("span", { class: "pickups-title" }, I.f("pickupsTitle")));
    var today = new Date(ymd(new Date()) + "T00:00:00");
    var seen = {};
    list.forEach(function (ev) {
      var day = String(ev.start).slice(0, 10);
      var key = day + "|" + (ev.waste_label || ev.summary);
      if (seen[key]) return;
      seen[key] = true;
      var days = Math.round((new Date(day + "T00:00:00") - today) / 86400000);
      var when = days <= 0 ? I.f("pickupToday") : days === 1 ? I.f("pickupTomorrow")
        : I.f("pickupInDays").replace("{n}", String(days));
      var chip = el("span", { class: "pickup-chip" + (days <= 0 ? " soon" : "") });
      chip.style.setProperty("--ev", ev.waste_color || "#9C27B0");
      chip.appendChild(wasteIcon(ev.waste_icon || ev.waste));
      chip.appendChild(el("span", { class: "pickup-label" }, ev.waste_label || ev.summary));
      chip.appendChild(el("span", { class: "pickup-when" }, when));
      box.appendChild(chip);
    });
  }

  function refreshUpcoming() {
    var now = new Date();
    request({ op: "events", start: ymd(now) + " 00:00:00", end: ymd(addDays(now, 14)) + " 00:00:00" })
      .then(function (events) { state.upcoming = events; renderWeek(); })
      .catch(function () { renderWeek(); });
  }

  // Theme chosen in the setup guide: "light" or "dark"; "auto" follows the system.
  function applyTheme(theme) {
    var root = document.documentElement;
    if (theme === "light" || theme === "dark") root.setAttribute("data-theme", theme);
    else root.removeAttribute("data-theme");
  }

  // Server error codes -> text in the user's language.
  function errorText(err) {
    var key = "err_" + (err && err.code ? err.code : "unknown");
    var text = I.f(key);
    return text === key ? I.f("err_unknown") : text;
  }

  function scheduleRefresh() {
    window.clearTimeout(state.refreshTimer);
    state.refreshTimer = window.setTimeout(refreshCalendars, 250);
  }

  function refreshAll() { refreshCalendars(); }

  // ---- week view -------------------------------------------------------------

  function renderFilters() {
    var box = $("filters");
    box.textContent = "";
    var family = state.calendars.filter(function (cal) { return !cal.external; });
    var others = state.calendars.filter(function (cal) { return cal.external; });
    family.forEach(function (cal) { box.appendChild(filterChip(cal)); });
    if (others.length === 0) return;
    var toggle = el("button", {
      type: "button",
      class: "chip more-toggle",
      "aria-expanded": state.moreOpen ? "true" : "false"
    }, I.f("moreCalendars").replace("{n}", String(others.length)));
    toggle.addEventListener("click", function () {
      state.moreOpen = !state.moreOpen;
      renderFilters();
    });
    box.appendChild(toggle);
    if (state.moreOpen) {
      var panel = el("div", { class: "more-calendars" });
      others.forEach(function (cal) {
        panel.appendChild(switchRow(cal.name, !state.hidden[cal.entity_id], function (on) {
          state.hidden[cal.entity_id] = !on;
          renderWeek();
        }));
      });
      box.appendChild(panel);
    }
  }

  function filterChip(cal) {
    var on = !state.hidden[cal.entity_id];
    var chip = el("button", {
      type: "button",
      class: "chip" + (on ? " on" : ""),
      "aria-pressed": on ? "true" : "false"
    });
    chip.style.setProperty("--chip", cal.color);
    chip.appendChild(el("span", { class: "swatch", "aria-hidden": "true" }));
    chip.appendChild(document.createTextNode(cal.name));
    chip.addEventListener("click", function () {
      state.hidden[cal.entity_id] = on;
      renderFilters();
      renderWeek();
    });
    return chip;
  }

  // ---- layouts: phone (agenda), tablet (week), pc (week + upcoming) --------------

  function layoutMode() {
    var width = window.innerWidth;
    if (width < 600) return "phone";
    if (width >= 1200) return "pc";
    return "tablet";
  }

  function visibleCalendars() {
    return state.calendars.filter(function (cal) { return !state.hidden[cal.entity_id]; });
  }

  // Events of the visible calendars, grouped by local day and sorted by start.
  // Events by day. The same event in more than one calendar (same title, start and end) is
  // listed once, with the colours of all its calendars and the persons of all of them.
  function eventsByDay(source) {
    var byDay = {};
    var seen = {};
    visibleCalendars().forEach(function (cal) {
      (source[cal.entity_id] || []).forEach(function (ev) {
        var key = String(ev.summary).trim() + "|" + String(ev.start).slice(0, 16) + "|" + String(ev.end).slice(0, 16);
        var color = ev.waste_color || cal.color;
        var twin = seen[key];
        if (twin) {
          if (twin.colors.indexOf(color) === -1) twin.colors.push(color);
          var ids = (twin.ev.person_ids || []).slice();
          (ev.person_ids || []).forEach(function (id) { if (ids.indexOf(id) === -1) ids.push(id); });
          // No persons on one copy means the family's: it stays the family's.
          if (!(twin.ev.person_ids || []).length || !(ev.person_ids || []).length) ids = [];
          twin.ev = Object.assign({}, twin.ev, { person_ids: ids });
          return;
        }
        var item = { ev: ev, color: cal.color, colors: [color], type: cal.external ? (cal.type || "altro") : "" };
        seen[key] = item;
        (byDay[dayKey(ev.start)] = byDay[dayKey(ev.start)] || []).push(item);
      });
    });
    Object.keys(byDay).forEach(function (key) {
      byDay[key].sort(compareItems);
    });
    return byDay;
  }

  // Order within a day: all-day first, then by start time, then by title. Times are compared
  // as moments, not as text, because the events come in more than one text format.
  function compareItems(a, b) {
    var allA = isAllDay(a.ev.start) ? 0 : 1;
    var allB = isAllDay(b.ev.start) ? 0 : 1;
    if (allA !== allB) return allA - allB;
    var ta = allA === 0 ? 0 : new Date(a.ev.start).getTime();
    var tb = allB === 0 ? 0 : new Date(b.ev.start).getTime();
    if (ta !== tb) return ta - tb;
    return String(a.ev.summary).localeCompare(String(b.ev.summary), I.lang);
  }

  // The day number; today's number sits in a red circle.
  function dayNumber(text, isToday) {
    var num = el("span", { class: "day-num" });
    num.appendChild(el("span", { class: isToday ? "today-num" : "" }, text));
    return num;
  }

  // An all-day event: one row with an icon (rubbish or calendar) and the name. On the tablet and
  // PC the name is cut with dots and shown whole on hover; on the phone it wraps.
  function allDayRow(item) {
    var phone = state.mode === "phone";
    var row = el("div", { class: "event allday" + (phone ? " allday-wrap" : "") });
    row.style.setProperty("--ev", item.ev.waste_color || item.color);
    if (item.ev.waste) row.appendChild(wasteIcon(item.ev.waste_icon || item.ev.waste));
    else if (item.ev.external) row.appendChild(iconSvg("calendar"));
    row.appendChild(el("span", { class: "allday-name", title: item.ev.summary }, shownTitle(item.ev)));
    if ((item.colors || []).length > 1) row.appendChild(calendarDots(item));
    if (item.ev.waste) {
      row.classList.add("waste-pill");
      row.setAttribute("aria-label", shownTitle(item.ev));
    }
    row.setAttribute("role", "button");
    row.setAttribute("tabindex", "0");
    row.addEventListener("click", function () { openCard(item); });
    return row;
  }

  // A rubbish pickup is shown as its type ("Organico"), as in the TrashCard; others by title.
  function shownTitle(ev) {
    return ev.waste_label || ev.summary;
  }

  function calendarDots(item) {
    var dots = el("span", { class: "cal-dots", "aria-hidden": "true" });
    (item.colors || []).slice(1).forEach(function (color) {
      var dot = el("span", { class: "cal-dot" });
      dot.style.background = color;
      dots.appendChild(dot);
    });
    return dots;
  }

  function eventRow(item) {
    if (isAllDay(item.ev.start)) return allDayRow(item);
    var row = el("div", { class: "event" });
    row.style.setProperty("--ev", item.ev.waste_color || item.color);
    if (item.ev.external) row.classList.add("external");
    row.appendChild(el("span", { class: "ev-time" }, timeOf(item.ev.start)));
    var title = el("span", { class: "ev-title" });
    if (item.ev.waste) {
      title.appendChild(wasteIcon(item.ev.waste_icon || item.ev.waste));
      row.classList.add("waste-pill");
      row.setAttribute("aria-label", shownTitle(item.ev));
    }
    title.appendChild(document.createTextNode(shownTitle(item.ev)));
    row.appendChild(title);
    if ((item.colors || []).length > 1) row.appendChild(calendarDots(item));
    row.setAttribute("role", "button");
    row.setAttribute("tabindex", "0");
    row.addEventListener("click", function () { openCard(item); });
    return row;
  }

  // A rubbish pill whose type name does not fit ("Org…") shows only a big icon in its colour;
  // the whole name is in its label and on the card that a tap opens.
  function fitWastePills(root) {
    Array.prototype.forEach.call(root.querySelectorAll(".event.waste-pill"), function (row) {
      row.classList.remove("icon-only");
      var name = row.querySelector(".allday-name, .ev-title");
      if (name && name.scrollWidth > name.clientWidth + 1) {
        row.classList.add("icon-only");
        row.setAttribute("title", row.getAttribute("aria-label") || name.textContent);
      }
    });
  }

  function renderWeek() {
    var week = $("week");
    week.textContent = "";
    var anyEvent;
    if (state.view === "month" || state.view === "list") {
      if (state.view === "month") renderMonth(week);
      else renderList(week);
      $("empty-note").hidden = true;
      return;
    }
    window.requestAnimationFrame(function () { fitWastePills(week); });
    if (state.mode === "phone") {
      week.className = "week agenda";
      anyEvent = renderAgenda(week);
    } else {
      week.className = "week";
      anyEvent = renderGrid(week);
    }
    renderUpcoming();
    var note = $("empty-note");
    if (state.calendars.length > 0) {
      note.textContent = anyEvent ? "" : t("noEvents");
      note.hidden = anyEvent;
    }
  }

  function renderGrid(week) {
    var today = ymd(new Date());
    var byDay = eventsByDay(state.events);
    var anyEvent = false;
    for (var i = 0; i < 7; i++) {
      var day = addDays(state.weekStart, i);
      var key = ymd(day);
      var column = el("section", { class: "day" + (key === today ? " today" : ""), "aria-label": key });
      var head = el("header", { class: "day-head" });
      // From today, the names follow the dates; otherwise the family's week order.
      var dayName = state.weekFromToday
        ? day.toLocaleDateString(I.lang, { weekday: "short" })
        : orderedDays(t("days"))[i];
      head.appendChild(el("span", { class: "day-name" }, dayName));
      head.appendChild(dayNumber(String(day.getDate()), key === today));
      var wx = dayWeather(key);
      if (wx) head.appendChild(wx);
      column.appendChild(head);
      (byDay[key] || []).forEach(function (item) {
        anyEvent = true;
        column.appendChild(eventRow(item));
      });
      week.appendChild(column);
    }
    return anyEvent;
  }

  // Phone: today and tomorrow, one list.
  function renderAgenda(week) {
    var byDay = eventsByDay(state.events);
    var anyEvent = false;
    for (var i = 0; i < 2; i++) {
      var day = addDays(new Date(), state.dayOffset + i);
      var key = ymd(day);
      var section = el("section", { class: "day", "aria-label": key });
      var head = el("header", { class: "day-head" });
      var label = state.dayOffset + i === 0 ? t("today")
        : state.dayOffset + i === 1 ? I.f("tomorrowLabel")
        : day.toLocaleDateString(I.lang, { weekday: "long" });
      head.appendChild(el("span", { class: "day-name" }, label));
      head.appendChild(dayNumber(day.toLocaleDateString(I.lang, { day: "numeric", month: "short" }), key === ymd(new Date())));
      var agendaWx = dayWeather(key);
      if (agendaWx) head.appendChild(agendaWx);
      section.appendChild(head);
      (byDay[key] || []).forEach(function (item) {
        anyEvent = true;
        section.appendChild(eventRow(item));
      });
      week.appendChild(section);
    }
    return anyEvent;
  }

  // PC: the next fourteen days beside the week.
  function renderUpcoming() {
    var box = $("upcoming");
    box.textContent = "";
    box.hidden = state.mode !== "pc";
    if (state.mode !== "pc") return;
    box.appendChild(el("h2", {}, I.f("upcomingTitle")));
    var byDay = eventsByDay(state.upcoming);
    for (var i = 0; i < 14; i++) {
      var day = addDays(new Date(), i);
      var key = ymd(day);
      if (!byDay[key]) continue;
      var section = el("section", { class: "upcoming-day", "aria-label": key });
      section.appendChild(el("h3", {}, day.toLocaleDateString(I.lang, { weekday: "long", day: "numeric", month: "long" })));
      byDay[key].forEach(function (item) { section.appendChild(eventRow(item)); });
      box.appendChild(section);
    }
    if (box.children.length === 1) box.appendChild(el("p", { class: "hint" }, t("noEvents")));
  }

  function updateClock() {
    var now = new Date();
    $("clock-time").textContent = pad(now.getHours()) + ":" + pad(now.getMinutes());
    $("clock-date").textContent = now.toLocaleDateString(I.lang, { weekday: "long", day: "numeric", month: "long" });
  }

  // ---- reminder popup --------------------------------------------------------

  function showReminder(data) {
    if (!data || !data.uid) return;
    if (state.popups.some(function (p) { return p.uid === data.uid; })) return;
    state.popups.push(data);
    renderReminder();
  }

  function closeReminder(uid) {
    state.popups = state.popups.filter(function (p) { return p.uid !== uid; });
    renderReminder();
  }

  function renderReminder() {
    var overlay = $("reminder-overlay");
    var current = state.popups[0];
    overlay.hidden = !current;
    if (!current) return;
    $("reminder-title").textContent = current.title || t("reminder");
    $("reminder-message").textContent = current.message || "";
    overlay.querySelector("[data-act='done']").focus();
  }

  function reminderAction(act, minutes) {
    var current = state.popups[0];
    if (!current) return;
    if (act === "done") {
      request({ op: "service", service: "stop_reminder", data: { uid: current.uid } }).catch(function () {});
    } else if (act === "snooze") {
      request({ op: "service", service: "snooze_reminder", data: { uid: current.uid, minutes: minutes } }).catch(function () {});
    }
    // "close" only hides this popup on this tablet.
    closeReminder(current.uid);
  }

  // ---- new event form --------------------------------------------------------

  function fillCategorySelect() {
    var select = document.querySelector("#event-form select[name='category']");
    select.textContent = "";
    state.calendars.forEach(function (cal) {
      if (cal.external || !cal.category_id) return;  // read only: no events can be added there
      select.appendChild(el("option", { value: cal.category_id }, cal.name));
    });
  }

  // ---- the date field: a small glass calendar, with the day's appointments below the form ----

  var dayCache = {};

  // Appointments of the month shown, by day (yyyy-mm-dd): each with its time, name and colour.
  function loadDayCache(month) {
    var first = ymd(month);
    var next = ymd(new Date(month.getFullYear(), month.getMonth() + 1, 1));
    return request({ op: "events", start: first + " 00:00:00", end: next + " 00:00:00" }).then(function (events) {
      dayCache = {};
      Object.keys(events).forEach(function (entity) {
        var cal = state.calendars.filter(function (c) { return c.entity_id === entity; })[0];
        events[entity].forEach(function (ev) {
          var key = dayKey(ev.start);
          (dayCache[key] = dayCache[key] || []).push({
            uid: ev.record_id, summary: ev.summary, start: ev.start, end: ev.end,
            allDay: isAllDay(ev.start), color: cal ? cal.color : "#64748B"
          });
        });
      });
    });
  }

  function openDatePicker(input) {
    var form = input.form;
    var current = parseDate(input.value) || ymd(new Date());
    var month = new Date(parseInt(current.slice(0, 4), 10), parseInt(current.slice(5, 7), 10) - 1, 1);
    var box = el("div", { class: "overlay timepick-overlay", role: "dialog", "aria-label": I.f("pickDate") });
    var panel = el("div", { class: "dialog timepick datepick" });
    document.body.appendChild(box);
    box.appendChild(panel);
    box.addEventListener("click", function (e) { if (e.target === box) box.remove(); });

    function paint() {
      panel.textContent = "";
      var head = el("div", { class: "month-nav" });
      head.appendChild(button("←", "btn", function () { month = new Date(month.getFullYear(), month.getMonth() - 1, 1); loadDayCache(month).then(paint); }));
      head.appendChild(el("span", { class: "month-title" }, month.toLocaleDateString(I.lang, { month: "long", year: "numeric" })));
      head.appendChild(button("→", "btn", function () { month = new Date(month.getFullYear(), month.getMonth() + 1, 1); loadDayCache(month).then(paint); }));
      panel.appendChild(head);
      var grid = el("div", { class: "month-grid", role: "grid" });
      orderedDays(t("days")).forEach(function (name) { grid.appendChild(el("div", { class: "wd" }, name)); });
      var offset = weekdayOffset(month);
      for (var i = 0; i < offset; i++) grid.appendChild(el("div", { class: "blank" }));
      var days = new Date(month.getFullYear(), month.getMonth() + 1, 0).getDate();
      var today = ymd(new Date());
      for (var d = 1; d <= days; d++) {
        var key = ymd(new Date(month.getFullYear(), month.getMonth(), d));
        var cell = el("button", { type: "button", class: "day-cell" + (key === today ? " today" : ""), "aria-pressed": key === dayKey(current) ? "true" : "false" });
        cell.appendChild(el("span", { class: "dnum" }, String(d)));
        var dots = el("span", { class: "day-dots", "aria-hidden": "true" });
        (dayCache[key] || []).slice(0, 4).forEach(function (item) {
          var dot = el("span", { class: "day-dot" });
          dot.style.setProperty("--dot", item.color);
          dots.appendChild(dot);
        });
        cell.appendChild(dots);
        cell.addEventListener("click", function (day) {
          return function () {
            input.value = showDate(day);
            box.remove();
            updateDayInfo(form);
          };
        }(key));
        grid.appendChild(cell);
      }
      panel.appendChild(grid);
      panel.appendChild(el("div", { class: "dialog-foot actions" }, null));
      panel.lastChild.appendChild(button(I.f("cardClose"), "btn", function () { box.remove(); }));
    }
    loadDayCache(month).then(paint);
  }

  // Under the form: what is on that day, and a warning if the chosen time overlaps something.
  function updateDayInfo(form) {
    var box = $("date-info");
    var day = parseDate(form.elements.date.value);
    if (!day) { box.textContent = ""; return; }
    var items = dayCache[day] || [];
    var lines = [];
    if (!items.length) {
      lines.push(I.f("noDayEvents"));
    } else {
      lines.push(I.f("thatDay") + ": " + items.map(function (it) {
        return (it.allDay ? I.f("allDayLabel") : timeOf(it.start)) + " " + it.summary;
      }).join(" · "));
    }
    if (!form.elements.all_day.checked) {
      var start = parseTime(form.elements.start_time.value);
      var end = parseTime(form.elements.end_time.value) || (start ? addOneHour(start) : null);
      if (start && end) {
        // The event being edited is not an overlap of itself.
        var editingUid = state.editing ? state.editing.ev.record_id : null;
        var overlap = items.filter(function (it) {
          if (it.allDay || (editingUid && it.uid === editingUid)) return false;
          var a = new Date(it.start).getTime();
          var b = new Date(it.end || it.start).getTime();
          var s = new Date(day + "T" + start + ":00").getTime();
          var e = new Date(day + "T" + end + ":00").getTime();
          return s < b && e > a;
        });
        if (overlap.length) {
          lines.push(I.f("overlapWith") + ": " + overlap.map(function (it) {
            return timeOf(it.start) + " " + it.summary;
          }).join(" · "));
        }
      }
    }
    box.textContent = "";
    lines.forEach(function (line, i) {
      box.appendChild(el("p", { class: i === 0 ? "" : "day-warning" }, line));
    });
  }

  // ---- the new-event and edit form ----------------------------------------------------
  // The same window creates an event (state.editing is null) or changes one (state.editing is
  // the event). Changing keeps the calendar: a Family Hub update cannot move an event.

  // The family's persons, from Family Hub's own calendars. (Calendars from Home Assistant list
  // only person ids, which are not persons to choose.)
  function personList() {
    var seen = {};
    var list = [];
    state.calendars.forEach(function (cal) {
      if (cal.external) return;
      (cal.persons || []).forEach(function (p) {
        if (!p || typeof p !== "object" || !p.id || seen[p.id]) return;
        seen[p.id] = true;
        list.push(p);
      });
    });
    return list;
  }

  function personName(id) {
    var found = personList().filter(function (p) { return p.id === id; })[0];
    return found ? found.name : id;
  }

  function openForm(item) {
    var form = $("event-form");
    form.reset();
    state.editing = item || null;
    $("event-error").hidden = true;
    var editing = !!item;
    $("event-title").textContent = I.f(editing ? "editEvent" : "newEvent");
    form.elements.category.disabled = editing;
    var ev = editing ? item.ev : null;
    form.elements.summary.value = editing ? ev.summary : "";
    form.elements.all_day.checked = editing ? isAllDay(ev.start) : false;
    var startDay = editing ? dayKey(ev.start) : ymd(new Date());
    form.elements.date.value = showDate(startDay);
    form.elements.start_time.value = editing && !isAllDay(ev.start)
      ? showTime(timeOfHHMM(ev.start), state.timeFormat) : showTime("09:00", state.timeFormat);
    form.elements.end_time.value = editing && !isAllDay(ev.start)
      ? showTime(timeOfHHMM(ev.end), state.timeFormat) : showTime("10:00", state.timeFormat);
    form.elements.reminders.value = editing && ev.reminder_offsets !== "default" ? ev.reminder_offsets : "";
    if (editing) {
      var cat = state.calendars.filter(function (c) { return c.category_id === ev.category_id; })[0];
      if (cat) form.elements.category.value = cat.category_id;
    }
    renderEventPersons(editing ? (ev.person_ids || []) : []);
    state.eventNotify = null;
    renderEventNotify();
    ensureNotifyData().then(function () {
      state.eventNotify = editing && ev.notify ? parseNotify(ev.notify)
        : notifyFromPersons(editing ? (ev.person_ids || []) : chosenEventPersons());
      renderEventNotify();
    });
    $("event-overlay").hidden = false;
    form.elements.summary.focus();
    var day = parseDate(form.elements.date.value);
    if (day) loadDayCache(parseLocalDay(day)).then(function () { updateDayInfo(form); });
  }

  function timeOfHHMM(iso) {
    var d = new Date(iso);
    return pad(d.getHours()) + ":" + pad(d.getMinutes());
  }

  function renderEventPersons(chosen) {
    var box = $("event-persons");
    box.textContent = "";
    personList().forEach(function (p) {
      box.appendChild(switchRow(p.name, chosen.indexOf(p.id) !== -1, function () {
        // Until "Avvisa su" is changed by hand, it follows the persons chosen.
        if (state.eventNotify && !state.eventNotify.touched) {
          state.eventNotify = notifyFromPersons(chosenEventPersons());
          renderEventNotify();
        }
      }, "event-person"));
    });
  }

  // ---- "Avvisa su": how this event's reminders go out --------------------------------
  // Filled in from the chosen persons' own settings. Sent with the event only when changed
  // here; otherwise the persons' settings apply, as before. Quiet hours always apply.

  function parseNotify(text) {
    var parts = String(text || "").split("|");
    return {
      touched: true,
      channels: parts[0] ? parts[0].split(",") : [],
      alexa_target: parts[1] || "",
      alexa_volume: parts[2] === undefined || parts[2] === "" ? null : Number(parts[2])
    };
  }

  function notifyFromPersons(ids) {
    var persons = (state.notifyData && state.notifyData.persons) || [];
    var chosen = persons.filter(function (p) { return ids.indexOf(p.id) !== -1; });
    var channels = [];
    chosen.forEach(function (p) {
      (p.channels || []).forEach(function (c) { if (channels.indexOf(c) === -1) channels.push(c); });
    });
    if (!chosen.length) channels = ["tablet"];
    var echo = chosen.filter(function (p) { return p.alexa_notify; })[0];
    return {
      touched: false,
      channels: channels,
      alexa_target: echo ? echo.alexa_notify : "",
      alexa_volume: echo && echo.alexa_volume != null ? echo.alexa_volume : null
    };
  }

  function renderEventNotify() {
    var box = $("event-notify");
    if (!box) return;
    box.textContent = "";
    var n = state.eventNotify;
    box.hidden = !n;
    if (!n) return;
    var f = I.f;
    box.appendChild(el("h3", { class: "notify-title" }, f("notifyOn")));
    box.appendChild(el("p", { class: "hint" }, f("notifyOnHint")));
    function touch() { n.touched = true; }
    var list = el("div", { class: "switch-list" });
    [["phone", f("chPhone")], ["alexa", f("chAlexa")], ["tablet", f("chTablet")]].forEach(function (c) {
      list.appendChild(switchRow(c[1], n.channels.indexOf(c[0]) !== -1, function (on) {
        touch();
        n.channels = n.channels.filter(function (x) { return x !== c[0]; });
        if (on) n.channels.push(c[0]);
        renderEventNotify();
      }, "notify-" + c[0]));
    });
    box.appendChild(list);
    if (n.channels.indexOf("alexa") !== -1 && state.notifyServices) {
      var echo = echoSelect(n.alexa_target, function (v) { touch(); n.alexa_target = v; });
      echo.setAttribute("name", "alexa_target");
      box.appendChild(fieldRow(f("alexa"), echo));
      box.appendChild(fieldRow(f("alexaVolume"), volumeControl(n.alexa_volume, function (v) {
        touch();
        n.alexa_volume = v;
      })));
    }
  }

  // "Telefono · Alexa Cucina 80% · Finestra sul tablet"
  function notifySummary(text) {
    var n = parseNotify(text);
    var f = I.f;
    var parts = [];
    if (n.channels.indexOf("phone") !== -1) parts.push(f("chPhone"));
    if (n.channels.indexOf("alexa") !== -1) {
      var name = f("chAlexa");
      if (n.alexa_target === "all") name += " " + f("allEchos");
      else if (n.alexa_target) name += " " + echoName(n.alexa_target);
      if (n.alexa_volume != null) name += " " + n.alexa_volume + "%";
      parts.push(name);
    }
    if (n.channels.indexOf("tablet") !== -1) parts.push(f("chTablet"));
    return parts.length ? parts.join(" · ") : f("notifyNone");
  }

  function echoName(entityId) {
    var list = (state.notifyServices && state.notifyServices.alexa) || [];
    var found = list.filter(function (s) { return s.entity_id === entityId; })[0];
    if (found) return found.name;
    var bare = String(entityId).split(".").pop().replace(/_/g, " ");
    return bare.charAt(0).toUpperCase() + bare.slice(1);
  }

  // Persons' settings and the Echo list, once, for the form (guests never open it).
  function ensureNotifyData() {
    if (state.notifyData && state.notifyServices) return Promise.resolve();
    return request({ op: "notify_get" }).then(function (data) {
      state.notifyData = data;
      loadNotifyOptions(data);
    }).catch(function () { /* no settings to read: the form still works */ });
  }

  function chosenEventPersons() {
    return Array.prototype.map.call(document.querySelectorAll("#event-persons input[type='checkbox']"), function (input, i) {
      return input.checked ? personList()[i].id : null;
    }).filter(function (id) { return id; });
  }

  function closeForm() { $("event-overlay").hidden = true; state.editing = null; }

  function addOneHour(hhmm) {
    var parts = hhmm.split(":");
    var total = (parseInt(parts[0], 10) * 60 + parseInt(parts[1], 10) + 60) % (24 * 60);
    return pad(Math.floor(total / 60)) + ":" + pad(total % 60);
  }

  function submitForm(event) {
    event.preventDefault();
    var form = event.target;
    if (form.querySelector("[aria-invalid='true']")) {
      showFormError(I.f("shiftBadTime"));
      return;
    }
    var summary = form.elements.summary.value.trim();
    var category = form.elements.category.value;
    if (!summary || !category) {
      showFormError(t("required"));
      return;
    }
    var day = parseDate(form.elements.date.value);
    if (!day) {
      showFormError(I.f("badDate"));
      return;
    }
    var allDay = form.elements.all_day.checked;
    var data = { summary: summary, category: category, persons: chosenEventPersons() };
    if (allDay) {
      data.start = day;
      data.end = ymd(addDays(parseLocalDay(day), 1));
    } else {
      var start = parseTime(form.elements.start_time.value);
      if (!start) {
        showFormError(I.f("shiftBadTime"));
        return;
      }
      var end = form.elements.end_time.value.trim() ? parseTime(form.elements.end_time.value) : addOneHour(start);
      if (!end) {
        showFormError(I.f("shiftBadTime"));
        return;
      }
      data.start = day + " " + start + ":00";
      data.end = day + " " + end + ":00";
    }
    var reminders = parseOffsets(form.elements.reminders.value);
    if (reminders === false) {
      showFormError(I.f("badReminders"));
      return;
    }
    if (reminders !== null) data.reminder_offsets = reminders;
    var n = state.eventNotify;
    if (n && n.touched) {
      var alexa = n.channels.indexOf("alexa") !== -1;
      data.channels = n.channels.slice();
      data.alexa_target = alexa && n.alexa_target ? n.alexa_target : null;
      data.alexa_volume = alexa ? n.alexa_volume : null;
    }
    var editing = state.editing;
    var call;
    if (editing) {
      data.uid = editing.ev.record_id;
      delete data.category;
      call = { op: "service", service: "update_event", data: data };
    } else {
      call = { op: "service", service: "add_event", data: data };
    }
    request(call).then(function () {
      closeForm();
      refreshEvents();
    }).catch(function (err) {
      showFormError(t("saveError") + errorText(err));
    });
  }

  // "30, 10" -> [30, 10]; empty -> null (the family's own reminders); bad text -> false.
  function parseOffsets(text) {
    var clean = String(text || "").trim();
    if (!clean) return null;
    var parts = clean.split(/[,;\s]+/).filter(function (p) { return p !== ""; });
    var out = [];
    for (var i = 0; i < parts.length; i++) {
      if (!/^\d{1,4}$/.test(parts[i])) return false;
      out.push(parseInt(parts[i], 10));
    }
    return out;
  }

  function parseLocalDay(day) {
    var p = day.split("-");
    return new Date(parseInt(p[0], 10), parseInt(p[1], 10) - 1, parseInt(p[2], 10));
  }

  // ---- the event card: tap an event to see it; change or delete it from here --------------

  function canChangeEvent(item) {
    if (!state.me || item.ev.external || item.ev.shift_id) return false;
    if (state.me.role === "adult") return true;
    if (state.me.role === "child") return (item.ev.person_ids || []).indexOf(state.me.person_id) !== -1;
    return false;
  }

  function cardWhen(ev) {
    var day = dayKey(ev.start);
    var text = showDate(day);
    if (isAllDay(ev.start)) return text + " · " + I.f("allDayLabel");
    var end = ev.end ? timeOf(ev.end) : "";
    return text + " · " + timeOf(ev.start) + (end ? " – " + end : "");
  }

  function openCard(item) {
    state.cardItem = item;
    var ev = item.ev;
    var box = $("card-body");
    box.textContent = "";
    box.appendChild(el("h2", { class: "card-title" }, shownTitle(ev)));
    if (ev.waste_label && ev.waste_label !== ev.summary) {
      box.appendChild(el("p", { class: "hint card-raw" }, ev.summary));
    }
    box.appendChild(el("p", { class: "hint" }, (ev.calendar || "") + " · " + cardWhen(ev)));
    if (ev.location) box.appendChild(el("p", {}, ev.location));
    if (ev.description) box.appendChild(el("p", { class: "card-text" }, ev.description));
    var names = (ev.person_ids || []).map(personName);
    if (names.length) box.appendChild(el("p", {}, I.f("evPersons") + ": " + names.join(", ")));
    if (ev.notify) box.appendChild(el("p", { class: "card-notify" }, I.f("notifyOn") + ": " + notifySummary(ev.notify)));
    // Family events have reminders of their own; calendars from outside do not.
    if (ev.reminder_offsets !== undefined) {
      var reminders = ev.reminder_offsets === "default" ? I.f("cardRemindersDefault")
        : ev.reminder_offsets === "" ? I.f("cardRemindersNone")
        : ev.reminder_offsets.split(",").map(function (m) { return I.f("cardReminderMin").replace("{n}", m); }).join(", ");
      box.appendChild(el("p", { class: "hint" }, reminders));
    }
    if (ev.external) box.appendChild(el("p", { class: "hint" }, I.f("cardExternal")));
    else if (ev.shift_id) box.appendChild(el("p", { class: "hint" }, I.f("cardShift")));
    var foot = $("card-foot");
    foot.textContent = "";
    if (canChangeEvent(item)) {
      foot.appendChild(button(I.f("cardEdit"), "btn btn-primary", function () {
        $("card-overlay").hidden = true;
        openForm(state.cardItem);
      }));
      foot.appendChild(button(I.f("cardDelete"), "btn", function () {
        askConfirm(I.f("cardDeleteAsk").replace("{name}", ev.summary), I.f("cardDelete")).then(function (yes) {
          if (!yes) return;
          request({ op: "service", service: "delete_event", data: { uid: ev.record_id } }).then(function () {
            $("card-overlay").hidden = true;
            refreshEvents();
          }).catch(function (err) { showStatusNote(I.f("saveError") + errorText(err)); });
        });
      }));
    }
    foot.appendChild(button(I.f("cardClose"), "btn", function () { $("card-overlay").hidden = true; }));
    $("card-overlay").hidden = false;
  }

  function showFormError(text) {
    var box = $("event-error");
    box.textContent = text;
    box.hidden = false;
  }

  // ---- setup guide -----------------------------------------------------------
  // The configuration lives in Home Assistant. The guide edits a copy (state.draft) and saves
  // it in one command at the end. Only adults get here; the server checks it again.

  var COLORS = ["#2563EB", "#059669", "#DC2626", "#D97706", "#7C3AED", "#DB2777"];

  function fieldRow(labelText, control) {
    var label = el("label", {}, labelText + " ");
    label.appendChild(control);
    if (control.errorEl) label.appendChild(control.errorEl);
    return label;
  }

  function textInput(value, onChange, attrs) {
    var input = el("input", Object.assign({ type: "text", autocomplete: "off" }, attrs || {}));
    input.value = value == null ? "" : String(value);
    input.addEventListener("input", function () { onChange(input.value); });
    return input;
  }

  function selectInput(options, value, onChange, attrs) {
    var select = el("select", attrs || {});
    options.forEach(function (opt) {
      select.appendChild(el("option", { value: opt[0] }, opt[1]));
    });
    select.value = value;
    select.addEventListener("change", function () { onChange(select.value); });
    return select;
  }

  function colorInput(value, onChange) {
    var input = el("input", { type: "color" });
    input.value = value || "#2563EB";
    input.addEventListener("input", function () { onChange(input.value); });
    return input;
  }

  function button(text, cls, onClick) {
    var b = el("button", { type: "button", class: cls }, text);
    b.addEventListener("click", onClick);
    return b;
  }

  function roleOptions() {
    var f = I.f;
    return [["adult", f("roleAdult")], ["child", f("roleChild")], ["guest", f("roleGuest")]];
  }

  function buildFamilyFields(box) {
    var f = I.f, fam = state.draft.family;
    box.appendChild(fieldRow(f("familyName"), textInput(fam.family_name, function (v) { fam.family_name = v; }, { maxlength: 60, required: true })));
    box.appendChild(fieldRow(f("language"), selectInput([["it", "Italiano"], ["de", "Deutsch"], ["en", "English"]], fam.language, function (v) { fam.language = v; })));
    box.appendChild(fieldRow(f("weekday"), selectInput([["monday", f("monday")], ["sunday", f("sunday")]], fam.first_weekday, function (v) { fam.first_weekday = v; })));
    box.appendChild(fieldRow(f("timeFormat"), selectInput([["24h", f("h24")], ["12h", f("h12")]], fam.time_format, function (v) { fam.time_format = v; })));
    box.appendChild(fieldRow(f("country"), textInput(fam.country, function (v) { fam.country = v; })));
    box.appendChild(fieldRow(f("region"), textInput(fam.region, function (v) { fam.region = v; })));
  }

  function buildPersonFields(box) {
    var f = I.f;
    var list = state.draft.persons;
    list.forEach(function (person, index) {
      var card = el("fieldset", { class: "card" });
      card.appendChild(el("legend", {}, person.name || "#" + (index + 1)));
      card.appendChild(fieldRow(f("personName"), textInput(person.name, function (v) { person.name = v; }, { maxlength: 60 })));
      card.appendChild(fieldRow(f("color"), colorInput(person.color, function (v) { person.color = v; })));
      card.appendChild(fieldRow(f("role"), selectInput(roleOptions(), person.role, function (v) { person.role = v; })));
      card.appendChild(fieldRow(f("haUser"), userSelect(person.ha_user_id, function (v) { person.ha_user_id = v; })));
      card.appendChild(fieldRow(f("phone"), phoneSelect(person.phone_notify, function (v) { person.phone_notify = v; })));
      card.appendChild(fieldRow(f("alexa"), echoSelect(person.alexa_notify, function (v) { person.alexa_notify = v; })));
      card.appendChild(button(f("remove"), "btn", function () {
        list.splice(index, 1);
        renderWizard();
      }));
      box.appendChild(card);
    });
    box.appendChild(el("p", { class: "hint" }, f("personsHint")));
    box.appendChild(button(f("add"), "btn", function () {
      list.push({ name: "", color: COLORS[list.length % COLORS.length], role: "adult", ha_user_id: "", phone_notify: "", alexa_notify: "" });
      renderWizard();
    }));
  }

  function buildCategoryFields(box) {
    var f = I.f;
    var list = state.draft.categories;
    list.forEach(function (cat, index) {
      var card = el("fieldset", { class: "card" });
      card.appendChild(fieldRow(f("calendarName"), textInput(cat.name, function (v) { cat.name = v; }, { maxlength: 60 })));
      card.appendChild(fieldRow(f("color"), colorInput(cat.color, function (v) { cat.color = v; })));
      card.appendChild(button(f("remove"), "btn", function () {
        list.splice(index, 1);
        renderWizard();
      }));
      box.appendChild(card);
    });
    box.appendChild(el("p", { class: "hint" }, f("categoriesHint")));
    box.appendChild(button(f("add"), "btn", function () {
      list.push({ name: "", color: COLORS[list.length % COLORS.length] });
      renderWizard();
    }));
  }

  function buildReminderFields(box) {
    var f = I.f, rem = state.draft.reminders;
    box.appendChild(fieldRow(f("offsets"), textInput((rem.offsets || []).join(", "), function (v) {
      rem.offsets = v.split(/[,\s]+/).filter(Boolean).map(Number);
    })));
    var channels = el("fieldset", { class: "card" });
    channels.appendChild(el("legend", {}, f("channels")));
    channels.appendChild(el("p", { class: "hint" }, f("channelsHint")));
    [["phone", f("chPhone")], ["speaker", f("chSpeaker")], ["tablet", f("chTablet")], ["popup", f("chPopup")]]
      .forEach(function (ch) {
        channels.appendChild(switchRow(ch[1], (rem.channels || []).indexOf(ch[0]) !== -1, function (on) {
          var rest = (rem.channels || []).filter(function (c) { return c !== ch[0]; });
          rem.channels = on ? rest.concat([ch[0]]) : rest;
        }));
      });
    box.appendChild(channels);
    box.appendChild(fieldRow(f("quietStart"), timeInput(rem.quiet_start, f("quietStart"), function (v) { rem.quiet_start = v; })));
    box.appendChild(fieldRow(f("quietEnd"), timeInput(rem.quiet_end, f("quietEnd"), function (v) { rem.quiet_end = v; })));
    box.appendChild(fieldRow(f("snooze"), segmented(snoozeChoices(rem.snooze_minutes),
      String(rem.snooze_minutes), function (v) { rem.snooze_minutes = Number(v); })));
    box.appendChild(fieldRow(f("morning"), timeInput(rem.morning_summary, f("morning"), function (v) { rem.morning_summary = v || null; })));
    box.appendChild(fieldRow(f("evening"), timeInput(rem.evening_summary, f("evening"), function (v) { rem.evening_summary = v || null; })));
    box.appendChild(fieldRow(f("allDay"), timeInput(rem.all_day_reminder, f("allDay"), function (v) { rem.all_day_reminder = v || null; })));
  }

  function buildScreenFields(box) {
    var f = I.f, screen = state.draft.screen;
    box.appendChild(fieldRow(f("theme"), selectInput([["auto", f("themeAuto")], ["light", f("themeLight")], ["dark", f("themeDark")]], screen.theme, function (v) { screen.theme = v; })));
    box.appendChild(switchRow(f("weekFromToday"), screen.week_from_today !== false, function (on) { screen.week_from_today = on; }));
    box.appendChild(el("p", { class: "hint" }, f("weekFromTodayHint")));
  }

  function openWizard(step) {
    state.wizardStep = step;
    if (state.draft) {
      showWizard();
      return;
    }
    Promise.all([request({ op: "config_get" }), request({ op: "notify_get" })]).then(function (both) {
      var config = both[0];
      loadNotifyOptions(both[1]);
      state.draft = {
        family: Object.assign({}, config.family),
        screen: Object.assign({}, config.screen),
        persons: config.persons.map(function (p) { return Object.assign({}, p); }),
        categories: config.categories.map(function (c) { return Object.assign({}, c); }),
        reminders: Object.assign({}, config.reminders),
        sources: {
          todo: (config.sources.todo || []).slice(),
          calendars: (config.sources.calendars || []).slice(),
          weather: (config.sources.weather || []).slice(),
          calendar_styles: Object.assign({}, config.sources.calendar_styles || {})
        }
      };
      showWizard();
    }).catch(function (err) {
      showStatusNote(I.f("loadError") + " " + errorText(err));
    });
  }

  // Messages about an action (saved, applied, failed to load). They have their own line, so
  // the week's "no events" note does not overwrite them.
  function showStatusNote(text) {
    var note = $("status-note");
    note.textContent = text;
    note.hidden = false;
    window.clearTimeout(state.statusTimer);
    state.statusTimer = window.setTimeout(function () { note.hidden = true; }, 6000);
  }

  function showWizard() {
    $("wizard-overlay").hidden = false;
    renderWizard();
  }

  function closeWizard() {
    $("wizard-overlay").hidden = true;
    state.draft = null;
  }

  function renderWizard() {
    var index = state.wizardStep;
    var steps = I.steps;
    var last = index === I.stepCount - 1;
    $("wizard-progress").textContent = t("stepOf").replace("{n}", String(index + 1));
    $("wizard-title").textContent = steps[index][0];
    $("wizard-text").textContent = steps[index][1];
    $("wizard-example").textContent = index === 4 ? I.f("sourcesHint") : steps[index][2];
    var body = $("wizard-body");
    body.textContent = "";
    if (index === 0) buildFamilyFields(body);
    if (index === 1) buildPersonFields(body);
    if (index === 2) buildCategoryFields(body);
    if (index === 3) buildReminderFields(body);
    if (index === 4) buildSourceFields(body);
    if (index === 5) buildScreenFields(body);
    $("wizard-error").hidden = true;
    $("wizard-back").hidden = index === 0;
    $("wizard-back").textContent = I.f("back");
    $("wizard-next").textContent = last ? I.f("save") : t("next");
    $("wizard-skip").textContent = t("skip");
    $("wizard-next").focus();
  }

  function draftForSave() {
    return {
      family: state.draft.family,
      screen: state.draft.screen,
      persons: state.draft.persons,
      categories: state.draft.categories.filter(function (c) { return c.name; }),
      reminders: state.draft.reminders,
      sources: sourcesForSave(state.draft.sources)
    };
  }

  function sourcesForSave(sources) {
    var chosen = sources.calendars || [];
    var styles = {};
    Object.keys(sources.calendar_styles || {}).forEach(function (id) {
      if (chosen.indexOf(id) !== -1) styles[id] = sources.calendar_styles[id];
    });
    return Object.assign({}, sources, { calendar_styles: styles });
  }

  function saveWizard() {
    var theme = state.draft.screen.theme;
    request({ op: "config_save", config: draftForSave() }).then(function () {
      applyTheme(theme);
      closeWizard();
      showStatusNote(I.f("saved"));
      // The add-on subscribes to the new calendars a moment after the save.
      window.setTimeout(refreshCalendars, 2500);
    }).catch(function (err) {
      var box = $("wizard-error");
      box.textContent = I.f("saveError") + errorText(err);
      if (err && err.message && err.message !== err.code) {
        box.appendChild(el("span", { class: "error-detail" }, err.message));
      }
      box.hidden = false;
    });
  }

  function renderWizardStep(index) {
    state.wizardStep = index;
    renderWizard();
  }

  function nextWizardStep() {
    if ($("wizard-body").querySelector("[aria-invalid='true']")) {
      $("wizard-error").textContent = I.f("shiftBadTime");
      $("wizard-error").hidden = false;
      return;
    }
    if (state.wizardStep >= I.stepCount - 1) {
      saveWizard();
    } else {
      renderWizardStep(state.wizardStep + 1);
    }
  }

  function skipWizard() {
    // "Salta": this step is left as it is. Skipping the last step closes the guide unsaved.
    if (state.wizardStep >= I.stepCount - 1) {
      closeWizard();
    } else {
      renderWizardStep(state.wizardStep + 1);
    }
  }

  // ---- to-do lists and external sources ---------------------------------------
  // Lists and calendars come from the entities the guide chose. The server checks every request.

  function openTodos() {
    $("todos-error").hidden = true;
    $("todo-overlay").hidden = false;
    loadTodos();
    $("todos-close").focus();
  }

  function closeTodos() {
    $("todo-overlay").hidden = true;
  }

  function showTodoError(err) {
    $("todos-error").textContent = errorText(err);
    $("todos-error").hidden = false;
  }

  function loadTodos() {
    request({ op: "todo_lists" }).then(function (lists) {
      state.todoLists = lists;
      return Promise.all(lists.map(function (list) {
        return request({ op: "todo_items", entity_id: list.entity_id }).then(function (items) {
          return { list: list, items: items };
        });
      }));
    }).then(renderTodos).catch(showTodoError);
  }

  function todoChange(payload) {
    request(payload).then(loadTodos).catch(showTodoError);
  }

  function renderTodos(groups) {
    var body = $("todos-body");
    body.textContent = "";
    if (groups.length === 0) {
      body.appendChild(el("p", { class: "hint" }, I.f("noLists")));
      return;
    }
    groups.forEach(function (group) {
      var section = el("section", { class: "todo-list", "aria-label": group.list.name });
      section.appendChild(el("h3", {}, group.list.name));
      if (group.items.length === 0) section.appendChild(el("p", { class: "hint" }, I.f("listEmpty")));
      group.items.forEach(function (item) {
        var row = el("div", { class: "todo-row" });
        var box = el("input", { type: "checkbox" });
        box.checked = item.status === "completed";
        box.setAttribute("aria-label", item.summary);
        box.disabled = state.role === "guest";
        box.addEventListener("change", function () {
          todoChange({ op: "todo_update", entity_id: group.list.entity_id, item: item.uid, done: box.checked });
        });
        row.appendChild(box);
        row.appendChild(el("span", { class: box.checked ? "done" : "" }, item.summary));
        if (state.role === "adult") {
          row.appendChild(button(I.f("remove"), "btn", function () {
            todoChange({ op: "todo_remove", entity_id: group.list.entity_id, item: item.uid });
          }));
        }
        section.appendChild(row);
      });
      if (state.role !== "guest") section.appendChild(addItemForm(group.list.entity_id));
      body.appendChild(section);
    });
  }

  function addItemForm(entityId) {
    var form = el("form", { class: "todo-add" });
    var input = el("input", { type: "text", maxlength: "255", placeholder: I.f("itemPlaceholder") });
    input.setAttribute("aria-label", I.f("itemPlaceholder"));
    form.appendChild(input);
    form.appendChild(el("button", { type: "submit", class: "btn btn-primary" }, I.f("listAdd")));
    form.addEventListener("submit", function (event) {
      event.preventDefault();
      var text = input.value.trim();
      if (text) todoChange({ op: "todo_add", entity_id: entityId, summary: text });
    });
    return form;
  }

  var ICS_TYPES = ["rifiuti", "vacanze_scuola", "vacanze_asilo", "festivita", "altro"];

  // The name shown, its type (rubbish, holidays, ...) and colour of a calendar from Home Assistant.
  function calendarStyleRow(entity, sources) {
    // Not created here: only a calendar that is ticked gets a style (the integration refuses
    // styles of calendars that are not chosen).
    var kept = sources.calendar_styles && sources.calendar_styles[entity.entity_id];
    var style = kept || { name: "", type: "altro", color: "#64748B" };
    var row = el("div", { class: "cal-style" });
    row.styleObj = style;
    row.appendChild(fieldRow(I.f("icsName"), textInput(style.name, function (v) { style.name = v; }, { placeholder: entity.name, maxlength: 60 })));
    var types = ICS_TYPES.map(function (k) { return [k, icsTypeName(k)]; });
    row.appendChild(fieldRow(I.f("icsType"), selectInput(types, style.type, function (v) { style.type = v; })));
    var colour = el("input", { type: "color", value: style.color, "aria-label": I.f("icsColor") });
    colour.addEventListener("input", function () { style.color = colour.value; });
    row.appendChild(fieldRow(I.f("icsColor"), colour));
    var people = (state.draft && state.draft.persons) || [];
    if (people.length) {
      if (!Array.isArray(style.persons)) style.persons = [];
      var who = el("div", { class: "switch-list cal-persons", role: "group", "aria-label": I.f("calPersons") });
      who.appendChild(el("span", { class: "hint" }, I.f("calPersons")));
      people.forEach(function (person) {
        who.appendChild(switchRow(person.name, style.persons.indexOf(person.id) !== -1, function (on) {
          var rest = style.persons.filter(function (id) { return id !== person.id; });
          style.persons = on ? rest.concat([person.id]) : rest;
        }));
      });
      row.appendChild(who);
    }
    return row;
  }

  // The "Fonti" step: adults pick the to-do lists and calendars to show.
  function buildSourceFields(box) {
    var f = I.f, sources = state.draft.sources;
    var status = el("p", { class: "hint" }, f("loading"));
    box.appendChild(status);
    // The external calendars (ICS) are managed in their own window, for adults.
    if (state.role === "adult") box.appendChild(button(I.f("icsOpen"), "btn", openIcs));
    request({ op: "entities" }).then(function (entities) {
      status.textContent = entities.length ? "" : f("noSources");
      if (!sources.weather) sources.weather = [];
      var weatherEntities = entities.filter(function (e) { return e.domain === "weather"; });
      // Only one weather entity: when there is just one, it is proposed.
      if (weatherEntities.length === 1 && sources.weather.length === 0) {
        sources.weather.push(weatherEntities[0].entity_id);
      }
      [["todo", "todo", f("sourcesTodo")], ["calendars", "calendar", f("sourcesCalendars")],
        ["weather", "weather", I.w.sources]]
        .forEach(function (group) {
          var card = el("fieldset", { class: "card" });
          card.appendChild(el("legend", {}, group[2]));
          entities.filter(function (e) { return e.domain === group[1]; }).forEach(function (entity) {
            var label = el("label", { class: "check" });
            var input = el("input", { type: "checkbox", value: entity.entity_id });
            input.checked = sources[group[0]].indexOf(entity.entity_id) !== -1;
            var styleBox = group[0] === "calendars" ? calendarStyleRow(entity, sources) : null;
            if (styleBox) styleBox.hidden = !input.checked;
            input.addEventListener("change", function () {
              var list = sources[group[0]];
              var pos = list.indexOf(entity.entity_id);
              if (styleBox) {
                styleBox.hidden = !input.checked;
                if (!input.checked && sources.calendar_styles) delete sources.calendar_styles[entity.entity_id];
                if (input.checked) {
                  if (!sources.calendar_styles) sources.calendar_styles = {};
                  sources.calendar_styles[entity.entity_id] = styleBox.styleObj;
                }
              }
              if (group[0] === "weather" && input.checked) {
                // One weather entity at a time: the others are unticked.
                list.splice(0, list.length);
                card.querySelectorAll("input").forEach(function (other) { other.checked = false; });
                input.checked = true;
                list.push(entity.entity_id);
                return;
              }
              if (input.checked && pos === -1) list.push(entity.entity_id);
              if (!input.checked && pos !== -1) list.splice(pos, 1);
            });
            label.appendChild(input);
            label.appendChild(document.createTextNode(" " + entity.name));
            card.appendChild(label);
            if (styleBox) card.appendChild(styleBox);
          });
          box.appendChild(card);
        });
    }).catch(function (err) {
      status.textContent = errorText(err);
    });
    if (state.role === "adult") buildImportCard(box);
  }

  // Old calendars (Home Assistant calendars that are not Family Hub's) are copied into a
  // category, once: a preview first, then the copy. Events already there are skipped, so the
  // copy can be repeated. Adults only.
  function buildImportCard(box) {
    var f = I.f;
    var card = el("fieldset", { class: "card" });
    card.appendChild(el("legend", {}, f("importTitle")));
    card.appendChild(el("p", { class: "hint" }, f("importHint")));
    var body = el("div", {});
    var out = el("p", { class: "hint" });
    var list = el("ul", { class: "import-list" });
    var run = button(f("importRun"), "btn btn-primary", function () { doImport(); });
    run.hidden = true;
    var choice = { entity: "", category: "", person: "" };
    card.appendChild(body);
    box.appendChild(card);

    function clearPreview() {
      out.textContent = "";
      list.textContent = "";
      run.hidden = true;
    }

    function preview() {
      clearPreview();
      out.textContent = f("loading");
      request({ op: "import_preview", entity_id: choice.entity, category_id: choice.category, person: choice.person })
        .then(function (r) {
          out.textContent = r.total ? f("importCount").replace("{n}", r.total).replace("{s}", r.skipped) : f("importNone");
          r.items.forEach(function (item) {
            list.appendChild(el("li", {}, item.summary + " · " + showDate(item.start.slice(0, 10))));
          });
          if (r.total > r.items.length) list.appendChild(el("li", {}, f("importMore").replace("{n}", r.total - r.items.length)));
          run.hidden = r.total === 0;
        })
        .catch(function (err) { out.textContent = errorText(err); });
    }

    function doImport() {
      request({ op: "import_run", entity_id: choice.entity, category_id: choice.category, person: choice.person })
        .then(function (r) {
          showStatusNote(f("importDone").replace("{n}", r.copied).replace("{s}", r.skipped));
          preview();
        })
        .catch(function (err) { out.textContent = errorText(err); });
    }

    Promise.all([request({ op: "import_sources" }), request({ op: "calendars" }), request({ op: "config_get" })])
      .then(function (res) {
        var sources = res[0];
        var categories = res[1].filter(function (c) { return !c.external; });
        var persons = res[2].persons || [];
        if (!sources.length) {
          body.appendChild(el("p", { class: "hint" }, f("importNoSource")));
          return;
        }
        choice.entity = sources[0].entity_id;
        choice.category = categories.length ? categories[0].category_id : "";
        body.appendChild(fieldRow(f("importSource"), selectInput(sources.map(function (s) { return [s.entity_id, s.name]; }), choice.entity, function (v) { choice.entity = v; clearPreview(); })));
        body.appendChild(fieldRow(f("importCategory"), selectInput(categories.map(function (c) { return [c.category_id, c.name]; }), choice.category, function (v) { choice.category = v; clearPreview(); })));
        body.appendChild(fieldRow(f("importPerson"), selectInput([["", f("importNobody")]].concat(persons.map(function (p) { return [p.id, p.name]; })), "", function (v) { choice.person = v; clearPreview(); })));
        body.appendChild(button(f("importPreview"), "btn", preview));
        body.appendChild(out);
        body.appendChild(list);
        body.appendChild(run);
      })
      .catch(function (err) { body.appendChild(el("p", { class: "hint" }, errorText(err))); });
  }

  // The menu opens under the Menu button, over the page, never over the top bar.
  function toggleMenu(open) {
    var menu = $("menu");
    menu.hidden = !open;
    $("menu-btn").setAttribute("aria-expanded", open ? "true" : "false");
    if (open) {
      var bar = document.querySelector(".topbar").getBoundingClientRect();
      menu.style.top = Math.round(bar.bottom + 8) + "px";
    }
  }

  // ---- shifts ("turni") -----------------------------------------------------------
  // Models per person (name, times, calendar). Days get a shift by tapping them; a shift can
  // run past midnight. The server checks who may change whose shifts.

  function openShifts() {
    $("shifts-error").hidden = true;
    $("shifts-overlay").hidden = false;
    showShiftTab("models");
    loadShifts();
  }

  function closeShifts() {
    $("shifts-overlay").hidden = true;
  }

  function showShiftError(err) {
    $("shifts-error").textContent = errorText(err);
    $("shifts-error").hidden = false;
  }

  function showShiftTab(tab) {
    $("shifts-models").hidden = tab !== "models";
    $("shifts-calendar").hidden = tab !== "calendar";
    $("tab-models").setAttribute("aria-selected", tab === "models" ? "true" : "false");
    $("tab-calendar").setAttribute("aria-selected", tab === "calendar" ? "true" : "false");
    if (tab === "calendar") loadShiftMarks();
  }

  function loadShifts() {
    request({ op: "shifts" }).then(function (data) {
      state.shiftData = data;
      if (!state.shiftPerson || !data.shifts[state.shiftPerson]) {
        state.shiftPerson = data.persons.length ? data.persons[0].id : null;
      }
      renderPersonPicker();
      renderShiftModels();
      if (!$("shifts-calendar").hidden) loadShiftMarks();
    }).catch(showShiftError);
  }

  function renderPersonPicker() {
    var select = $("shift-person");
    select.textContent = "";
    state.shiftData.persons.forEach(function (p) {
      select.appendChild(el("option", { value: p.id }, p.name));
    });
    select.value = state.shiftPerson || "";
  }

  // Times are stored as HH:MM. The screen shows them the way the family set it (24 h or 12 h).
  // What is typed is read loosely: "1030", "10.30", "10:30", "7" (7:00), "930", "8 pm".
  function parseTime(text) {
    var raw = String(text || "").trim().toLowerCase();
    var suffix = /(am|pm)$/.exec(raw);
    if (suffix) raw = raw.slice(0, -2).trim();
    var h;
    var min;
    var m = /^(\d{1,2})[:.](\d{1,2})$/.exec(raw);
    if (m) {
      h = parseInt(m[1], 10);
      min = parseInt(m[2], 10);
      if (m[2].length !== 2) return null;
    } else if ((m = /^(\d{3,4})$/.exec(raw))) {
      h = parseInt(raw.slice(0, raw.length - 2), 10);
      min = parseInt(raw.slice(-2), 10);
    } else if ((m = /^(\d{1,2})$/.exec(raw))) {
      h = parseInt(m[1], 10);
      min = 0;
    } else {
      return null;
    }
    if (suffix) {
      if (h < 1 || h > 12) return null;
      h = h % 12 + (suffix[1] === "pm" ? 12 : 0);
    }
    if (h > 23 || min > 59) return null;
    return pad(h) + ":" + pad(min);
  }

  function showTime(hhmm, format) {
    if (format !== "12h") return hhmm;
    var h = parseInt(hhmm.slice(0, 2), 10);
    return pad(h % 12 || 12) + ":" + hhmm.slice(3) + (h < 12 ? " AM" : " PM");
  }

  // A time field in the family's clock. An empty field means "no time". Typed times are
  // completed when the field is left ("1030" -> 10:30). A wrong time is shown in red with a
  // message under the field, and the window does not save until it is right.
  function timeInput(value, label, onChange, example) {
    var format = state.timeFormat;
    var input = el("input", {
      type: "text",
      autocomplete: "off",
      inputmode: "numeric",
      "aria-label": label,
      placeholder: showTime(example || "07:30", format)
    });
    input.value = value ? showTime(value, format) : "";
    bindTimeField(input, onChange);
    return input;
  }

  // Makes any time field (built here or already in the page) complete what is typed, show a
  // wrong time in red with a message, and open the touch picker on a tap.
  function bindTimeField(input, onChange) {
    var format = state.timeFormat;
    if (!input.errorEl) {
      input.errorEl = el("span", { class: "field-error", role: "alert", hidden: "" }, I.f("shiftBadTime"));
      input.insertAdjacentElement("afterend", input.errorEl);
    }
    function check() {
      var text = input.value.trim();
      if (!text) {
        input.removeAttribute("aria-invalid");
        input.errorEl.hidden = true;
        if (onChange) onChange("");
        return true;
      }
      var parsed = parseTime(text);
      if (parsed) {
        input.removeAttribute("aria-invalid");
        input.errorEl.hidden = true;
        if (onChange) onChange(parsed);
        return true;
      }
      input.setAttribute("aria-invalid", "true");
      input.errorEl.hidden = false;
      return false;
    }
    input.addEventListener("input", check);
    input.addEventListener("change", function () {
      var parsed = parseTime(input.value);
      if (parsed) input.value = showTime(parsed, format);
      check();
    });
    input.addEventListener("click", function () {
      var touch = navigator.maxTouchPoints > 0 || (window.matchMedia && window.matchMedia("(pointer: coarse)").matches);
      if (touch) openTimePicker(input, format, check);
    });
    input.timeCheck = check;
    return input;
  }

  // The name of a time field, without its error message or its control: "Inizio".
  function fieldTitle(input) {
    if (input.getAttribute("aria-label")) return input.getAttribute("aria-label");
    var label = input.labels && input.labels[0];
    if (!label) return "";
    var copy = label.cloneNode(true);
    copy.querySelectorAll(".field-error, input, select, textarea, button").forEach(function (n) { n.remove(); });
    return copy.textContent.trim();
  }

  // A glass picker for touch screens: hours 00 to 23, minutes in steps of 5, and "Fatto".
  function openTimePicker(input, format, check) {
    var parsed = parseTime(input.value) || "09:00";
    var hour = parseInt(parsed.slice(0, 2), 10);
    var minute = Math.round(parseInt(parsed.slice(3), 10) / 5) * 5 % 60;
    var box = el("div", { class: "overlay timepick-overlay", role: "dialog", "aria-label": input.getAttribute("aria-label") });
    var panel = el("div", { class: "dialog timepick" });
    var columns = el("div", { class: "timepick-columns" });
    var hours = el("div", { class: "timepick-col" });
    var minutes = el("div", { class: "timepick-col" });
    var hourCells = [];
    var minuteCells = [];
    // The cells are built once; a tap only moves the "on" mark, so the columns keep their scroll.
    function mark() {
      hourCells.forEach(function (b, h) { setOn(b, h === hour); });
      minuteCells.forEach(function (b, i) { setOn(b, i * 5 === minute); });
    }
    function setOn(b, selected) {
      b.classList.toggle("on", selected);
      b.setAttribute("aria-pressed", selected ? "true" : "false");
    }
    function pickCell(text, onPick) {
      var b = el("button", { type: "button", class: "timepick-cell", "aria-pressed": "false" }, text);
      b.addEventListener("click", function () { onPick(); mark(); });
      return b;
    }
    for (var h = 0; h < 24; h++) {
      hourCells.push(pickCell(pad(h), (function (value) { return function () { hour = value; }; })(h)));
      hours.appendChild(hourCells[h]);
    }
    for (var m = 0; m < 60; m += 5) {
      minuteCells.push(pickCell(pad(m), (function (value) { return function () { minute = value; }; })(m)));
      minutes.appendChild(minuteCells[minuteCells.length - 1]);
    }
    mark();
    // The values already written are shown selected, and scrolled into view.
    function scrollTo(col, cell) {
      if (!cell) return;
      var c = col.getBoundingClientRect();
      var b = cell.getBoundingClientRect();
      col.scrollTop += b.top - c.top - (c.height - b.height) / 2;
    }
    scrollTo(hours, hourCells[hour]);
    scrollTo(minutes, minuteCells[minute / 5]);
    columns.appendChild(hours);
    columns.appendChild(minutes);
    // Title, the two columns, and the buttons in a foot below them (never over the columns).
    var titleText = fieldTitle(input);
    panel.appendChild(el("h2", {}, titleText));
    panel.appendChild(columns);
    var cancel = button(t("cancel"), "btn", function () {
      box.remove();
      input.focus();
    });
    var done = button(I.f("timeDone"), "btn btn-primary", function () {
      input.value = showTime(pad(hour) + ":" + pad(minute), format);
      check();
      box.remove();
      input.focus();
    });
    var foot = el("div", { class: "dialog-foot actions timepick-foot" });
    foot.appendChild(cancel);
    foot.appendChild(done);
    panel.appendChild(foot);
    box.appendChild(panel);
    document.body.appendChild(box);
    scrollTo(hours, hourCells[hour]);
    scrollTo(minutes, minuteCells[minute / 5]);
  }

  // Models of the chosen person: one compact row each (name, start, end, calendar, remove).
  function renderShiftModels() {
    var box = $("shifts-models");
    box.textContent = "";
    var f = I.f;
    var models = state.shiftData.shifts[state.shiftPerson] || (state.shiftData.shifts[state.shiftPerson] = []);
    var head = el("div", { class: "shift-row shift-head" });
    [f("shiftName"), f("shiftStart"), f("shiftEnd"), t("calendar"), ""].forEach(function (text) {
      head.appendChild(el("span", {}, text));
    });
    box.appendChild(head);
    models.forEach(function (model, index) {
      var row = el("div", { class: "shift-row" });
      row.appendChild(textInput(model.name, function (v) { model.name = v; }, { maxlength: 60, "aria-label": f("shiftName") }));
      row.appendChild(timeInput(model.start, f("shiftStart"), function (v) { model.start = v; }));
      row.appendChild(timeInput(model.end, f("shiftEnd"), function (v) { model.end = v; }));
      var cats = state.shiftData.categories.map(function (c) { return [c.id, c.name]; });
      row.appendChild(selectInput(cats, model.category, function (v) { model.category = v; }, { "aria-label": t("calendar") }));
      row.appendChild(button(f("remove"), "btn", function () {
        models.splice(index, 1);
        renderShiftModels();
      }));
      box.appendChild(row);
    });
    box.appendChild(button(f("addShift"), "btn", function () {
      var cats = state.shiftData.categories;
      models.push({ id: "", name: "", start: "07:00", end: "15:00", category: cats.length ? cats[0].id : "" });
      renderShiftModels();
    }));
    box.appendChild(button(f("saveShifts"), "btn btn-primary", saveShiftModels));
  }

  function saveShiftModels() {
    var models = state.shiftData.shifts[state.shiftPerson] || [];
    if (document.querySelector("#shifts-models [aria-invalid='true']")) {
      $("shifts-error").textContent = I.f("shiftBadTime");
      $("shifts-error").hidden = false;
      return;
    }
    var payload = { op: "shifts_save", person: state.shiftPerson, shifts: models };
    request(payload).then(function (reply) {
      // The server answers "confirm" only when changed times reach events already entered.
      // Nothing is saved yet: the answer decides whether those events change too.
      if (reply.confirm === undefined) return finishShiftSave(0, false);
      return askFutureUpdate(reply.confirm).then(function (answer) {
        if (answer === "cancel") return;
        var update = answer === "yes";
        return request({ op: "shifts_save", person: state.shiftPerson, shifts: models, apply_future: update })
          .then(function () { finishShiftSave(reply.confirm, update); });
      });
    }).catch(showShiftError);
  }

  // Family Hub's own dialog (not a browser prompt, which the app may not show).
  // Resolves with "yes", "no" or "cancel".
  function askFutureUpdate(count) {
    return new Promise(function (resolve) {
      $("confirm-text").textContent = I.f("confirmFuture").replace("{n}", String(count));
      $("confirm-overlay").hidden = false;
      function answer(value) {
        $("confirm-overlay").hidden = true;
        resolve(value);
      }
      $("confirm-yes").onclick = function () { answer("yes"); };
      $("confirm-no").onclick = function () { answer("no"); };
      $("confirm-cancel").onclick = function () { answer("cancel"); };
    });
  }

  function finishShiftSave(count, updated) {
    $("shifts-error").hidden = true;
    loadShifts();
    showStatusNote(I.f("shiftSaved") + (updated ? " " + I.f("shiftUpdated").replace("{n}", String(count)) : ""));
  }

  // Calendar of one person's shifts: tap days, choose a shift, apply to the chosen days.
  function renderShiftCalendar() {
    var box = $("shifts-calendar");
    box.textContent = "";
    var month = state.shiftMonth;
    var controls = el("div", { class: "month-nav" });
    controls.appendChild(button("←", "btn", function () { moveMonth(-1); }));
    controls.appendChild(el("span", { class: "month-title" }, month.toLocaleDateString(I.lang, { month: "long", year: "numeric" })));
    controls.appendChild(button("→", "btn", function () { moveMonth(1); }));
    box.appendChild(controls);

    var pick = el("div", { class: "shift-pick" });
    var options = [["", I.f("shiftNone")]];
    (state.shiftData.shifts[state.shiftPerson] || []).forEach(function (m) { options.push([m.id, m.name]); });
    state.shiftChoice = state.shiftChoice || "";
    pick.appendChild(fieldRow(I.f("shiftChoose"), selectInput(options, state.shiftChoice, function (v) { state.shiftChoice = v; })));
    box.appendChild(pick);

    var grid = el("div", { class: "month-grid", role: "grid" });
    t("days").forEach(function (name) { grid.appendChild(el("div", { class: "wd" }, name)); });
    var first = new Date(month.getFullYear(), month.getMonth(), 1);
    var offset = (first.getDay() + 6) % 7;
    for (var i = 0; i < offset; i++) grid.appendChild(el("div", { class: "blank" }));
    var days = new Date(month.getFullYear(), month.getMonth() + 1, 0).getDate();
    for (var d = 1; d <= days; d++) {
      var key = ymd(new Date(month.getFullYear(), month.getMonth(), d));
      var label = state.shiftMarks[key] || "";
      var cell = el("button", { type: "button", class: "day-cell", "aria-pressed": state.shiftSelected[key] ? "true" : "false" });
      cell.appendChild(el("span", { class: "dnum" }, String(d)));
      if (label) cell.appendChild(el("span", { class: "dshift" }, label));
      cell.addEventListener("click", function (dayKey) {
        return function () {
          if (state.shiftSelected[dayKey]) delete state.shiftSelected[dayKey];
          else state.shiftSelected[dayKey] = true;
          renderShiftCalendar();
        };
      }(key));
      grid.appendChild(cell);
    }
    box.appendChild(grid);

    var chosen = Object.keys(state.shiftSelected).length;
    box.appendChild(el("p", { class: "hint" }, chosen ? I.f("selectedDays").replace("{n}", String(chosen)) : I.f("pickDays")));
    box.appendChild(button(I.f("applyDays"), "btn btn-primary", applyShiftDays));
  }

  function moveMonth(step) {
    var m = state.shiftMonth;
    state.shiftMonth = new Date(m.getFullYear(), m.getMonth() + step, 1);
    state.shiftSelected = {};
    loadShiftMarks();
  }

  // Marks: the shift name of each day of the month, for this person.
  function loadShiftMarks() {
    var m = state.shiftMonth;
    var start = ymd(new Date(m.getFullYear(), m.getMonth(), 1)) + " 00:00:00";
    var end = ymd(new Date(m.getFullYear(), m.getMonth() + 1, 1)) + " 00:00:00";
    request({ op: "events", start: start, end: end }).then(function (events) {
      var marks = {};
      Object.keys(events).forEach(function (entity) {
        events[entity].forEach(function (ev) {
          if (ev.shift_id && ev.person_ids.indexOf(state.shiftPerson) !== -1) {
            marks[dayKey(ev.start)] = ev.summary;
          }
        });
      });
      state.shiftMarks = marks;
      renderShiftCalendar();
    }).catch(showShiftError);
  }

  function applyShiftDays() {
    var days = Object.keys(state.shiftSelected);
    if (!days.length) return;
    request({ op: "shifts_apply", person: state.shiftPerson, shift_id: state.shiftChoice, days: days })
      .then(function (result) {
        state.shiftSelected = {};
        $("shifts-error").hidden = true;
        showStatusNote(I.f("shiftApplied").replace("{n}", String(result.inserted)));
        refreshEvents();
        loadShiftMarks();
      })
      .catch(showShiftError);
  }

  // ---- external calendars (ICS) ---------------------------------------------------
  // Adults only. A calendar comes from a link (kept up to date every 12 hours, and "Update now")
  // or from an uploaded .ics file. The server checks everything; errors are translated.

  var ICS_TYPES = ["rifiuti", "vacanze_scuola", "vacanze_asilo", "festivita", "altro"];
  var ICS_MAX_BYTES = 5 * 1024 * 1024;
  var WASTE_PATHS = {
    calendar: '<rect x="4" y="5" width="16" height="15" rx="3"/><path d="M4 10h16M9 3v4M15 3v4"/>',
    beach: '<path d="M4 13a8 8 0 0 1 16 0z"/><path d="M12 13v7M12 5v0"/>',
    star: '<path d="M12 3l2.7 5.6 6.1.9-4.4 4.3 1 6.1L12 17l-5.4 2.9 1-6.1-4.4-4.3 6.1-.9z"/>',
    trash: '<path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13M10 11v6M14 11v6"/>',
    leaf: '<path d="M5 19c0-8 5-13 14-14-1 9-6 14-14 14z"/><path d="M5 19l7-7"/>',
    paper: '<path d="M7 3h7l4 4v14H7z"/><path d="M14 3v4h4M9 12h6M9 16h6"/>',
    bag: '<path d="M6 8h12l-1 12H7z"/><path d="M9 8a3 3 0 0 1 6 0"/>',
    bottle: '<path d="M10 3h4v3l2 3v11H8V9l2-3z"/><path d="M8 14h8"/>'
  };

  // The icon of each rubbish kind, and its colour (the family can change colours).
  var WASTE_ICON = { restmuell: "trash", bio: "leaf", papier: "paper", gelb: "bag", glas: "bottle" };

  // An icon by name, drawn in the current colour.
  function iconSvg(name) {
    var span = el("span", { class: "wx-icon waste-icon", "aria-hidden": "true" });
    span.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" ' +
      'stroke-linecap="round" stroke-linejoin="round">' + (WASTE_PATHS[name] || WASTE_PATHS.calendar) + "</svg>";
    return span;
  }

  // The icon of an external calendar, by its type.
  function typeIcon(type) {
    var names = { rifiuti: "trash", vacanze_scuola: "beach", vacanze_asilo: "beach", festivita: "star", altro: "calendar" };
    return iconSvg(names[type] || "calendar");
  }

  function wasteIcon(kind) {
    var span = el("span", { class: "wx-icon waste-icon", "aria-hidden": "true" });
    var mdi = window.FH_MDI || {};
    if (String(kind).indexOf("mdi:") === 0) {
      span.classList.add("mdi");
      span.innerHTML = '<svg viewBox="0 0 24 24" fill="currentColor"><path d="' +
        (mdi[kind] || mdi["mdi:trash-can-outline"]) + '"/></svg>';
      return span;
    }
    var icon = WASTE_ICON[kind] || "trash";
    span.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" ' +
      'stroke-linecap="round" stroke-linejoin="round">' + (WASTE_PATHS[icon] || WASTE_PATHS.trash) + "</svg>";
    return span;
  }

  function icsTypeName(kind) {
    var keys = { rifiuti: "typeRifiuti", vacanze_scuola: "typeVacanzeScuola", vacanze_asilo: "typeVacanzeAsilo",
      festivita: "typeFestivita", altro: "typeAltro" };
    return I.f(keys[kind] || "typeAltro");
  }

  function openIcs() {
    $("ics-error").hidden = true;
    $("ics-overlay").hidden = false;
    state.icsMode = state.icsMode || "link";
    loadIcs();
  }

  function closeIcs() { $("ics-overlay").hidden = true; }

  function showIcsError(err) {
    $("ics-error").textContent = errorText(err);
    $("ics-error").hidden = false;
  }

  function loadIcs() {
    Promise.all([request({ op: "ics_list" }), request({ op: "config_get" })]).then(function (both) {
      state.icsCalendars = both[0].calendars || [];
      state.icsStyles = both[0].waste_styles || {};
      state.icsKinds = both[0].waste_kinds || {};
      state.icsTypes = (both[0].waste_types || []).map(function (t) { return Object.assign({}, t); });
      state.icsPersons = both[1].persons || [];
      renderIcs();
    }).catch(showIcsError);
  }

  function formatDay(iso) {
    var d = new Date(iso);
    return pad(d.getDate()) + "/" + pad(d.getMonth() + 1) + "/" + d.getFullYear() + " " +
      showTime(pad(d.getHours()) + ":" + pad(d.getMinutes()), state.timeFormat);
  }

  function renderIcs() {
    var box = $("ics-body");
    box.textContent = "";
    if (!state.icsCalendars.length) box.appendChild(el("p", { class: "hint" }, I.f("icsEmpty")));
    state.icsCalendars.forEach(function (cal) { box.appendChild(icsCard(cal)); });
    box.appendChild(el("h3", {}, I.f("icsAddCalendar")));
    box.appendChild(icsForm());
    box.appendChild(el("h3", {}, I.f("wasteTypesTitle")));
    box.appendChild(wasteTypesForm());
  }

  // A glass button that opens the file chooser, with the chosen file's name beside it.
  function fileChooser(label, onFile) {
    var wrap = el("div", { class: "file-choice" });
    var input = el("input", { type: "file", accept: ".ics,text/calendar", class: "visually-hidden" });
    var name = el("span", { class: "file-name" }, I.f("icsNoFile"));
    var choose = button(label, "btn file-button", function () { input.click(); });
    input.addEventListener("change", function () {
      var file = input.files[0];
      name.textContent = file ? file.name : I.f("icsNoFile");
      if (file) onFile(file);
    });
    wrap.appendChild(choose);
    wrap.appendChild(name);
    wrap.appendChild(input);
    return wrap;
  }

  function icsCard(cal) {
    var card = el("section", { class: "notify-card ics-card" });
    card.style.setProperty("--ev", cal.color);
    var head = el("div", { class: "ics-head" });
    head.appendChild(el("span", { class: "ics-dot", "aria-hidden": "true" }));
    head.appendChild(el("h3", {}, cal.name));
    card.appendChild(head);
    card.appendChild(el("p", { class: "hint" }, icsTypeName(cal.type)));
    var status = cal.updated ? I.f("icsUpdated").replace("{d}", formatDay(cal.updated)) : I.f("icsNever");
    card.appendChild(el("p", { class: "hint" }, status));
    if (cal.error) card.appendChild(el("p", { class: "error", role: "alert" }, errorText({ code: cal.error })));
    var actions = el("div", { class: "notify-tests" });
    if (cal.source === "link") {
      card.appendChild(el("p", { class: "hint ics-url" }, cal.url));
      actions.appendChild(button(I.f("icsRefresh"), "btn", function () {
        request({ op: "ics_refresh", calendar_id: cal.id }).then(function () {
          showStatusNote(I.f("icsRefreshed"));
          loadIcs();
        }).catch(showIcsError);
      }));
    } else {
      actions.appendChild(fileChooser(I.f("icsReplace"), function (file) {
        readIcsFile(file, function (text) {
          request({ op: "ics_replace", calendar_id: cal.id, content: text }).then(loadIcs).catch(showIcsError);
        });
      }));
    }
    actions.appendChild(button(I.f("icsRemove"), "btn", function () {
      askConfirm(I.f("icsRemoveAsk").replace("{name}", cal.name), I.f("icsRemove")).then(function (yes) {
        if (!yes) return;
        request({ op: "ics_remove", calendar_id: cal.id }).then(function () {
          showStatusNote(I.f("icsRemoved"));
          loadIcs();
        }).catch(showIcsError);
      });
    }));
    card.appendChild(actions);
    return card;
  }

  // A question in Family Hub's own window (the confirm window), with two answers.
  function askConfirm(text, yesLabel) {
    return new Promise(function (resolve) {
      $("confirm-text").textContent = text;
      $("confirm-yes").textContent = yesLabel;
      $("confirm-no").hidden = true;
      $("confirm-overlay").hidden = false;
      function done(value) {
        $("confirm-overlay").hidden = true;
        $("confirm-no").hidden = false;
        $("confirm-yes").textContent = I.f("confirmYes");
        resolve(value);
      }
      $("confirm-yes").onclick = function () { done(true); };
      $("confirm-cancel").onclick = function () { done(false); };
    });
  }

  // The file as text, if it is not too large. Too large: the server's error text is shown.
  function readIcsFile(file, done) {
    if (!file) return;
    if (file.size > ICS_MAX_BYTES) {
      showIcsError({ code: "too_large" });
      return;
    }
    var reader = new FileReader();
    reader.onload = function () { done(String(reader.result)); };
    reader.readAsText(file, "utf-8");
  }

  // iOS-style segmented control: "Da link" | "Da file".
  // 5, 10, 15, 30 and 60 minutes. A value saved before (for example 105 from the old number
  // field) is added as one more choice, "105 min", so it is seen and can be changed.
  function snoozeChoices(current) {
    var choices = [["5", "5"], ["10", "10"], ["15", "15"], ["30", "30"], ["60", "60"]];
    var value = Number(current);
    if (value > 0 && !choices.some(function (c) { return Number(c[0]) === value; })) {
      choices.push([String(value), value + " min"]);
    }
    return choices;
  }

  function segmented(options, value, onChange) {
    var group = el("div", { class: "segmented", role: "group" });
    options.forEach(function (opt) {
      var b = el("button", { type: "button", class: "segment", "aria-pressed": opt[0] === value ? "true" : "false" }, opt[1]);
      b.addEventListener("click", function () {
        Array.prototype.forEach.call(group.children, function (c) { c.setAttribute("aria-pressed", "false"); });
        b.setAttribute("aria-pressed", "true");
        onChange(opt[0]);
      });
      group.appendChild(b);
    });
    return group;
  }

  function icsForm() {
    var f = I.f;
    var form = el("form", { class: "notify-card ics-form" });
    var name = textInput("", function () {}, { maxlength: 60, "aria-label": f("icsName") });
    var kind = selectInput(ICS_TYPES.map(function (k) { return [k, icsTypeName(k)]; }), "altro", function () {});
    var color = colorInput("#64748B", function () {});
    var url = textInput("", function () {}, { type: "url", "aria-label": f("icsUrl"), placeholder: "https://" });
    var chosenFile = null;
    var mode = state.icsMode || "link";
    var linkRow = fieldRow(f("icsUrl"), url);
    var seg = segmented([["link", f("icsFromLink")], ["file", f("icsFromFile")]], mode, function (v) {
      mode = v;
      state.icsMode = v;
      showMode();
    });
    function showMode() {
      linkRow.hidden = mode !== "link";
      fileBox.hidden = mode !== "file";
    }
    // Choosing a file switches the form to "Da file", so the file is the one that is sent.
    var fileBox = fileChooser(f("icsChooseFile"), function (file) {
      chosenFile = file;
      mode = "file";
      state.icsMode = "file";
      Array.prototype.forEach.call(seg.children, function (c, i) {
        c.setAttribute("aria-pressed", i === 1 ? "true" : "false");
      });
      showMode();
    });
    form.appendChild(seg);
    form.appendChild(fieldRow(f("icsName"), name));
    form.appendChild(fieldRow(f("icsType"), kind));
    form.appendChild(fieldRow(f("icsColor"), color));
    var persons = el("div", { class: "switch-list" });
    var chosen = {};
    state.icsPersons.forEach(function (p) {
      persons.appendChild(switchRow(p.name, false, function (on) { chosen[p.id] = on; }));
    });
    form.appendChild(el("p", { class: "hint" }, f("icsPersons")));
    form.appendChild(persons);
    form.appendChild(linkRow);
    form.appendChild(fileBox);
    showMode();
    form.appendChild(button(f("icsSave"), "btn btn-primary", function () {
      var calendar = {
        name: name.value.trim(), type: kind.value, color: color.value,
        icon: "calendar", persons: Object.keys(chosen).filter(function (id) { return chosen[id]; })
      };
      var send = function (extra) {
        request(Object.assign({ op: "ics_add", calendar: calendar }, extra)).then(function () {
          showStatusNote(f("icsSaved"));
          loadIcs();
        }).catch(showIcsError);
      };
      if (mode === "link") {
        if (url.value.trim()) send({ url: url.value.trim() });
        else showIcsError({ code: "no_source" });
      } else if (chosenFile) {
        readIcsFile(chosenFile, function (text) { send({ content: text }); });
      } else {
        showIcsError({ code: "no_source" });
      }
    }));
    return form;
  }

  // The rubbish types, for the ICS calendars and the Home Assistant ones alike: label, icon
  // (Material Design icons included in the add-on), the text to look for in the title, colour.
  // "Importa da TrashCard" fills the list from a TrashCard on a dashboard; "Salva tipi" keeps it.
  var WASTE_ICON_CHOICES = ["mdi:trash-can-outline", "mdi:trash-can", "mdi:flower", "mdi:leaf",
    "mdi:sprout", "mdi:tree", "mdi:recycle", "mdi:newspaper-variant", "mdi:package-variant-closed",
    "mdi:bottle-wine-outline", "mdi:glass-fragile", "mdi:dump-truck"];

  function wasteTypesForm() {
    var f = I.f;
    var form = el("div", { class: "notify-card ics-form waste-types" });
    form.appendChild(el("p", { class: "hint" }, f("wtHint")));
    var list = el("div", { class: "waste-type-list" });
    form.appendChild(list);
    function paint() {
      list.textContent = "";
      state.icsTypes.forEach(function (type, index) { list.appendChild(wasteTypeRow(type, index, paint)); });
    }
    paint();
    var actions = el("div", { class: "actions" });
    actions.appendChild(button(f("wtAdd"), "btn", function () {
      state.icsTypes.push({ id: "", label: "", icon: "mdi:trash-can-outline", pattern: "", color: "#9C27B0" });
      paint();
    }));
    actions.appendChild(button(f("wtImport"), "btn", function () {
      request({ op: "trashcard_import" }).then(function (r) {
        if (!r.types || !r.types.length) { showStatusNote(f("wtNoCard")); return; }
        state.icsTypes = r.types;
        paint();
        showStatusNote(f("wtImported"));
      }).catch(showIcsError);
    }));
    actions.appendChild(button(f("wtSave"), "btn btn-primary", function () {
      request({ op: "ics_waste_types", types: state.icsTypes }).then(function () {
        showStatusNote(f("wtSaved"));
        loadIcs();
        refreshCalendars();
        refreshEvents();
      }).catch(function (err) {
        $("ics-error").textContent = errorText(err) + (err.message && err.message !== err.code ? " " + err.message : "");
        $("ics-error").hidden = false;
      });
    }));
    form.appendChild(actions);
    return form;
  }

  function wasteTypeRow(type, index, repaint) {
    var f = I.f;
    var row = el("div", { class: "waste-type" });
    row.style.setProperty("--ev", type.color);
    var preview = wasteIcon(type.icon);
    preview.classList.add("waste-preview");
    row.appendChild(preview);
    row.appendChild(fieldRow(f("wtLabel"), textInput(type.label, function (v) { type.label = v; }, { maxlength: 30 })));
    var icons = WASTE_ICON_CHOICES.slice();
    if (icons.indexOf(type.icon) === -1) icons.push(type.icon);
    row.appendChild(fieldRow(f("wtIcon"), selectInput(icons.map(function (i) { return [i, i.slice(4)]; }), type.icon, function (v) {
      type.icon = v;
      repaint();
    })));
    row.appendChild(fieldRow(f("wtPattern"), textInput(type.pattern, function (v) { type.pattern = v; }, { maxlength: 200, placeholder: "Bioabfall, Bio" })));
    row.appendChild(fieldRow(f("wtColor"), colorInput(type.color, function (v) {
      type.color = v;
      row.style.setProperty("--ev", v);
    })));
    row.appendChild(button(f("wtRemove"), "btn", function () {
      state.icsTypes.splice(index, 1);
      repaint();
    }));
    return row;
  }

  // The colour of each rubbish kind (kept for older integrations without types).
  function wasteColorsForm() {
    var f = I.f;
    var form = el("form", { class: "notify-card ics-form" });
    var inputs = {};
    Object.keys(state.icsKinds || {}).forEach(function (kind) {
      var input = colorInput((state.icsStyles || {})[kind] || "#64748B", function () {});
      inputs[kind] = input;
      var row = el("div", { class: "waste-row" });
      row.appendChild(wasteIcon(kind));
      row.appendChild(el("span", { class: "waste-label" }, state.icsKinds[kind].label));
      row.appendChild(input);
      form.appendChild(row);
    });
    form.appendChild(button(f("icsSaveColors"), "btn btn-primary", function () {
      var styles = {};
      Object.keys(inputs).forEach(function (kind) { styles[kind] = inputs[kind].value; });
      request({ op: "ics_styles", styles: styles }).then(function () {
        showStatusNote(f("icsColorsSaved"));
        loadIcs();
        // The week shows the new colours at once.
        refreshCalendars();
        refreshEvents();
      }).catch(showIcsError);
    }));
    return form;
  }


  // ---- month view: find the free time --------------------------------------------
  // "Settimana | Mese" in the top bar; the choice stays on this screen. Each day of the month
  // shows up to three appointments and a bar of how busy it is between 07:00 and 21:00.
  // Rubbish, holidays and other external calendars are shown but do not count; shifts do.
  // A person filter keeps that person's events, their shifts and the family's (no persons).
  // Tapping a day opens it hour by hour, with the free slots of 30 minutes or more; tapping a
  // free slot opens "Nuovo evento" with the date and time filled in.

  var DAY_FROM = 7 * 60;
  var DAY_TO = 21 * 60;
  var MIN_FREE = 30;

  function loadView() {
    try {
      var saved = window.localStorage.getItem("fh_view");
      return saved === "month" || saved === "list" ? saved : "week";
    } catch (err) {
      return "week";
    }
  }

  function saveView(view) {
    try {
      window.localStorage.setItem("fh_view", view);
    } catch (err) {
      /* a private window: the choice lasts this visit only */
    }
  }

  function firstOfMonth(d) {
    return new Date(d.getFullYear(), d.getMonth(), 1);
  }

  // The 6 weeks shown for the month, starting on the family's first day of the week.
  function monthGridStart(month) {
    return addDays(month, -weekdayOffset(month));
  }

  function setView(view) {
    state.view = view;
    saveView(view);
    paintViewSwitch();
    refreshEvents();
  }

  function paintViewSwitch() {
    var box = $("view-switch");
    if (!box) return;
    Array.prototype.forEach.call(box.querySelectorAll("[data-view]"), function (b) {
      b.setAttribute("aria-pressed", b.getAttribute("data-view") === state.view ? "true" : "false");
    });
  }

  // Events with this person, events without persons (the family's), and every external event.
  var NOT_BUSY = ["rifiuti", "vacanze_scuola", "vacanze_asilo", "festivita"];

  function notBusyType(it) {
    return NOT_BUSY.indexOf(it.type || "") !== -1;
  }

  // Rubbish and holidays are everyone's; any other event belongs to its persons, or to the
  // family when it has none (Home Assistant calendars get theirs in Fonti).
  function forPerson(items) {
    var person = state.monthPerson;
    if (!person) return items;
    return items.filter(function (it) {
      var ids = it.ev.person_ids || [];
      return notBusyType(it) || !ids.length || ids.indexOf(person) !== -1;
    });
  }

  function counts(it) {
    return !notBusyType(it) && !isAllDay(it.ev.start);
  }

  // Minutes from midnight of the day, kept between 07:00 and 21:00.
  function minutesIn(key, iso) {
    var dayStart = new Date(key + "T00:00:00").getTime();
    var m = Math.round((new Date(iso).getTime() - dayStart) / 60000);
    return Math.max(DAY_FROM, Math.min(DAY_TO, m));
  }

  // The busy stretches of a day (merged), between 07:00 and 21:00.
  function busyIntervals(items, key) {
    var spans = items.filter(counts).map(function (it) {
      return [minutesIn(key, it.ev.start), minutesIn(key, it.ev.end || it.ev.start)];
    }).filter(function (s) { return s[1] > s[0]; }).sort(function (a, b) { return a[0] - b[0]; });
    var merged = [];
    spans.forEach(function (s) {
      var last = merged[merged.length - 1];
      if (last && s[0] <= last[1]) last[1] = Math.max(last[1], s[1]);
      else merged.push([s[0], s[1]]);
    });
    return merged;
  }

  function busyMinutes(items, key) {
    return busyIntervals(items, key).reduce(function (sum, s) { return sum + s[1] - s[0]; }, 0);
  }

  // Free stretches of at least 30 minutes between the busy ones.
  function freeSlots(items, key) {
    var slots = [];
    var at = DAY_FROM;
    busyIntervals(items, key).forEach(function (s) {
      if (s[0] - at >= MIN_FREE) slots.push([at, s[0]]);
      at = Math.max(at, s[1]);
    });
    if (DAY_TO - at >= MIN_FREE) slots.push([at, DAY_TO]);
    return slots;
  }

  function hhmm(minutes) {
    return pad(Math.floor(minutes / 60)) + ":" + pad(minutes % 60);
  }

  function hoursText(minutes) {
    var h = minutes / 60;
    return (Math.round(h * 10) / 10).toLocaleString(I.lang);
  }

  function personFilter() {
    var f = I.f;
    var options = [["", f("personAll")]].concat(personList().map(function (p) { return [p.id, p.name]; }));
    var select = selectInput(options, state.monthPerson || "", function (v) {
      state.monthPerson = v;
      if (state.view === "month") repaintMonths();
      else renderWeek();
    }, { id: "month-person", "aria-label": f("personFilter") });
    return fieldRow(f("personFilter"), select);
  }

  // Months one under the other, from 3 months back to 12 ahead (more are added at the end).
  // Each month's events are read when the month comes near the screen; its title stays at
  // the top while its days scroll. "Oggi" goes back to this month; the arrows jump one month.
  var MONTHS_BACK = 3;
  var MONTHS_AHEAD = 12;

  function monthKey(d) { return d.getFullYear() + "-" + pad(d.getMonth() + 1); }

  function monthOf(key) {
    var p = key.split("-");
    return new Date(Number(p[0]), Number(p[1]) - 1, 1);
  }

  // Every loaded month's events together (the months do not overlap): for the days and the
  // day view.
  function monthEvents() {
    var all = {};
    Object.keys(state.monthLoaded).forEach(function (key) {
      var events = state.monthLoaded[key];
      Object.keys(events).forEach(function (entity) {
        all[entity] = (all[entity] || []).concat(events[entity]);
      });
    });
    return all;
  }

  function renderMonth(week) {
    var compact = state.mode === "phone";
    week.className = "week month" + (compact ? " compact" : "");
    var head = el("div", { class: "month-head" });
    head.appendChild(personFilter());
    week.appendChild(head);
    var scroller = el("div", { class: "month-scroll", id: "month-scroll", tabindex: "0",
      "aria-label": I.f("viewMonth") });
    week.appendChild(scroller);
    var now = firstOfMonth(new Date());
    var from = new Date(now.getFullYear(), now.getMonth() - MONTHS_BACK, 1);
    for (var i = 0; i <= MONTHS_BACK + MONTHS_AHEAD; i++) {
      scroller.appendChild(monthBlock(new Date(from.getFullYear(), from.getMonth() + i, 1)));
    }
    fitToScreen(scroller);
    watchMonths(scroller);
    scroller.addEventListener("keydown", function (e) {
      if (e.key === "PageDown") { e.preventDefault(); jumpMonth(1); }
      if (e.key === "PageUp") { e.preventDefault(); jumpMonth(-1); }
    });
    scrollToMonth(monthKey(state.monthStart), false);
  }

  function fitToScreen(box) {
    var top = box.getBoundingClientRect().top;
    box.style.maxHeight = Math.max(240, window.innerHeight - top - 8) + "px";
  }

  function monthBlock(month) {
    var key = monthKey(month);
    var block = el("section", { class: "month-block", "data-month": key });
    block.appendChild(el("h2", { class: "month-title" },
      month.toLocaleDateString(I.lang, { month: "long", year: "numeric" })));
    var grid = el("div", { class: "month-view" });
    block.appendChild(grid);
    paintMonthGrid(grid, month);
    if (state.monthLoaded[key]) block.classList.add("loaded");
    return block;
  }

  // Load the months that come near the screen; add more months at the end.
  function watchMonths(scroller) {
    if (state.monthObserver) state.monthObserver.disconnect();
    if (!("IntersectionObserver" in window)) {
      Array.prototype.forEach.call(scroller.children, function (b) { loadMonth(b); });
      return;
    }
    state.monthObserver = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (!entry.isIntersecting) return;
        loadMonth(entry.target);
        if (entry.target === scroller.lastElementChild) {
          var last = monthOf(entry.target.getAttribute("data-month"));
          for (var i = 1; i <= 6; i++) {
            var block = monthBlock(new Date(last.getFullYear(), last.getMonth() + i, 1));
            scroller.appendChild(block);
            state.monthObserver.observe(block);
          }
        }
      });
    }, { root: scroller, rootMargin: "400px 0px" });
    Array.prototype.forEach.call(scroller.children, function (b) { state.monthObserver.observe(b); });
  }

  function loadMonth(block) {
    var key = block.getAttribute("data-month");
    if (state.monthLoaded[key] || state.monthLoading[key]) return;
    state.monthLoading[key] = true;
    var month = monthOf(key);
    var next = new Date(month.getFullYear(), month.getMonth() + 1, 1);
    request({ op: "events", start: ymd(month) + " 00:00:00", end: ymd(next) + " 00:00:00" })
      .then(function (events) {
        state.monthLoaded[key] = events;
        delete state.monthLoading[key];
        paintMonthGrid(block.querySelector(".month-view"), month);
        block.classList.add("loaded");
      })
      .catch(function () { delete state.monthLoading[key]; });
  }

  function repaintMonths() {
    Array.prototype.forEach.call(document.querySelectorAll(".month-block"), function (block) {
      paintMonthGrid(block.querySelector(".month-view"), monthOf(block.getAttribute("data-month")));
    });
  }

  function scrollToMonth(key, smooth) {
    var scroller = $("month-scroll");
    var block = scroller && scroller.querySelector(".month-block[data-month='" + key + "']");
    if (!block) return;
    state.monthStart = monthOf(key);
    scroller.scrollTo({ top: block.offsetTop - scroller.offsetTop, behavior: smooth ? "smooth" : "auto" });
  }

  // The month whose title is at the top now.
  function monthAtTop() {
    var scroller = $("month-scroll");
    if (!scroller) return monthKey(state.monthStart);
    var top = scroller.getBoundingClientRect().top + 2;
    var found = null;
    Array.prototype.forEach.call(scroller.querySelectorAll(".month-block"), function (b) {
      if (b.getBoundingClientRect().top <= top) found = b;
    });
    return found ? found.getAttribute("data-month") : monthKey(state.monthStart);
  }

  function jumpMonth(direction) {
    var at = monthOf(monthAtTop());
    scrollToMonth(monthKey(new Date(at.getFullYear(), at.getMonth() + direction, 1)), false);
  }

  function paintMonthGrid(grid, month) {
    var f = I.f;
    var compact = state.mode === "phone";
    grid.textContent = "";
    orderedDays(t("days")).forEach(function (name) {
      grid.appendChild(el("div", { class: "month-dow" }, name));
    });
    var events = state.monthLoaded[monthKey(month)] || {};
    var byDay = eventsByDay(events);
    var today = ymd(new Date());
    var lead = weekdayOffset(month);
    for (var p = 0; p < lead; p++) grid.appendChild(el("span", { class: "month-pad", "aria-hidden": "true" }));
    var days = new Date(month.getFullYear(), month.getMonth() + 1, 0).getDate();
    for (var i = 0; i < days; i++) {
      var day = addDays(month, i);
      var key = ymd(day);
      var items = forPerson(byDay[key] || []);
      var busy = busyMinutes(items, key);
      var cell = el("button", { type: "button", class: "month-day" + (key === today ? " today" : ""),
        "data-day": key, "data-busy": String(busy),
        "aria-label": day.toLocaleDateString(I.lang, { weekday: "long", day: "numeric", month: "long" }) });
      cell.appendChild(el("span", { class: "month-num" }, String(day.getDate())));
      var bar = el("span", { class: "occ", title: f("busyHours").replace("{h}", hoursText(busy)) });
      var fill = el("span", { class: "occ-fill" });
      fill.style.width = Math.round(busy / (DAY_TO - DAY_FROM) * 100) + "%";
      bar.appendChild(fill);
      cell.appendChild(bar);
      if (compact) {
        var dots = el("span", { class: "month-dots" });
        var colors = [];
        items.forEach(function (it) { (it.colors || [it.color]).forEach(function (c) { colors.push(c); }); });
        colors.slice(0, 5).forEach(function (color) {
          var dot = el("span", { class: "month-dot" });
          dot.style.background = color;
          dots.appendChild(dot);
        });
        cell.appendChild(dots);
      } else {
        items.slice(0, 3).forEach(function (it) {
          var line = el("span", { class: "month-ev" + (it.ev.external ? " external" : "") });
          line.style.setProperty("--ev", it.ev.waste_color || it.color);
          var time = isAllDay(it.ev.start) ? "" : timeOf(it.ev.start) + " ";
          line.textContent = time + shownTitle(it.ev);
          if ((it.colors || []).length > 1) line.appendChild(calendarDots(it));
          cell.appendChild(line);
        });
        if (items.length > 3) {
          cell.appendChild(el("span", { class: "month-more" }, f("moreEvents").replace("{n}", String(items.length - 3))));
        }
      }
      cell.addEventListener("click", (function (k) { return function () { openDay(k); }; })(key));
      grid.appendChild(cell);
    }
  }

  // ---- list view: every appointment of the next 12 months --------------------------
  // By month and day, with time, title, calendar colour and persons. The person filter of the
  // month view applies; rubbish is hidden unless "Mostra rifiuti" is on. A tap opens the card.

  function renderList(week) {
    var f = I.f;
    week.className = "week list-view";
    var head = el("div", { class: "month-head" });
    head.appendChild(personFilter());
    head.appendChild(switchRow(f("showWaste"), !!state.listWaste, function (on) {
      state.listWaste = on;
      renderWeek();
    }));
    week.appendChild(head);
    var body = el("div", { class: "list-scroll", id: "list-scroll", tabindex: "0" });
    week.appendChild(body);
    fitToScreen(body);
    var byDay = eventsByDay(state.events);
    var today = ymd(new Date());
    var keys = Object.keys(byDay).filter(function (k) { return k >= today; }).sort();
    var shownMonth = "";
    var count = 0;
    keys.forEach(function (key) {
      var items = forPerson(byDay[key]).filter(function (it) {
        return state.listWaste || !(it.ev.waste || it.type === "rifiuti");
      });
      if (!items.length) return;
      var day = parseLocalDay(key);
      var mk = key.slice(0, 7);
      if (mk !== shownMonth) {
        shownMonth = mk;
        body.appendChild(el("h2", { class: "list-month" }, day.toLocaleDateString(I.lang, { month: "long", year: "numeric" })));
      }
      var section = el("section", { class: "list-day", "data-day": key });
      section.appendChild(el("h3", { class: "list-date" + (key === today ? " today" : "") },
        day.toLocaleDateString(I.lang, { weekday: "long", day: "numeric", month: "long" })));
      items.forEach(function (it) {
        count++;
        var row = el("button", { type: "button", class: "list-row" });
        row.style.setProperty("--ev", it.ev.waste_color || it.color);
        row.appendChild(el("span", { class: "list-time" }, isAllDay(it.ev.start) ? I.f("allDayLabel") : timeOf(it.ev.start)));
        var title = el("span", { class: "list-title" });
        if (it.ev.waste) title.appendChild(wasteIcon(it.ev.waste_icon || it.ev.waste));
        title.appendChild(document.createTextNode(shownTitle(it.ev)));
        if ((it.colors || []).length > 1) title.appendChild(calendarDots(it));
        row.appendChild(title);
        var names = (it.ev.person_ids || []).map(personName).filter(function (n) { return n; });
        row.appendChild(el("span", { class: "list-persons" }, names.join(", ")));
        row.addEventListener("click", function () { openCard(it); });
        section.appendChild(row);
      });
      body.appendChild(section);
    });
    if (!count) body.appendChild(el("p", { class: "hint" }, f("listEmpty")));
  }

  function canAdd() {
    return state.role === "adult" || state.role === "shared" || state.role === "child";
  }

  // One day, hour by hour from 07:00 to 21:00: busy blocks and free slots.
  function openDay(key) {
    var f = I.f;
    var old = document.querySelector(".day-overlay");
    if (old) old.remove();
    var source = state.view === "month" ? monthEvents() : state.events;
    var items = forPerson(eventsByDay(source)[key] || []);
    var box = el("div", { class: "overlay day-overlay", role: "dialog", "aria-label": key });
    var panel = el("div", { class: "dialog dayview" });
    panel.appendChild(el("h2", {}, new Date(key + "T12:00:00").toLocaleDateString(I.lang,
      { weekday: "long", day: "numeric", month: "long" })));
    var body = el("div", { class: "dialog-body dayview-body" });
    // All-day and external events: shown, but they do not take time.
    items.filter(function (it) { return !counts(it); }).forEach(function (it) {
      var line = el("div", { class: "day-note" });
      line.style.setProperty("--ev", it.ev.waste_color || it.color);
      if (it.ev.waste) line.appendChild(wasteIcon(it.ev.waste_icon || it.ev.waste));
      line.appendChild(document.createTextNode((isAllDay(it.ev.start) ? "" : timeOf(it.ev.start) + " ") + shownTitle(it.ev)));
      body.appendChild(line);
    });
    var timed = items.filter(counts);
    var free = freeSlots(items, key);
    var busy = busyIntervals(items, key);
    var parts = busy.map(function (s) { return { kind: "busy", from: s[0], to: s[1] }; })
      .concat(free.map(function (s) { return { kind: "free", from: s[0], to: s[1] }; }))
      .sort(function (a, b) { return a.from - b.from; });
    if (!free.length) body.appendChild(el("p", { class: "hint" }, f("noFreeSlot")));
    else if (canAdd()) body.appendChild(el("p", { class: "hint" }, f("dayHint")));
    var timeline = el("div", { class: "timeline" });
    parts.forEach(function (part) {
      var height = Math.max(44, Math.round((part.to - part.from) * 0.45)) + "px";
      var range = showTime(hhmm(part.from), state.timeFormat) + "–" + showTime(hhmm(part.to), state.timeFormat);
      if (part.kind === "busy") {
        var block = el("div", { class: "busy-block" });
        block.style.minHeight = height;
        block.appendChild(el("span", { class: "slot-time" }, range));
        timed.filter(function (it) {
          return minutesIn(key, it.ev.start) < part.to && minutesIn(key, it.ev.end || it.ev.start) > part.from;
        }).forEach(function (it) {
          var name = el("span", { class: "busy-name" }, timeOf(it.ev.start) + " " + shownTitle(it.ev));
          name.style.setProperty("--ev", it.color);
          block.appendChild(name);
        });
        timeline.appendChild(block);
      } else {
        var slot = el("button", { type: "button", class: "free-slot", "data-from": hhmm(part.from), "data-to": hhmm(part.to) },
          f("freeSlot") + " " + range);
        slot.style.minHeight = height;
        if (!canAdd()) slot.disabled = true;
        slot.addEventListener("click", function () {
          box.remove();
          openFormAt(key, part.from, Math.min(part.from + 60, part.to));
        });
        timeline.appendChild(slot);
      }
    });
    body.appendChild(timeline);
    panel.appendChild(body);
    var foot = el("div", { class: "dialog-foot actions" });
    foot.appendChild(button(f("cardClose"), "btn", function () { box.remove(); }));
    panel.appendChild(foot);
    box.appendChild(panel);
    box.addEventListener("click", function (e) { if (e.target === box) box.remove(); });
    document.body.appendChild(box);
  }

  // "Nuovo evento" for a free slot: the date and times are filled in (and the person chosen).
  function openFormAt(key, from, to) {
    openForm(null);
    var form = $("event-form");
    form.elements.all_day.checked = false;
    form.elements.all_day.dispatchEvent(new Event("change"));
    form.elements.date.value = showDate(key);
    form.elements.start_time.value = showTime(hhmm(from), state.timeFormat);
    form.elements.end_time.value = showTime(hhmm(to), state.timeFormat);
    if (state.monthPerson) {
      renderEventPersons([state.monthPerson]);
      ensureNotifyData().then(function () {
        state.eventNotify = notifyFromPersons([state.monthPerson]);
        renderEventNotify();
      });
    }
    loadDayCache(parseLocalDay(key)).then(function () { updateDayInfo(form); });
  }

  // ---- weather -------------------------------------------------------------------
  // The weather entity the guide chose: now (top bar) and the daily forecast (each day's
  // column, and the phone's Today and Tomorrow). Icons are drawn here, in the page itself.

  var WX_PATHS = {
    sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M2 12h2M20 12h2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
    moon: '<path d="M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z"/>',
    cloud: '<path d="M7 18h10a4 4 0 0 0 0-8 5.5 5.5 0 0 0-10.6 1.5A3.2 3.2 0 0 0 7 18z"/>',
    partly: '<circle cx="9" cy="8" r="3"/><path d="M9 2v1.2M3 8h1.2M4.6 3.6l.9.9M13.4 3.6l-.9.9"/><path d="M9 18h9a3.5 3.5 0 0 0 0-7 4.8 4.8 0 0 0-9.1 1.3A2.8 2.8 0 0 0 9 18z"/>',
    rain: '<path d="M7 15h10a4 4 0 0 0 0-8 5.5 5.5 0 0 0-10.6 1.5A3.2 3.2 0 0 0 7 15z"/><path d="M8 18l-1 3M12 18l-1 3M16 18l-1 3"/>',
    snow: '<path d="M7 15h10a4 4 0 0 0 0-8 5.5 5.5 0 0 0-10.6 1.5A3.2 3.2 0 0 0 7 15z"/><path d="M8 19h.01M12 20h.01M16 19h.01" stroke-width="2.6"/>',
    fog: '<path d="M3 8h18M5 12h14M3 16h18M6 20h12"/>',
    thunder: '<path d="M7 15h10a4 4 0 0 0 0-8 5.5 5.5 0 0 0-10.6 1.5A3.2 3.2 0 0 0 7 15z"/><path d="M13 14l-2 4h3l-2 4"/>',
    wind: '<path d="M3 8h11a3 3 0 1 0-3-3M3 12h15a3 3 0 1 1-3 3M3 16h7"/>',
    hail: '<path d="M7 15h10a4 4 0 0 0 0-8 5.5 5.5 0 0 0-10.6 1.5A3.2 3.2 0 0 0 7 15z"/><circle cx="8" cy="19" r="1"/><circle cx="12" cy="20" r="1"/><circle cx="16" cy="19" r="1"/>'
  };

  var WX_KIND = {
    sunny: "sun", "clear-night": "moon", cloudy: "cloud", exceptional: "cloud",
    partlycloudy: "partly", rainy: "rain", pouring: "rain", snowy: "snow", "snowy-rainy": "snow",
    fog: "fog", lightning: "thunder", "lightning-rainy": "thunder", windy: "wind",
    "windy-variant": "wind", hail: "hail"
  };

  function weatherIcon(condition) {
    var span = el("span", { class: "wx-icon", "aria-hidden": "true" });
    var kind = WX_KIND[condition] || "cloud";
    span.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" ' +
      'stroke-linecap="round" stroke-linejoin="round">' + WX_PATHS[kind] + "</svg>";
    return span;
  }

  function loadWeather() {
    request({ op: "weather" }).then(function (weather) {
      state.weather = weather;
      renderWeatherNow();
      renderWeatherDays();
      renderWeek();
    }).catch(function () {
      state.weather = null;
      renderWeatherNow();
      renderWeatherDays();
    });
  }

  function renderWeatherNow() {
    var box = $("weather-now");
    box.textContent = "";
    var w = state.weather;
    box.hidden = !w || w.temperature == null;
    if (box.hidden) return;
    box.appendChild(weatherIcon(w.condition));
    var text = el("span", { class: "wx-text" });
    text.appendChild(el("strong", {}, Math.round(w.temperature) + w.unit));
    text.appendChild(el("span", { class: "wx-cond" }, " " + I.w.cond(w.condition)));
    box.appendChild(text);
  }

  // The next three days in the top bar, beside the current weather: short day name, icon,
  // high and low. Always shown when there is a forecast for them.
  function renderWeatherDays() {
    var box = $("weather-days");
    box.textContent = "";
    var today = ymd(new Date());
    var list = state.weather && state.weather.forecast ? state.weather.forecast : [];
    var next = list.filter(function (f) { return String(f.datetime).slice(0, 10) > today; }).slice(0, 3);
    box.hidden = next.length === 0;
    next.forEach(function (f) {
      var day = new Date(String(f.datetime).slice(0, 10) + "T12:00:00");
      var cell = el("div", { class: "wx-day", title: I.w.cond(f.condition) });
      cell.appendChild(el("span", { class: "wx-day-name" }, day.toLocaleDateString(I.lang, { weekday: "short" })));
      cell.appendChild(weatherIcon(f.condition));
      var temps = el("span", { class: "wx-temps" });
      if (f.temperature != null) temps.appendChild(el("span", { class: "wx-max" }, Math.round(f.temperature) + "°"));
      if (f.templow != null) temps.appendChild(el("span", { class: "wx-min" }, Math.round(f.templow) + "°"));
      cell.appendChild(temps);
      box.appendChild(cell);
    });
  }

  // Forecast by day (yyyy-mm-dd): the high and low, and the condition.
  function forecastOn(key) {
    var list = state.weather && state.weather.forecast ? state.weather.forecast : [];
    for (var i = 0; i < list.length; i++) {
      if (String(list[i].datetime).slice(0, 10) === key) return list[i];
    }
    return null;
  }

  // The day's weather under its number: icon, high and low. Days without a forecast: nothing.
  function dayWeather(key) {
    var f = forecastOn(key);
    if (!f) return null;
    var row = el("div", { class: "day-weather" });
    row.appendChild(weatherIcon(f.condition));
    if (f.temperature != null) row.appendChild(el("span", { class: "wx-max" }, Math.round(f.temperature) + "°"));
    if (f.templow != null) row.appendChild(el("span", { class: "wx-min" }, Math.round(f.templow) + "°"));
    row.setAttribute("title", I.w.cond(f.condition));
    return row;
  }

  // ---- notification settings ("Avvisi") ------------------------------------------
  // Each person's phone, Echo speakers, channels, volume and quiet hours. Adults see everyone,
  // a child only their own, a guest nothing. The server checks every save.

  var CHANNEL_KEYS = ["phone", "alexa", "tablet"];

  function loadNotifyOptions(data) {
    state.notifyServices = data.services;
    state.notifyUsers = data.users || [];
  }

  // A choice list that still shows a value the family once chose, even if it has gone missing.
  function withCurrent(options, value) {
    if (value && !options.some(function (o) { return o[0] === value; })) {
      options.push([value, value + " · " + I.f("missingService")]);
    }
    return options;
  }

  function userSelect(value, onChange) {
    var options = [["", I.f("noUser")]];
    state.notifyUsers.forEach(function (u) { options.push([u.id, u.name]); });
    return selectInput(withCurrent(options, value), value || "", onChange);
  }

  function phoneSelect(value, onChange) {
    var options = [["", I.f("noService")]];
    state.notifyServices.phone.forEach(function (s) { options.push([s.name, s.label]); });
    return selectInput(withCurrent(options, value), value || "", onChange);
  }

  function echoSelect(value, onChange) {
    var options = [["", I.f("noService")], ["all", I.f("allEchos")]];
    state.notifyServices.alexa.forEach(function (s) { options.push([s.entity_id, s.name]); });
    return selectInput(withCurrent(options, value), value || "", onChange);
  }

  // Volume of the announcement on Echo speakers: a slider 0 to 100, or "predefinito" (the
  // speaker's own level, sent as null).
  // One slider with its value in %, and one switch "Predefinito" (on: the speaker's own level).
  function volumeControl(value, onChange) {
    var wrap = el("div", { class: "volume" });
    var slider = el("input", { type: "range", min: 0, max: 100, step: 1, "aria-label": I.f("alexaVolume") });
    var readout = el("span", { class: "volume-value" });
    var level = value == null ? 60 : value;
    var isDefault = value == null;
    var sliderRow = el("div", { class: "volume-slider" });
    sliderRow.appendChild(slider);
    sliderRow.appendChild(readout);
    var defaultSwitch = null;
    function paint() {
      slider.value = String(level);
      wrap.classList.toggle("is-default", isDefault);
      readout.textContent = level + " %";
      if (defaultSwitch) {
        defaultSwitch.checked = isDefault;
        defaultSwitch.setAttribute("aria-checked", isDefault ? "true" : "false");
      }
    }
    // Touching or dragging the slider means a volume of its own: "predefinito" goes off.
    function own() {
      level = Number(slider.value);
      if (isDefault) isDefault = false;
      paint();
      onChange(level);
    }
    slider.addEventListener("input", own);
    slider.addEventListener("pointerdown", function () { if (isDefault) { isDefault = false; paint(); onChange(level); } });
    wrap.appendChild(sliderRow);
    var row = switchRow(I.f("volumeDefault"), isDefault, function (on) {
      isDefault = on;
      paint();
      onChange(on ? null : level);
    });
    defaultSwitch = row.querySelector("input");
    wrap.appendChild(row);
    paint();
    return wrap;
  }

  // A full-width row as in the iOS Settings app: text on the left, switch on the right.
  function switchRow(text, checked, onChange) {
    var label = el("label", { class: "switch switch-row" });
    var input = el("input", { type: "checkbox", role: "switch" });
    input.checked = checked;
    input.setAttribute("aria-checked", checked ? "true" : "false");
    input.addEventListener("change", function () { onChange(input.checked); });
    label.appendChild(el("span", {}, text));
    label.appendChild(input);
    return label;
  }

  function openNotify() {
    $("notify-error").hidden = true;
    $("notify-overlay").hidden = false;
    $("notify-body").textContent = "";
    request({ op: "notify_get" }).then(function (data) {
      state.notifyData = data;
      loadNotifyOptions(data);
      renderNotify();
    }).catch(showNotifyError);
  }

  function closeNotify() { $("notify-overlay").hidden = true; }

  function showNotifyError(err) {
    $("notify-error").textContent = errorText(err);
    $("notify-error").hidden = false;
  }

  function renderNotify() {
    var box = $("notify-body");
    box.textContent = "";
    state.notifyData.persons.forEach(function (person) {
      box.appendChild(notifyCard(person));
    });
    box.appendChild(button(I.f("saveNotify"), "btn btn-primary", saveNotify));
    if (state.role === "adult") box.appendChild(sharedCard());
  }

  // Home Assistant users that are no person (the kitchen tablet): they may add, change and
  // tick events and lists, but not open the settings. Only users not linked to a person.
  function sharedCard() {
    var f = I.f;
    var card = el("section", { class: "notify-card" });
    card.appendChild(el("h3", {}, f("sharedTitle")));
    card.appendChild(el("p", { class: "hint" }, f("sharedHint")));
    var linked = {};
    state.notifyData.persons.forEach(function (p) { if (p.ha_user_id) linked[p.ha_user_id] = true; });
    var chosen = (state.notifyData.shared_users || []).slice();
    var list = el("div", { class: "switch-list" });
    state.notifyUsers.filter(function (u) { return !linked[u.id]; }).forEach(function (u) {
      list.appendChild(switchRow(u.name, chosen.indexOf(u.id) !== -1, function (on) {
        chosen = on ? chosen.concat([u.id]) : chosen.filter(function (c) { return c !== u.id; });
      }));
    });
    card.appendChild(list);
    card.appendChild(button(f("saveShared"), "btn", function () {
      request({ op: "shared_save", users: chosen }).then(function () {
        showStatusNote(f("sharedSaved"));
        openNotify();
      }).catch(showNotifyError);
    }));
    return card;
  }

  function notifyCard(person) {
    var f = I.f;
    var card = el("section", { class: "notify-card" });
    card.appendChild(el("h3", {}, person.name));
    if (state.role === "adult") {
      card.appendChild(fieldRow(f("haUser"), userSelect(person.ha_user_id, function (v) { person.ha_user_id = v; })));
    }
    card.appendChild(fieldRow(f("phone"), phoneSelect(person.phone_notify, function (v) { person.phone_notify = v; })));
    card.appendChild(fieldRow(f("alexa"), echoSelect(person.alexa_notify, function (v) { person.alexa_notify = v; })));
    card.appendChild(fieldRow(f("alexaVolume"), volumeControl(person.alexa_volume, function (v) { person.alexa_volume = v; })));
    var labels = { phone: f("chPhone"), alexa: f("chAlexa"), tablet: f("chTablet") };
    var list = el("div", { class: "switch-list" });
    CHANNEL_KEYS.forEach(function (key) {
      list.appendChild(switchRow(labels[key], person.channels.indexOf(key) !== -1, function (on) {
        var rest = person.channels.filter(function (c) { return c !== key; });
        person.channels = on ? rest.concat([key]) : rest;
      }));
    });
    card.appendChild(list);
    card.appendChild(fieldRow(f("quietStart"), timeInput(person.quiet_start, f("quietStart"), function (v) { person.quiet_start = v; }, "22:00")));
    card.appendChild(fieldRow(f("quietEnd"), timeInput(person.quiet_end, f("quietEnd"), function (v) { person.quiet_end = v; }, "07:00")));
    card.appendChild(el("p", { class: "hint" }, f("quietHint")));
    // Tests use the saved settings: they appear once a service is saved.
    var tests = el("div", { class: "notify-tests" });
    if (person.phone_notify) tests.appendChild(button(f("testPhone"), "btn", function () { testNotify(person, "phone"); }));
    if (person.alexa_notify) tests.appendChild(button(f("testEcho"), "btn", function () { testNotify(person, "alexa"); }));
    card.appendChild(tests);
    card.appendChild(el("p", { class: "hint" }, f("testHint")));
    return card;
  }

  function saveNotify() {
    if ($("notify-body").querySelector("[aria-invalid='true']")) {
      $("notify-error").textContent = I.f("shiftBadTime");
      $("notify-error").hidden = false;
      return;
    }
    var persons = {};
    state.notifyData.persons.forEach(function (p) {
      var change = {
        phone_notify: p.phone_notify || "",
        alexa_notify: p.alexa_notify || "",
        alexa_volume: p.alexa_volume == null ? null : p.alexa_volume,
        channels: p.channels,
        quiet_start: p.quiet_start || "",
        quiet_end: p.quiet_end || ""
      };
      if (state.role === "adult") change.ha_user_id = p.ha_user_id || "";
      persons[p.id] = change;
    });
    request({ op: "notify_save", persons: persons }).then(function () {
      showStatusNote(I.f("notifySaved"));
      openNotify();
    }).catch(showNotifyError);
  }

  function testNotify(person, kind) {
    request({ op: "notify_test", person: person.id, kind: kind }).then(function (result) {
      showStatusNote(I.f("testSent").replace("{n}", String(result.sent)));
    }).catch(showNotifyError);
  }

  // "Riduci trasparenza": solid panels instead of glass. Kept on this screen only.
  function applyTransparency(reduce) {
    document.body.classList.toggle("reduce-transparency", reduce);
    $("menu-transparency").checked = reduce;
  }

  function storedTransparency() {
    try {
      return window.localStorage.getItem("fh_reduce_transparency") === "1";
    } catch (err) {
      return false;
    }
  }

  function saveTransparency(reduce) {
    try {
      window.localStorage.setItem("fh_reduce_transparency", reduce ? "1" : "0");
    } catch (err) {
      /* a private window: the choice lasts this visit only */
    }
  }

  // ---- wiring ----------------------------------------------------------------

  function applyTexts() {
    document.documentElement.lang = I.lang;
    $("this-week").textContent = t("today");
    [["week", "viewWeek", "viewWeekShort"], ["month", "viewMonth", "viewMonthShort"],
      ["list", "viewList", "viewListShort"]].forEach(function (v) {
      var b = document.querySelector("#view-switch [data-view='" + v[0] + "']");
      b.textContent = "";
      b.appendChild(el("span", { class: "label-full" }, I.f(v[1])));
      b.appendChild(el("span", { class: "label-short", "aria-hidden": "true" }, I.f(v[2])));
    });
    $("view-switch").setAttribute("aria-label", I.f("viewChoice"));
    $("todo-btn").textContent = I.f("listsButton");
    $("menu-btn").textContent = I.f("menu");
    $("menu-btn").setAttribute("aria-label", I.f("menu"));
    $("menu-lists").textContent = I.f("listsButton");
    $("event-category-hint").textContent = I.f("evPersonsHint");
    $("menu-wizard").textContent = t("wizardStart");
    $("menu-shifts").textContent = I.f("menuShifts");
    $("menu-notify").textContent = I.f("menuNotify");
    $("menu-transparency-label").textContent = I.f("reduceTransparency");
    $("notify-title").textContent = I.f("menuNotify");
    $("notify-close").textContent = I.f("closeLists");
    $("menu-ics").textContent = I.f("menuIcs");
    $("ics-title").textContent = I.f("icsTitle");
    $("ics-close").textContent = I.f("closeLists");
    $("shifts-title").textContent = I.f("shiftsTitle");
    $("tab-models").textContent = I.f("tabModels");
    $("tab-calendar").textContent = I.f("tabCalendar");
    $("shifts-close").textContent = I.f("closeLists");
    $("shift-person-label").textContent = I.f("personLabel") + " ";
    $("confirm-yes").textContent = I.f("confirmYes");
    $("confirm-no").textContent = I.f("confirmNo");
    $("confirm-cancel").textContent = I.f("confirmCancel");
    $("todos-title").textContent = I.f("listsTitle");
    $("todos-close").textContent = I.f("closeLists");
    $("wizard-start").textContent = t("wizardStart");
    $("prev-week").setAttribute("aria-label", t("prevWeek"));
    $("next-week").setAttribute("aria-label", t("nextWeek"));
    $("add-btn").setAttribute("aria-label", t("newEvent"));
    $("event-cancel").textContent = t("cancel");
    document.querySelector("#event-form button[type='submit']").textContent = t("save");
    document.querySelectorAll("#event-form label").forEach(function (label) {
      if (label.querySelector("input[name='summary']")) label.firstChild.textContent = t("title") + " ";
      if (label.querySelector("select[name='category']")) label.firstChild.textContent = t("calendar") + " ";
      if (label.querySelector("input[name='date']")) label.firstChild.textContent = t("date") + " ";
      if (label.querySelector("input[name='all_day']")) label.lastChild.textContent = " " + t("wholeDay");
    });
    var times = document.querySelectorAll(".row label");
    times[0].firstChild.textContent = t("start") + " ";
    times[1].firstChild.textContent = t("end") + " ";
    document.querySelector("#reminder-overlay [data-act='done']").textContent = t("done");
    document.querySelector("#reminder-overlay [data-act='close']").textContent = t("close");
    document.querySelector("[data-act='snooze'][data-minutes='10']").textContent = t("snooze10");
    document.querySelector("[data-act='snooze'][data-minutes='60']").textContent = t("snooze1h");
  }

  function init() {
    applyTexts();
    // Hyphenation (hyphens: auto in the CSS) follows the page language.
    document.documentElement.lang = I.lang;
    // Every switch reports its state to assistive technology.
    document.addEventListener("change", function (e) {
      if (e.target.matches && e.target.matches(".switch input[type='checkbox'], .check input[type='checkbox']")) {
        e.target.setAttribute("aria-checked", e.target.checked ? "true" : "false");
      }
    });
    updateClock();
    window.setInterval(updateClock, 15000);
    window.addEventListener("resize", function () {
      fitWastePills($("week"));
      ["month-scroll", "list-scroll"].forEach(function (id) { if ($(id)) fitToScreen($(id)); });
    });
    window.addEventListener("resize", function () {
      var mode = layoutMode();
      if (mode !== state.mode) {
        state.mode = mode;
        refreshEvents();
      }
    });

    // On the phone the arrows step one day; on the tablet and PC they step one week.
    function step(direction) {
      if (state.view === "month") { jumpMonth(direction); return; }
      if (state.view === "list") return;
      if (state.mode === "phone") state.dayOffset += direction;
      else state.weekStart = addDays(state.weekStart, 7 * direction);
      refreshEvents();
    }
    // A finger swiped sideways over the week: the next or the previous week (or day on the phone).
    var swipe = null;
    $("week").addEventListener("pointerdown", function (e) {
      if (state.view !== "week" || e.pointerType === "mouse") return;
      swipe = { x: e.clientX, y: e.clientY };
    });
    $("week").addEventListener("pointerup", function (e) {
      if (!swipe || state.view !== "week") { swipe = null; return; }
      var dx = e.clientX - swipe.x;
      var dy = e.clientY - swipe.y;
      swipe = null;
      if (Math.abs(dx) > 60 && Math.abs(dx) > Math.abs(dy) * 1.5) step(dx < 0 ? 1 : -1);
    });
    $("week").addEventListener("pointercancel", function () { swipe = null; });
    $("prev-week").addEventListener("click", function () { step(-1); });
    $("next-week").addEventListener("click", function () { step(1); });
    $("this-week").addEventListener("click", function () {
      state.dayOffset = 0;
      state.weekStart = viewStart(new Date());
      state.monthStart = firstOfMonth(new Date());
      if (state.view === "month" && $("month-scroll")) { scrollToMonth(monthKey(state.monthStart), true); return; }
      if (state.view === "list" && $("list-scroll")) { $("list-scroll").scrollTo({ top: 0 }); return; }
      refreshEvents();
    });
    Array.prototype.forEach.call(document.querySelectorAll("#view-switch [data-view]"), function (b) {
      b.addEventListener("click", function () { setView(b.getAttribute("data-view")); });
    });
    paintViewSwitch();
    $("todo-btn").addEventListener("click", openTodos);
    $("todos-close").addEventListener("click", closeTodos);
    $("menu-btn").addEventListener("click", function () { toggleMenu($("menu").hidden); });
    $("menu-shifts").addEventListener("click", function () {
      toggleMenu(false);
      openShifts();
    });
    // On the phone the lists are in the menu (the top bar has no room for their button).
    $("menu-lists").addEventListener("click", function () {
      toggleMenu(false);
      openTodos();
    });
    $("shifts-close").addEventListener("click", closeShifts);
    $("menu-notify").addEventListener("click", function () {
      toggleMenu(false);
      openNotify();
    });
    $("notify-close").addEventListener("click", closeNotify);
    $("menu-ics").addEventListener("click", function () {
      toggleMenu(false);
      openIcs();
    });
    $("ics-close").addEventListener("click", closeIcs);
    $("menu-transparency").addEventListener("change", function (e) {
      applyTransparency(e.target.checked);
      saveTransparency(e.target.checked);
    });
    applyTransparency(storedTransparency());
    $("tab-models").addEventListener("click", function () { showShiftTab("models"); });
    $("tab-calendar").addEventListener("click", function () { showShiftTab("calendar"); });
    $("shift-person").addEventListener("change", function (e) {
      state.shiftPerson = e.target.value;
      state.shiftSelected = {};
      renderShiftModels();
      loadShiftMarks();
    });
    $("menu-wizard").addEventListener("click", function () {
      toggleMenu(false);
      state.draft = null;
      openWizard(0);
    });

    $("add-btn").addEventListener("click", function () { openForm(null); });
    var eventForm = $("event-form");
    eventForm.elements.date.addEventListener("click", function () { openDatePicker(eventForm.elements.date); });
    bindTimeField(eventForm.elements.start_time, null);
    bindTimeField(eventForm.elements.end_time, null);
    ["date", "start_time", "end_time", "all_day"].forEach(function (name) {
      eventForm.elements[name].addEventListener("input", function () { updateDayInfo(eventForm); });
      eventForm.elements[name].addEventListener("change", function () { updateDayInfo(eventForm); });
    });
    $("event-cancel").addEventListener("click", closeForm);
    $("event-form").addEventListener("submit", submitForm);
    $("event-form").elements.all_day.addEventListener("change", function (e) {
      $("event-form").elements.start_time.disabled = e.target.checked;
      $("event-form").elements.end_time.disabled = e.target.checked;
    });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && !$("todo-overlay").hidden) closeTodos();
      if (e.key === "Escape" && !$("shifts-overlay").hidden) closeShifts();
      if (e.key === "Escape" && !$("event-overlay").hidden) closeForm();
    });

    document.querySelectorAll("#reminder-overlay [data-act]").forEach(function (button) {
      button.addEventListener("click", function () {
        reminderAction(button.getAttribute("data-act"), Number(button.getAttribute("data-minutes")));
      });
    });

    $("wizard-next").addEventListener("click", nextWizardStep);
    $("wizard-skip").addEventListener("click", skipWizard);
    $("wizard-back").addEventListener("click", function () { renderWizardStep(state.wizardStep - 1); });

    $("wizard-start").addEventListener("click", function () { state.draft = null; openWizard(0); });

    connect();
  }

  document.addEventListener("DOMContentLoaded", init);
})();
