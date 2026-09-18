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
    main.py         create_app(): bouwt de applicatie
    api/            de eindpunten, plus deps.py (wie ben je, en mag je dit)
    core/           instellingen, database, beveiliging, rechten
    models/         de tabellen
    schemas/        wat er in en uit de API gaat
    services/       de regels
    integrations/   de buitenwereld
      base.py       de koppelvlakken waar iedereen zich aan houdt
      finance/      handmatig, crypto-koersen, register
      social/       YouTube, Instagram, TikTok, register
      voice/        SpeechBrain achter een koppelvlak
      fx.py         wisselkoersen naar euro
    workers/        de achtergrondtaken
    utils/          geld, tijd, versleuteling, audio, afdrukken, pincode-eisen
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

## De applicatie wordt gemaakt door een functie

`create_app()` bouwt hem. Wie hem aanroept bepaalt welke instellingen en welke database
erin gaan; een test geeft zijn eigen database mee en hoeft niets te vervangen wat er al
staat. De regel `app = create_app()` onderaan `main.py` is er voor `uvicorn app.main:app`
en legt zelf nog geen verbinding aan — dat gebeurt pas bij het opstarten (de lifespan).

### Geen verbinding in een modulevariabele

Eerder stonden `engine` en `SessionLocal` los in `core/database.py`. Dat werkt, maar dan
deelt het hele programma één verbinding die al bij het importeren wordt aangelegd: een
test kan er niet omheen, twee apps naast elkaar zitten elkaar in de weg, en bij het
afsluiten blijft er van alles openstaan.

Nu is er een `Database`-object. De lifespan zet er één klaar in `app.state`, endpoints
vragen erom via `Depends(get_session)`, en wie geen verzoek heeft — de scheduler, de
scripts — krijgt hem meegegeven of maakt zijn eigen met `create_database()`.

## /health zegt pas 'ok' als de database antwoordt

Vroeger gaf `/health` altijd `{"status": "ok"}`, ook met een database die plat lag. Dan
meldt de monitor dat alles goed gaat terwijl niets werkt. Nu doet het endpoint een
`SELECT 1` over de sessie die het binnenkrijgt, en geeft het een `503` met
`status: degraded` als dat niet lukt — geen `500`, want dat is de uitkomst van de
controle en niet een fout in de app.

Eén valkuil zit daarin vast: een platliggende PostgreSQL komt **niet** als nette
`SQLAlchemyError` binnen maar als kale `ConnectionRefusedError` uit asyncpg. Vangen op
`SQLAlchemyError` alleen is dus niet genoeg. `tests/test_health.py` houdt dat vast.

## Stubs met een echt koppelvlak

Twee onderdelen doen nog niet wat ze straks moeten doen, maar zijn wel al zo gebouwd dat de
echte versie erin past zonder dat de rest verandert:

- **`SpeakerEncoder`** — SpeechBrain, of straks pyannote, of in de tests een namaakversie.
- **`ToolRegistry` / `SkillExecutor`** — de stappen van een skill worden nagelopen en gelogd,
  maar er gebeurt nog niets in de buitenwereld. Een echt gereedschap aansluiten is één
  `register()` erbij; de Task-API verandert er niet van. Zie [skills.md](skills.md).

Dat `simulated: true` staat in elk antwoord. Een stub die zich voordoet als het echte werk is
erger dan geen stub.

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
