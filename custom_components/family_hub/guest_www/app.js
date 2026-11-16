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
  // What the phone keeps (its token, what it may see, the last copy of the appointments) is in
  // IndexedDB under a name of its own: not in localStorage, next to Home Assistant's own login on
  // the same address. 0.9.0b1/b2 kept it in localStorage: it is moved here once, then removed.
  var DB_NAME = "family-hub-guest";
  var DB_STORE = "kv";
  var LEGACY_KEYS = ["fh_guest_token", "fh_guest_me", "fh_guest_cache"];
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
      iosStep1: "Condividi → «Aggiungi alla schermata Home». Condividi è il quadrato con la freccia in su: in Safari nella barra in basso, in Chrome nella barra dell'indirizzo.",
      iosStep2: "Apri Family Hub dall'icona sulla schermata Home: l'invito si attiva lì, e solo così arrivano le notifiche.",
      iosNote: "Va bene Safari o Chrome, con iOS 16.4 o più recente. Qui nel browser l'invito non viene usato.",
      pasteButton: "Incolla il link dell'invito",
      pasteLabel: "Oppure incolla qui il link dell'invito",
      pasteUse: "Usa questo link",
      pasteBad: "Questo non è un link di invito di Family Hub.",
      pasteDenied: "Non riesco a leggere gli appunti: tieni premuto nel campo qui sotto e scegli «Incolla».",
      haYes: "Sì, usalo su questo telefono",
      haNo: "No, torna indietro",
      androidStep1: "Tocca il menu ⋮ in alto a destra.",
      androidStep2: "Tocca «Installa app» (oppure «Aggiungi a schermata Home»).",
      installButton: "Installa app",
      continueApp: "Continua",
      pushOn: "🔔 Attiva le notifiche",
      pushOff: "Disattiva le notifiche",
      pushActive: "Le notifiche sono attive.",
      pushDenied: "Le notifiche sono bloccate nelle impostazioni del telefono.",
      pushBanner: "🔔 Attiva le notifiche per ricevere i promemoria",
      pushIos: "Su iPhone le notifiche funzionano solo con iOS 16.4 o più recente e aprendo Family Hub dall'icona sulla schermata Home (aggiunta da Safari o da Chrome).",
      pushNone: "Questo browser non può ricevere notifiche.",
      pushError: "Non è stato possibile attivare le notifiche.",
      installAgain: "Come installare l'app",
      myShifts: "🗓️ I miei turni", shiftTypes: "Tipi di turno", shiftName: "Nome",
      shiftStart: "Inizio", shiftEnd: "Fine", addType: "+ Aggiungi tipo", saveTypes: "Salva i tipi",
      removeType: "Togli", nextDays: "Prossimi giorni", rest: "Riposo",
      rotation: "Rotazione che si ripete",
      rotationHint: "Tocca i turni nell'ordine, per esempio Mattina, Mattina, Notte, Riposo.",
      rotationStart: "Dal giorno", rotationWeeks: "Per quante settimane", weeksN: "{n} settimane",
      weekOne: "1 settimana", applyRotation: "Applica la rotazione", clearPattern: "Ricomincia",
      shiftsSaved: "Turni salvati.", typesSaved: "Tipi salvati.", typesFirst: "Prima scrivi i tipi di turno e salvali.",
      defaultTypes: "Mattina|06:00|14:00;Pomeriggio|14:00|22:00;Notte|22:00|06:00",
      chooseShift: "Scegli il turno", clearShift: "Cancella", saveShifts: "Salva",
      saveShiftsN: "Salva ({n} giorni)", saveShiftsOne: "Salva (1 giorno)",
      boardHint: "Scegli un turno e tocca i giorni. Un secondo tocco lo toglie. Riposo e Cancella lasciano il giorno libero.",
month: "Mese", lists: "🛒 Liste", waste: "🗑️ Rifiuti", everyone: "Tutti",
      noCalendar: "Il calendario non è attivo per questo telefono.",
      listEmpty: "La lista è vuota.", listNew: "Cosa aggiungere?", listAdd: "Aggiungi",
      listReadOnly: "Puoi guardare la lista, non cambiarla.", listNone: "Nessuna lista.",
      wasteNone: "Nessun ritiro nei prossimi 14 giorni.", wasteTitle: "Rifiuti dei prossimi giorni",
      errLoad: "Non è stato possibile caricare. Riprova.",
      haTitle: "Questo link è per il telefono dell'invitato",
      haText: "Questo browser è già collegato a Home Assistant. Se apri l'invito qui, lo usi tu e sul telefono dell'invitato non funzionerà più. Manda il link alla persona invitata.",
      haAnyway: "Usalo comunque su questo telefono",
      haConfirm: "L'invito vale per un solo telefono. Usarlo su questo?"
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
      iosStep1: "Share → “Add to Home Screen”. Share is the square with the arrow pointing up: in Safari in the bottom bar, in Chrome in the address bar.",
      iosStep2: "Open Family Hub from its icon on the Home Screen: the invite is used there, and only then do notifications arrive.",
      iosNote: "Safari or Chrome both work, with iOS 16.4 or later. Here in the browser the invite is not used.",
      pasteButton: "Paste the invite link",
      pasteLabel: "Or paste the invite link here",
      pasteUse: "Use this link",
      pasteBad: "This is not a Family Hub invite link.",
      pasteDenied: "The clipboard cannot be read: press and hold in the field below and choose “Paste”.",
      haYes: "Yes, use it on this phone",
      haNo: "No, go back",
      androidStep1: "Tap the ⋮ menu at the top right.",
      androidStep2: "Tap “Install app” (or “Add to Home screen”).",
      installButton: "Install app",
      continueApp: "Continue",
      pushOn: "🔔 Turn on notifications",
      pushOff: "Turn off notifications",
      pushActive: "Notifications are on.",
      pushDenied: "Notifications are blocked in the phone's settings.",
      pushBanner: "🔔 Turn on notifications to get the reminders",
      pushIos: "On iPhone, notifications work only with iOS 16.4 or later and when Family Hub is opened from its icon on the Home Screen (added from Safari or Chrome).",
      pushNone: "This browser cannot receive notifications.",
      pushError: "Notifications could not be turned on.",
      installAgain: "How to install the app",
      myShifts: "🗓️ My shifts", shiftTypes: "Shift types", shiftName: "Name",
      shiftStart: "Start", shiftEnd: "End", addType: "+ Add a type", saveTypes: "Save the types",
      removeType: "Remove", nextDays: "Next days", rest: "Day off",
      rotation: "Repeating rotation",
      rotationHint: "Tap the shifts in their order, for example Morning, Morning, Night, Day off.",
      rotationStart: "From", rotationWeeks: "For how many weeks", weeksN: "{n} weeks",
      weekOne: "1 week", applyRotation: "Apply the rotation", clearPattern: "Start again",
      shiftsSaved: "Shifts saved.", typesSaved: "Types saved.", typesFirst: "First write the shift types and save them.",
      defaultTypes: "Morning|06:00|14:00;Afternoon|14:00|22:00;Night|22:00|06:00",
      chooseShift: "Choose the shift", clearShift: "Clear", saveShifts: "Save",
      saveShiftsN: "Save ({n} days)", saveShiftsOne: "Save (1 day)",
      boardHint: "Choose a shift and tap the days. A second tap takes it away. Day off and Clear leave the day free.",
month: "Month", lists: "🛒 Lists", waste: "🗑️ Rubbish", everyone: "Everyone",
      noCalendar: "The calendar is not on for this phone.",
      listEmpty: "The list is empty.", listNew: "What to add?", listAdd: "Add",
      listReadOnly: "You can look at the list, not change it.", listNone: "No lists.",
      wasteNone: "No pickup in the next 14 days.", wasteTitle: "Rubbish in the next days",
      errLoad: "It could not be loaded. Please try again.",
      haTitle: "This link is for the invited person's phone",
      haText: "This browser is already signed in to Home Assistant. If you open the invite here, you use it up and it will no longer work on the invited person's phone. Send the link to the person invited.",
      haAnyway: "Use it on this phone anyway",
      haConfirm: "The invite works for one phone only. Use it on this one?"
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
      iosStep1: "Teilen → „Zum Home-Bildschirm“. Teilen ist das Quadrat mit dem Pfeil nach oben: in Safari unten in der Leiste, in Chrome in der Adressleiste.",
      iosStep2: "Family Hub über das Symbol auf dem Home-Bildschirm öffnen: dort wird die Einladung benutzt, und nur so kommen Mitteilungen an.",
      iosNote: "Safari oder Chrome, mit iOS 16.4 oder neuer. Hier im Browser wird die Einladung nicht benutzt.",
      pasteButton: "Einladungslink einfügen",
      pasteLabel: "Oder den Einladungslink hier einfügen",
      pasteUse: "Diesen Link verwenden",
      pasteBad: "Das ist kein Einladungslink von Family Hub.",
      pasteDenied: "Die Zwischenablage ist nicht lesbar: im Feld unten lange drücken und „Einsetzen“ wählen.",
      haYes: "Ja, auf diesem Telefon verwenden",
      haNo: "Nein, zurück",
      androidStep1: "Oben rechts auf das Menü ⋮ tippen.",
      androidStep2: "Auf „App installieren“ (oder „Zum Startbildschirm hinzufügen“) tippen.",
      installButton: "App installieren",
      continueApp: "Weiter",
      pushOn: "🔔 Mitteilungen einschalten",
      pushOff: "Mitteilungen ausschalten",
      pushActive: "Mitteilungen sind eingeschaltet.",
      pushDenied: "Mitteilungen sind in den Einstellungen des Telefons gesperrt.",
      pushBanner: "🔔 Mitteilungen einschalten, um die Erinnerungen zu bekommen",
      pushIos: "Auf dem iPhone gehen Mitteilungen nur ab iOS 16.4 und wenn Family Hub über sein Symbol auf dem Home-Bildschirm geöffnet wird (hinzugefügt aus Safari oder Chrome).",
      pushNone: "Dieser Browser kann keine Mitteilungen empfangen.",
      pushError: "Mitteilungen konnten nicht eingeschaltet werden.",
      installAgain: "So wird die App installiert",
      myShifts: "🗓️ Meine Schichten", shiftTypes: "Schichtarten", shiftName: "Name",
      shiftStart: "Beginn", shiftEnd: "Ende", addType: "+ Art hinzufügen", saveTypes: "Arten speichern",
      removeType: "Entfernen", nextDays: "Nächste Tage", rest: "Frei",
      rotation: "Sich wiederholender Wechsel",
      rotationHint: "Die Schichten der Reihe nach antippen, zum Beispiel Früh, Früh, Nacht, Frei.",
      rotationStart: "Ab", rotationWeeks: "Für wie viele Wochen", weeksN: "{n} Wochen",
      weekOne: "1 Woche", applyRotation: "Wechsel übernehmen", clearPattern: "Neu beginnen",
      shiftsSaved: "Schichten gespeichert.", typesSaved: "Arten gespeichert.", typesFirst: "Zuerst die Schichtarten eintragen und speichern.",
      defaultTypes: "Früh|06:00|14:00;Spät|14:00|22:00;Nacht|22:00|06:00",
      chooseShift: "Schicht wählen", clearShift: "Löschen", saveShifts: "Speichern",
      saveShiftsN: "Speichern ({n} Tage)", saveShiftsOne: "Speichern (1 Tag)",
      boardHint: "Schicht wählen und die Tage antippen. Ein zweites Antippen nimmt sie weg. Frei und Löschen lassen den Tag frei.",
month: "Monat", lists: "🛒 Listen", waste: "🗑️ Müll", everyone: "Alle",
      noCalendar: "Der Kalender ist für dieses Telefon nicht eingeschaltet.",
      listEmpty: "Die Liste ist leer.", listNew: "Was hinzufügen?", listAdd: "Hinzufügen",
      listReadOnly: "Du kannst die Liste ansehen, nicht ändern.", listNone: "Keine Listen.",
      wasteNone: "Keine Abholung in den nächsten 14 Tagen.", wasteTitle: "Müll der nächsten Tage",
      errLoad: "Laden war nicht möglich. Bitte noch einmal versuchen.",
      haTitle: "Dieser Link ist für das Telefon der eingeladenen Person",
      haText: "Dieser Browser ist schon bei Home Assistant angemeldet. Wird die Einladung hier geöffnet, ist sie verbraucht und funktioniert auf dem Telefon der eingeladenen Person nicht mehr. Den Link bitte der eingeladenen Person schicken.",
      haAnyway: "Trotzdem auf diesem Telefon verwenden",
      haConfirm: "Die Einladung gilt für ein einziges Telefon. Hier verwenden?"
    }
  };

  var state = {
    lang: pickLanguage(),
    token: null,
    invite: null,
    me: null,
    cache: {},
    ended: null,
    forceHere: false,
    view: "list",
    weekStart: null,
    monthStart: null,
    filter: null,
    events: [],
    offline: false,
    installPrompt: null,
    refreshTimer: null,
    pendingTimer: null
  };

  // ----- small helpers --------------------------------------------------------

  function $(id) { return document.getElementById(id); }

  // ----- what the phone keeps (IndexedDB) ------------------------------------
  // Without IndexedDB (some private modes) the app still works, for this visit only.

  var db = null;

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

  function save(key, value) {
    if (!db) return;
    try {
      var store = db.transaction(DB_STORE, "readwrite").objectStore(DB_STORE);
      if (value === null || value === undefined) store.delete(key);
      else store.put(value, key);
    } catch (e) { /* kept for this visit only */ }
  }

  function legacy(key) {
    try { return window.localStorage.getItem(key); } catch (e) { return null; }
  }

  function forgetLegacy() {
    LEGACY_KEYS.forEach(function (key) {
      try { window.localStorage.removeItem(key); } catch (e) { /* nothing to remove */ }
    });
  }

  function loadStored() {
    return openDb().then(function () {
      return Promise.all([dbGet("token"), dbGet("me"), dbGet("cache"), dbGet("ended")]);
    }).then(function (values) {
      state.token = values[0];
      state.me = values[1];
      state.cache = values[2] || {};
      state.ended = values[3];
      var oldToken = legacy("fh_guest_token");
      if (oldToken && !state.token && db) {
        state.token = oldToken;
        save("token", oldToken);
        try { state.me = JSON.parse(legacy("fh_guest_me") || "null"); } catch (e) { state.me = null; }
        try { state.cache = JSON.parse(legacy("fh_guest_cache") || "null") || {}; } catch (e) { state.cache = {}; }
        save("me", state.me);
        save("cache", state.cache);
      }
      if (db) forgetLegacy();
    });
  }

  // The phone forgets everything of the family: token, what it could see, the saved
  // appointments and the push subscription. Only a note of why stays, to say so on reopening.
  function wipe(reason) {
    state.token = null;
    state.me = null;
    state.cache = {};
    state.events = [];
    if (db) {
      try { db.transaction(DB_STORE, "readwrite").objectStore(DB_STORE).clear(); } catch (e) { /* gone */ }
    }
    forgetLegacy();
    state.ended = reason;
    save("ended", reason);
    unsubscribeQuietly();
  }

  // Home Assistant's own page keeps its login here (hassTokens): only its presence is looked at.
  function hasHomeAssistantLogin() {
    try { return window.localStorage.getItem("hassTokens") !== null; } catch (e) { return false; }
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

  // What an adult turned on for this phone. A copy saved by 0.9 has no list: only the calendar.
  function feature(name) {
    if (!state.me) return false;
    if (!state.me.features) return name === "calendar";
    return !!state.me.features[name];
  }
  function fullMode() { return !!(state.me && state.me.mode === "full"); }

  function canAdd() {
    return !!(state.me && feature("calendar")
      && (state.me.permission === "add" || state.me.permission === "edit_own"));
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
    $("paste-box").hidden = true;
    $("message-cancel").hidden = true;
    $("push-banner").hidden = true;
    $("message-icon").textContent = icon;
    $("message-title").textContent = title;
    $("message-text").textContent = text;
    var button = $("message-retry");
    button.hidden = !retry;
    button.className = "btn btn-primary";
    button.textContent = t("retry");
    button.onclick = retry || null;
    $("hello").hidden = true;
    show("screen-message");
  }

  function accessOff() {
    wipe("off");
    withoutInvite("🔒", t("offTitle"), t("offText"));
  }

  function inviteInvalid() {
    wipe("invalid");
    withoutInvite("✉️", t("invalidTitle"), t("invalidText"));
  }

  function homeAssistantWarning() {
    message("⚠️", t("haTitle"), t("haText"));
    var button = $("message-retry");
    button.hidden = false;
    button.textContent = t("haAnyway");
    button.className = "btn";
    button.onclick = function () {
      $("message-text").textContent = t("haConfirm");
      button.textContent = t("haYes");
      button.className = "btn btn-primary";
      var cancel = $("message-cancel");
      cancel.textContent = t("haNo");
      cancel.hidden = false;
      cancel.onclick = homeAssistantWarning;
      button.onclick = function () {
        state.forceHere = true;
        begin();
      };
    };
  }

  // Without an invite in the address: the invite link can be pasted (the plan B on iPhone, when
  // the Home Screen icon did not bring it). The same rules follow as for a link that is opened.
  function withoutInvite(icon, title, text) {
    message(icon, title, text);
    $("paste-button").textContent = t("pasteButton");
    $("paste-label").textContent = t("pasteLabel");
    $("paste-use").textContent = t("pasteUse");
    $("paste-error").hidden = true;
    $("paste-box").hidden = false;
  }

  function inviteFromText(text) {
    var value = String(text || "").trim();
    var inLink = /[#?&]i=([A-Za-z0-9_-]{20,128})(?![A-Za-z0-9_-])/.exec(value);
    if (inLink) return inLink[1];
    return /^[A-Za-z0-9_-]{20,128}$/.test(value) ? value : null;
  }

  function usePasted(text) {
    var invite = inviteFromText(text);
    if (!invite) {
      $("paste-error").textContent = t("pasteBad");
      $("paste-error").hidden = false;
      return;
    }
    state.invite = invite;
    state.forceHere = false;
    begin();
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
    ["iosStep1", "iosStep2", "androidStep1", "androidStep2"].forEach(function (key) {
      $(key.replace(/Step/, "-step")).textContent = t(key);
    });
    $("ios-note").textContent = t("iosNote");
    var ios = isIOS();
    $("install-ios").hidden = !ios;
    $("install-android").hidden = ios;
    $("install-button").textContent = t("installButton");
    $("install-button").hidden = !state.installPrompt;
    // On iPhone in the browser there is nothing to continue: the app on the Home Screen does it.
    $("install-continue").hidden = !onContinue;
    $("install-continue").textContent = t("continueApp");
    $("install-continue").onclick = onContinue;
    show("screen-install");
  }

  // ----- start --------------------------------------------------------------------

  // The invite comes after # in the link; when the iPhone's Home Screen icon opens the app it
  // comes as ?i= (the address iOS saved). Either is taken out of the address as soon as it is used.
  function readInvite() {
    var match = /[#&]i=([A-Za-z0-9_-]{20,128})/.exec(window.location.hash || "") ||
      /[?&]i=([A-Za-z0-9_-]{20,128})(?:&|$)/.exec(window.location.search || "");
    return match ? match[1] : null;
  }

  function readOpenEvent() {
    var match = /[#&]e=([0-9a-f]{32})\.(\d{4}-\d{2}-\d{2})/.exec(window.location.hash || "");
    return match ? { id: match[1], day: match[2] } : null;
  }

  // Show one appointment: its day in the list or in its week, then its card.
  function showEvent(open) {
    state.pendingOpen = open;
    if (!state.me || $("screen-main").hidden) return;  // done once the list is there
    var day = fromKey(open.day);
    var ahead = Math.round((day - today()) / 86400000);
    if (ahead >= 0 && ahead < 14) {
      state.view = "list";
    } else {
      state.view = "week";
      state.weekStart = weekStartOf(day);
    }
    loadEvents();
  }

  function openPendingEvent() {
    var open = state.pendingOpen;
    if (!open || $("screen-main").hidden) return;
    var item = state.events.filter(function (e) { return e.id === open.id; })[0];
    if (!item) {
      if (!state.pendingOpenTried) {
        state.pendingOpenTried = true;
        showEvent(open);
      }
      return;
    }
    state.pendingOpen = null;
    state.pendingOpenTried = false;
    if (/[#&]e=/.test(window.location.hash || "") && window.history && window.history.replaceState) {
      window.history.replaceState(null, "", BASE);
    }
    openDetail(item);
  }

  function forgetInviteInUrl() {
    if ((window.location.hash || window.location.search) && window.history && window.history.replaceState) {
      window.history.replaceState(null, "", BASE);
    }
  }

  // iPhone, in the browser: the address becomes .../guest/?i=<invite>, so the icon that
  // "Aggiungi alla schermata Home" makes opens the app with the invite (a # can be lost there).
  function keepInviteForHomeScreen() {
    if (window.history && window.history.replaceState) {
      window.history.replaceState(null, "", BASE + "?i=" + encodeURIComponent(state.invite));
    }
  }

  // The manifest only off iPhone: on iPhone the icon must open the address above, not the
  // manifest's start_url (which has no invite).
  function addManifest() {
    if (isIOS() || document.querySelector('link[rel="manifest"]')) return;
    var link = document.createElement("link");
    link.rel = "manifest";
    link.href = BASE + "manifest.json";
    document.head.appendChild(link);
  }

  function start() {
    addManifest();
    applyStaticTexts();
    registerWorker();
    state.invite = readInvite();
    state.pendingOpen = readOpenEvent();
    loadStored().then(begin);
  }

  function begin() {
    if (state.invite && state.token) {
      // A link with an invite, and a phone that already has a token: the token wins only if
      // it still works; a token that was turned off or rejected gives way to the new invite.
      checkOldToken();
      return;
    }
    if (state.token) {
      forgetInviteInUrl();
      loadMe();
      return;
    }
    // From here on a saved reason ("Accesso disattivato", "Invito non valido") counts only
    // when the app opens without an invite: a link with a new one follows the invite.
    if (!state.invite) {
      if (state.ended === "off") withoutInvite("🔒", t("offTitle"), t("offText"));
      else if (state.ended === "invalid") withoutInvite("✉️", t("invalidTitle"), t("invalidText"));
      else withoutInvite("✉️", t("noInviteTitle"), t("noInviteText"));
      return;
    }
    if (hasHomeAssistantLogin() && !state.forceHere) {
      // Probably an adult who opened the link to look at it: using it here would spend it.
      homeAssistantWarning();
      return;
    }
    if (isIOS() && !standalone()) {
      // On iPhone the app on the Home Screen keeps its own storage: the invite is never used in
      // the browser. It goes into the address the icon will open; the app uses it there.
      keepInviteForHomeScreen();
      installScreen(null);
      return;
    }
    activate();
  }

  function checkOldToken() {
    stopTimers();
    show("screen-loading");
    api("GET", "me").then(function (me) {
      if (me.status === "active" || me.status === "pending") {
        // This phone is already in: the link is not needed (it may be the old one again).
        state.invite = null;
        forgetInviteInUrl();
        loadMe();
        return;
      }
      dropOldToken();
    }).catch(function (err) {
      if (isNetwork(err)) {
        message("📶", t("netTitle"), t("netText"), checkOldToken);
      } else if (err.status === 429) {
        message("⏱️", t("netTitle"), t("errSlow"), checkOldToken);
      } else {
        dropOldToken();
      }
    });
  }

  // The old token no longer works: everything of it goes, and the new invite is followed.
  function dropOldToken() {
    wipe(null);
    begin();
  }

  function activate() {
    show("screen-loading");
    api("POST", "activate", { token: state.invite }).then(function (data) {
      state.token = data.token;
      save("token", data.token);
      state.ended = null;
      save("ended", null);
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
        inviteInvalid();
      }
    });
  }

  function loadMe() {
    stopTimers();
    api("GET", "me").then(function (me) {
      if (me.token) {
        state.token = me.token;
        save("token", me.token);
      }
      if (me.status === "pending") {
        waiting();
        return;
      }
      if (me.status !== "active") {
        accessOff();
        return;
      }
      state.offRetries = 0;
      state.me = me;
      save("me", me);
      // "Completa" with the calendar: the panel of Home Assistant (full.html). Only when
      // Family Hub answered: without network this page shows the copy the phone keeps.
      if (me.mode === "full" && me.features && me.features.calendar) {
        window.location.replace(BASE + "full.html");
        return;
      }
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
      // 403 (disabled, rejected): no more access, at once. 401 and 404 may be Family Hub
      // reloading for a moment: asked again twice before the phone forgets everything.
      if ((err.status === 401 || err.status === 404) && (state.offRetries || 0) < 2) {
        state.offRetries = (state.offRetries || 0) + 1;
        state.refreshTimer = window.setTimeout(loadMe, 3000 * state.offRetries);
        return;
      }
      accessOff();
    });
  }

  // ----- main screen --------------------------------------------------------

  function weekStartOf(d) {
    // As the family's wall tablet: from today, unless the family starts the week on its first day.
    if (!state.me || state.me.week_from_today !== false) return new Date(d.getTime());
    var first = state.me && state.me.first_weekday === "sunday" ? 0 : 1;
    var day = d.getDay();
    var back = (day - first + 7) % 7;
    return addDays(d, -back);
  }

  function openMain() {
    $("hello").textContent = t("hello", { name: state.me.name || "" });
    $("hello").hidden = false;
    if (!state.weekStart) state.weekStart = weekStartOf(today());
    if (!state.monthStart) state.monthStart = new Date(today().getFullYear(), today().getMonth(), 1);
    // Completa: smaller letters, the month and the person filter, as on the panel.
    document.documentElement.classList.toggle("mode-full", fullMode());
    if (!fullMode() && state.view === "month") state.view = "list";
    show("screen-main");
    renderPush();
    $("install-again").hidden = standalone();
    $("shifts-button").hidden = !state.me.has_shifts;
    $("tool-lists").hidden = !feature("lists") || !(state.me.lists || []).length;
    $("tool-waste").hidden = !feature("waste");
    $("tab-month").hidden = !fullMode();
    renderFilter();
    loadWeather();
    var calendar = feature("calendar");
    $("tabs").hidden = !calendar;
    $("days").hidden = !calendar;
    $("no-calendar").hidden = calendar;
    $("no-calendar").textContent = t("noCalendar");
    if (!calendar) {
      $("week-nav").hidden = true;
      $("add-button").hidden = true;
      return;
    }
    loadEvents();
  }

  function monthGridStart() {
    var first = state.me && state.me.first_weekday === "sunday" ? 0 : 1;
    var back = (state.monthStart.getDay() - first + 7) % 7;
    return addDays(state.monthStart, -back);
  }

  function range() {
    if (state.view === "week") return { from: state.weekStart, days: 7 };
    if (state.view === "month") return { from: monthGridStart(), days: 42 };
    return { from: today(), days: 14 };
  }

  function loadEvents() {
    window.clearTimeout(state.refreshTimer);
    var r = range();
    var key = state.view + ":" + dayKey(r.from);
    if (!feature("calendar")) return;
    // Only the latest request may draw: an older answer (another view or week, still on its
    // way) must not replace what is on screen now.
    var seq = state.loadSeq = (state.loadSeq || 0) + 1;
    function current() { return seq === state.loadSeq; }
    // Until it answers, the screen shows this view's last copy, never another view's.
    var saved = state.cache[key];
    state.events = saved ? saved.events : [];
    render();
    api("GET", "events?from=" + dayKey(r.from) + "&days=" + r.days).then(function (data) {
      var events = data.events || [];
      if (!state.token) return;  // access ended meanwhile: nothing is kept
      // Only this view is kept: what Family Hub no longer shows this phone (an appointment made
      // private, a person taken away) leaves the phone with the next answer.
      var cache = {};
      cache[key] = { at: Date.now(), events: events };
      state.cache = cache;
      save("cache", cache);
      if (!current()) return;
      state.events = events;
      state.offline = false;
      render();
    }).catch(function (err) {
      if (!current()) return;
      if (isNetwork(err)) {
        state.events = state.cache[key] ? state.cache[key].events : [];
        state.offline = true;
        render();
      } else if (err.status === 401 || err.status === 404) {
        loadMe();  // decides, with its own retries
        return;
      } else if (err.status !== 429) {
        accessOff();
        return;
      }
    }).then(function () {
      if (current() && !$("screen-main").hidden) {
        state.refreshTimer = window.setTimeout(loadEvents, REFRESH_MS);
      }
    });
  }

  function personOf(id) {
    return (state.me.persons || []).filter(function (p) { return p.id === id; })[0];
  }
  function categoryOf(id) {
    return (state.me.categories || []).concat(state.me.externals || [])
      .filter(function (c) { return c.id === id; })[0];
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
    $("tab-month").setAttribute("aria-selected", state.view === "month" ? "true" : "false");
    $("week-nav").hidden = state.view !== "week" && state.view !== "month";
    var r = range();
    if (state.view === "week") {
      var fmt = new Intl.DateTimeFormat(state.lang, { day: "numeric", month: "short" });
      $("week-range").textContent = fmt.format(r.from) + " – " + fmt.format(addDays(r.from, 6));
    } else if (state.view === "month") {
      $("week-range").textContent = new Intl.DateTimeFormat(state.lang, { month: "long", year: "numeric" })
        .format(state.monthStart);
    }
    var byDay = {};
    state.events.filter(passesFilter).forEach(function (item) {
      daysOf(item).forEach(function (key) { (byDay[key] = byDay[key] || []).push(item); });
    });
    var box = $("days");
    box.textContent = "";
    if (state.view === "month") {
      box.appendChild(monthGrid(r, byDay));
      openPendingEvent();
      return;
    }
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
    openPendingEvent();
  }

  // ----- Completa: the month and the person filter ------------------------------------

  function passesFilter(item) {
    if (!state.filter) return true;
    return (item.persons || []).some(function (id) { return state.filter.indexOf(id) !== -1; });
  }

  function renderFilter() {
    var box = $("person-filter");
    box.textContent = "";
    var persons = state.me.persons || [];
    box.hidden = !fullMode() || !feature("calendar") || persons.length < 2;
    if (box.hidden) { state.filter = null; return; }
    function chip(text, pressed, onTap, color) {
      var dot = el("span", { class: "dot" });
      if (color) dot.style.background = color;
      return el("button", { type: "button", class: "filter-chip", "aria-pressed": pressed ? "true" : "false",
        onclick: onTap }, [color ? dot : null, text]);
    }
    box.appendChild(chip(t("everyone"), !state.filter, function () {
      state.filter = null; renderFilter(); render();
    }));
    persons.forEach(function (p) {
      var on = !!state.filter && state.filter.indexOf(p.id) !== -1;
      var button = chip(p.name, on, function () {
        var chosen = (state.filter || []).filter(function (id) { return id !== p.id; });
        if (!on) chosen.push(p.id);
        state.filter = chosen.length ? chosen : null;
        renderFilter();
        render();
      }, p.color);
      button.setAttribute("data-person", p.id);
      box.appendChild(button);
    });
  }

  function monthGrid(r, byDay) {
    var grid = el("div", { class: "month-grid", role: "grid" });
    var names = new Intl.DateTimeFormat(state.lang, { weekday: "narrow" });
    for (var w = 0; w < 7; w++) grid.appendChild(el("div", { class: "month-wd", text: names.format(addDays(r.from, w)) }));
    var todayKey = dayKey(today());
    for (var i = 0; i < r.days; i++) {
      var d = addDays(r.from, i);
      var key = dayKey(d);
      var items = byDay[key] || [];
      var cell = el("button", { type: "button", class: "month-day"
        + (d.getMonth() !== state.monthStart.getMonth() ? " other" : "")
        + (key === todayKey ? " today" : "") + (items.length ? " busy" : ""), "data-month-day": key,
        onclick: (function (day, list) { return function () { openDay(day, list); }; })(d, items) },
        [el("span", { class: "month-num", text: String(d.getDate()) })]);
      var bars = el("span", { class: "month-bars" });
      items.slice(0, 3).forEach(function (item) {
        var bar = el("span", { class: "month-bar", text: item.title });
        var color = colorOf(item);
        if (color) bar.style.borderLeftColor = color;
        bars.appendChild(bar);
      });
      if (items.length > 3) bars.appendChild(el("span", { class: "month-more", text: "+" + (items.length - 3) }));
      cell.appendChild(bars);
      grid.appendChild(cell);
    }
    return grid;
  }

  function openDay(d, items) {
    var body = el("div", { class: "day-sheet" });
    if (!items.length) body.appendChild(el("p", { class: "empty", text: t("nothingDay") }));
    // A tap on one opens its details in place of this list.
    items.forEach(function (item) { body.appendChild(eventCard(item)); });
    openSheet(dayTitle(d), body, [closeButton()]);
  }

  function closeButton() {
    return el("button", { type: "button", class: "btn", text: t("close"), onclick: closeSheet });
  }

  // A function the adult has just turned off answers 403: the phone asks again what it may do.
  function featureError(err) {
    if (err && (err.status === 403 || err.status === 401)) { closeSheet(); loadMe(); return; }
    toast(t("errLoad"));
  }

  // ----- lists ---------------------------------------------------------------------------

  function openLists() {
    var lists = state.me.lists || [];
    if (lists.length === 1) { openList(lists[0]); return; }
    var body = el("div", { class: "list-choice" });
    if (!lists.length) body.appendChild(el("p", { class: "empty", text: t("listNone") }));
    lists.forEach(function (list) {
      body.appendChild(el("button", { type: "button", class: "btn list-open", "data-list": list.id, text: list.name,
        onclick: function () { openList(list); } }));
    });
    openSheet(t("lists").replace(/^\S+\s/, ""), body, [closeButton()]);
  }

  function openList(list) {
    api("GET", "lists/" + list.id).then(function (data) {
      renderList(list, data.items || []);
    }).catch(featureError);
  }

  function changeList(list, payload) {
    api("POST", "lists/" + list.id, payload).then(function (data) {
      renderList(list, data.items || []);
    }).catch(function (err) {
      if (err && err.status === 403) { featureError(err); return; }
      sheetError(t("errSave"));
    });
  }

  function renderList(list, items) {
    var body = el("div", { class: "todo" });
    if (!items.length) body.appendChild(el("p", { class: "empty", text: t("listEmpty") }));
    items.forEach(function (item) {
      var box = el("input", { type: "checkbox" });
      box.checked = !!item.done;
      box.disabled = !list.edit || state.offline;
      box.addEventListener("change", function () { changeList(list, { item: item.id, done: box.checked }); });
      body.appendChild(el("label", { class: "todo-item" + (item.done ? " done" : ""), "data-item": item.id },
        [box, el("span", { text: item.summary })]));
    });
    var actions = [];
    if (list.edit) {
      var input = el("input", { type: "text", id: "list-new", maxlength: "100", placeholder: t("listNew") });
      body.appendChild(input);
      actions.push(el("button", { type: "button", class: "btn btn-primary", id: "list-add", text: t("listAdd"),
        onclick: function () {
          var text = input.value.trim();
          if (text) changeList(list, { add: text });
        } }));
    } else {
      body.appendChild(el("p", { class: "note-box", text: t("listReadOnly") }));
    }
    actions.push(closeButton());
    openSheet(list.name, body, actions);
  }

  // ----- rubbish days and weather -----------------------------------------------------

  function openWaste() {
    api("GET", "waste?from=" + dayKey(today()) + "&days=14").then(function (data) {
      var body = el("div", { class: "waste" });
      var days = data.days || [];
      if (!days.length) body.appendChild(el("p", { class: "empty", text: t("wasteNone") }));
      days.forEach(function (day) {
        var section = el("section", { class: "day", "data-waste-day": day.date }, [el("h3", { text: dayTitle(fromKey(day.date)) })]);
        day.items.forEach(function (item) {
          var dot = el("span", { class: "dot" });
          if (item.color) dot.style.background = item.color;
          section.appendChild(el("p", { class: "waste-item" }, [dot, item.label]));
        });
        body.appendChild(section);
      });
      openSheet(t("wasteTitle"), body, [closeButton()]);
    }).catch(featureError);
  }

  var WEATHER_ICONS = { "clear-night": "🌙", sunny: "☀️", cloudy: "☁️", partlycloudy: "⛅", rainy: "🌧️",
    pouring: "🌧️", snowy: "❄️", "snowy-rainy": "🌨️", fog: "🌫️", hail: "🌨️", lightning: "⛈️",
    "lightning-rainy": "⛈️", windy: "💨", "windy-variant": "💨" };

  function loadWeather() {
    var line = $("weather-line");
    if (!feature("weather") || state.offline) { line.hidden = true; return; }
    api("GET", "weather").then(function (data) {
      line.textContent = data.line ? (WEATHER_ICONS[data.condition] || "🌡️") + " " + data.line : "";
      line.hidden = !data.line;
    }).catch(function () { line.hidden = true; });
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


  // ----- my shifts (a guest who works) -------------------------------------------------
  // The same board as Family Hub's "Turni": choose a shift, tap the days of the month, Salva.
  // Only its own shifts: Family Hub decides who that is, never this page.

  var SHIFT_COLORS = ["#F59E0B", "#F97316", "#4F46E5", "#059669", "#DB2777", "#0284C7", "#7C3AED"];
  var REST = "rest";
  var CLEAR = "clear";

  function shiftColor(index) { return SHIFT_COLORS[index % SHIFT_COLORS.length]; }
  function shiftMark(name) { return String(name || "?").trim().slice(0, 2).toUpperCase(); }

  function openShifts() {
    state.board = state.board || {
      month: new Date(today().getFullYear(), today().getMonth(), 1),
      tool: "", plan: {}, saved: {}, types: []
    };
    loadBoard();
  }

  function loadBoard(retries) {
    var b = state.board;
    var days = new Date(b.month.getFullYear(), b.month.getMonth() + 1, 0).getDate();
    api("GET", "shifts?from=" + dayKey(b.month) + "&days=" + days).then(function (data) {
      b.types = data.types;
      b.saved = {};
      data.days.forEach(function (d) { b.saved[d.date] = d.shift_id; });
      if (!b.tool && b.types.length) b.tool = b.types[0].id;
      renderBoard();
      if (retries && !b.types.length) window.setTimeout(function () { loadBoard(retries - 1); }, 800);
    }).catch(function (err) {
      if (err.status === 403) { accessOff(); return; }
      if (retries) { window.setTimeout(function () { loadBoard(retries - 1); }, 800); return; }
      toast(t("errSave"));
    });
  }

  function typeIndex(id) {
    var types = state.board.types;
    for (var i = 0; i < types.length; i++) if (types[i].id === id) return i;
    return -1;
  }

  // What a day shows: the change not saved yet, else what is saved.
  function dayValue(key) {
    var b = state.board;
    return Object.prototype.hasOwnProperty.call(b.plan, key) ? b.plan[key] : (b.saved[key] || "");
  }

  function tapDay(key) {
    var b = state.board;
    var tool = b.tool;
    if (!tool) return;
    var current = dayValue(key);
    var target = tool === CLEAR ? "" : tool;
    // A second tap with the same shift takes it away again.
    if (current === target || (tool === REST && current === REST)) target = "";
    if (target === (b.saved[key] || "")) delete b.plan[key];
    else b.plan[key] = target;
    renderBoard();
  }

  function renderBoard() {
    var b = state.board;
    var body = el("div", { class: "board" });

    // The shift buttons: big and coloured, plus Riposo and Cancella.
    var tools = el("div", { class: "board-tools", role: "group", "aria-label": t("chooseShift") });
    b.types.forEach(function (type, index) {
      var button = el("button", { type: "button", class: "board-tool", "data-tool": type.id,
        "aria-pressed": b.tool === type.id ? "true" : "false",
        onclick: function () { b.tool = type.id; renderBoard(); } },
        [el("span", { class: "board-mark", text: shiftMark(type.name) }), type.name]);
      button.style.setProperty("--shift", shiftColor(index));
      tools.appendChild(button);
    });
    [[REST, t("rest"), "#64748B"], [CLEAR, t("clearShift"), ""]].forEach(function (x) {
      var button = el("button", { type: "button", class: "board-tool" + (x[0] === CLEAR ? " board-clear" : ""),
        "data-tool": x[0], "aria-pressed": b.tool === x[0] ? "true" : "false",
        onclick: function () { b.tool = x[0]; renderBoard(); } }, [x[1]]);
      if (x[2]) button.style.setProperty("--shift", x[2]);
      tools.appendChild(button);
    });
    if (b.types.length) {
      body.appendChild(el("p", { class: "note-box", text: t("boardHint") }));
      body.appendChild(tools);
    } else {
      body.appendChild(el("p", { class: "note-box", text: t("typesFirst") }));
    }

    // The month: Monday to Sunday, arrows, today marked.
    var nav = el("div", { class: "week-nav board-nav" }, [
      el("button", { type: "button", class: "btn btn-icon", "aria-label": "‹", text: "‹",
        onclick: function () { moveBoard(-1); } }),
      el("p", { class: "board-month", text: new Intl.DateTimeFormat(state.lang, { month: "long", year: "numeric" }).format(b.month) }),
      el("button", { type: "button", class: "btn btn-icon", "aria-label": "›", text: "›",
        onclick: function () { moveBoard(1); } })
    ]);
    body.appendChild(nav);
    var grid = el("div", { class: "board-grid", role: "grid" });
    var names = [];
    for (var w = 0; w < 7; w++) {
      names.push(new Intl.DateTimeFormat(state.lang, { weekday: "short" }).format(new Date(2024, 0, 1 + w)));
    }
    names.forEach(function (n) { grid.appendChild(el("div", { class: "board-wd", text: n })); });
    var first = new Date(b.month.getFullYear(), b.month.getMonth(), 1);
    var offset = (first.getDay() + 6) % 7;
    for (var i = 0; i < offset; i++) grid.appendChild(el("div", { class: "board-blank" }));
    var count = new Date(b.month.getFullYear(), b.month.getMonth() + 1, 0).getDate();
    var todayKey = dayKey(today());
    for (var d = 1; d <= count; d++) {
      (function (day) {
        var key = dayKey(day);
        var value = dayValue(key);
        var index = typeIndex(value);
        var changed = Object.prototype.hasOwnProperty.call(b.plan, key);
        var cell = el("button", { type: "button", class: "board-day" + (key === todayKey ? " today" : "") + (changed ? " changed" : ""),
          "data-day": key, onclick: function () { tapDay(key); } },
          [el("span", { class: "board-num", text: String(day.getDate()) })]);
        if (index !== -1) {
          cell.appendChild(el("span", { class: "board-mark", text: shiftMark(b.types[index].name) }));
          cell.style.setProperty("--shift", shiftColor(index));
          cell.classList.add("has-shift");
          cell.setAttribute("aria-label", dayTitle(day) + ": " + b.types[index].name);
        } else if (value === REST) {
          cell.appendChild(el("span", { class: "board-mark", text: "R" }));
          cell.style.setProperty("--shift", "#64748B");
          cell.classList.add("has-shift");
          cell.setAttribute("aria-label", dayTitle(day) + ": " + t("rest"));
        } else {
          cell.setAttribute("aria-label", dayTitle(day));
        }
        grid.appendChild(cell);
      })(new Date(b.month.getFullYear(), b.month.getMonth(), d));
    }
    body.appendChild(grid);
    var pending = Object.keys(b.plan).length;
    body.appendChild(el("button", { type: "button", class: "btn btn-primary", id: "board-save",
      text: pending === 1 ? t("saveShiftsOne") : pending ? t("saveShiftsN", { n: String(pending) }) : t("saveShifts"), onclick: saveBoard }));

    // A rotation that repeats.
    if (b.types.length) body.appendChild(rotationSection());
    // The shift types, closed until needed.
    body.appendChild(typesSection());
    openSheet(t("myShifts").replace(/^\S+\s/, ""), body, [
      el("button", { type: "button", class: "btn", text: t("close"), onclick: function () {
        state.board.plan = {};
        closeSheet();
        loadEvents();
      } })
    ]);
  }

  function moveBoard(step) {
    var b = state.board;
    b.month = new Date(b.month.getFullYear(), b.month.getMonth() + step, 1);
    loadBoard();
  }

  // One request per shift (or free day), for all its days; then "Turni salvati".
  function saveBoard() {
    var b = state.board;
    var groups = {};
    Object.keys(b.plan).forEach(function (key) {
      var value = b.plan[key] === REST ? "" : b.plan[key];
      (groups[value] = groups[value] || []).push(key);
    });
    var ids = Object.keys(groups);
    if (!ids.length) { toast(t("shiftsSaved")); return; }
    var chain = Promise.resolve();
    ids.forEach(function (id) {
      chain = chain.then(function () { return api("POST", "shifts/apply", { days: groups[id], shift_id: id }); });
    });
    chain.then(function () {
      b.plan = {};
      toast(t("shiftsSaved"));
      loadBoard();
    }).catch(function () { sheetError(t("errSave")); });
  }

  function rotationSection() {
    var b = state.board;
    var box = el("section", { class: "board-section" });
    box.appendChild(el("h3", { text: t("rotation") }));
    box.appendChild(el("p", { class: "note-box", text: t("rotationHint") }));
    var pattern = [];
    var shown = el("div", { class: "chips", id: "rotation-pattern" });
    function drawPattern() {
      shown.textContent = "";
      pattern.forEach(function (id) {
        var index = typeIndex(id);
        shown.appendChild(el("span", { class: "chip", text: index === -1 ? t("rest") : b.types[index].name }));
      });
    }
    var pick = el("div", { class: "chips" });
    b.types.concat([{ id: "", name: t("rest") }]).forEach(function (x) {
      pick.appendChild(el("button", { type: "button", class: "chip", "data-pattern": x.id, text: "+ " + x.name,
        onclick: function () { if (pattern.length < 28) { pattern.push(x.id); drawPattern(); } } }));
    });
    var from = el("input", { type: "date", id: "rotation-start", value: dayKey(today()) });
    var weeks = el("select", { id: "rotation-weeks" });
    for (var w = 1; w <= 8; w++) {
      weeks.appendChild(el("option", { value: String(w), text: w === 1 ? t("weekOne") : t("weeksN", { n: String(w) }) }));
    }
    weeks.value = "4";
    box.appendChild(pick);
    box.appendChild(shown);
    box.appendChild(el("button", { type: "button", class: "btn", text: t("clearPattern"), onclick: function () {
      pattern = []; drawPattern();
    } }));
    box.appendChild(el("label", { class: "field" }, [el("span", { text: t("rotationStart") }), from]));
    box.appendChild(el("label", { class: "field" }, [el("span", { text: t("rotationWeeks") }), weeks]));
    box.appendChild(el("button", { type: "button", class: "btn btn-primary", id: "apply-rotation", text: t("applyRotation"),
      onclick: function () {
        if (!pattern.length) return;
        api("POST", "shifts/rotation", { start: from.value, pattern: pattern, days: Number(weeks.value) * 7 })
          .then(function () { toast(t("shiftsSaved")); loadBoard(); })
          .catch(function () { sheetError(t("errSave")); });
      } }));
    return box;
  }

  function defaultTypes() {
    return t("defaultTypes").split(";").map(function (row) {
      var p = row.split("|");
      return { name: p[0], start: p[1], end: p[2] };
    });
  }

  function typesSection() {
    var b = state.board;
    var types = b.types.length ? b.types.map(function (x) { return Object.assign({}, x); }) : defaultTypes();
    var box = el("details", { class: "board-section board-types", id: "board-types" });
    if (!b.types.length) box.open = true;  // nothing to choose yet: open
    box.appendChild(el("summary", { text: t("shiftTypes") }));
    var list = el("div", { class: "shift-types" });
    function drawTypes() {
      list.textContent = "";
      types.forEach(function (type, index) {
        var name = el("input", { type: "text", maxlength: "60", value: type.name, "aria-label": t("shiftName") });
        name.addEventListener("input", function () { type.name = name.value; });
        var start = el("input", { type: "time", value: type.start, "aria-label": t("shiftStart") });
        start.addEventListener("input", function () { type.start = start.value; });
        var end = el("input", { type: "time", value: type.end, "aria-label": t("shiftEnd") });
        end.addEventListener("input", function () { type.end = end.value; });
        list.appendChild(el("div", { class: "shift-type", "data-type": index }, [
          name, el("div", { class: "row" }, [start, end]),
          el("button", { type: "button", class: "btn", text: t("removeType"), onclick: function () {
            types.splice(index, 1); drawTypes();
          } })
        ]));
      });
    }
    drawTypes();
    box.appendChild(list);
    box.appendChild(el("button", { type: "button", class: "btn", text: t("addType"), onclick: function () {
      types.push({ name: "", start: "08:00", end: "16:00" }); drawTypes();
    } }));
    box.appendChild(el("button", { type: "button", class: "btn btn-primary", id: "save-types", text: t("saveTypes"),
      onclick: function () {
        var payload = types.filter(function (x) { return x.name.trim(); }).map(function (x) {
          var item = { name: x.name.trim(), start: x.start, end: x.end };
          if (x.id) item.id = x.id;
          return item;
        });
        api("PUT", "shifts/types", { types: payload }).then(function () {
          toast(t("typesSaved"));
          // Family Hub reloads its shift types: the board asks again until they are there.
          b.tool = "";
          window.setTimeout(function () { loadBoard(6); }, 400);
        }).catch(function () { sheetError(t("errSave")); });
      } }));
    return box;
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

  // A strip at the top, well in sight, until notifications are on.
  function pushBanner(text, onTap) {
    var banner = $("push-banner");
    banner.hidden = !text;
    banner.textContent = text || "";
    banner.disabled = !onTap;
    banner.onclick = onTap || null;
  }

  // Blocked in the phone's settings: Family Hub is told, so the adults see "Bloccate".
  function reportBlocked(blocked) {
    if (!state.me || state.me.blockedReported === blocked) return;
    state.me.blockedReported = blocked;
    api("POST", "push", { blocked: blocked }).catch(function () { state.me.blockedReported = null; });
  }

  function renderPush() {
    var box = $("push-box");
    box.textContent = "";
    pushBanner("");
    // Notifications or reminders: Family Hub gives the key only when one of them is on.
    if (!state.me || !state.me.vapid) return;
    if (!pushSupported()) {
      box.appendChild(el("p", { class: "note-box", text: isIOS() ? t("pushIos") : t("pushNone") }));
      pushBanner(isIOS() ? t("pushIos") : "");
      return;
    }
    if (window.Notification.permission === "denied") {
      box.appendChild(el("p", { class: "note-box", text: t("pushDenied") }));
      pushBanner(t("pushDenied"));
      reportBlocked(true);
      return;
    }
    if (!state.me.push) {
      pushBanner(t("pushBanner"), pushOn);
      return;  // the strip at the top is the one button
    }
    if (state.me.push) {
      box.appendChild(el("p", { class: "note-box", text: t("pushActive") }));
      box.appendChild(el("button", { type: "button", class: "btn", id: "push-off", text: t("pushOff"), onclick: pushOff }));
      return;
    }
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
      save("me", state.me);
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
      save("me", state.me);
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
    $("tab-month").textContent = t("month");
    $("tool-lists").textContent = t("lists");
    $("tool-waste").textContent = t("waste");
    $("add-button").textContent = t("add");
    $("install-again").textContent = t("installAgain");
    $("shifts-button").textContent = t("myShifts");
  }

  $("tab-list").addEventListener("click", function () { state.view = "list"; render(); loadEvents(); });
  $("tab-week").addEventListener("click", function () { state.view = "week"; render(); loadEvents(); });
  $("tab-month").addEventListener("click", function () { state.view = "month"; render(); loadEvents(); });
  function step(n) {
    if (state.view === "month") {
      state.monthStart = new Date(state.monthStart.getFullYear(), state.monthStart.getMonth() + n, 1);
    } else {
      state.weekStart = addDays(state.weekStart, 7 * n);
    }
    render();
    loadEvents();
  }
  $("week-prev").addEventListener("click", function () { step(-1); });
  $("week-next").addEventListener("click", function () { step(1); });
  $("tool-lists").addEventListener("click", openLists);
  $("tool-waste").addEventListener("click", openWaste);
  $("add-button").addEventListener("click", function () { openForm(null); });
  $("install-button").addEventListener("click", install);
  $("install-again").addEventListener("click", function () { installScreen(openMain); });
  $("shifts-button").addEventListener("click", openShifts);
  $("sheet").addEventListener("click", function (event) { if (event.target === $("sheet")) closeSheet(); });
  document.addEventListener("keydown", function (event) { if (event.key === "Escape" && !$("sheet").hidden) closeSheet(); });
  document.addEventListener("visibilitychange", function () {
    // Back on screen: ask at once, so a disabled phone shows it without waiting.
    if (document.visibilityState === "visible" && state.token && !$("screen-main").hidden) loadMe();
  });
  window.addEventListener("online", function () { if (state.token) loadMe(); });
  $("paste-button").addEventListener("click", function () {
    // Read only now, after the tap (iOS asks before it lets the page read).
    if (!navigator.clipboard || !navigator.clipboard.readText) {
      $("paste-error").textContent = t("pasteDenied");
      $("paste-error").hidden = false;
      $("paste-input").focus();
      return;
    }
    navigator.clipboard.readText().then(function (text) {
      $("paste-input").value = text;
      usePasted(text);
    }).catch(function () {
      $("paste-error").textContent = t("pasteDenied");
      $("paste-error").hidden = false;
      $("paste-input").focus();
    });
  });
  $("paste-use").addEventListener("click", function () { usePasted($("paste-input").value); });
  // A new link opened in the tab that is already open changes only the part after #: the page
  // does not load again, so the new invite is taken from here.
  // From a notification: the app is open (the service worker sends a message) or opened with
  // #e=<appointment>.<day>.
  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.addEventListener("message", function (event) {
      var data = event.data || {};
      if (data.type === "open") showEvent({ id: String(data.id), day: String(data.day) });
    });
  }

  window.addEventListener("hashchange", function () {
    var open = readOpenEvent();
    if (open) { showEvent(open); return; }
    var invite = readInvite();
    if (!invite || invite === state.invite) return;
    stopTimers();
    $("sheet").hidden = true;
    state.invite = invite;
    state.forceHere = false;
    begin();
  });

  start();
})();
