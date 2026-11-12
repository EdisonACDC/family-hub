<p align="center">
  <img src="addon/icon.png" width="96" alt="Family Hub Symbol">
</p>

<h1 align="center">Family Hub</h1>

<p align="center">
  <a href="README.md">English</a> · <a href="README.it.md">Italiano</a> · <b>Deutsch</b>
</p>

<p align="center">
  Der Familienkalender, den Home Assistant gefehlt hat: eine Farbe pro Person, Erinnerungen auf dem
  Handy, bei Alexa und auf dem Wand-Tablet, Mülltermine und Schulferien – in wenigen Minuten
  eingerichtet, ohne YAML.
</p>

<p align="center">
  <a href="https://github.com/EdisonACDC/family-hub/releases/latest"><img src="https://img.shields.io/github/v/release/EdisonACDC/family-hub" alt="Version"></a>
  <a href="https://hacs.xyz/"><img src="https://img.shields.io/badge/HACS-Custom-41BDF5.svg" alt="HACS custom"></a>
  <a href="https://ko-fi.com/edisonacdc"><img src="https://img.shields.io/badge/Ko--fi-Support%20on%20Ko--fi-FF5E5B?logo=kofi&logoColor=white" alt="Auf Ko-fi unterstützen"></a>
</p>

<p align="center">
  <a href="https://my.home-assistant.io/redirect/hacs_repository/?owner=EdisonACDC&repository=family-hub&category=integration"><img src="https://my.home-assistant.io/badges/hacs_repository.svg" alt="Home Assistant öffnen und die Family-Hub-Integration in HACS öffnen"></a>
  &nbsp;
  <a href="https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2FEdisonACDC%2Ffamily-hub"><img src="https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg" alt="Home Assistant öffnen und das Family-Hub-Add-on-Repository hinzufügen"></a>
</p>

<p align="center">
  <img src="docs/images/demo.gif" width="320" alt="Family Hub auf dem Wand-Tablet">
</p>

<p align="center">
  <img src="docs/images/screenshots.png" alt="Family-Hub-Bildschirme: Wochenansicht, Erinnerungen, Abholtermine und Wiederholungen">
</p>

## Funktionen

- **Wochenansicht** auf dem Wand-Tablet und am PC, und eine **Agenda** auf dem Handy (heute und morgen).
- **Eine Farbe pro Person**, ganztägige und terminierte Ereignisse, Filter pro Kalender, und die Schaltfläche **+** für neue Termine.
- **Wiederkehrende Termine**: täglich, wöchentlich an gewählten Tagen, alle 2 Wochen, monatlich, jährlich. Sie enden nie, an einem Datum oder nach einer Anzahl. Beim Bearbeiten oder Löschen wird gefragt: *nur dieser*, *dieser und die folgenden* oder *alle*.
- **Erinnerungen**: Hinweise auf dem Tablet (*Erledigt*, *Verschieben*, *Stopp*), Handy-Benachrichtigungen mit Schaltflächen, Alexa oder Sprachausgabe, und Zusammenfassungen am Morgen und am Abend.
- **Mülltermine**: eine Erinnerung pro Abholung, am Abend vorher und am Morgen. Die Arten werden am Titel erkannt (Restmüll, Bio, Papier, Gelber Sack, Glas), die Farben lassen sich ändern. Abholungen können auch von Hand eingetragen werden: wöchentlich, alle 2 oder 4 Wochen oder monatlich, mit zusätzlichen und übersprungenen Daten.
- **Wetter** aus der Entität deiner Wahl: oben, unter jedem Tag und in den Zusammenfassungen.
- **Schichten** pro Person, über mehrere Tage eingetragen.
- **Einkaufslisten** aus den To-do-Listen von Home Assistant.
- **Rollen**: Erwachsene sehen alles, Kinder sehen ihre eigenen Termine und Erinnerungen, Gäste können nur lesen.
- **Externe Kalender** (ICS): Schulferien, Feiertage, Müllkalender der Gemeinde. Nur lesen.

## Installation

1. **Integration installieren.** Öffne in HACS **⋮ → Benutzerdefinierte Repositories**, füge `https://github.com/EdisonACDC/family-hub` als **Integration** hinzu, installiere **Family Hub** und starte Home Assistant neu. Füge sie unter **Einstellungen → Geräte & Dienste → Integration hinzufügen** hinzu.
2. **Add-on installieren.** Nutze die Schaltfläche oben oder gehe zu **Einstellungen → Add-ons → Add-on-Store → ⋮ → Repositories** und füge `https://github.com/EdisonACDC/family-hub` ein. Öffne **Family Hub UI**, drücke **Installieren** und dann **Starten**.
3. **Family Hub öffnen** aus dem Seitenmenü. Die Einrichtungshilfe öffnet sich beim ersten Mal von selbst: Gib der Familie einen Namen, füge die Personen hinzu, wähle die Kalender – fertig.

Das Add-on setzt voraus, dass die Integration schon eingerichtet ist.

## Konfiguration

In der Einrichtungshilfe, oder später unter **Einstellungen → Geräte & Dienste → Family Hub → Konfigurieren**:

- **Familie**: Name, Sprache, erster Tag der Woche, 24-h- oder 12-h-Uhr.
- **Personen**: Name, Farbe, Rolle (Erwachsener, Kind, Gast), verknüpfter Home-Assistant-Benutzer, Handy und Lautsprecher für Hinweise, Ruhezeiten.
- **Kalender**: Kategorien wie Familie, Schule, Arzt, Geburtstage oder eigene.
- **Erinnerungen**: Vorlauf, Kanäle, Familienruhe, Zeiten der Zusammenfassung.
- **Quellen**: To-do-Listen, bereits in Home Assistant vorhandene Kalender, eine Wetter-Entität (`weather.*`).
- **Externe Kalender** (nur Erwachsene): eine ICS-Datei per Link oder Datei. Aktualisierung alle 12 Stunden.
- **Hinweise**: pro Person, Handy und Echo, aus denen Home Assistant bekannt sind, Kanäle, Lautstärke der Ansage, Ruhezeit und ein Test.

## Häufige Fragen

**Brauche ich Alexa?** Nein. Lautsprecher sind optional; ohne sie funktionieren die anderen Kanäle.

**Brauche ich die Home-Assistant-App auf dem Handy?** Nein. Für Handy-Benachrichtigungen schon; ohne sie sind diese Optionen einfach ausgeblendet.

**Brauche ich YAML?** Nein. Alles wird in der Oberfläche eingerichtet.

**Brauche ich das Add-on?** Kalender und Erinnerungen funktionieren mit der Integration allein. Die Bildschirmansicht fürs Tablet ist das Add-on.

**Wo werden die Daten gespeichert?** Es gibt keine Datenbank. Die Einstellungen stehen in den Optionen der Integration, der Inhalt externer Kalender im Speicher von Home Assistant.

**In welchen Sprachen gibt es es?** Italienisch, Deutsch und Englisch, je nach Sprache von Home Assistant.

## Stand und Grenzen

- Getestet mit Home Assistant 2026.10.4 auf einer Testinstallation (automatische Tests) und auf einem Tablet im Browser. Noch zu prüfen in einem echten Zuhause: den Download eines externen Kalenders über einen Link, die Schaltflächen der Handy-Benachrichtigungen (Ereignis `mobile_app_notification_action` der Companion-App) und Alexa-Ansagen.
- Die Wetter- und Müll-Symbole wurden für dieses Projekt gezeichnet.
- Die Personen und Kalender in den Tests sind erfunden.

## Unterstützung

Wenn Family Hub deiner Familie hilft, kannst du mir einen Kaffee spendieren ☕ [ko-fi.com/edisonacdc](https://ko-fi.com/edisonacdc)

Wenn es deiner Familie hilft, gib dem Repository einen ⭐ – so finden andere Familien es.

## Entwicklung

Integration (aus dem Hauptordner, mit einer Test-Instanz von Home Assistant):

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements_test.txt
pytest
ruff check . && ruff format --check .
mypy
```

Add-on (mit einem Fake-Home-Assistant und dem Browser Microsoft Edge):

```bash
cd addon
pip install -r requirements.txt pytest playwright
pytest
```

## Lizenz

MIT, siehe [LICENSE](LICENSE). Changelog des Add-ons: [addon/CHANGELOG.md](addon/CHANGELOG.md).
