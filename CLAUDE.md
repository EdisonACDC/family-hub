# Family Hub: rules for working on this project

Family Hub is a product for anyone who installs it, not for one household. Every choice must work
on any Home Assistant.

## A. Never depend on names

- No detection by entity-id prefix, device name, area or service name. Family Hub's own entities
  are found in the entity registry (platform `family_hub`, unique id `<entry>_<category>` or
  `<entry>_ext_<source>`) or by their attributes. External entities are found by domain plus the
  registry.
- Echo speakers are found in the registry (platform `alexa_media`), leaving out groups,
  Fire TV, "This Device", disabled entries and unavailable ones.
- It must work when the device is in an area (the area is put in front of the entity id), when
  entity ids have been renamed by hand, and with accents, emoji, spaces and long names.

## B. No assumptions about the home

- All text comes from the translation tables (it, de, en), including notifications, summaries and
  Alexa announcements. The default language comes from Home Assistant.
- The default rubbish types follow the language and country of Home Assistant.
- Everything works without Alexa Media Player, the mobile app, a weather entity, to-do lists,
  external calendars, or persons linked to users. A missing part is hidden, without errors.
- Time zone and clock/date format come from Home Assistant. The week starts on Monday or Sunday,
  according to the language.
- Several families or instances: no fixed data and no invented ids.

## C. A perfect first install

- An end-to-end test of a clean install (integration added, guide, calendars shown at once, an
  event created) must pass for: an area on the device, English, German, no Alexa and no mobile
  app, and a non-admin user opening the page.
- When something is missing (integration not installed, add-on and integration versions
  different, no calendar) the page says what to do. It is never an empty page.

## D. Test data

- No real names of people, Echo speakers, phones or calendars from anyone's home in the
  repository, tests or examples. Use invented names.
- The layout tests also use long names, accents and emoji.

## Working practice

- Commit and publish only when asked. Commit messages end with the Co-Authored-By line.
- Run the integration and add-on suites (both must be green) and ruff before a release.
