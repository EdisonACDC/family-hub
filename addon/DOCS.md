# Family Hub UI

Interfaccia per tablet da parete del calendario Family Hub. Richiede l'integrazione **Family Hub** già installata (vedi il README del repository).

## Cosa si vede

- Settimana a colonne: una colonna per giorno, oggi evidenziato. Le colonne occupano tutta l'altezza dello schermo.
- Filtri per calendario in alto: tocca un calendario per nasconderlo o mostrarlo.
- **+** in basso a destra: nuovo evento (titolo, calendario, data, orario o tutto il giorno).
- **Popup dei promemoria**: quando Home Assistant segnala un promemoria, compare a schermo con *Fatto*, *Posticipa 10 min*, *Posticipa 1 ora* e *Ferma*.
- **Procedura guidata** (solo adulti): 6 passi con i campi veri: famiglia, persone, calendari, promemoria, fonti, schermo. Si apre da sola finché Home Assistant non segna Family Hub come configurato. Ogni passo si può saltare; «Salva» all'ultimo passo scrive tutto in una volta, dopo aver validato i dati.

## Chi può fare cosa

L'utente viene da Home Assistant (Ingress). Il ruolo dipende dalla persona collegata a quell'utente nella configurazione di Family Hub (campo *Utente Home Assistant*):

| Ruolo | Vede | Modifica |
| --- | --- | --- |
| Adulto | tutti gli eventi | tutto |
| Bambino | solo gli eventi in cui è tra le persone | solo i propri eventi; un nuovo evento è suo |
| Ospite, o utente non collegato a una persona | tutti gli eventi | niente (nessun pulsante +, nessun popup) |

Se Family Hub non ha ancora calendari, la procedura guidata è aperta per tutti, perché non c'è nulla da proteggere.

## Sicurezza

- Il servizio accetta richieste solo dal proxy di Ingress di Home Assistant (indirizzo `172.30.32.2`). Ogni altro accesso riceve 403.
- L'add-on non salva dati: legge e scrive solo tramite la WebSocket di Home Assistant, con il token del supervisor.
- Si ascoltano solo le modifiche dei calendari `calendar.family_hub_*`, e si inoltrano solo le azioni `family_hub.*` previste.

## Limiti

- Fonti (festività, vacanze, rifiuti) ancora non disponibili: il passo le indica come «in arrivo».
- Non ci sono colori per persona negli eventi, né trascinamento, PIN o screensaver.
- Eventi ricorrenti e layout per PC e telefono non sono ancora inclusi.

## Support / Supporta / Unterstützen

**English:** Family Hub is free. If it helps your family, you can buy me a coffee ☕ [ko-fi.com/edisonacdc](https://ko-fi.com/edisonacdc)

**Italiano:** Family Hub è gratuito. Se ti aiuta in famiglia, puoi offrirmi un caffè ☕ [ko-fi.com/edisonacdc](https://ko-fi.com/edisonacdc)

**Deutsch:** Family Hub ist kostenlos. Wenn es deiner Familie hilft, kannst du mir einen Kaffee spendieren ☕ [ko-fi.com/edisonacdc](https://ko-fi.com/edisonacdc)
