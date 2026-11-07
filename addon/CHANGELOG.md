# Changelog: Family Hub UI (add-on)

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
