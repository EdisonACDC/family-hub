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
    weekStart: mondayOf(new Date()),
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
    weather: null
  };

  // ---- small helpers -------------------------------------------------------

  function pad(n) { return n < 10 ? "0" + n : "" + n; }

  function ymd(d) { return d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate()); }

  function mondayOf(d) {
    var x = new Date(d.getFullYear(), d.getMonth(), d.getDate());
    x.setDate(x.getDate() - ((x.getDay() + 6) % 7));
    return x;
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
      // Guests only read: no add button for them.
      $("add-btn").hidden = msg.role === "guest";
      $("wizard-start").hidden = msg.role !== "adult";
      $("menu-wizard").hidden = msg.role !== "adult";
      $("menu-shifts").hidden = msg.role === "guest";
      $("menu-notify").hidden = msg.role === "guest";
      $("menu-ics").hidden = msg.role !== "adult";
      $("menu-btn").hidden = msg.role === "guest";
      if (msg.role === "adult") openGuideIfNeeded();
    } else if (msg.type === "theme") {
      applyTheme(msg.theme);
      if (msg.time_format) state.timeFormat = msg.time_format;
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
    if (state.mode === "phone") {
      start = ymd(addDays(now, state.dayOffset)) + " 00:00:00";
      end = ymd(addDays(now, state.dayOffset + 2)) + " 00:00:00";
    } else {
      start = ymd(state.weekStart) + " 00:00:00";
      end = ymd(addDays(state.weekStart, 7)) + " 00:00:00";
    }
    request({ op: "events", start: start, end: end }).then(function (events) {
      state.events = events;
      if (state.mode === "pc") refreshUpcoming();
      else renderWeek();
    }).catch(function () { renderWeek(); });
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
    state.calendars.forEach(function (cal) {
      var on = !state.hidden[cal.entity_id];
      var chip = el("button", {
        type: "button",
        class: "chip" + (on ? " on" : ""),
        "aria-pressed": on ? "true" : "false"
      });
      chip.style.setProperty("--chip", cal.color);
      chip.appendChild(el("span", { class: "swatch", "aria-hidden": "true" }));
      if (cal.external) chip.appendChild(typeIcon(cal.type));
      chip.appendChild(document.createTextNode(cal.name));
      chip.addEventListener("click", function () {
        state.hidden[cal.entity_id] = on;
        renderFilters();
        renderWeek();
      });
      box.appendChild(chip);
    });
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
  function eventsByDay(source) {
    var byDay = {};
    visibleCalendars().forEach(function (cal) {
      (source[cal.entity_id] || []).forEach(function (ev) {
        (byDay[dayKey(ev.start)] = byDay[dayKey(ev.start)] || []).push({ ev: ev, color: cal.color });
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
    if (item.ev.waste) row.appendChild(wasteIcon(item.ev.waste));
    else if (item.ev.external) row.appendChild(iconSvg("calendar"));
    row.appendChild(el("span", { class: "allday-name", title: item.ev.summary }, item.ev.summary));
    return row;
  }

  function eventRow(item) {
    if (isAllDay(item.ev.start)) return allDayRow(item);
    var row = el("div", { class: "event" });
    row.style.setProperty("--ev", item.ev.waste_color || item.color);
    if (item.ev.external) row.classList.add("external");
    row.appendChild(el("span", { class: "ev-time" }, timeOf(item.ev.start)));
    var title = el("span", { class: "ev-title" });
    if (item.ev.waste) title.appendChild(wasteIcon(item.ev.waste));
    title.appendChild(document.createTextNode(item.ev.summary));
    row.appendChild(title);
    return row;
  }

  function renderWeek() {
    var week = $("week");
    week.textContent = "";
    var anyEvent;
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
      head.appendChild(el("span", { class: "day-name" }, t("days")[i]));
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
      select.appendChild(el("option", { value: cal.category_id }, cal.name));
    });
  }

  function openForm() {
    var form = $("event-form");
    form.reset();
    form.elements.date.value = showDate(ymd(new Date()));
    form.elements.start_time.value = showTime("09:00", state.timeFormat);
    form.elements.end_time.value = showTime("10:00", state.timeFormat);
    $("event-error").hidden = true;
    $("event-overlay").hidden = false;
    form.elements.summary.focus();
  }

  function closeForm() { $("event-overlay").hidden = true; }

  function submitForm(event) {
    event.preventDefault();
    var form = event.target;
    var summary = form.elements.summary.value.trim();
    var category = form.elements.category.value;
    if (!summary || !category) {
      showFormError(t("required"));
      return;
    }
    var allDay = form.elements.all_day.checked;
    var day = parseDate(form.elements.date.value);
    if (!day) {
      showFormError(I.f("badDate"));
      return;
    }
    var data = { category: category, summary: summary };
    if (allDay) {
      data.start = day;
    } else {
      var start = parseTime(form.elements.start_time.value);
      var end = form.elements.end_time.value ? parseTime(form.elements.end_time.value) : "";
      if (!start || (form.elements.end_time.value && !end)) {
        showFormError(I.f("shiftBadTime"));
        return;
      }
      data.start = day + " " + start + ":00";
      if (end) data.end = day + " " + end + ":00";
    }
    request({ op: "service", service: "add_event", data: data }).then(function () {
      closeForm();
      refreshEvents();
    }).catch(function (err) {
      showFormError(t("saveError") + errorText(err));
    });
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
    [["phone", f("chPhone")], ["speaker", f("chSpeaker")], ["tablet", f("chTablet")], ["popup", f("chPopup")]]
      .forEach(function (ch) {
        var label = el("label", { class: "check" });
        var box2 = el("input", { type: "checkbox", value: ch[0] });
        box2.checked = (rem.channels || []).indexOf(ch[0]) !== -1;
        box2.addEventListener("change", function () {
          rem.channels = Array.prototype.filter.call(channels.querySelectorAll("input"), function (i) { return i.checked; })
            .map(function (i) { return i.value; });
        });
        label.appendChild(box2);
        label.appendChild(document.createTextNode(" " + ch[1]));
        channels.appendChild(label);
      });
    box.appendChild(channels);
    box.appendChild(fieldRow(f("quietStart"), timeInput(rem.quiet_start, f("quietStart"), function (v) { rem.quiet_start = v; })));
    box.appendChild(fieldRow(f("quietEnd"), timeInput(rem.quiet_end, f("quietEnd"), function (v) { rem.quiet_end = v; })));
    box.appendChild(fieldRow(f("snooze"), textInput(rem.snooze_minutes, function (v) { rem.snooze_minutes = Number(v); }, { type: "number", min: 1, max: 1440, inputmode: "numeric" })));
    box.appendChild(fieldRow(f("morning"), timeInput(rem.morning_summary, f("morning"), function (v) { rem.morning_summary = v || null; })));
    box.appendChild(fieldRow(f("evening"), timeInput(rem.evening_summary, f("evening"), function (v) { rem.evening_summary = v || null; })));
    box.appendChild(fieldRow(f("allDay"), timeInput(rem.all_day_reminder, f("allDay"), function (v) { rem.all_day_reminder = v || null; })));
  }

  function buildScreenFields(box) {
    var f = I.f, screen = state.draft.screen;
    box.appendChild(fieldRow(f("theme"), selectInput([["auto", f("themeAuto")], ["light", f("themeLight")], ["dark", f("themeDark")]], screen.theme, function (v) { screen.theme = v; })));
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
          weather: (config.sources.weather || []).slice()
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
      sources: state.draft.sources
    };
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
      $("wizard-error").textContent = I.f("saveError") + errorText(err);
      $("wizard-error").hidden = false;
    });
  }

  function renderWizardStep(index) {
    state.wizardStep = index;
    renderWizard();
  }

  function nextWizardStep() {
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
            input.addEventListener("change", function () {
              var list = sources[group[0]];
              var pos = list.indexOf(entity.entity_id);
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
          });
          box.appendChild(card);
        });
    }).catch(function (err) {
      status.textContent = errorText(err);
    });
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
  function parseTime(text) {
    var m = /^\s*(\d{1,2})[:.](\d{2})\s*([AaPp][Mm])?\s*$/.exec(text || "");
    if (!m) return null;
    var h = parseInt(m[1], 10);
    var min = parseInt(m[2], 10);
    if (m[3]) {
      if (h < 1 || h > 12) return null;
      h = h % 12 + (/p/i.test(m[3]) ? 12 : 0);
    }
    if (h > 23 || min > 59) return null;
    return pad(h) + ":" + pad(min);
  }

  function showTime(hhmm, format) {
    if (format !== "12h") return hhmm;
    var h = parseInt(hhmm.slice(0, 2), 10);
    return pad(h % 12 || 12) + ":" + hhmm.slice(3) + (h < 12 ? " AM" : " PM");
  }

  // A time field in the family's clock (24 h or 12 h). An empty field means "no time".
  // The placeholder is an example in 24 h (HH:MM), shown in the family's clock.
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
    input.addEventListener("input", function () {
      if (!input.value.trim()) {
        input.removeAttribute("aria-invalid");
        onChange("");
        return;
      }
      var parsed = parseTime(input.value);
      if (parsed) {
        input.removeAttribute("aria-invalid");
        onChange(parsed);
      } else {
        input.setAttribute("aria-invalid", "true");
      }
    });
    input.addEventListener("change", function () {
      var parsed = parseTime(input.value);
      if (parsed) input.value = showTime(parsed, format);
    });
    return input;
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
    box.appendChild(el("h3", {}, I.f("icsWasteColors")));
    box.appendChild(wasteColorsForm());
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

  // The colour of each rubbish kind (the icons are fixed; the colours can be changed).
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
      renderWeek();
    }).catch(function () {
      state.weather = null;
      renderWeatherNow();
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
    text.appendChild(document.createTextNode(" " + I.w.cond(w.condition)));
    box.appendChild(text);
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
    state.notifyServices.phone.forEach(function (name) { options.push([name, name]); });
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
    function paint() {
      slider.value = String(level);
      slider.disabled = isDefault;
      readout.textContent = isDefault ? "—" : level + " %";
    }
    slider.addEventListener("input", function () {
      level = Number(slider.value);
      isDefault = false;
      paint();
      onChange(level);
    });
    wrap.appendChild(sliderRow);
    wrap.appendChild(switchRow(I.f("volumeDefault"), isDefault, function (on) {
      isDefault = on;
      paint();
      onChange(on ? null : level);
    }));
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
    $("todo-btn").textContent = I.f("listsButton");
    $("menu-btn").textContent = I.f("menu");
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
      var mode = layoutMode();
      if (mode !== state.mode) {
        state.mode = mode;
        refreshEvents();
      }
    });

    // On the phone the arrows step one day; on the tablet and PC they step one week.
    function step(direction) {
      if (state.mode === "phone") state.dayOffset += direction;
      else state.weekStart = addDays(state.weekStart, 7 * direction);
      refreshEvents();
    }
    $("prev-week").addEventListener("click", function () { step(-1); });
    $("next-week").addEventListener("click", function () { step(1); });
    $("this-week").addEventListener("click", function () {
      state.dayOffset = 0;
      state.weekStart = mondayOf(new Date());
      refreshEvents();
    });
    $("todo-btn").addEventListener("click", openTodos);
    $("todos-close").addEventListener("click", closeTodos);
    $("menu-btn").addEventListener("click", function () { toggleMenu($("menu").hidden); });
    $("menu-shifts").addEventListener("click", function () {
      toggleMenu(false);
      openShifts();
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

    $("add-btn").addEventListener("click", openForm);
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
