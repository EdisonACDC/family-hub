# Changelog: Family Hub UI (add-on)

## 0.7.0

Nuova impaginazione: il calendario ha almeno l'80% dello schermo.

- Tablet e PC: una sola barra in alto di 64 px (ora e data piccole; Settimana | Mese | Elenco,
  ← Oggi → e il periodo mostrato; meteo compatto, Liste, ☰ Menu e "+ Nuovo"). La procedura guidata
  è nel Menu. Sotto, una riga di 40 px: le persone a sinistra, "Calendari ▾" e i prossimi ritiri
  (icone colorate con il giorno abbreviato) a destra; il meteo dei prossimi giorni va in questa riga
  sotto i 1280 px.
- Persone in primo piano: "Tutti · Mamma · Papà …" con il colore di ciascuno. Toccandone una si
  filtrano Settimana, Mese, Elenco e la giornata (i suoi eventi e turni, e quelli della famiglia
  senza persone); la scelta resta sullo schermo. Ogni evento mostra i pallini delle sue persone.
  Il menu "Persona" di Mese ed Elenco non c'è più.
- "Calendari ▾": un pannello con un interruttore per ogni calendario (Family Hub ed esterni), al
  posto dei chip.
- Settimana a tutta altezza; Mese con le settimane del mese intere nello schermo (le righe di ogni
  giorno si adattano), poi scorrimento; "Prossimi 14 giorni" solo da 1400 px.
- Nuovo evento: "+ Nuovo" nella barra in alto; un tocco sullo spazio libero di un giorno della
  settimana apre il modulo con la data, uno spazio libero della giornata anche con l'ora.
- Mese: ogni appuntamento (nel mese e nella giornata) apre la sua scheda (Modifica / Elimina /
  Chiudi; sola lettura per esterni e turni); il tocco sul giorno apre la giornata; dopo una modifica
  tutto si aggiorna e il mese resta dov'era.
- Telefono, stile Calendario iPhone: una barra di una riga (ora e meteo; il periodo, che riporta a
  oggi, e ☰), sotto i chip delle persone che scorrono, e in basso quattro schede: Giorni, Mese,
  Elenco, Liste. Giorni: oggi e i 13 giorni dopo, con meteo e icone dei ritiri nell'intestazione,
  righe grandi; lo scorrimento laterale cambia giorno. Mese: griglia compatta con puntini e sotto il
  giorno scelto con appuntamenti e spazi liberi. Il + da 56 px sta sopra le schede e niente resta
  coperto. Calendari, Prossimi ritiri, Procedura guidata, Avvisi e Turni sono nel Menu.
- Suono dei promemoria sul telefono, per persona in Avvisi (Normale / Importante, predefinito /
  Critico) e per evento in "Avvisa su". Importante: su iPhone suono e "time-sensitive"; su Android
  priorità alta, ttl 0 e canale "Promemoria Family Hub". Critico: su iPhone avviso critico (serve
  il permesso "Avvisi critici" per l'app Home Assistant); su Android canale "Promemoria Family Hub
  urgenti" e alarm_stream. iPhone o Android si riconoscono dal dispositivo dell'app; se non si sa,
  si mandano entrambi. Anche "Invia avviso di prova" usa il suono scelto.

## 0.6.5

- Vista Mese a scorrimento continuo: i mesi uno sotto l'altro, da 3 mesi indietro a 12 avanti (altri
  si aggiungono in fondo), letti man mano che arrivano sullo schermo. Il titolo del mese resta fisso
  in alto mentre si scorre. "Oggi" torna al mese corrente, le frecce saltano di un mese; funziona con
  il dito, la rotella e la tastiera (Pagina giù / Pagina su).
- Vista Settimana: uno scorrimento laterale del dito passa alla settimana successiva o precedente
  (sul telefono al giorno successivo o precedente, come le frecce).
- Nuova vista "Elenco" (Settimana | Mese | Elenco): gli appuntamenti dei prossimi 12 mesi divisi per
  mese e per giorno, con ora, titolo, colore del calendario e persone. Filtro persona come nel Mese,
  interruttore "Mostra rifiuti" (spento all'inizio); toccando una riga si apre la scheda dell'evento.
- Telefono: "Sett. | Mese | Elenco" su una riga propria, larga quanto lo schermo, e sotto ← Oggi →;
  i nomi stanno nei pulsanti anche con caratteri più larghi.
- Mese: la prima riga di giorni non resta più sotto il titolo fisso; il mese mostrato resta al suo
  posto mentre si caricano quelli vicini, e "Oggi" ci torna direttamente.
- Vista Elenco su tablet e PC: senza il pannello "Prossimi 14 giorni", a tutta larghezza.

## 0.6.4

- Volume Alexa in Avvisi: il cursore non è più bloccato; toccandolo o trascinandolo "predefinito" si spegne e il
  volume si vede in %. Accendendo "predefinito" il cursore torna grigio.
- "Avvisa su" nel modulo evento (sotto Persone): Telefono, Alexa (con Echo e volume), Finestra sul tablet.
  Precompilato dalle persone scelte; se non lo cambi valgono le loro impostazioni. Salvato sull'evento
  (channels, alexa_target, alexa_volume) e usato dai suoi promemoria; gli orari di silenzio valgono sempre.
  La scheda evento mostra "Avvisa su: ...".
- Vista Mese: tolta l'opzione vuota in più nel filtro Persona.

## 0.6.3

- "Prossimi ritiri" sta su una sola riga che scorre in orizzontale, sul tablet e sul telefono:
  i chip non vanno più uno sotto l'altro.
- Nella settimana, se il nome del tipo di rifiuto non sta nella pillola ("Org…"), si vede solo
  l'icona, più grande, nel colore del tipo; toccandola si apre la scheda con il nome intero e il
  titolo del calendario.
- Vista Mese: gli eventi dei calendari di Home Assistant scelti come fonti (per esempio i vecchi
  calendar.papa, calendar.mamma) contano come impegni; non contano solo rifiuti, festività e
  vacanze.
- Fonti: per ogni calendario di Home Assistant si sceglie a chi appartiene (calendar.mamma ->
  Mamma), come per i calendari .ics. Il filtro persona del mese, la giornata e l'occupazione usano
  questa scelta; un calendario senza persone è della famiglia.
- Lo stesso evento in più calendari (stesso titolo, inizio e fine) compare una volta sola nella
  settimana, nel mese e nei prossimi 14 giorni, con un puntino per ogni altro calendario.
- Nuovo evento: nel menu "Calendario" ci sono solo i calendari di Family Hub (i calendari esterni
  sono in sola lettura e non si potevano salvare); sotto, "Per chi? Scegli le persone qui sotto."
- Telefono (anche 360 px): la barra in alto non esce più dallo schermo. Riga 1 ora, data, meteo e
  menu ☰; riga 2 i prossimi tre giorni, più stretti; riga 3 "Settimana | Mese" e ← Oggi →;
  "Liste" è nel menu; i chip dei calendari scorrono in orizzontale; la barra occupa al massimo
  circa un terzo dello schermo.

## 0.6.2

- Dopo un riavvio di Home Assistant il tablet riconosce di nuovo chi lo usa: un tablet avviato
  mentre Home Assistant non risponde mostra "Collegamento a Home Assistant…" e non diventa
  ospite; appena il collegamento c'è, la sua identità viene ricalcolata senza ricaricare.
- Il nome dei calendari Family Hub nel tablet è quello della categoria, non il nome che Home
  Assistant mostra (che può contenere anche il nome del dispositivo).
- Selettore dell'ora: il titolo è il nome del campo (mai il messaggio di errore), l'orario già
  scritto è selezionato e la colonna scorre fino a lui.
- La settimana non resta più vuota se un calendario di Home Assistant è di tipo rifiuti: i colori
  dei rifiuti valgono anche per lui, e un calendario che non si riesce a leggere non svuota gli altri
  (l'errore va nel log).
- Procedura guidata: si salvano solo gli stili dei calendari spuntati; l'integrazione scarta gli
  stili dei calendari non scelti invece di rifiutare tutto. Sotto "Non salvato" si legge il motivo
  dato da Home Assistant (campo e causa).
- Posticipo: un valore salvato prima che non è tra 5/10/15/30/60 (per esempio 105) compare come
  scelta in più ("105 min").
- Tipi di rifiuti come nella TrashCard: Indifferenziato, Organico, Plastica, Carta, Altro, con
  icone Material Design incluse nell'add-on e colori. Nella settimana, nell'agenda e nei promemoria
  si vede l'etichetta con l'icona, non il titolo grezzo ("Abfuhr: Bioabfall" diventa "Organico").
  L'elenco si modifica nella pagina dei calendari esterni (etichetta, icona, testo da cercare,
  colore) e vale per i calendari .ics e per quelli di Home Assistant. "Importa da TrashCard" legge
  i tipi di una custom:trash-card in una plancia e li propone.
- Fila "Prossimi ritiri" nella barra in alto: icona, etichetta e "oggi" / "domani" / "tra N giorni"
  per i ritiri dei prossimi 7 giorni.
- Vista "Mese" (controllo "Settimana | Mese" nella barra in alto; la scelta resta sullo schermo):
  fino a 3 appuntamenti per giorno e "+N altri", una barretta di occupazione tra le 7 e le 21
  (rifiuti, festività e vacanze non contano, i turni sì), filtro per persona. Toccando un giorno si
  vede la giornata con gli spazi liberi di almeno 30 minuti; toccando uno spazio libero si apre
  "Nuovo evento" con data e ora già scritte. Sul telefono il mese è compatto, con puntini.

## 0.6.1

- Nuovo evento: il titolo del modulo è "Nuovo evento" (in tutte e tre le lingue). Un test verifica
  che ogni testo usato dal tablet esista in italiano, tedesco e inglese.
- Avviso di sovrapposizione: modificando un evento non segnala più l'evento stesso.
- Selettore dell'ora: il titolo e i pulsanti Annulla e Fatto stanno in un piede fisso sotto le
  due colonne, e non più sopra la colonna dei minuti.
- "Altri calendari (N)": ha lo stesso aspetto dei chip, non più sbiadito, con contrasto oltre 4,5:1.
- Meteo: nella barra in alto, accanto al meteo attuale, i prossimi tre giorni (giorno, icona,
  massima e minima).
- Opzione dello schermo "La settimana parte da oggi" (predefinita sì sul tablet): la vista mostra
  oggi e i sei giorni seguenti; le frecce spostano di 7 giorni, "Oggi" torna a partire da oggi.
- Promemoria della sera prima e della mattina per i calendari di Home Assistant scelti come
  rifiuti in Fonti (come per i file .ics). Gli orari sono le 19:00 e le 7:00.

## 0.6.0

- "Importa dai vecchi calendari" (Fonti, solo adulti): si sceglie un calendario di Home
  Assistant, il calendario Family Hub e la persona, si vede l'anteprima (primi 10 eventi) e poi si
  copiano gli eventi degli ultimi 30 giorni e quelli futuri. Gli eventi già presenti (stesso titolo,
  inizio e fine) vengono saltati: ripetere l'importazione non crea duplicati.

- Evento: toccandolo si apre una scheda con titolo, calendario, data e ora, persone e promemoria,
  con Modifica (stesso modulo, già compilato) ed Elimina (con conferma). Gli eventi esterni
  (rifiuti, festività, turni) sono di sola lettura.
- Orari: si scrivono anche a mano (1030 diventa 10:30, 930 diventa 09:30, 7 diventa 07:00,
  10.30 diventa 10:30). Il selettore a rotella usa ore 00–23 e minuti a passi di 5. Un orario
  non valido diventa rosso con un messaggio sotto il campo, e non si può andare avanti né salvare.
- Data: toccando il campo si apre un piccolo calendario del mese, con oggi evidenziato, un punto
  colorato per ogni calendario e gli appuntamenti del giorno scelto. Avvisa se un nuovo evento
  si sovrappone a un altro. Si può ancora scrivere la data a mano.
- Pulsanti in basso fissi in ogni finestra: scorre solo il contenuto.
- Esempi leggibili, in riquadri traslucidi.
- Snooze dei promemoria: scelta fra 5, 10, 15, 30 e 60 minuti.
- Avvisi: telefoni ed Echo con un nome leggibile (per esempio "iPhone Luca", "Alexa Cucina"),
  in ordine alfabetico. Il nome è quello che Home Assistant conosce per l'Echo.
- Calendari di Family Hub: il nome è la categoria (per esempio "Sport"), senza prefisso.
  Gli identificativi restano calendar.family_hub_<categoria>.
- Canali dei promemoria: interruttori a destra. "Popup" diventa "Notifica in Home Assistant" e
  "Popup tablet" diventa "Finestra sul tablet", con una riga che spiega la differenza.
- Barra in alto: testo scuro sul colore chiaro, contrasto oltre 4,5:1.
- Ruoli: un amministratore di Home Assistant non legato a una persona ha sempre i permessi di
  adulto, quindi il tablet non diventa più ospite dopo la configurazione.
- Schermi condivisi (in Avvisi, solo adulti): si scelgono utenti di Home Assistant non legati a
  una persona (per esempio il tablet della cucina). Possono aggiungere, modificare e spuntare
  eventi e liste, ma non aprire le impostazioni. Gli schermi condivisi ricevono i popup dei
  promemoria.
- Ospite: una riga in basso dice "Sei collegato come <utente>: solo lettura" invece di nascondere
  i pulsanti senza spiegazione.
- Calendari: in alto solo quelli di Family Hub. Gli altri stanno dietro al pulsante
  "Altri calendari (N)", che apre un elenco con interruttori.
- Fonti: per ogni calendario di Home Assistant si può scegliere il nome da mostrare, il tipo
  (rifiuti, vacanze scolastiche, vacanze d'asilo, festività, altro) e il colore.
- La settimana e il mini calendario partono dal primo giorno scelto nelle impostazioni
  (lunedì o domenica).

Non ancora incluso (rimandato): i promemoria della sera prima e della mattina per i calendari di Home Assistant scelti come fonti (rifiuti). Il nome, il tipo e il colore
si impostano già in Fonti; i promemoria per questi calendari non sono ancora attivi.

## 0.5.2

- Barre di scorrimento in stile iOS (sottili, traslucide, arrotondate) in tutte le finestre e
  i pannelli; grigio pieno con "Riduci trasparenza". Una barra appare solo dove il contenuto scorre.

## 0.5.1

- Corretto avvio: SUPERVISOR_TOKEN non arrivava al programma. L'add-on ora parte come servizio
  s6 (con l'ambiente del Supervisor) e, se un errore lo ferma, il container si arresta
  invece di riavviarsi in loop. Nel log compaiono solo i nomi delle variabili, mai i valori.

## 0.5.0

- Notification settings per person ("Avvisi"): phone and Echo speakers chosen from the
  services Home Assistant has, channels, announcement volume, quiet hours, test messages.
- Weather from a chosen `weather.*` entity: in the top bar, under each day, and on the
  phone's Today and Tomorrow.
- External calendars from a link or an `.ics` file (read only), refreshed every 12 hours,
  with rubbish pickups recognised by their title and reminders with "Fatto" and "Posticipa 1 ora".
- All-day events on one compact row; events always in time order.
- Shifts per person, as models with a calendar of days.
- Glass style with a "Riduci trasparenza" switch; times in the family's 24 h or 12 h clock.
- Guided setup now uses the services Home Assistant has, not free text.

## 0.4.0

- Layouts for the PC and the phone; shopping lists (to-do) and external calendars chosen in
  the guided setup; the theme saved in the setup is applied.

Earlier versions are in the repository history.
