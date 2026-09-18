# Ganz als server voor meerdere mensen

Ganz draait op één machine bij je thuis of in een datacenter, en jij en je broer komen er
allebei bij vanaf je laptop, je pc en je telefoon. Dit document zegt hoe dat in elkaar zit
en waarom het zo is, en het benoemt wat er mis kan gaan.

Eén zin die de rest verklaart: **Ganz beheert je accounts.** Hij heeft levende
toegangssleutels voor YouTube, Instagram en TikTok, en hij kan namens jou publiceren. Wie
bij Ganz kan, kan bij die accounts. Dat maakt van een gewone webapplicatie iets waar je
strenger mee omgaat dan met een takenlijstje.

---

## 1. Het netwerk

```
   Jouw laptop            Telefoon van je broer          Zijn pc
   ┌────────────┐         ┌────────────────┐         ┌────────────┐
   │ Electron   │         │ browser        │         │ Electron   │
   │ + Tailscale│         │ + Tailscale-app│         │ + Tailscale│
   └─────┬──────┘         └────────┬───────┘         └─────┬──────┘
         │                         │                       │
         └──────────── WireGuard (versleuteld) ────────────┘
                                   │
                  ╔════════════════╧════════════════════════════════╗
                  ║  De machine waar Ganz op draait                 ║
                  ║                                                 ║
                  ║   tailscale0  100.x.y.z   ← enige ingang        ║
                  ║        │                                        ║
                  ║   ┌────┴─────┐   :443                           ║
                  ║   │  Caddy   │  certificaat van Tailscale       ║
                  ║   └──┬────┬──┘                                  ║
                  ║      │    │                                     ║
                  ║  /api│    │ al het andere                       ║
                  ║      │    └──────► frontend/dist (bestanden)    ║
                  ║      ▼                                          ║
                  ║  ┌────────────┐      ┌──────────────┐           ║
                  ║  │  FastAPI   │─────►│  PostgreSQL  │           ║
                  ║  │  uvicorn   │      │  (geen poort │           ║
                  ║  └─────┬──────┘      │   naar buiten)│          ║
                  ║        │             └──────────────┘           ║
                  ║        │ /videos (read-only)                    ║
                  ╚════════╪════════════════════════════════════════╝
                           │
                           ▼  uitgaand, over gewoon internet
                YouTube · Instagram · TikTok · Higgsfield · je bank
```

Let op wat er **niet** staat: er is geen lijn van internet naar de machine toe. Alles wat
Ganz doet is uitgaand. Binnenkomen kan alleen via de tailnet.

### Waarom Caddy en niet Nginx

Caddy. Twee redenen die er hier toe doen:

- **Certificaten zonder plakwerk.** Nginx zelf doet niets met certificaten; daar komt
  certbot bij, plus een vernieuwingstaak, plus een haak die Nginx herlaadt. Drie bewegende
  delen die stilletjes kunnen stoppen, en dat merk je pas als je browser gaat klagen. Caddy
  regelt het zelf, en in deze opzet wijs je hem simpelweg het certificaat van Tailscale aan.
- **De configuratie past op één scherm.** Zie `deploy/Caddyfile`. Wat Nginx daar tegenover
  zet — fijnmazige tuning voor duizenden verbindingen — heb je met twee gebruikers niet
  nodig.

### Waarom er tóch een VPN overheen gaat, en waarom Tailscale

**Ja, doen. Tailscale, en dan helemaal niets publiek.**

Een inlogscherm op internet is een inlogscherm dat continu geprobeerd wordt. Dat hoeft niet
erg te zijn — een goed wachtwoord houdt stand — maar de vraag is wat er gebeurt als het één
keer wél misgaat. Hier is het antwoord: iemand publiceert video's op jouw kanaal, ziet je
vermogen, en heeft een koppeling met je Google-account. Dat is geen "we zetten het
wachtwoord terug", dat is een middag bellen met YouTube.

Met Tailscale bestaat het inlogscherm niet voor wie niet op de tailnet zit. Een aanvaller
moet eerst een van jullie apparaten in handen krijgen. Het wachtwoord is dan de tweede
drempel geworden in plaats van de eerste.

**Wat het kost, eerlijk gezegd:** op elk apparaat moet de Tailscale-app staan en aanstaan.
Voor Windows, macOS, iOS en Android is dat een app uit de winkel en één keer inloggen. Staat
hij uit, dan is Ganz niet bereikbaar — dat is precies de bedoeling, maar het betekent wel
dat je het een keer vergeet en even niet snapt waarom het niet werkt.

**Tailscale en niet kaal WireGuard:** WireGuard geeft dezelfde versleuteling, maar je regelt
zelf de sleutels, de adressen en het doorkomen door routers. Tailscale is WireGuard met dat
werk eraf, plus twee dingen die je hier echt wilt: een apparaat toevoegen gaat via een login,
en een apparaat intrekken gaat met één klik in een webscherm. Bij kaal WireGuard is
"telefoon kwijt" een avondje configuratiebestanden bijwerken.

**Het niet-voor-de-hand-liggende punt: de YouTube-koppeling werkt gewoon.** Je zou denken
dat Google bij `/api/youtube/oauth/callback` moet kunnen komen, maar dat is niet zo: Google
stuurt *jouw browser* daarheen, niet zijn eigen servers. Zit die browser op de tailnet, dan
komt hij er. Zet het adres van de tailnet in de Google Cloud-console en klaar. Er hoeft dus
geen enkel gaatje open.

---

## 2. Welke machine

De vraag is niet "hoeveel gebruikers" — twee mensen doen niets. De vraag is **wat er op die
machine gebeurt**, en dat hangt aan één ding: waar de video's gemaakt worden.

| Als... | dan is de zwaarte... |
| --- | --- |
| Higgsfield (of een andere dienst) rendert, Ganz stuurt alleen aan en uploadt | licht: een gewone VPS volstaat |
| Ganz zelf video's rendert of modellen draait | zwaar: een GPU, en dat is geen VPS meer |

Ga uit van het eerste, want dat is wat er nu in de code zit. Dan is dit de ondergrens:

| | Minimum | Waarom |
| --- | --- | --- |
| **RAM** | 8 GB | PostgreSQL ~1 GB, FastAPI ~300 MB, en dan het stille stuk: het stemmodel en het skill-model draaien allebei op PyTorch, en die staan samen al gauw op 2–3 GB. Met 4 GB draait het tot je ze allebei tegelijk aanraakt. |
| **vCPU** | 4 | Stemherkenning en het matchen van skills zijn korte rekenpieken. Met 2 vCPU staat de rest van Ganz te wachten terwijl er iemand praat. |
| **Schijf** | 80 GB, SSD | Database en logboek zijn klein. Wat plaats kost zijn de video's: reken op 1 GB per tien minuten 1080p, en je wilt er een stuk of tien tegelijk kwijt kunnen. |
| **Upload** | 50 Mbit, zonder datalimiet | Publiceren is uploaden. Een video van 1 GB duurt op 10 Mbit veertien minuten; op 50 Mbit drie. En let op de maandlimiet: veel goedkope VPS'en knijpen na een paar terabyte. |

**Om te bepalen of jouw huidige VPS voldoet, heb ik precies dit nodig:**

1. RAM, aantal vCPU en schijfruimte.
2. Uploadsnelheid en of er een maandelijkse datalimiet is.
3. Of het een echte VM is (KVM) of een container (OpenVZ/LXC) — in een container werkt Docker
   vaak niet of half.
4. Of Higgsfield het renderen doet, of dat je dat op termijn zelf wilt draaien.

Met 1 en 2 kan ik het meteen zeggen. Punt 4 is degene die het antwoord kan omgooien: zelf
renderen betekent een machine met een GPU, en daar is een VPS zelden geschikt voor.

---

## 3. Inloggen en rechten

### Twee tokens, met een verschillende taak

| | Inlogtoken | Vernieuwingstoken |
| --- | --- | --- |
| Wat het is | een JWT, ondertekend | 32 bytes toeval |
| Geldig | 15 minuten | 60 dagen, en de klok begint opnieuw bij elk gebruik |
| Waar het staat | nergens op de server | als afdruk in `user_sessions` |
| In te trekken | nee | ja, per apparaat |
| Gaat mee bij | elk verzoek | alleen `/auth/refresh` |

Dat onderscheid is de hele truc. Een token dat je bij elk verzoek meestuurt, wil je kort
geldig hebben, want je kunt het niet terughalen. Een token dat lang geldig is, wil je ergens
hebben staan, want dan kun je het doorstrepen. Beide willen kan niet, dus zijn het er twee.

Voor de gebruiker is dit onzichtbaar: de app vernieuwt zelf zodra een verzoek 401 zegt, en
één keer inloggen is genoeg tot je twee maanden niets doet.

### Een gestolen vernieuwingstoken herkennen

Bij elk gebruik komt er een nieuw vernieuwingstoken en schuift het oude opzij. Komt dat oude
daarna alsnog langs, dan bestaat er een kopie — en welke van de twee partijen de echte is,
valt niet te zeggen. Dus gaan ze er allebei uit en moet iedereen opnieuw inloggen. Er komt
een regel in het activiteitenlog (`SESSION_REUSE_DETECTED`).

Dit is het enige moment waarop je diefstal van een token kúnt zien. Vandaar dat het niet bij
een waarschuwing blijft.

### Het permissiemodel

Twee lagen, en de tweede is de reden dat het uitbreidbaar is.

**Laag 1 — de tier.** Elke gebruiker heeft een nummer: 1 is de eigenaar en mag alles, hoger
is minder. Het register in `backend/app/core/permissions.py` zegt per recht vanaf welke tier
je het hebt. Endpoints bevatten geen eigen regels; ze noemen alleen waar ze over gaan
(`require_permission("upload.execute")`).

**Laag 2 — uitzonderingen per persoon.** Een tier is een rechte lijn: tier 2 mag alles wat
tier 3 mag, plus meer. Maar "mag alleen de lampen, de mail en het weer" is geen stuk van die
lijn — dat is een greep eruit. Zonder een tweede laag zou zo iemand een tier moeten krijgen
die hem meteen ook het uploadschema, de skills en de systeemmonitor laat zien.

Dus: `user_permissions` met één rij per uitzondering. `granted=true` geeft een recht dat de
tier niet geeft, `granted=false` neemt er een af die de tier wel geeft. Wat iemand werkelijk
mag, is `effective_permissions(tier, uitzonderingen)` — en dat is ook wat `/auth/me`
teruggeeft, zodat het scherm precies verbergt wat toch niet werkt.

Zo ziet jullie opzet eruit:

| Wie | tier | uitzonderingen |
| --- | --- | --- |
| jij | 1 | geen |
| je broer | 1 of 2 | geen (zie §4) |
| iemand later, alleen smart home + mail + weer | **geen** (`NULL`) | drie rijen met `granted=true` |
| een huisgenoot die alles mag zien behalve het geld | 2 | `finance.read` op `false` |

`tier = NULL` betekent nu: **geen rechten uit een tier**. Heeft zo iemand ook geen
uitzonderingen, dan mag hij nog steeds niets — precies als voorheen. Dat is belangrijk voor
de stem: iemand kan herkend worden ("dag Piet") zonder ergens binnen te komen.

### De tabellen

```sql
users
  id, email (uniek), display_name, password_hash,
  tier int NULL,            -- 1..4, of NULL = geen rechten uit een tier
  active bool,              -- uitgezet account; iets anders dan tier NULL
  pin_hash, pin_updated_at  -- tweede bevestiging, gehasht

user_sessions                       -- één rij per ingelogd apparaat
  id, user_id → users(id) CASCADE
  refresh_hash      char(64) uniek  -- sha256 van het token, nooit het token zelf
  previous_hash     char(64)        -- om hergebruik te zien
  device_name, user_agent, ip_address
  created_at, last_used_at, expires_at
  revoked_at, revoked_reason        -- logout | ingetrokken | hergebruikt | verlopen

user_permissions                    -- uitzonderingen op de tier
  id, user_id → users(id) CASCADE
  permission_key    varchar(80)     -- moet in het register bestaan
  granted           bool            -- true = erbij, false = eraf
  note              varchar(200)    -- waarom; over een jaar weet niemand het meer
  UNIQUE (user_id, permission_key)

voice_profiles                      -- bestond al
  id, user_id → users(id) CASCADE, label, embedding (JSON), sample_count

confirmation_requests               -- bestond al: de tweede bevestiging
  id, user_id, permission_key, method (password|pin), status, attempts,
  expires_at, confirmed_at, origin (password|voice), origin_confidence
```

### Waar de stem in past

Een stem is een **naamplaatje, geen sleutel**. Concreet:

1. **Een stem hoort bij een account.** `voice_profiles.user_id`. Ganz herkent geen "stemmen"
   in het algemeen; hij herkent Stef of Bram, en daarmee hun rechten.
2. **Een herkende stem levert een inlogtoken op, maar geen sessie.** Dus geen
   vernieuwingstoken, dus na een kwartier is het voorbij. Een opname van je stem is zo
   gemaakt; die mag nooit twee maanden toegang worden.
3. **Een zwakke herkenning telt niet voor gevoelige dingen.** Kwam je binnen met een
   gelijkenis onder `GANZ_VOICE_STRONG_THRESHOLD`, dan kun je met dat token niets
   bevestigen — ook niet met de juiste pincode. Het staat in de bevestigingsrij
   (`origin`, `origin_confidence`) en wordt daar gecontroleerd.
4. **Gevoelige handelingen vragen altijd een tweede stap.** Publiceren, geld, accounts
   koppelen: daar komt je pincode of wachtwoord bij, hoe goed de herkenning ook was.
5. **Een onbekende stem: Ganz zegt dat hij je niet kent en doet verder niets.** Geen account,
   geen terugval op "dan maar de eigenaar". Er komt een regel `VOICE_UNKNOWN` in het log, en
   dat is alles. Een bekend gezicht zonder tier krijgt "dag Piet, maar je hebt geen toegang".

Waarom zo streng: stemherkenning geeft een cijfer tussen -1 en 1, geen ja of nee. Waar je de
grens ook legt, iemand die op je lijkt komt af en toe net erboven. Dat is te overzien
zolang een stem alleen bepaalt wát Ganz zegt, en nooit of hij iets onomkeerbaars doet.

---

## 4. Samen of apart

**Advies: één installatie, één gedeelde omgeving, per rij een eigenaar.** Geen aparte
schema's per persoon, geen tweede installatie.

Waarom niet gescheiden: het doel is samen kanalen draaien. Een gedeeld uploadschema en
gedeelde kanaalcijfers zijn de reden dat Ganz bestaat. Zet je dat in twee werelden, dan is
elk gezamenlijk overzicht een koppeling tussen twee databases — alle kosten, geen opbrengst.
En het werkt averechts voor de toekomst: iemand die alleen het weer mag zien heeft *minder*
nodig, geen eigen wereld.

Waarom niet schema-per-gebruiker (multi-tenancy): dat verdubbelt elke migratie en levert bij
twee mensen niets op. Het is het antwoord op "verschillende klanten mogen elkaars gegevens
nooit zien". Jullie zijn broers die samen kanalen draaien; dat is een ander probleem.

**Wat er in de database staat:** elke rij heeft een `user_id`, en elke service filtert
daarop. Dat is al zo en het is consequent gedaan — voor "bestaat niet" en "is niet van jou"
komt overal dezelfde 404 terug, zodat je via foutmeldingen geen ID's kunt aftasten.

**Wat er nog niet is, en wat ik zou doen:** op dit moment ziet jouw broer jouw kanalen niet.
Voor een gedeelde contentpijplijn wil je dat wel. De kleinst mogelijke stap is één kolom:

```sql
ALTER TABLE social_channels ADD COLUMN shared boolean NOT NULL DEFAULT false;
-- lezen wordt: WHERE user_id = :ik OR shared
-- wijzigen blijft: WHERE user_id = :ik
```

Uploads hangen aan een kanaal en erven het vanzelf. Finance blijft buiten schot — dat is
tier 1 en privé, en dat hoort zo. Dit staat nog niet in de code: het is een wijziging aan
het datamodel die zijn eigen ronde verdient, en het is ook de enige beslissing hier waarvan
ik eerst van jullie wil horen *wat* er precies gedeeld moet worden. Kanalen en uploads, ja.
Skills ook? To-do's niet, denk ik.

---

## 5. Draaien en bijwerken

### Hoe het draait

Docker Compose, met systemd eromheen zodat het na een herstart vanzelf terugkomt. Alles
staat in `deploy/`:

| Bestand | Wat het doet |
| --- | --- |
| `Dockerfile` | de backend, als niet-root gebruiker, met `--proxy-headers` zodat het adres van de bezoeker klopt |
| `docker-compose.yml` | database, backend en Caddy; de database heeft geen poort naar buiten |
| `Caddyfile` | `/api` naar de backend, de rest is het gebouwde scherm |
| `ganz.service` | systemd-unit die Compose start en stopt |
| `ganz.env.example` | alle sleutels die je moet invullen, met uitleg |

Waarom Compose en niet alles los onder systemd: de backend heeft een database nodig die al
draait, de goede netwerknaam, en een map die read-only is aangekoppeld. Dat in losse units
regelen is drie keer hetzelfde wiel.

### Bijwerken zonder dat iemand het merkt

De eerlijke versie: je hebt geen tweede machine, dus je krijgt geen nul seconden. Wat je
krijgt is **een paar seconden, op een moment dat je zelf kiest, waarin de app een nette
pagina laat zien in plaats van een foutmelding** — de desktopschil heeft daar al een scherm
voor.

De volgorde die dat waarmaakt:

```bash
cd /opt/ganz && git pull
docker compose build api                          # bouwen mag terwijl de oude draait
docker compose run --rm api alembic upgrade head  # migratie eerst
docker compose up -d api caddy                    # daarna pas omzetten
```

Wat dit werkend houdt, is niet de volgorde maar een **regel over migraties**: elke migratie
moet werken met de versie die op dat moment nog draait. Kolom erbij met een `server_default`,
nooit een kolom weggooien in dezelfde ronde als de code die hem gebruikt. Weghalen doe je een
release later, als niets hem meer aanraakt. Dat is de discipline waarmee dit project al is
gebouwd, en het is wat "zonder downtime" in de praktijk betekent.

`--timeout-graceful-shutdown 20` staat in de Dockerfile: een verzoek dat al bezig is — een
upload van een gigabyte bijvoorbeeld — mag aflopen voordat het proces stopt.

### Sleutels

- Alles in **`/etc/ganz/ganz.env`**, rechten `0600`, eigendom van root. systemd leest het met
  `EnvironmentFile=`. Niet in de repository (`.env` staat in `.gitignore`), niet in het image,
  niet in een `docker run -e` op je commandoregel — die belandt in je shellgeschiedenis.
- **Tokens van YouTube en de rest staan versleuteld in de database** (Fernet, sleutel uit
  `GANZ_ENCRYPTION_KEY`). Ze komen in geen enkel API-antwoord voor: er is geen veld waarin ze
  passen, en daar is een test voor.
- **In productie start Ganz niet op de ontwikkelsleutels.** Dat is geen waarschuwing maar een
  weigering.
- **Bewaar `GANZ_ENCRYPTION_KEY` los van je databaseback-up.** Samen in één bestand betekent
  dat één gestolen back-up al je gekoppelde accounts openlegt. Helemaal niet bewaard betekent
  dat een teruggezette back-up onbruikbaar is en je alles opnieuw moet koppelen. Dus: wel
  bewaren, ergens anders.

---

## 6. Wat er mis kan gaan

Op volgorde van hoe erg het is, niet van hoe waarschijnlijk.

| Risico | Waarom het hier erger is dan elders | Wat ertegen gedaan is |
| --- | --- | --- |
| **Iemand komt binnen en publiceert namens jou** | Ganz heeft levende tokens voor je kanalen. Publiceren kun je niet terugnemen — het is gezien. | Geen publieke ingang (Tailscale). Publiceren is `sensitive`: er komt een tweede bevestiging bij, per handeling, met een bevestiging die maar één keer telt. Uploads staan standaard op privé. |
| **Een gestolen vernieuwingstoken** | 60 dagen geldig, en een JWT kun je niet terughalen. | Het token staat als afdruk in de database, is per apparaat in te trekken, en wordt bij elk gebruik vervangen. Komt een oud token terug, dan gaat de hele sessie dicht. |
| **Een gestolen telefoon** | Ingelogd, en misschien met de pincode in het hoofd van de dief. | **Instellingen → Apparaten** laat elk ingelogd apparaat zien en gooit hem er met één knop uit. Daarna werkt zelfs een token dat hij al had niet meer. Doe dat vóór het wachtwoord wijzigen — dat laatste doet namelijk niets met bestaande sessies. |
| **Een back-up die uitlekt** | Daar staat je hele database in, inclusief de versleutelde tokens. | De tokens zijn versleuteld met een sleutel die je apart bewaart. Bewaar je hem ernaast, dan is deze mitigatie er niet. |
| **Een sleutel die via een API-antwoord naar buiten glipt** | Ganz heeft sleutels van je kanalen en van betaalde diensten. Eén veld te veel in een antwoord en ze staan in de netwerkinspecteur van elke browser. | Elk eindpunt heeft een responsemodel met een opgesomde lijst velden, en een test die faalt zodra er een eindpunt zonder zo'n model bij komt. Zie [security.md](security.md). |
| **Een lek in het scherm (XSS)** | De tokens staan in `localStorage`; een vreemd script in de pagina kan ze meenemen. | Het scherm laadt geen enkel script van buiten, en de Content-Security-Policy in de `Caddyfile` legt dat vast: `default-src 'self'`. Zonder die regel is dit het meest onderschatte risico van de hele opzet. |
| **Een skill die een verkeerd bestand uploadt** | Een skill noemt een bestandsnaam, en Ganz mag publiceren. | Uploaden kan alleen uit één ingestelde map, en zonder die instelling helemaal niet. `..` en een symbolische link naar buiten worden geweigerd. De map is read-only aangekoppeld. |
| **Doorproberen van de pincode** | Vier cijfers is tienduizend mogelijkheden — voor een computer geen werk. | Vijf mispogingen per gebruiker binnen een kwartier en het slot gaat erop, ook voor de juiste pincode. |
| **Een nagemaakte of opgenomen stem** | Een stem is geen geheim: hij staat in elke video die je publiceert. | Een stem levert hooguit een kwartier toegang op en nooit een sessie. Een zwakke herkenning kan niets bevestigen. Alles wat onomkeerbaar is, vraagt sowieso je pincode. |
| **De database open naar buiten** | Eén open poort 5432 is de kortste weg naar alles. | Geen `ports:` op de databasedienst; hij bestaat alleen binnen het Compose-netwerk. |
| **Een verkeerd ingestelde CORS** | `allow_origins=["*"]` betekent dat elke website namens jou bij je API kan. | `GANZ_CORS_ORIGINS` blijft leeg: het scherm komt van dezelfde naam als de API, dus er is geen andere herkomst die toegang nodig heeft. |
| **Iemand die je tailnet binnenkomt** | Dan is de buitenste schil weg. | Dan staat het wachtwoord er nog, en de pincode voor alles wat ertoe doet. Zet op je Tailscale-account tweestapsverificatie aan — dat is de deur waar dit allemaal achter hangt. |

Wat er **niet** is, en wat je moet weten:

- **Geen aparte vertraging bij het inloggen.** Onbeperkt wachtwoorden proberen kan, zolang je
  op de tailnet zit. Op een publieke opzet zou dat het eerste zijn wat ik zou toevoegen;
  hier is het de tweede laag.
- **Geen tweestapsverificatie op het inloggen zelf.** De pincode is een tweede stap bij
  handelingen, niet bij het inloggen. Voor deze opzet is de tailnet die eerste factor.
- **Geen automatische back-up.** Zie de implementatiestappen.

---

## 7. Wat er nu moet gebeuren

In deze volgorde. De eerste vier gaan over de machine; de rest staat al in de code.

1. **Stuur me de gegevens uit §2** (RAM, vCPU, schijf, upload, KVM of container, en wie de
   video's rendert). Dan zeg ik of je huidige VPS het doet of niet.
2. **Tailscale op de server**, en daarna op je laptop, je pc en jullie telefoons.
   `tailscale up`, inloggen, klaar. Zet op je Tailscale-account tweestapsverificatie aan.
3. **Een certificaat halen:** `sudo tailscale cert ganz.jouw-tailnet.ts.net`, en leg de twee
   bestanden neer als `ganz.crt` en `ganz.key` in de map uit `GANZ_CERT_DIR`.
4. **`/etc/ganz/ganz.env` invullen** met `deploy/ganz.env.example` als voorbeeld. Drie
   sleutels maak je zelf aan; de opdrachten staan erin.
5. **Starten:**
   ```bash
   sudo cp deploy/ganz.service /etc/systemd/system/
   sudo systemctl daemon-reload && sudo systemctl enable --now ganz
   docker compose run --rm api alembic upgrade head
   ```
6. **Twee accounts maken**, met `python -m scripts.create_user --email ... --name ... --tier 1` in `backend/`. Jij en je broer allebei
   tier 1, of je broer tier 2 als hij niet bij het geld hoeft — dat is jullie afspraak, niet
   de mijne.
7. **Inloggen op elk apparaat.** Elk apparaat komt in *Instellingen → Apparaten* te staan;
   geef ze een naam die je herkent, dan zie je later meteen welke je mist.
8. **Een pincode instellen** bij Instellingen, allebei. Zonder pincode is bevestigen op een
   telefoon je hele wachtwoord intikken.
9. **Stemmen inschrijven**, allebei, in een rustige kamer. Zie [voice.md](voice.md).
10. **YouTube koppelen** met het adres van de tailnet als terugkeeradres. Zie
    [youtube.md](youtube.md).
11. **Je eigen sleutels erin zetten** bij Instellingen → Gekoppelde diensten (Higgsfield,
    en wat er verder bijkomt). Ze staan dan op de server en niet op de computer waar je
    toevallig achter zit — dat is de hele reden dat je dit vanaf je telefoon kunt doen.
12. **Een back-up instellen.** Dagelijks `pg_dump` naar een andere machine, en de
    encryptiesleutel op een derde plek. Dit staat er nog niet en het is het enige punt op
    deze lijst waar ik echt aan zou trekken: zonder back-up is één kapotte schijf het einde
    van alles wat Ganz weet.
13. **Pas als er een derde gebruiker komt:** een tier van `NULL` en een paar rijen in
    `user_permissions`. Er is nog geen scherm om die rijen te beheren — dat gaat nu met de
    hand in de database. Komt er een derde gebruiker aan, zeg het dan, dan bouw ik dat erbij.

---

## Zie ook

- [security.md](security.md) — tiers, de tweede bevestiging, sleutels
- [deployment.md](deployment.md) — de desktopschil en installers bouwen
- [voice.md](voice.md) — wat een stem wel en niet opent
- [youtube.md](youtube.md) — koppelen met Google
