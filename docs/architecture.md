# Architectuur

Ganz bestaat uit drie delen die los van elkaar draaien:

```
React + Vite (frontend)        ← wat je ziet
        │  HTTP, alleen /api/...
FastAPI (backend)              ← alle regels en berekeningen
        │
PostgreSQL + APScheduler       ← wat onthouden wordt, en wat vanzelf gebeurt
```

Electron is een schil om de frontend heen: dezelfde pagina, maar dan als programma op
je computer. Hij start de backend er desgewenst zelf bij.

## De vaste volgorde

```
Provider  →  Integratie  →  Service  →  API  →  Frontend
```

- **Provider** praat met de buitenwereld (YouTube, een exchange, een koersendienst).
- **Integratie** vertaalt hun antwoord naar iets dat Ganz begrijpt.
- **Service** bevat de regels: optellen, omrekenen, bepalen wat zichtbaar is.
- **API** doet de rechtencontrole en levert het antwoord.
- **Frontend** toont het. Meer niet.

Er zit geen bedrijfslogica in React, en React praat nooit rechtstreeks met YouTube of
een bank. Dat is niet uit netheid: een sleutel die de browser bereikt, is een sleutel
die weg is.

## Waarom het dashboard nooit een provider aanroept

```
Scheduler  →  Provider  →  Database
                              ↓
Dashboard  ←  API  ←  Database
```

De scheduler haalt periodiek gegevens op en schrijft ze weg. Het dashboard leest
uitsluitend wat er al staat. Zou elke pagina-refresh langs alle providers gaan, dan
zit je binnen een dag tegen hun rate limits aan — en wordt het scherm net zo traag als
de traagste bank.

Eén uitzondering die géén uitzondering is: de aftelling van een upload. Die rekent de
frontend zelf uit op basis van het opgeslagen moment en de servertijd. Dat kost geen
enkele aanroep.

## Mappen

```
backend/
  app/
    models/         de tabellen
    schemas/        wat er in en uit de API gaat
    services/       de regels
    routers/        de eindpunten
    integrations/   de buitenwereld
      base.py       de koppelvlakken waar iedereen zich aan houdt
      finance/      handmatig, crypto-koersen, register
      social/       YouTube, Instagram, TikTok, register
      fx.py         wisselkoersen naar euro
    scheduler/      de achtergrondtaken
    utils/          geld, tijd, versleuteling
  alembic/          de migraties
  tests/            de testsuite
  scripts/          gebruiker aanmaken, voorbeelddata
frontend/
  src/
    api/            de verbinding met de backend
    components/     panelen en bouwstenen
    hooks/          dashboard ophalen, klok, aftellen
    pages/          de schermen
    lib/format.ts   alle opmaak van getallen en tijden
electron/           de desktopschil
docs/               deze documentatie
```

## Een nieuwe partij toevoegen

Een bank, exchange of platform erbij betekent: één klasse schrijven die voldoet aan
`FinanceProvider` of `SocialProvider` in `app/integrations/base.py`, en hem in het
register zetten. De services, de API, het dashboard en de database veranderen niet
mee. Zie `docs/finance.md` en `docs/social.md` voor een voorbeeld.

## Het dashboard in één aanroep

`GET /api/dashboard` levert alle panelen tegelijk. Dat scheelt een stuk of tien losse
verzoeken bij het openen. Panelen waar je geen recht op hebt komen er niet in — dan
staat er `null` en laat de frontend het paneel weg.

## De indeling van het scherm

| Rij | Panelen |
| --- | --- |
| 1 | Core overzicht · Ganz Circle · Live intelligence feed |
| 2 | **To do list** · Mission/Tasks · Quick commands |
| 3 | **Finance** · **Social media stats** · LLM status · **Channel upload schedule** |
| 4 | System monitor · Memory insights |

De vier vetgedrukte panelen beantwoorden de vragen waar het command center voor
bedoeld is: wat moet ik vandaag doen, hoeveel heb ik, hoe doen mijn kanalen het, en
wanneer gaat de volgende upload eruit.

In de Ganz Circle staat uitsluitend het woord GANZ. Geen versienummer, geen CPU, geen
status: die horen in de panelen eromheen. De ring beweegt alleen als Ganz daadwerkelijk
luistert of iets uitvoert.
