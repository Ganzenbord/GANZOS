# API

## /health — buiten het API-voorvoegsel

`GET /health` (dus niet `/api/health`) zegt of de app én de database het doen. Een monitor
moet hem op een vaste plek kunnen vinden, ook als het voorvoegsel verandert.

```json
{ "status": "ok", "environment": "production", "database": "ok", "detail": null }
```

Antwoordt de database niet, dan komt er een `503` met `"status": "degraded"`,
`"database": "unavailable"` en een zin in `detail` die zegt wat eraan te doen is. Geen
`500`: dat de database plat ligt is de uitkomst van de controle, geen fout in de app.

Alles staat onder `/api`. Inloggen gaat met een bearer-token in de
`Authorization`-header.

## Het Command Center

| Endpoint | Wat het doet | Recht |
| --- | --- | --- |
| `GET /api/status` | draait alles nog: core, stem, skills, integraties, systeem | `core.read` |
| `GET /api/activity` | het logboek, per pagina (`limit`, `offset`, `action`) | `activity.read` |
| `GET /api/schedule/today` | wat er vandaag op de rol staat: uploads én taken | `tasks.read` |
| `GET /api/skills/active` | de skills die aanstaan, meest gebruikte eerst | `skills.read` |
| `GET /api/system/metrics` | de ruwe metingen van de computer | `system.admin` (**tier 1**) |
| `GET /api/memory/overview` | hoeveel Ganz onthoudt en wat er het laatst gebeurde | `memory.read` |

`/api/dashboard` blijft bestaan en levert alle panelen in één keer — dat scheelt een stuk of
tien aanroepen bij het openen. De endpoints hierboven zijn er voor wie één ding wil, of wil
doorbladeren.

### Pagineren

`/api/activity` geeft een omslag om de lijst heen:

```json
{ "items": [ … ], "total": 412, "limit": 50, "offset": 0, "has_more": true }
```

Zonder dat totaal kan de frontend niet weten of er nog meer is. Er wordt gesorteerd op tijd
én op id: twee regels in dezelfde milliseconde zouden anders tussen twee pagina's van
volgorde kunnen wisselen, en dan zie je er één dubbel en mis je er één.

## Skills en taken

| Endpoint | Wat het doet | Recht |
| --- | --- | --- |
| `GET /api/skills` · `POST` · `PATCH /{id}` · `DELETE /{id}` | skills beheren | `skills.read` / `skills.write` |
| `GET /api/skills/tools` | waar een skill uit kan bestaan | `skills.read` |
| `GET /api/tasks` · `POST` | taken bekijken en aanmaken | `tasks.read` / `tasks.write` |
| `POST /api/tasks/{id}/match` | zoek de skill die erbij hoort | `tasks.write` |
| `POST /api/tasks/{id}/execute` | uitvoeren | `tasks.execute` |
| `POST /api/tasks/{id}/cancel` | afbreken | `tasks.write` |

`match` geeft altijd een reden terug, ook als er niets past. `execute` vraagt om een
bevestiging zodra er gevoelig gereedschap in de stappen zit, en antwoordt met
`"simulated": true` zolang de gereedschappen nog niets in de buitenwereld doen. Zie
[skills.md](skills.md).

## Stem

| Endpoint | Wat het doet | Nodig |
| --- | --- | --- |
| `POST /api/voice/enroll` | een stem inschrijven bij een `user_id` (multipart: `audio`, `user_id`, optioneel `label`) | `voice.enroll` + bevestiging — behalve de allereerste keer |
| `POST /api/voice/identify` | uitzoeken wiens stem dit is (multipart: `audio`) | niets: dit ís de controle |
| `GET /api/voice/profiles` | de ingeschreven stemmen | `voice.read` |

`identify` geeft `result: "identified"` met een gewoon inlogtoken, of `result: "unknown"`
zonder token. Hoe de cijfers te lezen zijn en waarom een stem nooit genoeg is voor gevoelige
handelingen: [voice.md](voice.md).

## Inloggen en bevestigen

| Methode | Pad | Wat het doet |
| --- | --- | --- |
| POST | `/auth/login` | e-mailadres + wachtwoord → inlogtoken + vernieuwingstoken |
| POST | `/auth/refresh` | vernieuwingstoken → een nieuw stel; geen inlogcontrole nodig |
| GET | `/auth/sessions` | welke apparaten nu toegang hebben (zonder tokens) |
| DELETE | `/auth/sessions/{id}` | één apparaat uitloggen |
| POST | `/auth/logout` | dit apparaat uitloggen, of met `?alles=true` allemaal |
| POST | `/auth/confirm` | wachtwoord óf pincode → kortlopend bevestigingstoken |
| POST | `/auth/pin` | pincode instellen of wijzigen (je huidige wachtwoord is nodig) |
| GET | `/auth/me` | wie ben ik, wat mag ik, en of ik een pincode heb (`has_pin`) |
| GET | `/auth/permissions` | het hele rechtenregister, met per recht of jij het hebt |

Een inlogtoken is vijftien minuten geldig; het vernieuwingstoken zestig dagen, en de klok
begint bij elk gebruik opnieuw. Het scherm vernieuwt zelf zodra een verzoek 401 antwoordt, dus
daar merk je niets van. Zie [server.md](server.md).

Gevoelige handelingen vragen naast het inlogtoken ook een bevestigingstoken in de
header `X-Ganz-Confirmation`. Ontbreekt die, dan antwoordt de API met **428** en de
melding dat je eerst moet bevestigen. Zie `docs/security.md`.

## YouTube

| Methode | Pad | Wat het doet |
| --- | --- | --- |
| GET | `/youtube/status` | staat de koppeling, en zo niet: wat ontbreekt er |
| POST | `/youtube/connect` | geeft het adres waar je bij Google toestemming geeft |
| GET | `/youtube/oauth/callback` | hier zet Google je neer; geen JSON maar een pagina |
| POST | `/youtube/disconnect` | gooit de tokens weg, houdt het kanaal |

Koppelen en losmaken zijn gevoelige handelingen: ze vragen een bevestigingstoken. De
terugkeerpagina juist niet — die wordt door Google aangeroepen en heeft dus geen
inlogtoken; wat daarvoor in de plaats komt is een ondertekende `state`. Zie
[youtube.md](youtube.md).

## Dashboard

| Methode | Pad | Wat het doet |
| --- | --- | --- |
| GET | `/dashboard` | alle panelen in één antwoord |
| GET | `/time` | de servertijd (vrij toegankelijk, voor de aftelling) |

## To do

| Methode | Pad | Wat het doet |
| --- | --- | --- |
| GET | `/todos/today` | de lijst van vandaag (`?day=2025-09-15` voor een andere dag) |
| GET | `/todos` | alle taken, ook de inactieve |
| POST | `/todos` | taak aanmaken, eventueel meteen met subtaken |
| PATCH | `/todos/{id}` | taak wijzigen |
| DELETE | `/todos/{id}` | taak verwijderen |
| POST | `/todos/{id}/complete` | afvinken of terugzetten voor een dag |
| POST | `/todos/{id}/toggle` | omzetten |
| POST | `/todos/{id}/subtasks` | subtaak toevoegen |
| PATCH | `/todos/subtasks/{id}` | subtaak wijzigen of afvinken |
| DELETE | `/todos/subtasks/{id}` | subtaak verwijderen |
| POST | `/todos/reorder` | de hele volgorde in één keer zetten |
| GET | `/todos/{id}/history` | de stand per dag, plus hoeveel dagen op rij |

## Finance

| Methode | Pad | Bevestiging nodig |
| --- | --- | --- |
| GET | `/finance/overview` | nee |
| GET | `/finance/accounts` | nee |
| GET | `/finance/providers` | nee |
| GET | `/finance/history` | nee |
| POST | `/finance/accounts` | **ja** |
| PATCH | `/finance/accounts/{id}` | **ja** |
| DELETE | `/finance/accounts/{id}` | **ja** |
| POST | `/finance/sync` | **ja** |

`GET /finance/overview` geeft:

```json
{
  "total_eur": "42684.21",
  "connected_accounts": 4,
  "counted_accounts": 3,
  "excluded_accounts": [{ "name": "Kraken", "reason": "reauth_required" }],
  "breakdown": [{ "account_type": "bank", "total_eur": "12420.00" }],
  "last_updated": "2025-09-15T20:56:13Z",
  "stale": false,
  "trend_pct": 2.4,
  "server_time": "2025-09-15T20:58:02Z"
}
```

`trend_pct` is `null` zolang er geen momentopname van een week terug is. Een percentage
uit één meetpunt is geen trend.

## Social

| Methode | Pad | Bevestiging nodig |
| --- | --- | --- |
| GET | `/social/overview` | nee |
| GET | `/social/channels` | nee |
| GET | `/social/channels/{id}/stats` | nee |
| GET | `/social/history` | nee |
| GET | `/social/providers` | nee |
| POST | `/social/channels` | **ja** |
| PATCH | `/social/channels/{id}` | **ja** |
| DELETE | `/social/channels/{id}` | **ja** |
| POST | `/social/sync` | **ja** |

In `/social/overview` betekent `null` bij een metriek: geen enkel gekoppeld platform
levert dit cijfer. `revenue_available: false` betekent hetzelfde voor de omzet; het
dashboard toont dan "Niet beschikbaar" in plaats van € 0,00.

## Uploads

| Methode | Pad | Bevestiging nodig |
| --- | --- | --- |
| GET | `/uploads/schedule` | nee |
| GET | `/uploads` | nee |
| POST | `/uploads` | nee (wel `upload.schedule`) |
| PATCH | `/uploads/{id}` | nee |
| POST | `/uploads/{id}/cancel` | nee |
| DELETE | `/uploads/{id}` | nee |
| POST | `/uploads/{id}/status` | **ja** (`upload.execute`) |

`GET /uploads/schedule` geeft per kanaal de eerstvolgende upload, en bovenaan
`server_time`:

```json
{
  "server_time": "2025-09-15T11:18:21Z",
  "channels": [
    {
      "channel_id": 3,
      "platform": "tiktok",
      "channel_name": "TikTok Kanaal 1",
      "channel_status": "connected",
      "needs_reauth": false,
      "next_upload": {
        "id": 12,
        "scheduled_at": "2025-09-15T11:46:37Z",
        "effective_at": "2025-09-15T11:46:37Z",
        "seconds_until": 1696,
        "overdue": false,
        "status": "scheduled"
      }
    }
  ]
}
```

`seconds_until` is een momentopname, bedoeld als startwaarde. De frontend telt zelf
verder vanaf `effective_at` en gebruikt `server_time` om het verschil met de eigen klok
weg te rekenen.

`effective_at` verschilt van `scheduled_at` bij een herhaling waarvan het moment al
voorbij is: dan staat er alvast de volgende keer.

## Ganz-modules

| Methode | Pad |
| --- | --- |
| GET | `/core`, `/system`, `/llm` |
| GET | `/skills`, `/missions`, `/memory`, `/conversations` |
| GET | `/integrations`, `/workflows`, `/activity` |

## Foutcodes

| Code | Betekenis |
| --- | --- |
| 401 | niet ingelogd of sessie verlopen |
| 403 | je tier is te laag voor dit onderdeel |
| 404 | bestaat niet, óf is niet van jou (met opzet dezelfde melding) |
| 422 | het verzoek klopt niet |
| 428 | bevestig eerst met je wachtwoord |
