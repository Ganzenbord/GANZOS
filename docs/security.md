# Beveiliging

## Tiers

Tier 1 is de eigenaar en mag alles. Hoe hoger het nummer, hoe minder rechten. Je hebt
een recht als je tier kleiner of gelijk is aan het maximum van dat recht.

**Geen tier (`NULL`) betekent: wel bekend, geen toegang.** Dat is iets anders dan een
uitgezet account (`active=False`) en iets anders dan de laagste tier (mag een beetje). Je
hebt het nodig zodra een stem herkend kan worden: dan wil je "dag Piet" kunnen zeggen zonder
Piet ergens binnen te laten. Zo iemand krijgt wel een token, maar elk endpoint antwoordt met
403.

| Recht | Vanaf tier | Tweede bevestiging |
| --- | --- | --- |
| `core.read` | 4 | |
| `system.read`, `skills.read`, `tasks.read` | 3 | |
| `todo.read` | 3 | |
| `social.read`, `upload.read` | 3 | |
| `todo.write` | 2 | |
| `upload.schedule` | 2 | |
| `memory.read`, `conversations.read`, `workflows.read` | 2 | |
| `activity.read`, `integrations.read` | 2 | |
| `social.manage` | 2 | **ja** |
| `voice.read` | 2 | |
| `skills.write` | 2 | |
| `tasks.write`, `tasks.execute` | 2 | zie hieronder |
| `finance.read` | **1** | |
| `system.admin` | **1** | |
| `finance.manage` | **1** | **ja** |
| `upload.execute` | **1** | **ja** |
| `integrations.manage` | **1** | **ja** |
| `voice.enroll`, `voice.delete` | **1** | **ja** |

Finance is tier 1. Een upload daadwerkelijk uitvoeren ook: dat zet iets in gang naar
buiten toe. Een stem inschrijven eveneens — dat ís de handeling waarmee je toegang uitdeelt.

`system.read` en `system.admin` zijn met opzet twee dingen. Het stoplicht op het dashboard
(`/system`) zegt of alles nog draait en mag iedereen zien. De ruwe metingen
(`/system/metrics`: belasting, schijfruimte, hoe lang de machine al aanstaat) gaan over de
computer zelf en zijn alleen voor tier 1.

Het register staat in `backend/app/core/permissions.py` — één lijst, zodat je in één oogopslag
ziet wie wat mag. Endpoints bevatten geen eigen regeltjes: ze noemen alleen waar ze over gaan
(`require_permission("upload.execute")`) en het register bepaalt de rest. Wil je iets van
niveau veranderen, dan verander je één regel daar en niets aan de endpoints.

Voor het enkele geval dat er geen passend recht bestaat is er `require_tier(min_tier)`. Heeft
wat je afschermt een naam, gebruik dan het register — dan zie je het ook terug in
`/api/auth/me`.

## Tweede bevestiging

Voor gevoelige handelingen is een inlogtoken niet genoeg. Je haalt eerst een
bevestigingstoken op:

```
POST /api/auth/confirm    { "password": "..." }
POST /api/auth/confirm    { "pin": "2468", "permission_key": "upload.execute" }
```

Dat token is vijf minuten geldig en gaat mee in de header `X-Ganz-Confirmation`.
Ontbreekt hij, dan antwoordt de API met 428.

### Waarom er een tabel achter zit

Elke bevestiging staat als rij in `confirmation_requests`, en het token verwijst ernaar.
Alleen een token zou geen spoor nalaten: je kunt achteraf niet zien dát er bevestigd is,
waarvoor, of hoe vaak het misging. Met de rij erbij geldt bovendien:

- **Eén bevestiging dekt één handeling af.** Daarna gaat de rij op `used`; hetzelfde token
  komt niet nog een keer langs de kassa.
- **Vul je `permission_key` in, dan geldt de bevestiging alleen daarvoor.** Bevestigen om het
  weer op te vragen en er dan een upload mee doen, kan niet.
- **Drie mispogingen en het is klaar.** Een pincode van vier cijfers is anders zo
  doorgeprobeerd; het rekenwerk van de hashing alleen is daarvoor niet genoeg.

### De pincode

`POST /api/auth/pin` met je huidige wachtwoord en een nieuwe pincode (4 tot 12 cijfers, niet
allemaal dezelfde en geen oplopende reeks). De pincode wordt gehasht met dezelfde functie als
wachtwoorden (pbkdf2_sha256) en staat nooit leesbaar in de database.

De pincode is bedoeld voor de telefoon en voor bediening met de stem, waar een heel wachtwoord
intikken onhandig is. Hij vervángt het wachtwoord niet: je kunt hem alleen gebruiken als je al
ingelogd of herkend bent.

### Een uitzondering: bevestiging per stap, niet per endpoint

`tasks.execute` staat niet als gevoelig in het register, en dat is geen slordigheid. Of er
bevestigd moet worden hangt af van de skill: één haalt het weer op, de volgende publiceert
een video. Het endpoint kijkt daarom naar de stappen en vraagt alleen een bevestiging als er
gevoelig gereedschap bij zit. Dat loopt via dezelfde `confirmation_requests` als de rest —
er is geen tweede, zwakkere weg. Zie [skills.md](skills.md).

### En een herkende stem?

Die telt als aanmelding, niet als bevestiging. Sterker nog: kwam je binnen via een
stemherkenning die **zwakker was dan `GANZ_VOICE_STRONG_THRESHOLD`**, dan kun je met dat token
helemaal niets bevestigen — ook niet met de juiste pincode. Zie [voice.md](voice.md).

Een inlogtoken kan nooit als bevestiging dienen: er zit een `purpose` in het token en
die wordt gecontroleerd. Anders zou de extra drempel een formaliteit zijn — en zou wie
even een openstaande laptop tegenkomt je rekeningen kunnen loskoppelen.

## Sleutels en tokens

- Tokens van banken, exchanges en platforms staan **versleuteld** in de database
  (Fernet, sleutel uit `GANZ_ENCRYPTION_KEY`).
- Ze gaan **nooit** mee in een API-antwoord. De accountlijst bevat geen veld
  `credentials`.
- Ze komen **nooit** in het activiteitenlog.
- Er staat geen enkele sleutel in de repository. `.env` staat in `.gitignore`.
- In productie weigert Ganz te starten op de ontwikkelsleutels. Een standaardsleutel
  zou betekenen dat versleutelde tokens door iedereen te lezen zijn.

Wissel je `GANZ_ENCRYPTION_KEY`, dan zijn de bestaande tokens onleesbaar. Ganz crasht
daar niet op: het account krijgt de status "opnieuw koppelen".

## Het activiteitenlog

Elke mutatie wordt gelogd: wie, wat, wanneer. Maar de context gaat eerst door een
schoonmaakstap die alles weghaalt wat lijkt op een sleutel, token, wachtwoord, pincode,
rekeningnummer — of een bedrag.

Dat laatste is bewust. Het log mag vertellen dát een rekening is gekoppeld, niet hoeveel
erop staat. Logbestanden belanden in back-ups en foutmeldingen, en daar hoort je saldo
niet in thuis.

## Wachtwoorden

Opgeslagen als pbkdf2-sha256 via passlib. Bij een verkeerd wachtwoord én bij een
onbekend e-mailadres komt exact dezelfde melding terug, zodat je niet kunt aftasten
welke accounts bestaan.

## Alleen je eigen gegevens

Elke service controleert of een rij van de ingelogde gebruiker is. Voor "bestaat niet"
en "is niet van jou" komt dezelfde 404 terug — anders kun je via de foutmelding
afleiden welke ID's bestaan.

## Read-only waar het kan

De financiële providers zijn read-only. Ganz hoeft nooit geld te verplaatsen, dus kan
hij het ook niet. Gebruik bij een exchange of broker altijd een sleutel zonder
handels- of opnamerechten.
