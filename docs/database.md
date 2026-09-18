# Database

PostgreSQL, benaderd via SQLAlchemy 2 (async). De tests draaien op SQLite, zodat je
geen database hoeft te installeren om ze te draaien.

## Migraties

```bash
cd backend
alembic upgrade head          # tabellen aanmaken of bijwerken
alembic downgrade -1          # één stap terug
alembic revision --autogenerate -m "wat je veranderde"
alembic check                 # staat de database gelijk aan de modellen?
```

De databaseverbinding staat **niet** in `alembic.ini`. Hij komt uit
`GANZ_DATABASE_URL`, zodat er nooit een wachtwoord in de repository belandt. Wil je een
migratie tegen een andere database draaien, dan kan dat met `-x db_url=...`.

## De tabellen

### Ganz zelf

| Tabel | Waarvoor |
| --- | --- |
| `users` | e-mailadres, naam, wachtwoordhash, tier |
| `activity_log_entries` | wat er is gebeurd (nooit waarmee) |
| `skills` | wat Ganz kan: waar hij op aanslaat, welke stappen, hoe vaak het lukte |
| `mission_tasks` | wat Ganz zelf uitvoert, met de gekozen skill en waarom |
| `memory_entries` | wat Ganz onthoudt |
| `conversations`, `conversation_messages` | gesprekken |
| `integrations` | gekoppelde diensten, met versleutelde tokens |
| `workflows` | reeksen stappen |
| `llm_provider_status` | laatst gemeten toestand van de taalmodellen |
| `voice_profiles` | de vingerafdruk van een ingesproken stem |
| `videos` | video's, van concept tot gepubliceerd |
| `confirmation_requests` | elke tweede bevestiging, geslaagd of niet |

### Dezelfde tabel, een andere naam

De architectuurprompt noemt een aantal tabellen die hier al bestaan onder een eigen naam.
Ze zijn met opzet niet dubbel aangemaakt — twee tabellen voor hetzelfde is precies de
tijdelijke architectuur die later weggegooid moet worden.

| In de prompt | Hier |
| --- | --- |
| `Task` | `mission_tasks` |
| `Message` | `conversation_messages` |
| `ChannelAccount` | `social_channels` |
| `Memory` | `memory_entries` |
| `ChannelStats` | `social_channel_stats` |
| `Permission` | geen tabel: het register in `app/core/permissions.py` |
| `ConfirmationRequest` | `confirmation_requests` |

Nog niet gebouwd, en waar ze horen als ze nodig zijn:

| Nog te maken | Waarvoor, en wanneer |
| --- | --- |
| `AuthSession` | een lopende aanmelding vasthouden in plaats van alleen een JWT; nodig zodra een sessie ingetrokken moet kunnen worden |
| `ScheduledTask` | geplande taken in het algemeen; nu is er alleen `upload_schedules`, dat over uploads gaat |

## Tijdstippen

Alles wordt opgeslagen als UTC met tijdzone, en komt er ook zo weer uit — op elke
database. Dat laatste gaat niet vanzelf: PostgreSQL bewaart de tijdzone, SQLite (de
tests) niet. Zonder ingrijpen krijg je op SQLite een kale datetime terug, en klapt een
vergelijking eruit met "can't compare offset-naive and offset-aware datetimes" — en dan
alleen in de tests, of juist alleen op de echte database.

`UtcDateTime` in `app/models/base.py` vangt dat af. Aan de tabellen verandert het niets;
het is puur de vertaling aan de Python-kant. Gebruik dat type voor elke nieuwe
datumkolom, niet `DateTime(timezone=True)` rechtstreeks.

### To do

| Tabel | Waarvoor |
| --- | --- |
| `todo_tasks` | de taak zelf: naam, categorie, prioriteit, herhaling, tijdstip, volgorde |
| `todo_subtasks` | subtaken, met een eigen volgorde |
| `todo_completions` | **één rij per taak per dag** |
| `todo_subtask_completions` | één rij per subtaak per dag |

De stand staat per dag in een eigen rij, niet als vlaggetje op de taak. Zo blijft
15 september afgevinkt terwijl 16 september nog open staat — en kun je later zien hoe
vaak iets is gelukt.

`todo_subtask_completions` is er omdat "Pip gevoerd" morgen weer uit moet staan. Zonder
die tabel zou een subtaak één keer afgevinkt worden en dan voor altijd af zijn.

### Finance

| Tabel | Waarvoor |
| --- | --- |
| `financial_accounts` | rekening, wallet of beleggingsrekening |
| `finance_snapshots` | het totaal op een moment, voor de grafiek en de trend |

Een account bewaart altijd **twee** bedragen: `current_value` in de oorspronkelijke
valuta, en `current_value_eur` omgerekend. Is `current_value_eur` leeg, dan was er geen
betrouwbare koers en telt het account zichtbaar niet mee in het totaal.

`credentials_encrypted` is versleuteld met de sleutel uit `GANZ_ENCRYPTION_KEY` en gaat
nooit naar de frontend.

### Social

| Tabel | Waarvoor |
| --- | --- |
| `social_channels` | een kanaal bij een platform |
| `social_channel_stats` | één meting: volgers, views, likes, reacties, berichten, omzet |

Elke metriek mag leeg zijn. Instagram levert geen totaal aantal weergaven, TikTok geen
omzet. Leeg betekent "niet geleverd" en is iets anders dan nul; het dashboard laat dat
verschil ook zien.

Er wordt een nieuwe meetrij weggeschreven, nooit een oude overschreven. Daardoor kan de
groei uit twee metingen worden berekend in plaats van geraden.

### Uploads

| Tabel | Waarvoor |
| --- | --- |
| `upload_schedules` | één geplande upload: kanaal, soort, moment, status, herhaling, tijdzone |

De aftelling staat er **niet** in. Er staat één exact moment in UTC; het verschil met nu
rekent de frontend uit. Een opgeslagen "nog 28 minuten" is binnen een minuut onwaar.

`timezone` staat er los bij omdat `scheduled_at` in UTC blijft. Zonder de zone van de
gebruiker kun je een dagelijkse herhaling niet correct over de zomertijdgrens tillen:
18:00 in Amsterdam zou dan ineens 17:00 worden.

## Geldbedragen

Alle bedragen zijn `NUMERIC(20, 2)` en worden in Python als `Decimal` behandeld. Met
floats loopt een optelling van twintig rekeningen tientallen centen uit de pas — precies
bij het getal dat het grootst in beeld staat. Ook in de API gaan bedragen als tekst de
deur uit, zodat JavaScript er niet alsnog een float van maakt.
