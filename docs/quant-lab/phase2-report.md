# Quant Lab — Fase 2: datalaag en replay

**Kort:** de Scout, de ruwe append-only opslag met een hashketting, de validatiechecks en de
replay-runner staan er. De testsuite is groen: **397 tests, waarvan 40 nieuw**. Een opgenomen
uur is bit-voor-bit herhaalbaar — aangetoond tegen een echte PostgreSQL, niet alleen in de
tests. Het datakwaliteitsrapport is er en meldt per controle wat hij vond.

**En nu het ding dat je als eerste moet weten: er is geen echte databron aangesloten, en dat
kon niet.** De netwerkpolicy van deze omgeving laat geen enkele marktbron door — ik heb het
opnieuw gemeten, zie §4.1. Wat er dus staat is de volledige machinerie, bewezen met een
**synthetische** (verzonnen) bron. Die bron heet ook letterlijk `synthetic`, elk event draagt
die naam, en het kwaliteitsrapport zet er een waarschuwing boven. Er is geen enkel cijfer in
dit rapport dat iets over de markt zegt, en dat is met opzet.

Er is in dit project geen live handel.

---

## 1. Wat is gebouwd

### De ruwe opslag: tekst, niet betekenis

`quant_raw_events` bewaart de feed **zoals hij binnenkwam**: de tekst, niet een geparste en
opnieuw opgeschreven structuur. Dat is het hele verschil tussen "herhaalbaar" en
"bit-voor-bit herhaalbaar". `{"a":1,"b":2}` en `{"b": 2, "a": 1}` betekenen hetzelfde maar
zijn niet dezelfde bytes; een feed die morgen zijn sleutelvolgorde wijzigt, zou anders stil
een ander corpus opleveren en niemand zou het zien. Er is een test die precies dit vastlegt
(`test_de_hash_gaat_over_de_tekst_en_niet_over_de_betekenis`).

Elke rij hangt aan de vorige: `chain_hash = sha256(vorige_schakel + hash van deze tekst)`.
Verandert er één byte in een oude rij, dan sluit alles erna niet meer aan en zegt
`verify_chain()` bij welk event het voor het eerst misgaat.

**Een dubbel event wordt niet weggegooid.** De tabel is append-only; weggooien zou betekenen
dat de ruwe opslag niet meer ruw is. In plaats daarvan wijst `duplicate_of_id` naar het
eerste exemplaar en telt het kwaliteitsrapport ze.

### Van ruw naar bruikbaar, en volledig terug te draaien

`quant_market_ticks` is de genormaliseerde vorm, en is **volledig afgeleid en dus volledig
weggooibaar**. Dat is geen netheid maar de kern van het bewijs: de enige manier om aan te
tonen dat een replay hetzelfde resultaat geeft, is het afgeleide deel weggooien, het opnieuw
opbouwen uit de ruwe tabel, en de afdrukken vergelijken.

De velden van een tick volgen niet uit een aanbieder maar uit hypothese H1 zelf. Die heeft
precies vier dingen nodig, en die staan er:

| H1 vraagt | Veld |
| --- | --- |
| tokenleeftijd 5–30 minuten | `pool_created_at` |
| hoogste prijs van de eerste 10 minuten | `price_usd` over de tijd |
| volume laatste 5 min ≥ 3× mediaan eerste 10 min | `volume_usd` + `volume_window_seconds` |
| liquiditeit ≥ 50× de positiegrootte | `liquidity_usd` |

Zo blijft de laag venue-agnostisch: komt er een bron bij, dan hoeft alleen de `Normalizer`
van die bron geschreven te worden en verandert er niets aan de Screener.

Twee details die er echt uitmaken:

- **JSON wordt geparsed met `Decimal`, niet met float.** Een prijs van 0,000000123456 die
  door een float gaat, komt er niet hetzelfde uit — en bij memecoins zijn dat precies de
  prijzen. Er is een test op (`test_prijzen_gaan_niet_door_een_float`).
- **De afdruk rekent met vaste schalen.** PostgreSQL geeft een `Numeric(30,12)` terug met
  twaalf decimalen, dus 1,5 komt terug als 1,500000000000. Zou de afdruk de tekst van het
  getal gebruiken zoals hij toevallig is, dan verschilde hij voor en na het opslaan en leek
  elke replay een ander resultaat te geven terwijl de data identiek is. Dat is precies het
  soort fout waar je een week aan kwijt bent, dus er staat een test op
  (`test_de_afdruk_van_een_tick_is_stabiel`).

### De Scout, in zijn eigen proces

`app/quantlab/scout.py` + `scripts/quant_scout.py`. Eén taak, geen beslissingen: ophalen,
ruw wegzetten, kloppen. De Scout kijkt niet naar prijzen en weet niet wat een hypothese is.

Hij draait **niet** in de scheduler van de API, zoals ik in fase 0 adviseerde, en daar is nu
een test op die faalt als die scheduler ooit iets uit `quantlab` importeert
(`test_de_scout_draait_niet_in_het_api_proces`). De drie redenen staan in de code: de
scheduler draait in hetzelfde proces als de verzoeken, zijn jobstore zit in het geheugen, en
een gat in een append-only corpus kun je nooit meer vullen.

**De hartslag van de Scout is de dead-man switch van fase 1.** Dat is geen theorie: zie §2.4,
waar een echte Scout-run de risicolaag van een geblokkeerde naar een werkende stand brengt.

Elke run komt in `quant_ingest_runs` met een `stop_reason`. Ook als de bron eruit klapt:
een run die openblijft, is een gat in de boekhouding van het corpus
(`test_een_klapper_in_de_bron_sluit_de_run_netjes_af`).

### De validatiechecks

Acht controles, elk met een aantal, drie voorbeelden en een uitleg in gewone taal:

| Controle | Wanneer |
| --- | --- |
| `gap` | meer dan 3× de normale afstand stil, met een minimum van 30 seconden |
| `duplicate` | identieke tekst twee keer binnengekomen |
| `zero_or_negative_price` | prijs ≤ 0 — **altijd alarm**, één keer is genoeg |
| `rounded_price` | prijs past op 2 decimalen terwijl de mediaan van die pool veel kleiner is |
| `out_of_order` | een event met een tijdstip vóór zijn voorganger |
| `future_timestamp` | tijdstip ná het moment van ontvangen — **altijd alarm** |
| `stale_feed` | meer dan 60 seconden tussen het tijdstip in het event en de ontvangst |
| `parse_failure` | niet te lezen als JSON; ruw bewaard, niet gerepareerd |

Twee keuzes daarin:

**De controle op volgorde kijkt naar de aankomstvolgorde, de gatcontrole naar de klok.** Dat
is geen detail: zou je de reeks eerst chronologisch sorteren, dan verdwijnt elke bevinding
over verkeerde volgorde — het sorteren repareert precies wat je wilde meten. Dit heeft me
tijdens het bouwen één failing test gekost en staat nu expliciet in de code.

**Een nulprijs is meteen een alarm, een gat eerst een waarschuwing.** Een prijs van nul kan
niet bestaan, dus die ene is al genoeg om de data van die pool niet te vertrouwen. Een gat
kan een hikje zijn; vanaf 1% van de events wordt het een patroon en dus een alarm.

### De replay-runner

`replay()` rekent **eerst de ketting na** en weigert te draaien als die niet aansluit.
Replayen van data waarvan je niet weet of hij nog klopt, levert een getal op waar je niets
aan hebt. Daarna gooit hij alleen het genormaliseerde deel van het gevraagde venster weg,
bouwt het opnieuw op, en geeft de afdruk terug. De ruwe tabel wordt niet aangeraakt.

### Opslaggroei en retentie

`storage_report()` **meet** en schat niet: bytes gedeeld door de tijd die werkelijk is
opgenomen. Is er minder dan een minuut opgenomen, dan staat er geen projectie — dan zegt het
getal niets.

Opruimen (`prune_raw_events`) vraagt een expliciete grens en heeft geen standaardwaarde en
geen achtergrondtaak: **een replay-corpus dat zichzelf opruimt, is een corpus dat je niet
kunt replayen.** Er is een test die faalt als iemand die grens optioneel maakt.

Compressie heb ik niet gebouwd en dat is een keuze: `payload_raw` is een `Text`-kolom, en
PostgreSQL comprimeert die vanaf ongeveer 2 kB zelf (TOAST). Een eigen compressielaag erbij
zou de replay ingewikkelder maken voor winst die ik niet heb gemeten.

### Nieuw in de API en in deployment

```
GET /api/quant/data/quality   het kwaliteitsrapport plus de stand van de ketting
GET /api/quant/data/storage   hoeveel er staat en hoeveel het per dag wordt
GET /api/quant/data/runs      wat de Scout wanneer heeft opgenomen, en waarom hij stopte
```

Alle drie achter `quant.read` (tier 2), met een expliciet responsemodel. `/data/quality`
geeft **alle acht controles** terug, ook die niets vonden: een scherm dat alleen de
bevindingen toont, geeft de indruk dat er niet meer gecontroleerd wordt.

In `deploy/docker-compose.yml` staat een `quant-scout`-service met `profiles: ["quant"]` —
standaard uit, want er is nog geen echte bron. `stop_grace_period: 30s` zodat SIGTERM de
laatste batch nog kan wegschrijven en de run met een reden dicht kan.

Migratie `0007_quant_lab_datalaag`: drie tabellen, geen bestaande kolom aangeraakt.

---

## 2. Bewijs

### 2.1 Testoutput

```
$ cd backend && .venv/bin/python -m pytest -q
397 passed in 165.46s (0:02:45)

$ .venv/bin/python -m pytest tests/test_quant_data.py -q
40 passed in 37.63s
```

Voor fase 2 waren het 357 tests; er zijn er 40 bij gekomen en geen bestaande test is
aangepast.

### 2.2 De acceptatie-eis: een opgenomen uur, bit-voor-bit

`backend/scripts/quant_replay_proof.py` tegen PostgreSQL 16. De tests draaien op SQLite, en
het verschil tussen die twee zit juist in hoe ze getallen en tijdstippen teruggeven — precies
waar een afdruk over heen kan vallen. Vandaar deze losse proef:

```
1. Een uur opnemen
  events opgeslagen:   1029
  ticks genormaliseerd: 1029
  onleesbaar:          0
  dubbel:              0
  bytes ruwe tekst:    294731

2. De ketting narekenen
  sluit aan:  True
  afdruk:     d5346a9e0dcb2a1e62cdcde04dd5b53ee1220218191d26244732d411392081fc

3. Replayen en de afdrukken vergelijken
  afdruk voor:  c39fe967c4790fcc4a3b661d0db7aac6383616d089472a83a81551a804d1f728
  afdruk na:    c39fe967c4790fcc4a3b661d0db7aac6383616d089472a83a81551a804d1f728
  identiek:     True
  ticks voor/na:1029 / 1029
  ruwe opslag onveranderd: True

4. Zou de afdruk een verschil wel merken?
  één prijs veranderd (0.002213453209 -> 1): afdruk verschilt = True
  na een replay weer de oude afdruk:       True

5. Een aangepaste ruwe rij stopt de replay
  ketting sluit aan: False
  eerste foute seq:  1
  replay weigert:    De ketting sluit niet aan bij event 1. De tekst van dit event is
                     veranderd nadat het was opgeslagen, of er is een event tussenuit gehaald.
  na herstel sluit de ketting weer aan: True
```

Stap 4 staat er omdat stap 3 zonder die stap niets bewijst: een afdruk die bij elke data
hetzelfde blijft, is altijd "identiek". Eén prijs veranderen laat de afdruk verschillen, en
een replay zet hem terug — want de ruwe opslag is de waarheid.

### 2.3 Het datakwaliteitsrapport

Hetzelfde uur, eerst schoon en daarna met vier ingebouwde gebreken. De synthetische bron
maakt die gebreken met opzet; een controle die nooit iets vindt, is niet te onderscheiden van
een controle die stuk is.

```
6. Datakwaliteit en opslaggroei van het schone uur
  oordeel:     ok
  pools:       3
  bevindingen: geen
  uitleg:      De opgenomen data ziet er schoon uit. Let op: 1029 van de 1029 events zijn
               synthetisch (verzonnen) en zeggen niets over de markt.

  1029 events, 287.8 KiB aan ruwe tekst. Over 1.0 uur gemeten, dus ongeveer 6.8 MiB per dag
  en 202.9 MiB per maand.
  bytes per event: 286

7. Hetzelfde uur, nu met ingebouwde gebreken
  oordeel: alarm
    gap                         1  warning
      voorbeeld: pool-1: 610s stil vanaf 2026-10-07T09:04:50+00:00
    zero_or_negative_price      1  alarm
      voorbeeld: pool-1@2026-10-07T09:00:20+00:00=0E-12
    duplicate                   1  warning
      voorbeeld: 1 dubbele events in de ruwe opslag
    parse_failure               1  warning
      voorbeeld: 1 onleesbare events
```

Elk van de acht controles heeft daarnaast een eigen test waarin de bron precies dat gebrek
inbouwt (`test_elk_ingebouwd_gebrek_wordt_gemeld`, acht keer geparametriseerd).

### 2.4 De Scout als eigen proces, en de hartslag uit fase 1

Een echte run via `python -m scripts.quant_scout`, in een eigen proces, tegen PostgreSQL:

```
Scout stopte na 489 events (489 ticks, 0 onleesbaar): source_exhausted
Run 5: 489 events, 489 ticks, 0 onleesbaar, 146791 bytes (source_exhausted)
```

```sql
SELECT source, events, ticks, parse_failures, bytes_stored, stop_reason FROM quant_ingest_runs;
  source   | events | ticks | parse_failures | bytes_stored |   stop_reason
-----------+--------+-------+----------------+--------------+------------------
 synthetic |    489 |   489 |              0 |       146791 | source_exhausted

SELECT count(*) AS ruwe_events, count(DISTINCT chain_hash) AS unieke_schakels FROM quant_raw_events;
 ruwe_events | unieke_schakels
-------------+-----------------
         489 |             489

SELECT pool_address, count(*) AS ticks FROM quant_market_ticks GROUP BY pool_address;
 pool-1 | 181
 pool-2 | 163
 pool-3 | 145
```

489 events, 489 unieke schakels: geen enkele botsing in de ketting.

En dan het stuk dat fase 1 en fase 2 aan elkaar knoopt — direct na die run:

```
hartslag oud (seconden):   12.6
dead-man switch getrokken: False
instap toegestaan:         True  (geen veto)
1R bij 1000 euro equity:   EUR 7.50
```

In fase 1 blokkeerde de dead-man switch élke instap, omdat er niets klopte. Nu klopt de
Scout, en gaat de risicolaag open. Dat is de bedoeling van die switch, en nu is hij ook
daadwerkelijk aangesloten.

### 2.5 De migratie

```
$ .venv/bin/python -m alembic upgrade head
Running upgrade 0006_quant_lab_risk_en_kosten -> 0007_quant_lab_datalaag

$ .venv/bin/python -m alembic check
No new upgrade operations detected.
```

### 2.6 Geen screenshots

De schermen van de module staan in fase 5 van de opdracht. Er is in fase 2 niets te zien
behalve JSON uit drie endpoints, dus er zijn geen screenshots. Dat is geen vergeetpost maar
de fase-indeling.

---

## 3. Afwijkingen van de prompt, en waarom

1. **Geen echte databron.** De opdracht vraagt in fase 2 "Scout, raw opslag, validatiechecks,
   replay-runner" en gaat er impliciet van uit dat er data in komt. Dat kon niet: zie §4.1.
   Wat er is, is de hele machinerie plus twee bronnen die wél werken — `synthetic` (verzonnen)
   en `jsonl` (een opname van schijf). Een echte bron is **één klasse** die `FeedSource`
   implementeert; de rest van het lab merkt het verschil niet.

2. **Een synthetische bron, en die staat niet in de opdracht.** Ik heb hem gebouwd omdat de
   alternatieven slechter waren: wachten tot het netwerk open is (dan staat fase 2 stil), of
   de machinerie bouwen zonder hem ooit te draaien (dan is "het werkt" een bewering). Hij doet
   geen enkele poging om op een echte memecoin te lijken — dat zou de verkeerde suggestie
   wekken — maar geeft wel genoeg events met genoeg variatie om de laag echt te belasten. En
   hij is overal als verzonnen gemarkeerd: in de bronnaam, in elk event, en met een
   waarschuwing boven het kwaliteitsrapport.

3. **De `defects`-stand van de synthetische bron.** Die staat ook niet in de opdracht. Zonder
   een manier om met opzet slechte data te maken, is een controle die nooit iets vindt niet te
   onderscheiden van een controle die stuk is.

4. **Geen compressie.** De opdracht vraagt "pas retentie/compressie toe". De retentie staat er
   (expliciet, zonder automaat); compressie laat PostgreSQL zelf doen via TOAST. Een eigen
   compressielaag maakt de replay ingewikkelder voor winst die ik niet heb gemeten, en meten
   kan ik hem niet zonder echte data.

5. **Geen alarm in het dashboard.** De opdracht noemt "met alarm in het dashboard" bij de
   validatiechecks. Het dashboard is fase 5; het alarm zit nu in het rapport en in het
   endpoint (`verdict: "alarm"`), zodat er in fase 5 alleen een scherm omheen hoeft.

6. **Twee tabellen in plaats van één.** `quant_raw_events` naast `quant_market_ticks` kost
   opslag die je zou kunnen uitsparen door alleen het genormaliseerde deel te bewaren. Dat is
   bewust niet gedaan: zonder de ruwe tekst kun je niet bewijzen dat een replay hetzelfde
   oplevert, en kun je een fout in de normalisatie nooit meer herstellen.

---

## 4. Bekende problemen en risico's

### 4.1 Het netwerk is nog steeds dicht — en dit blokkeert fase 3 hierna ook

Opnieuw gemeten, vandaag:

| Host | Resultaat |
| --- | --- |
| `api.dexscreener.com` | geen verbinding |
| `api.mainnet-beta.solana.com` | geen verbinding |
| `lite-api.jup.ag` | geen verbinding |
| `public-api.birdeye.so` | geen verbinding |
| `api.geckoterminal.com` | geen verbinding |
| `docs.claude.com` | 301 (bereikbaar) |
| `pypi.org` | 200 (bereikbaar) |

Wat dit betekent, in volgorde van ernst:

1. **Het replay-corpus groeit pas vanaf het moment dat er een bron aan hangt.** Dat staat ook
   in de opdracht ("begin hiermee zo vroeg mogelijk") en het is niet in te halen: data van
   gisteren kun je niet achteraf opnemen. Elke dag dat dit wacht, is een dag die nooit in het
   corpus komt.
2. **Fase 3 (paper broker) kan ik bouwen en testen, maar niet valideren.** Een fill-model dat
   alleen tegen synthetische pooldiepte is getest, zegt niets over echte slippage.
3. **De opslagprojectie van 6,8 MiB per dag is van de synthetische bron**, met drie pools en
   een tick per tien seconden. Een echte Solana-feed levert een veelvoud daarvan. Dat getal
   is dus wél een echte meting, maar van de verkeerde markt — gebruik het niet voor je
   schijfplanning.

### 4.2 Verder

4. **De `Normalizer` voor een echte bron bestaat niet, en kan niet verzonnen worden.** Ik kan
   geen adapter schrijven tegen een API-vorm die ik niet heb gezien; dat zou een adapter zijn
   die er werkend uitziet en bij de eerste echte respons omvalt.

5. **Dubbele events worden opgespoord met een lookup op de hash, niet in een venster.** Een
   feed die hetzelfde event na een herverbinding opnieuw stuurt, wordt gevonden. Maar een
   legitiem event dat exact dezelfde tekst heeft als iets van een uur eerder (bijvoorbeeld een
   tick met dezelfde prijs, hetzelfde volume én hetzelfde tijdstip) wordt óók als dubbel
   gemarkeerd. Met een tijdstip in de tekst is dat in de praktijk onmogelijk, maar het is een
   aanname en geen garantie.

6. **`verify_chain()` leest het hele corpus.** Bij een uur is dat niets; bij een maand draaien
   wordt het een query van minuten. De oplossing is een afdruk per dag ("checkpoint") zodat je
   alleen vanaf de laatste hoeft na te rekenen. Dat bouw ik als het nodig is, niet nu.

7. **`normalize_pending()` gebruikt een `NOT IN`-subquery** over alle al genormaliseerde
   events. Dat werkt tot het corpus groot wordt en dan niet meer. Ook hier: oplossen als het
   zover is, met een vlag of een watermerk, niet met een voorbarige optimalisatie.

8. **De Scout klopt per batch en niet op een eigen klok.** Komt de bron helemaal stil te
   liggen zónder de verbinding te verbreken, dan klopt de Scout ook niet meer — en dan valt
   de dead-man switch terecht. Maar hij merkt zelf niet dat hij stilstaat en kan dus ook niet
   proberen te herverbinden. Dat hoort bij een echte bron, en dus bij het moment dat die er is.

9. **De synthetische bron blijft in de code staan.** Dat is nuttig (tests, proefdraaien) en
   tegelijk een risico: iemand kan er per ongeluk een hypothese op laten lopen. De
   bescherming is nu een waarschuwing in het rapport. Zodra er echte data is, zou een harde
   regel beter zijn: een hypothese-run weigert te starten op een corpus dat synthetische
   events bevat. Dat hoort bij fase 3, waar de runs ontstaan.

---

## 5. Open vragen voor Stef

1. **De netwerkpolicy — dit is de enige vraag die echt uitmaakt.** Zonder uitgaand netwerk
   blijft het lab een lege machine. Het gaat om de instelling van deze cloudomgeving
   (*Network access*); zet die open voor de bronnen die we kiezen, of laat me weten dat dit
   lab op jouw eigen server moet draaien in plaats van hier. **En elke dag dat dit wacht, is
   een dag data die nooit in het corpus komt.**

2. **Welke bron wordt het?** Zodra er netwerk is, moet ik de officiële docs kunnen lezen om
   rate limits, voorwaarden en kosten te verifiëren — dat was punt 5 van fase 0 en is nog
   open. Mijn voorstel om mee te beginnen: één bron voor nieuwe pools en trades (streaming),
   en één voor contract- en holdergegevens. Welke dat worden, hangt af van wat de docs zeggen
   en niet van wat ik me herinner.

3. **Mag ik een eigen opname van iemand anders gebruiken?** Als je ergens een bestaande
   dataset of export van een feed kunt krijgen (JSONL, CSV), dan kan `jsonl` die zo inlezen en
   hebben we meteen een corpus met echte historie. Dat is de snelste weg om fase 3 zinvol te
   maken zonder op het netwerk te wachten.

4. **Hoeveel schijfruimte is er?** Dit was openstaande vraag 4 uit fase 0 en is nog niet
   beantwoord. Ik kan nu wel zeggen wat een opname kóst (286 bytes per event, gemeten), maar
   niet hoeveel events een echte feed geeft. Zonder jouw serverspecificaties kan ik geen
   retentietermijn voorstellen die ergens op gebaseerd is.

5. **De vragen uit fase 1 staan nog open:** de prijs van JEV.ai (en dus of de Classifier ooit
   kan draaien), de papieren inleg in euro's, en of de €200 per maand exclusief de bouwkosten
   is.

---

## Hoe je dit zelf nakijkt

```bash
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt

# alle tests
.venv/bin/python -m pytest -q

# alleen de datalaag
.venv/bin/python -m pytest tests/test_quant_data.py -v

# de replay tegen een echte database (schrijft rijen, ruimt ze daarna op)
createdb ganz_proef
export GANZ_DATABASE_URL=postgresql+asyncpg://ganz:ganz@localhost:5432/ganz_proef
.venv/bin/python -m alembic upgrade head
.venv/bin/python -m scripts.quant_replay_proof

# de Scout als eigen proces (Ctrl-C stopt hem netjes)
.venv/bin/python -m scripts.quant_scout --source synthetic --minutes 30
```

---

Fase 2 is hiermee af, voor zover het zonder netwerk af kan. Ik wacht op **"Start Fase 3"** —
maar lees eerst §4.1 en vraag 1: fase 3 is de paper broker, en een fill-model dat alleen
tegen verzonnen pooldiepte is getest, levert een getal op waar je niets aan hebt.
