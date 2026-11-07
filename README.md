# Family Hub

Calendario di famiglia per Home Assistant: persone, un calendario per categoria, promemoria
con notifiche su telefono, altoparlanti e tablet, e un pannello da parete per tablet. Tutto si
configura dall'interfaccia, senza YAML.

Il progetto è composto da due parti:

- **Integrazione** `custom_components/family_hub`: calendari, eventi, promemoria, riepiloghi,
  turni, avvisi per persona, meteo, calendari esterni (ICS).
- **Add-on** «Family Hub UI» (`addon/`): l'interfaccia per tablet, nel pannello laterale di
  Home Assistant.

## Installazione

### 1. L'integrazione, da HACS

1. In HACS: **⋮ → Repository personalizzati**, indirizzo `https://github.com/EdisonACDC/family-hub`,
   categoria **Integrazione**.
2. Cerca **Family Hub** in HACS e installalo.
3. Riavvia Home Assistant.
4. Impostazioni → Dispositivi e servizi → **Aggiungi integrazione** → **Family Hub**.

### 2. L'add-on, dallo store

1. Impostazioni → Add-on → **Store** (in basso a destra) → **⋮ → Repository**.
2. Incolla `https://github.com/EdisonACDC/family-hub` e conferma.
3. Apri **Family Hub UI**, premi **Installa**, poi **Avvia**.
4. Nel menu laterale compare **Family Hub**: è il pannello del tablet.

L'add-on richiede che l'integrazione sia già configurata. Per la prima configurazione il pannello
apre la procedura guidata da sola.

## Configurazione

Dalla procedura guidata (o da Impostazioni → Dispositivi e servizi → Family Hub → Configura):

- **Famiglia**: nome, lingua, primo giorno della settimana, orario 24 h o 12 h.
- **Persone**: nome, colore, ruolo (adulto, bambino, ospite), utente Home Assistant collegato,
  telefono e altoparlante per gli avvisi, orari di silenzio.
- **Calendari**: categorie (Famiglia, Scuola, Dottore, Compleanni, o altre).
- **Promemoria**: anticipi, canali, silenzio della famiglia, orari del riepilogo.
- **Fonti**: liste della spesa (to-do), calendari già presenti in Home Assistant, un'entità
  meteo (`weather.*`).
- **Calendari esterni** (solo adulti): un file ICS da link o da file, per esempio rifiuti,
  vacanze o festività. Sola lettura, aggiornamento ogni 12 ore.
- **Avvisi**: per ogni persona, telefono ed Echo scelti tra quelli che Home Assistant conosce,
  canali, volume dell'annuncio, silenzio, prova.

## Cosa fa

- **Settimana a colonne** sul tablet e sul PC, **agenda** sul telefono (oggi e domani).
- **Eventi** di tutto il giorno e a orario, con filtri per calendario; nuovo evento con il pulsante **+**.
- **Promemoria** con popup sul tablet (*Fatto*, *Posticipa*, *Ferma*), notifiche con pulsanti,
  altoparlanti Alexa o tts, riepiloghi del mattino e della sera.
- **Rifiuti**: un promemoria per giorno di ritiro, la sera prima e la mattina, con i tipi
  riconosciuti dal titolo (Restmüll, Bio, Papier, Gelber Sack, Glas) e colori modificabili.
- **Meteo** dall'entità scelta: in alto, sotto ogni giorno, e nei riepiloghi.
- **Turni** per persona, inseriti su più giorni.
- **Liste** della spesa dal to-do di Home Assistant.

Chi usa il tablet vede ciò che gli spetta: l'adulto tutto, il bambino i propri eventi e avvisi,
l'ospite solo la lettura.

## Sicurezza e dati

- Nessun database: la configurazione è nelle opzioni dell'integrazione, il contenuto dei
  calendari esterni nello storage di Home Assistant.
- L'add-on parla con Home Assistant solo tramite la sua WebSocket, con il token del supervisor,
  e il browser parla con l'add-on solo tramite Ingress. Le richieste da fuori Ingress ricevono 403.
- I comandi che cambiano la configurazione richiedono un amministratore di Home Assistant. Il
  controllo di ruolo (adulto, bambino, ospite) è nel server dell'add-on.
- Il link di un calendario esterno può contenere un token: è mostrato solo agli adulti e non viene
  scritto nei log.

## Stato e limiti

- Testato con Home Assistant 2026.10.4 su un'installazione finta (test automatici) e su un
  tablet nel browser. **Non ancora provato su un'installazione reale**: scaricare un calendario
  da un link, i pulsanti delle notifiche sul telefono (evento `mobile_app_notification_action`
  dell'app Companion) e l'invio ad Alexa vanno verificati su casa propria.
- L'icona del meteo e quelle dei rifiuti sono disegnate per il progetto.
- Le persone e i calendari di esempio nei test sono inventati.

## Test

Integrazione (da cartella principale, con Home Assistant di test):

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements_test.txt
pytest
ruff check . && ruff format --check .
mypy
```

Add-on (con un Home Assistant finto e il browser Microsoft Edge):

```bash
cd addon
pip install -r requirements.txt pytest playwright
pytest
```

## Licenza

MIT, vedi [LICENSE](LICENSE). Changelog dell'add-on: [addon/CHANGELOG.md](addon/CHANGELOG.md).
