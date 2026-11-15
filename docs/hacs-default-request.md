# Richiesta per la lista predefinita di HACS (hacs/default)

Perché: dall'ottobre 2026 le statistiche di Home Assistant
(`analytics.home-assistant.io/custom_integrations.json`) contano le integrazioni personalizzate
riconosciute da **home-assistant/brands oppure dalla lista predefinita di HACS**
(analytics.home-assistant.io PR #1128 e #1149, unite; la PR #1091 che toglieva del tutto il
vincolo è stata chiusa). brands non accetta più nuove integrazioni personalizzate: la strada è
`hacs/default`. Oggi `family_hub` non è né nei dati delle statistiche né nella lista HACS.

## Prima di inviarla (sul ramo predefinito `main`, quindi dopo la 0.9 stabile)

- [ ] `main` contiene la 0.9 stabile (manifest ordinato, `ical>=14.3.0`, `CONFIG_SCHEMA`,
      `actions/checkout@v7`): oggi su `main` hassfest fallisce ancora per i problemi della 0.8.
- [ ] Azione «Validate» verde su `main` (HACS action senza `ignore` e hassfest).
- [ ] Una **release completa** (non pre-release) creata dopo quell'azione verde, con l'asset
      `family_hub.zip`.
- [ ] Repository pubblico, attivo, con descrizione, issue attive, topic (già presenti) e licenza
      riconosciuta (MIT: già presente).
- [ ] Cartella `custom_components/family_hub/brand/` con `icon.png` (già presente).
- [ ] Il dominio `family_hub` non è un'integrazione core (verificato: non lo è).
- [ ] La PR la apre il proprietario (account personale EdisonACDC, non un'organizzazione).

## Come inviarla

1. Fork di `hacs/default`, nuovo ramo da `master` (non usare `master` direttamente).
2. Nel file `integration` aggiungere, **in ordine alfabetico** (non in fondo):

   ```
   "EdisonACDC/family-hub",
   ```

3. Aprire la PR con il testo qui sotto, senza chiedere revisioni.

## Testo della PR

Titolo: `Adds new integration [EdisonACDC/family-hub]`

```markdown
## Checklist

- [x] I've read the [publishing documentation](https://hacs.xyz/docs/publish/start).
- [x] I've added the [HACS action](https://hacs.xyz/docs/publish/action) to my repository.
- [x] (For integrations only) I've added the [hassfest action](https://developers.home-assistant.io/blog/2020/04/16/hassfest/) to my repository.
- [x] The actions are passing without any disabled checks in my repository.
- [x] I've added a link to the action run on my repository below in the links section.
- [x] I've created a new release of the repository after the validation actions were run successfully.

## Links

Link to current release: <https://github.com/EdisonACDC/family-hub/releases/tag/v0.9.0>
Link to successful HACS action (without the `ignore` key): <https://github.com/EdisonACDC/family-hub/actions/runs/RUN_ID>
Link to successful hassfest action (if integration): <https://github.com/EdisonACDC/family-hub/actions/runs/RUN_ID>
```

Al posto di `RUN_ID` va il numero della corsa «Validate» verde su `main`, e la release deve
essere quella stabile pubblicata dopo quella corsa.

Dopo l'inserimento, le statistiche possono richiedere qualche giorno per mostrare `family_hub`.
