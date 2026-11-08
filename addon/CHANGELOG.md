# Changelog: Family Hub UI (add-on)

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
