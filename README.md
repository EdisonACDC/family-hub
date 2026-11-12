<p align="center">
  <img src="addon/icon.png" width="96" alt="Family Hub icon">
</p>

<h1 align="center">Family Hub</h1>

<p align="center">
  <b>English</b> · <a href="README.it.md">Italiano</a> · <a href="README.de.md">Deutsch</a>
</p>

<p align="center">
  The family calendar Home Assistant was missing: one colour per person, reminders on phone, Alexa
  and wall tablet, bin days and school holidays – set up in minutes, no YAML.
</p>

<p align="center">
  <a href="https://github.com/EdisonACDC/family-hub/releases/latest"><img src="https://img.shields.io/github/v/release/EdisonACDC/family-hub" alt="Release"></a>
  <a href="https://hacs.xyz/"><img src="https://img.shields.io/badge/HACS-Custom-41BDF5.svg" alt="HACS custom"></a>
  <a href="https://ko-fi.com/edisonacdc"><img src="https://img.shields.io/badge/Ko--fi-Support%20on%20Ko--fi-FF5E5B?logo=kofi&logoColor=white" alt="Support on Ko-fi"></a>
</p>

<p align="center">
  <a href="https://my.home-assistant.io/redirect/hacs_repository/?owner=EdisonACDC&repository=family-hub&category=integration"><img src="https://my.home-assistant.io/badges/hacs_repository.svg" alt="Open your Home Assistant and open the Family Hub integration in HACS"></a>
  &nbsp;
  <a href="https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2FEdisonACDC%2Ffamily-hub"><img src="https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg" alt="Open your Home Assistant and add the Family Hub add-on repository"></a>
</p>

<p align="center">
  <img src="docs/images/demo.gif" width="320" alt="Family Hub on a wall tablet">
</p>

<p align="center">
  <img src="docs/images/screenshots.png" alt="Family Hub screenshots: week view, reminders, pickups and repeating events">
</p>

## Features

- **Week view** on the wall tablet and the PC, and an **agenda** on the phone (today and tomorrow).
- **One colour per person**, all-day and timed events, filters per calendar, and a **+** button for new events.
- **Repeating events**: every day, weekly on the days you choose, every 2 weeks, monthly, yearly. They
  end never, on a date, or after a number of times. Editing or deleting asks: *only this*, *this and
  the following*, or *all*.
- **Reminders**: pop-ups on the tablet (*Done*, *Snooze*, *Stop*), phone notifications with buttons,
  Alexa or text-to-speech, and morning and evening summaries.
- **Bin days**: one reminder per pickup, the evening before and in the morning. Types are recognised
  from the event title (Restmüll, Bio, Papier, Gelber Sack, Glas), colours can be changed. Pickups can
  also be made by hand: weekly, every 2 or 4 weeks, or monthly, with extra and skipped dates.
- **Weather** from the entity you choose: at the top, under each day, and in the summaries.
- **Shifts** per person, entered across several days.
- **Shopping lists** from Home Assistant's to-do lists.
- **Roles**: adults see everything, children see their own events and reminders, guests can only read.
- **External calendars** (ICS): school holidays, public holidays, bins from your municipality. Read-only.

## Installation

1. **Install the integration.** In HACS, open **⋮ → Custom repositories**, add
   `https://github.com/EdisonACDC/family-hub` as an **Integration**, install **Family Hub**, then restart
   Home Assistant. Add it under **Settings → Devices & services → Add integration**.
2. **Install the add-on.** Use the button above, or go to **Settings → Add-ons → Add-on Store → ⋮ →
   Repositories** and paste `https://github.com/EdisonACDC/family-hub`. Open **Family Hub UI**, press
   **Install**, then **Start**.
3. **Open Family Hub** from the side menu. The setup guide opens by itself the first time: name the
   family, add the people, choose the calendars, and you are done.

The add-on needs the integration to be set up first.

## Configuration

Everything is set from the guide, or later from **Settings → Devices & services → Family Hub → Configure**:

- **Family**: name, language, first day of the week, 24 h or 12 h clock.
- **People**: name, colour, role (adult, child, guest), linked Home Assistant user, phone and speaker for
  alerts, quiet hours.
- **Calendars**: categories such as Family, School, Doctor, Birthdays, or your own.
- **Reminders**: how early, which channels, family quiet time, summary times.
- **Sources**: to-do lists, calendars already in Home Assistant, one weather entity (`weather.*`).
- **External calendars** (adults only): an ICS file from a link or a file. Refreshed every 12 hours.
- **Alerts**: per person, the phone and Echo speaker chosen from those Home Assistant knows, channels,
  announcement volume, quiet time, and a test.

## FAQ

**Do I need Alexa?** No. Speakers are optional; without them the other channels still work.

**Do I need the Home Assistant mobile app?** No. Phone notifications need it; without it those options
are simply hidden.

**Do I need YAML?** No. Everything is set up in the interface.

**Do I need the add-on?** The calendars and reminders work with the integration alone. The wall-tablet
screen is the add-on.

**Where is my data kept?** There is no database. The settings are in the integration's options, and the
content of external calendars is in Home Assistant's storage.

**Does it work in other languages?** Italian, German and English, from the Home Assistant language.

## Status and limits

- Tested with Home Assistant 2026.10.4 on a test installation (automated tests) and on a tablet in the
  browser. Still to check on a real home: downloading an external calendar from a link, the notification
  buttons on the phone (the Companion app's `mobile_app_notification_action` event), and Alexa announcements.
- The weather and bin icons were drawn for this project.
- The people and calendars in the tests are invented.

## Support

If Family Hub helps your family, you can buy me a coffee ☕ [ko-fi.com/edisonacdc](https://ko-fi.com/edisonacdc)

If it helps your family, please ⭐ the repo – it helps other families find it.

## Development

Integration (from the main folder, with a test Home Assistant):

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements_test.txt
pytest
ruff check . && ruff format --check .
mypy
```

Add-on (with a fake Home Assistant and the Microsoft Edge browser):

```bash
cd addon
pip install -r requirements.txt pytest playwright
pytest
```

## License

MIT, see [LICENSE](LICENSE). Add-on changelog: [addon/CHANGELOG.md](addon/CHANGELOG.md).
