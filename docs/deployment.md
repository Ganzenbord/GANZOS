# Draaien en uitleveren

Ganz bestaat uit drie delen die los van elkaar starten: een backend, een scherm, en een
desktopschil die dat scherm in een venster zet. Ze weten van elkaar via één adres.

## De backend

```bash
cd backend
uvicorn app.main:app --port 8000
```

Dit is het enige deel dat een database nodig heeft. Start hem eerst; de rest sluit erop aan.

## Het scherm

**Tijdens het bouwen:**

```bash
cd frontend
npm run dev          # http://localhost:5173
```

Vite stuurt `/api` door naar `http://127.0.0.1:8000`, dus je hebt geen CORS-gedoe.

**Als gebouwd bestand:**

```bash
npm run build        # levert frontend/dist/
```

Zet die map achter een webserver, of laat de desktopschil hem openen.

## De desktopschil

```bash
npm run app          # opent het gebouwde scherm
npm run app:dev      # opent het scherm van de dev-server (GANZ_DEV=1)
```

### De schil start géén backend

Dat deed hij eerder wel: stond er een virtualomgeving in `backend/`, dan startte hij daar
uvicorn in. Dat leek handig maar maakt de schil verantwoordelijk voor iets wat hij niet kan
overzien — welke Python, welke database, of de migraties gedraaid zijn. En als het misging,
zag je dat nergens.

Nu zoekt hij een draaiende Ganz op het ingestelde adres en toont het scherm. Is die er niet,
dan komt er een pagina die zegt wát er scheelt, met het adres erbij en een knop om het
opnieuw te proberen. Nooit een wit venster.

De schil onderscheidt drie dingen, want ze vragen om verschillende stappen van jou:

| Wat er staat | Wat er aan de hand is |
| --- | --- |
| "Er luistert niets op dit adres" | de backend draait niet |
| "Geen verbinding met de database" | de backend draait, PostgreSQL niet |
| "Het scherm is nog niet gebouwd" | `npm run build:frontend` ontbreekt |

### Waar de backend draait

Drie plekken, in deze volgorde:

1. `GANZ_API_URL` in de omgeving — overrulet alles, zonder het bewaarde adres te wissen
2. wat er bewaard is, via het veld op de uitlegpagina
3. `http://localhost:8000`

Het bewaarde adres staat in `settings.json` in de gebruikersmap van het besturingssysteem
(macOS: `~/Library/Application Support/Ganz`, Windows: `%APPDATA%\Ganz`, Linux:
`~/.config/Ganz`). Eén regel tekst, met opzet: als de app niet meer opstart moet je hem met
de hand kunnen aanpassen.

## Hoe het eruitziet

De schil zelf is op alle drie de systemen hetzelfde programma; alleen het venster eromheen
komt van het besturingssysteem — op Windows een strakke balk met een kruisje rechts, op macOS
drie rondjes links. Wat erin staat is identiek:

![De desktopschil met het command center](afbeeldingen/desktop-app.png)

Draait er geen backend, dan komt er geen leeg venster maar dit:

![De uitlegpagina als de backend niet draait](afbeeldingen/desktop-offline.png)

En dezelfde Ganz op een telefoon:

| Het dashboard | Achter "Meer" |
| --- | --- |
| ![Ganz op een telefoon](afbeeldingen/telefoon-dashboard.png) | ![Het menu Meer](afbeeldingen/telefoon-meer.png) |

## Een installeerbaar programma bouwen

```bash
npm run app:build          # voor het systeem waar je op zit
npm run app:build:win      # Windows (nsis-installer)
npm run app:build:mac      # macOS (dmg en zip)
npm run app:build:linux    # Linux (AppImage en deb)
```

Het resultaat komt in `dist/` (de electron-builder-map, niet `frontend/dist`).

Het pictogram komt uit `assets/icon.png` — het aangeleverde logo met de gans, met de witte
rand eraf zodat het op een taakbalk een vol vierkant is in plaats van een witte tegel. Hoe
dat gemaakt is staat in `assets/LEESMIJ.md`, met het bronbestand ernaast. Eén bestand van 1024 × 1024; electron-builder
maakt daar zelf een `.icns` (macOS) en een `.ico` (Windows) van.

De map heet `assets` en niet `build`, wat bij electron-builder gebruikelijker is: `build/`
staat in `.gitignore` (daar zet Node zijn bouwsel neer), en dan zou het pictogram bij het
klonen ontbreken zonder dat je het merkt — tot de app met het standaardpictogram van
Electron verschijnt.

### Op welke computer bouw je wat

**Bouw voor Windows op Windows en voor macOS op een Mac** — dan is `npm run app:build`
genoeg en klopt alles. Moet het toch vanaf een andere computer, dan is dit wat wel en niet
kan; het is uitgeprobeerd, niet gegokt:

| Wat je wilt | Vanaf Linux | Hoe |
| --- | --- | --- |
| Windows, als map in een zip | **lukt** | `npx electron-builder --win zip -c.win.signAndEditExecutable=false` |
| Windows, als installer (nsis) | lukt niet | vraagt om **wine, inclusief de 32-bits helft**; zonder dat strandt het op het maken van de uninstaller |
| macOS, als app in een zip | **lukt** | `npx electron-builder --mac zip -c.mac.identity=null` |
| macOS, als dmg | lukt niet | vraagt om de gereedschappen van macOS zelf |

Die `signAndEditExecutable=false` slaat de stap over die het pictogram en het versienummer
ín `Ganz.exe` zet — dat gereedschap is 32-bits Windows. De app werkt gewoon, maar draag je
hem zo over, dan staat er het standaardpictogram van Electron op. Bouw je op Windows, laat
die schakelaar dan weg.

Een zip is voor eigen gebruik prima: uitpakken en `Ganz.exe` (of `Ganz.app`) starten. Er is
dan alleen geen snelkoppeling in het startmenu.

### Of laat GitHub het doen

Heb je maar één van de twee computers, dan hoef je er niet omheen te werken: GitHub heeft
een Windows-machine én een Mac staan. In `.github/workflows/desktop.yml` staat een opdracht
die daar allebei de versies bouwt — met installer, met pictogram, precies zoals het hoort.

1. Ga in de repo naar het tabblad **Actions** → *Desktop-app bouwen* → **Run workflow**.
2. Wacht een minuut of tien.
3. Onderaan die pagina staan de bestanden onder **Artifacts**.

> De knop **Run workflow** verschijnt pas als dit bestand op de hoofdtak (`main`) staat; zo
> werkt GitHub nu eenmaal. Staat het nog op een zijtak, zet er dan een versielabel op
> (`git tag v2.0.1 && git push --tags`) — dan draait hij ook, en komen de bestanden
> bovendien onder **Releases** te staan met een vaste downloadlink.

Deze builds zijn **niet ondertekend**. Zonder certificaat waarschuwt macOS (Gatekeeper) en
Windows (SmartScreen) bij het openen dat de maker onbekend is. Voor eigen gebruik kun je dat
toestaan; wil je het breder verspreiden, dan is code-signing de volgende stap — en dat kost
geld per jaar.

Wat je in de praktijk tegenkomt:

- **Windows** zegt "Windows heeft uw pc beveiligd". Klik op *Meer informatie* en dan op
  *Toch uitvoeren*.
- **macOS** zegt bij een app die je gedownload hebt dat hij "beschadigd is en naar de
  prullenmand moet". Hij is niet beschadigd; hij is niet ondertekend. Klik hem met de
  rechtermuisknop aan en kies *Open*, of haal het downloadmerkje eraf:

  ```bash
  xattr -dr com.apple.quarantine /Applications/Ganz.app
  ```

## De schil nalopen zonder venster

```bash
npm run test:shell
```

Controleert waar de backend gezocht wordt en wat de schil zegt als die er niet is. Electron
zelf heeft een scherm nodig en wordt daarom niet geladen; de twee stukken die echt
beslissingen nemen staan met opzet in aparte modules (`electron/settings.cjs` en
`electron/backend.cjs`).

## Wat er nog niet is

- **Geen automatische updates.** Een nieuwe versie installeer je zelf. (De bestanden die
  GitHub bouwt hebben wel al een `latest-*.yml` en een blockmap, dus de leidingen voor
  automatisch bijwerken liggen er — er is alleen nog geen plek waar ze vandaan komen.)
- **Geen ondertekende builds.** Zie hierboven.
- **De backend start niet mee als dienst.** Op een machine die altijd aanstaat wil je hem als
  systemd-unit of launchd-job draaien; dat staat er nog niet.
