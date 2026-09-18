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

## Inloggen en bevestigen

| Methode | Pad | Wat het doet |
| --- | --- | --- |
| POST | `/auth/login` | e-mailadres + wachtwoord → token |
| POST | `/auth/confirm` | wachtwoord → kortlopend bevestigingstoken |
| GET | `/auth/me` | wie ben ik en wat mag ik |
| GET | `/auth/permissions` | het hele rechtenregister, met per recht of jij het hebt |

Gevoelige handelingen vragen naast het inlogtoken ook een bevestigingstoken in de
header `X-Ganz-Confirmation`. Ontbreekt die, dan antwoordt de API met **428** en de
melding dat je eerst moet bevestigen. Zie `docs/security.md`.

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
