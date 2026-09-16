# Channel upload schedule

Per kanaal wanneer de volgende upload eruit gaat, met een aftelling.

## De aftelling staat niet in de database

Er staat één exact moment in UTC (`scheduled_at`). Het verschil met nu rekent de
frontend uit. Een opgeslagen "nog 28 minuten" is binnen een minuut onwaar.

De server geeft bij elk antwoord zijn eigen tijd mee (`server_time`). De frontend rekent
daar één keer het verschil met de eigen klok uit en gebruikt dat bij elke tik. Staat de
computer een paar minuten verkeerd, dan klopt de aftelling nog steeds.

## Geen wegdrijvende teller

De teller haalt elke seconde het verschil opnieuw uit de twee tijdstempels, in plaats van
er een seconde af te trekken. Aftrekken loopt scheef zodra een tik iets te laat komt — en
na een uur ben je merkbaar de weg kwijt. Zo blijft hij ook kloppen nadat de laptop dicht
is geweest.

Bereikt de teller nul, dan haalt het scherm één keer de nieuwe status op bij de backend.

## Weergave

In de interface staat `1d 13u 42m`, `4u 52m` of `28m 16s`. Onderliggend is het gewoon een
aantal seconden vanaf een exacte tijdstempel.

## Herhaling

| Waarde | Wat er gebeurt |
| --- | --- |
| `once` | één keer; is het moment voorbij, dan is de upload **achterstallig** |
| `daily` | elke dag op hetzelfde tijdstip |
| `weekly` | elke week op hetzelfde moment |

Bij een herhaling waarvan het moment al voorbij is, schuift `effective_at` automatisch op
naar de volgende keer. Dat gebeurt bij het uitrekenen, niet in de database — zo ontstaan
er geen achterstallige rijen als Ganz een nacht uit heeft gestaan.

Een eenmalige upload die te laat is houdt zijn oorspronkelijke tijd en wordt gemeld als
"Wacht op uitvoering". Hij is niet verlopen, hij is achterstallig, en dat moet je zien.

## Tijdzones

`scheduled_at` staat altijd in UTC. De tijdzone van de gebruiker staat er los bij, omdat
je een herhaling anders niet correct over de zomertijdgrens tilt: 18:00 in Amsterdam zou
dan ineens 17:00 worden. Bij het opschuiven van een herhaling wordt daarom in de lokale
tijdzone gerekend, niet in UTC.

Een onbekende tijdzone valt terug op UTC in plaats van het inplannen te blokkeren.

## Statussen

`scheduled`, `uploading`, `completed`, `failed`, `cancelled`, `waiting_confirmation`.

Alleen `scheduled`, `uploading` en `waiting_confirmation` tellen mee voor "de volgende
upload". Zet je een herhalende upload op `completed`, dan blijft die rij staan en wordt
de volgende keer als nieuwe rij ingepland — zo houd je zicht op wat er wanneer is
geplaatst.

Een upload daadwerkelijk starten (`POST /uploads/{id}/status`) vereist `upload.execute`,
dus tier 1 én je wachtwoord: dit zet iets in gang naar buiten toe.

## Soorten inhoud

`video`, `short`, `reel`, `post`, `story`, `other`.

## Op het dashboard

```
CHANNEL UPLOAD SCHEDULE          Alles bekijken ›
──────────────────────────────────────────────
▶ YouTube Kanaal 1        Upload in 1d 13u 42m
▶ YouTube Kanaal 2            Upload in 4u 52m
♪ TikTok Kanaal 1            Upload in 28m 16s
◉ Instagram Reels             Upload in 2u 04m
```

Zonder geplande upload: **"Geen upload gepland"**. Bij een verlopen koppeling:
**"Opnieuw inloggen"** — dat is dringender dan een aftelling en komt daarom in de plaats
ervan. Platformiconen blijven klein; het gaat om de tijd, niet om het logo.
