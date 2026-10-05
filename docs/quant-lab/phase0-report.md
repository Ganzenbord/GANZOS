# Quant Lab — Fase 0: lezen en rapporteren

Geen code geschreven. Dit is wat ik in de codebase heb gevonden, wat ik heb kunnen
verifiëren, en wat ik **niet** heb kunnen verifiëren.

Eén ding vooraf, omdat het de rest kleurt: **punt 5 (databronnen) is niet af en kon niet af.**
De netwerkpolicy van deze omgeving laat alleen `docs.claude.com` door; elke kandidaat-bron
is onbereikbaar. Ik heb geen rate limits of prijzen uit mijn hoofd opgeschreven — dat is
precies wat de opdracht verbiedt. Zie §5.

---

## 1. Modules, auth en Postgres-conventies

### Een module registreren

`backend/app/main.py` houdt één tuple bij:

```python
API_MODULES = (auth, dashboard, integrations_api, platform, todos, finance,
               social, uploads, voice, skills, status, youtube)

app.include_router(health.router)                      # buiten het voorvoegsel
for module in API_MODULES:
    app.include_router(module.router, prefix=settings.api_prefix)   # "/api"
```

Een module toevoegen is dus: een bestand `backend/app/api/<naam>.py` met een
`router = APIRouter(prefix="/quant", tags=["quant"])`, plus één regel in `API_MODULES`.
Geen refactor nodig; dat sluit aan op de eis uit sectie 3 van de opdracht.

**Valkuil met precedent.** `app.api.integrations` en `app.integrations` botsten eerder op
naam; dat is opgelost met een alias in de import (`from app.api import integrations as
integrations_api`). Een module `quant` is veilig zolang er geen `app/quant/` naast komt.

Er is een test die faalt als twee routes dezelfde `(methode, pad)` claimen. Dat is er
gekomen nadat één pad per ongeluk twee keer bediend werd en FastAPI stilletjes de eerste
koos.

### Auth

| Laag | Waar | Wat |
| --- | --- | --- |
| Wie ben je | `get_current_user` | Bearer-JWT, 15 minuten geldig, `purpose: access` |
| Sessie | `user_sessions` | vernieuwingstoken 60 dagen, per apparaat intrekbaar, hergebruik van een vervangen token sluit de sessie |
| Mag je dit | `require_permission("key")` | één register van 26 rechten in `app/core/permissions.py`; endpoints bevatten geen eigen regels |
| Uitzondering per persoon | `user_permissions` | `granted=true/false` bovenop de tier |
| Wil je dit nú | `require_confirmation("key")` | alleen voor rechten met `sensitive=True`: wachtwoord of pincode, één bevestiging dekt één handeling, als rij in `confirmation_requests` |

Tiers: 1 = eigenaar, hoger = minder, `NULL` = geen rechten uit een tier.

**Wat dit betekent voor het Quant Lab.** Nieuwe rechten horen in het register, niet als
if-jes in de endpoints. Voorstel (ter goedkeuring, nog niet gebouwd):

| Recht | Tier | `sensitive` |
| --- | --- | --- |
| `quant.read` | 2 | nee |
| `quant.hypothesis.write` | 1 | **ja** — een nieuwe hypothese-versie zet de teller op nul |
| `quant.run.start` | 1 | **ja** |
| `quant.run.stop` | 2 | **nee, met opzet** |

Die laatste regel is een ontwerpkeuze die ik expliciet wil maken: **de kill switch mag geen
tweede bevestiging vragen.** Stoppen is altijd veilig, starten niet. Een pincode opzoeken
terwijl je wilt stoppen is precies het verkeerde moment. Hetzelfde patroon staat al in de
apparatenlijst: een apparaat uitloggen vraagt ook niets.

### Postgres-conventies

- Tabelnamen: snake_case, meervoud (`social_channels`, `user_sessions`, `todo_tasks`).
- `id` als `Integer` primary key; `user_id` als FK met `ondelete="CASCADE"` en een index.
- `TimestampMixin` geeft `created_at`/`updated_at`, allebei tijdzone-bewust UTC via een
  eigen `UtcDateTime`-type. **Alle tijdstempels in dit project zijn tz-aware UTC.**
- JSON-kolommen die onderscheid moeten maken tussen "leeg" en "niet ingevuld" gebruiken
  `NullableJSON` — gewone `JSON` slaat Python-`None` op als JSON-`null`, en dan is
  `IS NOT NULL` waar terwijl er niets staat. Dat is een keer echt misgegaan.
- Migraties: `backend/alembic/versions/000N_naam.py`, nu tot `0005_sessions_and_permissions`.
  De volgende is dus `0006_`.
- Twee harde regels uit eerdere fases: de revisie-id past in **32 tekens**
  (`alembic_version.version_num` is `varchar(32)`), en een `NOT NULL`-kolom op een gevulde
  tabel krijgt een `server_default` die daarna weer weg mag.
- `alembic/env.py` heeft een `render_item`-hook die `UtcDateTime` naar
  `sa.DateTime(timezone=True)` schrijft; zonder die hook schrijft autogenerate een import
  die in de migratie niet bestaat.

---

## 2. Design tokens en componenten

**Aanwezig.** Niet stoppen en vragen.

### Tokens

`frontend/src/styles/theme.css`, in `:root`. De vier merkkleuren uit de opdracht staan er
lettergelijk in:

```css
--merk-antraciet: #12141A;
--merk-amber:     #E8A33D;
--merk-groen:     #2F6F5E;
--merk-wit:       #F5F1E8;
```

Maar — en dit is waar de codebase wint — de kleuren die het scherm **werkelijk** gebruikt
zijn deels andere:

| Rol | Token | Waarde | Verhouding tot de huisstijl |
| --- | --- | --- | --- |
| Achtergrond | `--bg` | `#080c14` | donkerder dan `#12141A`, bewust: dit scherm staat vaak de hele dag aan |
| Accent | `--amber` | `var(--merk-amber)` | **is** de merkkleur |
| Tekst | `--text` | `#e8eef6` | koel wit, niet het warme `#F5F1E8` |
| Goed/actief | `--green` | `#3ecf8e` | fel groen, niet het bosgroen `#2F6F5E` |
| Fout | `--red` | `#e5484d` | **bestaat al**, en wordt gebruikt voor foutmeldingen |

Dat laatste raakt sectie 13 van de opdracht direct: er wordt één nieuw token voor verlies
voorgesteld (`#C25B4A`), maar er is al een rood. Open vraag 5.

Verder aanwezig en bruikbaar: `--mono` (monospace cijfers — eis uit sectie 13), `--radius`,
`--gap`, `--sidebar-w`, `--topbar-h`.

### Componenten

`frontend/src/components/`:

- `ui/Panel.tsx` — de basisbouwsteen van elk scherm (titel, meta, body, footer, optionele link).
- `ui/StatusDot.tsx` — stoplicht plus `toneFor(status)` dat een statuswoord naar een kleur vertaalt.
- `ui/EmptyState.tsx`, `ui/ConfirmDialog.tsx` (pincode óf wachtwoord), `ui/Icons.tsx`.
- `layout/Shell.tsx` — zijbalk, bovenbalk, en op mobiel een onderbalk met vier vaste plekken
  plus "Meer".
- Klassen in `theme.css` die een nieuw scherm meteen kan gebruiken: `.stack`, `.listrow*`,
  `.table`, `.keyvals`, `.tag`, `.formgrid`, `.btn--small`, `.notice`, `.modal`, `.switch`.

Routering: `frontend/src/App.tsx`, nu 19 routes. Navigatie-items staan in `Shell.tsx`;
`MOBILE_ITEMS` bepaalt welke vier onderaan staan.

### Twee dingen om op te letten bij zeven nieuwe schermen

1. **Mobiele volgorde.** In het `@media (max-width: 768px)`-blok krijgt elk paneel een
   expliciete `order` per `data-panel`. Een paneel zonder regel krijgt `order: 0` en springt
   daarmee vóór álles. Dat is een keer echt gebeurd. Elk nieuw paneel hoort daar een plek te
   krijgen.
2. **"Pixel-identiek" is nu niet aantoonbaar.** Er zijn 279 backendtests, maar **nul
   frontendtests** en geen visuele regressietest (`frontend/package.json` heeft geen
   test-script). De eis "bestaande schermen blijven pixel-identiek" uit fase 5 is dus niet
   automatisch te bewijzen. Voorstel: Playwright-screenshots van de bestaande schermen vóór
   en na, op 375 en 1440 px — dat is het gereedschap dat in dit project al voor elke
   UI-fase is gebruikt. Dat moet dan wel in fase 5 begroot worden.

---

## 3. Achtergrondworker en scheduler

`backend/app/workers/scheduler.py`: APScheduler (`AsyncIOScheduler`, tijdzone UTC), gestart
in de FastAPI-lifespan.

| Job | Interval | Opties |
| --- | --- | --- |
| `finance_sync` | 15 min (config) | `coalesce=True, max_instances=1` |
| `social_sync` | 30 min (config) | `coalesce=True, max_instances=1` |
| `system_sample` | 30 s | `max_instances=1` |

De scheduler krijgt de database als argument mee in plaats van er zelf een te pakken, zodat
tests tegen hun eigen database draaien. Providers worden **alleen** hier aangeroepen; het
dashboard leest wat er is opgeslagen.

### De bevinding die ertoe doet

**Alles draait in het API-proces.** Voor een synchronisatie elke 15 minuten is dat prima.
Voor het Quant Lab is het dat niet, om drie redenen:

1. Een data-ingest die per seconde events verwerkt, concurreert met het afhandelen van
   verzoeken in dezelfde event loop.
2. Herstart je de API (een update, een crash), dan valt de ingest stil — en in fase 2 is dat
   een gat in een append-only corpus dat je nooit meer kunt vullen.
3. De job store is de standaard (in geheugen). Er overleeft niets een herstart.

**Advies voor fase 2:** het Quant Lab krijgt een eigen procesmodule die los van `uvicorn`
draait (eigen systemd-unit of een eigen dienst in `deploy/docker-compose.yml`), schrijft naar
dezelfde database, en wordt door de API alleen gelézen. Dat is dezelfde scheiding die dit
project al hanteert tussen scheduler en dashboard, maar dan met een eigen proces erbij.
Zonder dit is "bit-voor-bit replaybaar" (acceptatiecriterium fase 2) niet houdbaar.

---

## 4. Serverresources

**Wat ik kon meten is níét de machine waar Ganz op draait.** Deze omgeving is een container
in de cloud waarin ik werk:

| | Deze container |
| --- | --- |
| CPU | 4 vCPU, Intel Xeon @ 2.10 GHz |
| RAM | 15 GiB totaal, ~15 GiB vrij |
| Schijf | 252 GB totaal, 19 GB vrij (52% in gebruik) |
| PostgreSQL | 16 geïnstalleerd, stond stil |

De echte server is de Mac van Stef of een VPS. Wat ik daarvoor nodig heb staat al in
[`docs/server.md`](../server.md) §2 en is nog steeds onbeantwoord: RAM, vCPU, schijf,
uploadsnelheid en eventuele datalimiet, en of het een echte VM is of een container.

Twee dingen die het Quant Lab daar bovenop legt en die de bestaande schatting kunnen
omgooien:

- **Geheugen.** Ganz draait al het stemmodel en het skill-model op PyTorch (samen 2–3 GB als
  ze allebei geladen zijn). Een losse ingest-worker komt daarbovenop.
- **Schijf.** Append-only ruwe feedevents groeien onbeperkt. De groei per dag is nu niet te
  schatten, want die hangt volledig af van welke bron het wordt en hoeveel events die levert
  — en dat is precies wat §5 blokkeert. Dit hoort bij fase 2, maar het is een reden te meer
  om §5 eerst op te lossen.

---

## 5. Databronnen voor H1 — **niet geverifieerd, en niet verifieerbaar vanaf hier**

De opdracht is duidelijk: *verifieer in de officiële docs, gok niet.* Dat kan ik niet, en ik
vul het gat niet met cijfers uit mijn geheugen.

### Wat er gebeurde

De netwerkpolicy van deze omgeving staat uitgaand verkeer alleen toe naar een korte lijst.
Gemeten, elke host op poort 443:

| Host | Antwoord |
| --- | --- |
| `docs.claude.com` | 301 — bereikbaar |
| `api.dexscreener.com` | geen verbinding |
| `api.mainnet-beta.solana.com` | geen verbinding |
| `lite-api.jup.ag` | geen verbinding |
| `public-api.birdeye.so` | geen verbinding |
| `api.rugcheck.xyz` | geen verbinding |
| `api.geckoterminal.com` | geen verbinding |
| `mainnet.helius-rpc.com` | geen verbinding |

Ook `docs.dexscreener.com` en `docs.helius.dev` worden door de proxy geweigerd. Websearch
werkt wel, maar leverde vrijwel uitsluitend blogs en MCP-wrappers op — geen officiële docs.
Dat is niet de bron waar een rate limit of een prijs uit mag komen.

**Gevolg: punt 5 van fase 0 is open.** Hieronder staat wat ik heb voorbereid, niet wat ik
heb vastgesteld.

### Te verifiëren per bron (werklijst, nog niets geverifieerd)

| Bron | Waarvoor in H1 | Wat ik ga verifiëren |
| --- | --- | --- |
| Solana RPC (eigen node of een aanbieder) | mint-/freeze-authority, supply, grootste houders, `simulateTransaction` | rate limits, kosten, of `getTokenLargestAccounts` genoeg is voor "top-10 exclusief LP en burn" |
| Een streaming-aanbieder (Helius/Geyser-achtig) | nieuwe pools en trades op het moment zelf | websocket of webhook, gratis laag, kosten, vertraging |
| DexScreener / GeckoTerminal | prijs, liquiditeit, pooldiepte | rate limit, of nieuwe pools binnen minuten verschijnen, voorwaarden voor commercieel gebruik |
| Birdeye of vergelijkbaar | OHLCV per minuut | of er 1-minuutsdata is voor een pool van 10 minuten oud, kosten |
| Jupiter quote-API | **verkoopbaarheid** | of een quote voor de omgekeerde richting als verkoopsimulatie telt |
| RugCheck of vergelijkbaar | LP burned/gelockt | hoe "30 dagen gelockt" wordt vastgesteld, en of dat te controleren is |

### Wat ik nu al kan zeggen, zonder vendor-docs

Dit volgt uit H1 zelf en niet uit een leverancier, dus het blijft staan ongeacht welke bron
het wordt:

1. **De entry-trigger vraagt om data die een REST-API achteraf meestal niet heeft.** De
   trigger is "prijs breekt boven de hoogste prijs van de eerste 10 minuten, met volume van
   de laatste 5 minuten ≥ 3× de mediaan van die eerste 10 minuten", bij een token van 5 tot
   30 minuten oud. Dat vereist handelsdata op minuutniveau vanaf minuut nul. Of de bron die
   met terugwerkende kracht levert voor een pool die tien minuten bestaat, is de kernvraag.
   Zo niet, dan **moet Scout al luisteren op het moment dat de pool ontstaat** — een stream,
   geen poll. Dat bepaalt de vorm van Scout, en het bepaalt dat het replay-corpus pas groeit
   vanaf het moment dat Scout live gaat. Er is dan geen historische backtest om mee te
   beginnen.
2. **"Technisch geverifieerd verkoopbaar" is waarschijnlijk niet hard te maken.** Een
   simulatie van een verkoop op dit moment zegt niets over een verkoop over tien minuten: de
   contracteigenaar kan er tussenin aan draaien, en er zijn constructies die precies op dat
   verschil leunen. Ik markeer dit nu al als **niet verifieerbaar in absolute zin**. Wat wél
   kan is een momentopname plus de afwezigheid van bekende gevaarlijke eigenschappen, en dat
   is iets anders dan een garantie. De filterregel "kan het niet geverifieerd worden:
   uitsluiten en tellen" is daarmee de juiste regel — maar hij zal vaak afgaan.
3. **"Top-10 houders ≤ 20%, exclusief LP- en burn-adressen" vereist een lijst van wat een
   LP- of burn-adres ís.** Dat is niet één veld in een API; het is per DEX en per
   lock-programma anders. Dit filter is het meest foutgevoelige van de vijf.

---

## 6. Openstaande vragen voor Stef

Op volgorde van wat het meest blokkeert.

1. **Mag ik de netwerkpolicy laten verruimen?** Zonder uitgaande toegang tot de
   databronnen kan ik §5 niet afmaken en kan fase 2 niet beginnen. Je past dit aan in de
   instellingen van de cloudomgeving (menu in de titelbalk → Edit → Network access), met de
   hosts uit de tabel in §5 onder *Allowed domains* en de standaardlijst met package
   managers erbij. Uitleg: https://code.claude.com/docs/en/cloud-environments#network-access
2. **Welke machine wordt de server, en wat zijn de specificaties?** RAM, vCPU, schijf,
   uploadsnelheid, datalimiet, en KVM of container. Dit bepaalt of een losse ingest-worker
   erbij past naast wat Ganz al draait.
3. **JEV: bestaat het, en heb jij toegang?** Mijn kennis loopt tot mei 2026 en de docs zijn
   vanaf hier onbereikbaar, dus ik kan niet bevestigen dat JEV (TypeSafe AI) bestaat, wat
   het kost of hoe het presteert. Stuur me de link naar de officiële docs. Zo niet, dan
   bouwen we `RulesOnly` + Haiku en laten we de `DecisionModel`-interface open staan — het
   ontwerp uit sectie 7 overleeft dat zonder wijziging.
4. **Budget: €200/maand is exclusief de bouwkosten van Claude Code, bevestig je dat?**
   (Expliciet gevraagd in sectie 4 van de opdracht.)
5. **Modelnaam gecorrigeerd — akkoord?** De opdracht noemt `claude-haiku-4-5-20251001`. De
   juiste identifier is `claude-haiku-4-5`, zonder datumachtervoegsel. `claude-fable-5-1`
   klopt wel. Geverifieerde prijzen (officiële docs, vandaag):

   | Model | Invoer | Uitvoer | Cache-hit |
   | --- | --- | --- | --- |
   | `claude-haiku-4-5` | $1 / MTok | $5 / MTok | $0,10 / MTok |
   | `claude-fable-5-1` | $10 / MTok | $50 / MTok | $0,25 / MTok |

   Twee gevolgen. **(a)** De Reviewer op Fable is haalbaar binnen €70 zolang je zijn invoer
   begrenst: bij ~60k invoertokens en ~4k uitvoer per dagrapport kost dat ongeveer $0,80 per
   dag, dus ruwweg $25–35 per maand. Bij 500k invoertokens per dag is het $150 per maand en
   is het budget op. De knop die dit bepaalt is hoeveel context de Reviewer krijgt, niet hoe
   vaak hij draait. **(b)** Fable 5.1 is niet beschikbaar onder zero-dataretentie zonder
   aparte toestemming van Anthropic; voor dit project vermoedelijk geen probleem, maar je
   moet het weten.
6. **Verlieskleur.** `--red: #e5484d` bestaat al en wordt gebruikt voor foutmeldingen. Wordt
   verlies diezelfde kleur (geen nieuw token), of komt `#C25B4A` erbij als aparte kleur voor
   P&L? Mijn voorkeur: hergebruiken. Eén rood is duidelijker dan twee die bijna hetzelfde
   zijn.
7. **Rechten en de kill switch.** Krijgt je broer toegang tot het Quant Lab, en op welk
   niveau? En ga je mee met het voorstel uit §1: stoppen zonder tweede bevestiging, starten
   en hypotheses wijzigen mét?
8. **Positiegrootte in euro's.** 1R is 0,75% van de paper-equity, maar het filter
   "liquiditeit ≥ 50× de positiegrootte" en het slippage-model hebben een absoluut bedrag
   nodig. Met welk startvermogen rekent de paper-account?
9. **Geen historie om mee te beginnen — akkoord?** Als §5 uitwijst wat ik in punt 1 van die
   paragraaf beschrijf, dan begint het replay-corpus leeg en duurt het weken voordat er 150
   gesloten trades zijn. Fase 6 zegt dan terecht "te vroeg". Is dat het tempo waar je op
   rekent?
10. **Waar komt het Quant Lab in de navigatie?** Het wordt de 20e route; de onderbalk op
    telefoon heeft vier vaste plekken plus "Meer". Voorstel: één item "Quant Lab" in de
    zijbalk, met de zeven schermen als tabbladen binnen die module, zodat de rest van Ganz
    niet verschuift.

---

## Afwijkingen van de opdracht

- **Punt 5 is niet afgerond.** Reden en bewijs staan in §5. Ik heb geen cijfers ingevuld die
  ik niet kon verifiëren.
- Verder niets. Er is geen code geschreven, geen bestaande module aangeraakt, en niets uit de
  lijst "hard out of scope" benaderd.

## Bewijs

- Module-registratie, scheduler, tokens, componenten, migraties: gelezen in de codebase op
  commit `49b8951` (tak `claude/ganz-fase-1-fundament`, bevat de samengevoegde hoofdtak).
- Resources: `nproc`, `free -h`, `df -h` in deze container.
- Bereikbaarheid van de databronnen: `curl` naar acht hosts, uitkomst in de tabel in §5.
- Modelprijzen: https://platform.claude.com/docs/en/about-claude/pricing, opgehaald vandaag.

**Fase 0 is hiermee klaar. Ik stop en wacht op "Start Fase 1".**
