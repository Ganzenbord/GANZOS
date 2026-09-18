# Beveiliging

## Tiers

Tier 1 is de eigenaar en mag alles. Hoe hoger het nummer, hoe minder rechten. Je hebt
een recht als je tier kleiner of gelijk is aan het maximum van dat recht.

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
| `finance.read` | **1** | |
| `finance.manage` | **1** | **ja** |
| `upload.execute` | **1** | **ja** |
| `integrations.manage` | **1** | **ja** |

Finance is tier 1. Een upload daadwerkelijk uitvoeren ook: dat zet iets in gang naar
buiten toe.

Het register staat in `backend/app/core/permissions.py` — één lijst, zodat je in één oogopslag
ziet wie wat mag.

## Tweede bevestiging

Voor gevoelige handelingen is een inlogtoken niet genoeg. Je haalt eerst een
bevestigingstoken op:

```
POST /api/auth/confirm    { "password": "..." }
```

Dat token is vijf minuten geldig en gaat mee in de header `X-Ganz-Confirmation`.
Ontbreekt hij, dan antwoordt de API met 428.

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
