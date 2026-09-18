# YouTube

Ganz kan drie dingen met YouTube: je cijfers lezen, je geschatte omzet ophalen, en een
video publiceren. Het eerste kan met een API-sleutel; de andere twee niet — daarvoor moet
je Ganz eenmalig toestemming geven namens je Google-account.

## Wat je eenmalig in Google moet doen

Dit is het vervelendste deel en het is niet te omzeilen: Google geeft geen toegang tot een
kanaal zonder een eigen project. Het kost een kwartier en je doet het één keer.

1. Ga naar [console.cloud.google.com](https://console.cloud.google.com) en maak een project
   (een naam verzinnen is genoeg).
2. Zet bij **APIs & Services → Library** twee dingen aan: *YouTube Data API v3* en
   *YouTube Analytics API*.
3. Vul bij **Google Auth Platform → Branding** een naam en je e-mailadres in.
4. Zet bij **Audience** je eigen Google-account neer als **testgebruiker**. Sla je dit over,
   dan weigert Google met `403 access_denied` — het scherm staat namelijk op "Testing".
5. Maak bij **Credentials → Create credentials → OAuth client ID** een client van het type
   **Web application**, en zet daar als *Authorized redirect URI* exact dit adres neer:

   ```
   http://localhost:8000/api/youtube/oauth/callback
   ```

   Lettergelijk hetzelfde als `GANZ_YOUTUBE_REDIRECT_URI` hieronder. Eén schuine streep
   verschil en Google weigert met `redirect_uri_mismatch`.
6. Zet de client-ID en het secret in `backend/.env`.

> **Let op:** zolang het scherm op "Testing" staat, vervalt de toestemming na zeven dagen en
> moet je opnieuw koppelen. Wil je daar vanaf, dan moet de app door Google's verificatie —
> een traject dat voor een app die alleen jijzelf gebruikt niet de moeite is.

## Instellingen

```bash
GANZ_YOUTUBE_CLIENT_ID=...apps.googleusercontent.com
GANZ_YOUTUBE_CLIENT_SECRET=...
GANZ_YOUTUBE_REDIRECT_URI=http://localhost:8000/api/youtube/oauth/callback
GANZ_YOUTUBE_UPLOAD_PRIVACY=private
GANZ_YOUTUBE_VIDEO_DIR=/pad/naar/je/videos
```

`GANZ_YOUTUBE_VIDEO_DIR` is leeg totdat je hem invult, en dan staat uploaden uit. Dat is
geen slordigheid: zie [Waarom uploaden aan één map vastzit](#waarom-uploaden-aan-één-map-vastzit).

## Koppelen

In de app: **YouTube-kanalen → Koppel met YouTube**. Dat vraagt eerst om je wachtwoord of
pincode (het is een gevoelige handeling), en opent dan een tabblad bij Google. Geef daar
toestemming en klik in Ganz op **Controleer**.

Het tabblad is met opzet een echt tabblad van je eigen browser: je logt daar in bij Google,
en dat hoort niet in een venster van Ganz te gebeuren.

Waar Ganz toestemming voor vraagt, en nergens anders voor:

| Scope | Waarvoor |
| --- | --- |
| `youtube.readonly` | je kanaal en je statistieken lezen |
| `youtube.upload` | een video uploaden |
| `yt-analytics-monetary.readonly` | de geschatte omzet |

Bewust **niet** `youtube.force-ssl`: die mag ook video's en reacties verwijderen, en Ganz
hoeft nooit iets weg te gooien.

### Wat er onder water gebeurt

- Google stuurt na je toestemming een **code** terug naar `/api/youtube/oauth/callback`.
  Dat eindpunt heeft met opzet geen inlogcontrole — Google roept het aan, niet de app, dus
  er is geen `Authorization`-header. Wat daarvoor in de plaats komt is de **state**: een
  door Ganz ondertekend token dat zegt van wie het verzoek kwam en dat na een kwartier
  vervalt. Zonder geldige state gebeurt er niets.
- De code wordt omgewisseld voor een toegangstoken (één uur geldig) en een
  **vernieuwingstoken** (blijft geldig). Allebei gaan ze **versleuteld** de database in, bij
  het kanaal. Ze komen nooit in een API-antwoord en nooit in het logboek.
- Geeft Google geen vernieuwingstoken, dan weigert Ganz de koppeling met een uitleg. Dat
  gebeurt als je dit Google-account al eerder toestemming gaf. Trek de toegang van Ganz in
  bij je Google-account (Beveiliging → Apps van derden) en koppel opnieuw. Een koppeling die
  na een uur stuk is, is erger dan geen koppeling: je merkt het pas als je hem nodig hebt.
- Het toegangstoken wordt twee minuten vóór het verloopt vernieuwd, en het vernieuwde token
  gaat meteen weer versleuteld de database in. Zonder dat laatste vraagt elke aanroep een
  nieuw token aan en loop je tegen de limieten van Google aan.

### Losmaken

**Koppeling losmaken** gooit de tokens weg. Het kanaal en de gemeten cijfers blijven staan:
wat je gemeten hebt, blijf je zien. Alleen de sleutel naar Google is weg.

## Uploaden

Uploaden loopt via een skill, niet via een los knopje. Een stap ziet er zo uit:

```json
{
  "tool": "youtube.upload",
  "file": "aflevering-12.mp4",
  "title": "Aflevering 12",
  "description": "Waar het deze week over gaat",
  "tags": ["podcast", "aflevering"],
  "privacy": "private"
}
```

`file` en `title` zijn verplicht; de rest niet. Ontbreekt er een, dan wordt de skill **niet
opgeslagen** — dat merk je dus bij het opslaan en niet halverwege het uitvoeren, als je al
bevestigd hebt dat er gepubliceerd mag worden.

`youtube.upload` is het eerste gereedschap dat écht iets doet. Het is gevoelig, dus er komt
een tweede bevestiging aan te pas voordat een taak met deze stap draait.

Een upload gaat in twee stappen (dat schrijft Google voor bij grote bestanden, en het komt
goed uit): eerst de titel en de omschrijving, dan pas de bytes. Een afgekeurde titel mislukt
zo vóórdat er een gigabyte over de lijn is gegaan. Het bestand gaat in blokken van een
megabyte de deur uit en staat nooit in zijn geheel in het geheugen.

### Standaard privé

`GANZ_YOUTUBE_UPLOAD_PRIVACY` staat op `private`, en dat is een keuze: een verkeerde upload
die meteen openbaar is, is niet meer terug te nemen — mensen hebben hem dan al gezien. Zet
hem desnoods per stap op `unlisted` of `public`.

### Waarom uploaden aan één map vastzit

Een skill noemt alleen een bestandsnaam, en die wordt opgezocht in `GANZ_YOUTUBE_VIDEO_DIR`.
Zou Ganz elk pad accepteren, dan is `upload vakantie.mp4` hetzelfde soort verzoek als
`upload ../../.ssh/id_rsa` — en dan zet één ongelukkige skill je sleutels op internet.

Het pad wordt uitgerekend en daarna gecontroleerd, dus `..` helpt niet en een symbolische
link naar buiten ook niet. Staat er geen map ingesteld, dan staat uploaden gewoon uit.

## Wat er misgaat en wat het betekent

| Melding | Wat eraan te doen |
| --- | --- |
| `redirect_uri_mismatch` | Het adres in de Google-console is niet lettergelijk hetzelfde als `GANZ_YOUTUBE_REDIRECT_URI`. |
| `403 access_denied` | Je eigen account staat nog niet als testgebruiker bij *Audience*. |
| "Google gaf geen vernieuwingstoken" | Trek de toegang in bij je Google-account en koppel opnieuw. |
| "De YouTube-koppeling is verlopen" | Het vernieuwen is afgewezen (na zeven dagen in "Testing", of je hebt de toegang ingetrokken). Koppel opnieuw. |
| "Uploaden staat uit" | `GANZ_YOUTUBE_VIDEO_DIR` is nog leeg. |
| "Dat bestand staat buiten de videomap" | Zet de video in die map; een pad eromheen wordt niet geaccepteerd. |

## Wat er nog niet is

- **Een upload uit het uploadschema gaat nog niet vanzelf de deur uit.** Het schema plant en
  telt af; het publiceren doe je via een skill. De twee aan elkaar knopen is de volgende stap.
- **Een afgebroken upload begint opnieuw.** Google's resumable upload kán hervatten vanaf het
  punt waar het misging; Ganz doet dat nog niet.
- **Eén kanaal per gebruiker.** Heb je meerdere kanalen onder één Google-account, dan pakt
  Ganz het kanaal dat Google als eerste teruggeeft.
