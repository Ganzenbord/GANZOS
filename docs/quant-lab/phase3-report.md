# Quant Lab — Fase 3: paper broker en H0

**Kort:** het fill-model staat er met 47 unit tests, H0 draait end-to-end, en er is een
rapport met verwachte versus gesimuleerde fills. De testsuite is groen: **486 tests, waarvan
88 nieuw.** H0 kwam over 263 gesloten trades uit op een expectancy van **+0,096R met een
90%-interval van [−0,012, +0,208]** — nul zit erin, en dat is precies wat een controlegroep
hoort te doen.

**Maar lees eerst §3 en §4.** Ik heb tijdens deze fase drie fouten in mijn eigen werk
gevonden, en één ervan maakte de eerste resultaten waardeloos: mijn synthetische prijsreeks
had een drift die élke willekeurige instap liet winnen. H0 kwam uit op +8R met een winrate
van 100%. Dat zag er geloofwaardig uit en berustte op niets. Het staat hieronder met de
cijfers erbij, want dat is precies het soort fout waar deze opdracht tegen waarschuwt.

De data is synthetisch (verzonnen) en **geen enkele kostenparameter is geverifieerd.** Er
staat in dit rapport geen cijfer dat iets over de markt zegt.

Er is in dit project geen live handel.

---

## 1. Wat is gebouwd

### Het fill-model (`app/quantlab/fills.py`)

Memecoin-paper-trading gaat altijd op dezelfde manier om zeep: je rekent met de prijs op het
moment van het signaal. Alle vijf de dingen die daar tussen zitten, zijn nu gemodelleerd:

| | Hoe |
| --- | --- |
| **Vertraging** | Lognormaal met de p50 en p95 uit het hypothese-bestand. Lognormaal omdat vertraging niet negatief kan zijn en een lange staart heeft. De fill valt op de eerste tick ná de vertraging. |
| **Slippage** | Constant-product: `tokens = x·dy/(y+dy)`. De diepte volgt uit de gerapporteerde liquiditeit — die is de totale waarde, dus de quote-kant is de helft. |
| **Fees** | De swap-fee zit in de fill-prijs (net als in werkelijkheid), de tip en netwerkkosten staan apart. |
| **Mislukte transacties** | Met kans `failure_probability`. **De tip en netwerkkosten worden wél geboekt** — op een chain betaal je die ook als je transactie faalt. |
| **Exit-liquiditeit** | Boven een deel van de pool komt er een haircut bovenop de AMM-curve: in paniek ben je niet de enige die eruit wil. Bewust conservatief. |

De uitkomst is uitgesplitst in vier prijzen, omdat "de fill was slechter" een nutteloze
mededeling is als je niet weet waardoor:

```
expected_price  de prijs waarop het signaal mikte
market_price    de prijs na de vertraging   -> het verschil hiermee is wat de klok kostte
fill_price      wat je werkelijk kreeg      -> het verschil hiermee is slippage
fee_usd         tip en netwerkkosten, ook bij een mislukte poging
```

De belangrijkste test in dat bestand is `test_een_fill_is_nooit_gunstiger_dan_de_verwachte_prijs`,
25 keer geparametriseerd. Een paper broker die soms een betere prijs geeft dan waarop je
mikte, verzint geld.

### De pre-registratie (`app/quantlab/hypothesis.py`, `hypotheses/*.yaml`)

`H0_v1.yaml` en `H1_v1.yaml` staan er, vastgelegd en gehasht. De hash gaat over de **tekst
van het bestand**, commentaar incluis — want dat commentaar legt uit waarom een waarde zo
staat, en dat is onderdeel van de registratie.

Dezelfde `(naam, versie)` met andere inhoud wordt geweigerd. Uit de proef:

```
geweigerd: H0_v1 is al geregistreerd met een andere inhoud. Een hypothese wijzigen betekent
een nieuwe versie (bijvoorbeeld H0_v2); dan begint de trade-teller opnieuw.
```

Elke kostenparameter moet een `cost_model_provenance` hebben, en een hypothese zonder die
herkomst wordt niet geladen. Op dit moment staat bij alle acht "niet geverifieerd" met wat
er nodig is om het na te meten. Dat is lelijk en het is de waarheid.

H1_v1 is geregistreerd maar draait nog niet: de Screener die zijn entry-trigger uitvoert
komt in fase 4. Pre-registratie betekent vastleggen vóór de run, niet eraan beginnen.

### De exits (`app/quantlab/exits.py`)

Harde stop op −1R, de helft eruit op +2R, de rest met een trailing stop, en een maximale
houdtijd. Twee keuzes die uitleg verdienen:

**De stop weegt zwaarder dan de winstneming.** Raakt één tick allebei, dan wordt de stop
uitgevoerd. Je weet niet in welke volgorde het binnen die tick gebeurde, dus je kiest de
ongunstige kant. Zou je de winst pakken, dan verzin je geld.

**De trailing stop gaat pas aan ná de winstneming.** Zou hij eerder gelden, dan is de stop
niet meer −1R en klopt de positiegrootte niet met het risico.

### De veiligheidsfilters (`app/quantlab/safety.py`)

Drie uitkomsten in plaats van twee: goed, afgewezen, of **niet te verifiëren**. Dat derde
is de regel uit sectie 10 — wat je niet kunt verifiëren, gaat eruit en wordt geteld. Niet
"waarschijnlijk wel goed".

`NeverVerifiableOracle` is niet alleen een testdubbel: dat is wat er werkelijk gebeurt als
het lab vandaag zou draaien, want er is geen chaindata. Elk signaal wordt dan uitgesloten en
geteld, en dat is het juiste gedrag.

### De engine (`app/quantlab/engine.py`)

De volgorde is het ontwerp:

1. **Eerst de open posities bijwerken.** Een stop die op deze tick wordt geraakt, moet
   gebeuren vóór er op diezelfde tick wordt ingestapt — anders handel je met geld dat je
   volgens de stop al kwijt was.
2. Dan de strategie laten voorstellen.
3. Dan de veiligheidsfilters.
4. Dan de risicolaag: **dezelfde pure code en dezelfde grenzen als in fase 1.**
5. Dan het fill-model.

Elke weigering onderweg komt in `quant_signals` met een reden. Zonder die log kun je achteraf
elke uitkomst mooi praten door te vergeten wat je hebt laten lopen.

**De risicostand is per run en zit in het geheugen,** niet in de tabellen van fase 1. Vier
stressvarianten over hetzelfde corpus zouden anders in elkaars dagstand gaan zitten. De
tabellen van fase 1 zijn voor het echte lab; een simulatie houdt zijn eigen boekhouding.

### De stresstest

Vier varianten over hetzelfde corpus met hetzelfde zaad: `base`, `slippage_2x`,
`latency_2x`, `both_2x`. Het toeval van de strategie komt uit een **eigen generator**, los
van het fill-model, zodat alle vier exact dezelfde instappen proberen. Dat is wat de
vergelijking geldig maakt; zouden de instappen ook verschillen, dan vergelijk je twee
strategieën in plaats van twee werelden. Er is een test op (`test_de_varianten_proberen_dezelfde_instappen`).

De faalkans staat met opzet **niet** in de stress: zou die ook opschroeven, dan weet je bij
een slechter resultaat niet meer waar het vandaan komt.

### Expectancy met een interval (`app/quantlab/metrics.py`)

De cultuurregel uit de opdracht staat in code: geen claim zonder N, kosten en
onzekerheidsmarge. Het 90%-interval komt uit een **bootstrap** en niet uit een formule,
omdat de verdeling van R-uitkomsten scheef is met een lange staart — een normale benadering
gaat daar precies de verkeerde kant op.

Onder de drempel uit de hypothese (150 trades) zegt het oordeel "te vroeg". Dat is geen
bescheidenheid maar rekenkunde.

### Nieuw in de database en de API

Vijf tabellen in migratie `0008_quant_lab_papieren_handel`: `quant_hypotheses`,
`quant_strategy_runs`, `quant_signals`, `quant_paper_trades`, `quant_paper_fills`.

```
GET /api/quant/hypotheses                      de registratie met de hashes
GET /api/quant/hypotheses/{id}                 één hypothese, met het hele bestand
GET /api/quant/paper/runs                      de runs, met de afdruk van hun corpus
GET /api/quant/paper/runs/{id}/expectancy      N, expectancy, interval, oordeel
GET /api/quant/paper/runs/{id}/skipped         de signalen die níét zijn genomen
GET /api/quant/paper/trades                    de trades
GET /api/quant/paper/trades/{id}/fills         verwacht versus gesimuleerd, per order
```

Alle zeven achter `quant.read` (tier 2), met een expliciet responsemodel.

---

## 2. Bewijs

### 2.1 Testoutput

```
$ cd backend && .venv/bin/python -m pytest -q
486 passed in 232.34s (0:03:52)

$ .venv/bin/python -m pytest tests/test_quant_fills.py tests/test_quant_paper.py -q
88 tests
```

Voor fase 3 waren het 398 tests. Eén bestaande test is aangepast (zie §3).

### 2.2 H0 end-to-end, en de vier stressvarianten

`backend/scripts/quant_paper_proof.py` tegen PostgreSQL 16. Drie dagen synthetische data,
866 pools die doorlopend opengaan en na een uur ophouden:

```
1. Drie dagen synthetische data opnemen
  events: 155756, ticks: 155756
  pools in het corpus: 866 (doorlopend nieuwe, elk een uur actief)
  corpusafdruk: d078270d5ad2c6cd1e110d71b775c2ab5654eca36693366bf6805469e0c413b9

2. H0 in vier stressvarianten over hetzelfde corpus
  hypothese: H0_v1  hash 76b4903c051e5bbb...

  variant      signalen  trades gesloten gewaardeerd       R  drawdown   fees $   slip $
  base             2061     263      263           4  25.2563   8.6458   28.713   73.218
  slippage_2x      2061     261      261           4  13.4765  13.1387   28.509  146.873
  latency_2x       2061     263      263           4  25.2563   8.6458   28.713   73.218
  both_2x          2061     261      261           4  13.4765  13.1387   28.509  146.873
```

2061 signalen in alle vier de varianten — exact gelijk, dus het enige verschil is het
fill-model. Twee keer slippage halveert de opbrengst (25,3R → 13,5R) en verhoogt de drawdown
(8,6R → 13,1R). "Gewaardeerd" zijn de vier posities die aan het eind van het corpus nog open
stonden; die zijn op de laatst bekende prijs afgerekend en apart geteld, want het zijn geen
uitstappen volgens een regel.

### 2.3 Waarom signalen niet zijn genomen

```
3. Waarom signalen niet zijn genomen
  risk_veto                     618
  sellability_unverified        430
  already_in_position           375
  safety_failed                 364
  fill_failed                    11
  genomen                       263

  risicolaag: maximaal 5.0000R tegelijk open (grens is 5R)
```

Dit is het belangrijkste tabelletje van de hele fase. 618 keer heeft de risicolaag uit fase 1
een instap geblokkeerd, en het open risico raakte precies de grens van 5R en ging er niet
over. 430 keer ging een token eruit omdat de verkoopbaarheid niet te verifiëren was — geteld,
niet aangenomen. En 11 transacties mislukten, met de kosten wel geboekt.

### 2.4 Verwachte versus gesimuleerde fill

```
  trade 155 in pool-3  stop  R=-1.1314
    order              verwacht           markt            fill    slip $   klok $   fee $    ms
    entry/entry  0.000207396224  0.000203910483  0.000205365248  0.195513 -0.468465  0.051   609
    exit/stop    0.000153516192  0.000148924893  0.000148036588  0.119383  0.617046  0.051   725

  trade 153 in pool-2  stale_data  R=-0.0494
    entry/entry  0.001796977479  0.001738107843  0.001745400933  0.115326 -0.930905  0.051  2056
    exit/stale_data 0.001737548260 0.001737548260 0.001730297184 0.114661  0.000000  0.051     0
```

Trade 155 verloor 1,13R terwijl de stop op −1R stond. Dat is correct en het hoort zo: de
stop wordt uitgevoerd tegen slippage, en de prijs na de vertraging lag onder de stop. Een
simulatie waarin een stop altijd exact −1R kost, is te mooi.

### 2.5 Expectancy — en wat een controlegroep hoort te doen

```
  base:        N=263, expectancy 0.0960R, 90%-interval [-0.0120, 0.2079], winrate 0.4639, kosten $101.93
  slippage_2x: N=261, expectancy 0.0516R, 90%-interval [-0.0549, 0.1554], winrate 0.4253, kosten $175.38

  Over 263 trades is de expectancy 0.0960R, maar de ondergrens van het 90%-interval ligt op
  -0.0120R. Daarmee is nul niet uitgesloten.
```

**Dit is het resultaat waar ik op hoopte.** H0 stapt willekeurig in, en nul zit in het
interval. Een controlegroep die geld verdient, zou betekenen dat het kostenmodel te mild
staat — en dat was precies wat er eerst gebeurde (§3.1). Onder twee keer slippage zakt de
expectancy naar 0,05R en wordt het interval breder naar de verkeerde kant.

### 2.6 De latency-stresstest doet bij 20 seconden per tick niets

Dit viel me op in de cijfers van §2.2: `latency_2x` is tot de laatste decimaal gelijk aan
`base`. Dat is geen bug maar een grens van de data. Een fill valt op de eerste tick ná de
vertraging; is de cadans 20 seconden en de vertraging 800 of 1600 milliseconden, dan is dat
allebei dezelfde volgende tick.

Met een tick per seconde valt het verschil wél ergens:

```
7. De latency-stresstest heeft fijnere data nodig
  variant       trades         R    slip $
  base              11    2.5100  3.321943
  slippage_2x       11    1.8348  6.580702
  latency_2x        11    1.4023  3.269693
  both_2x           11    1.1064  6.514179

  latency_2x gelijk aan base: False  (bij een cadans van 20 seconden was dit wel zo)
```

**Gevolg voor de databron:** om latency te kunnen meten heeft het lab data met
sub-seconde-resolutie nodig, dus trade-events en niet prijs-snapshots per 20 seconden. Dat
is een eis aan de bron die ik zonder deze meting niet had geweten.

### 2.7 De migratie

```
$ .venv/bin/python -m alembic upgrade head
Running upgrade 0007_quant_lab_datalaag -> 0008_quant_lab_papieren_handel

$ .venv/bin/python -m alembic check
No new upgrade operations detected.

$ alembic downgrade 0007_quant_lab_datalaag && alembic upgrade head
(beide zonder fout)
```

---

## 3. Afwijkingen van de prompt, en waarom

### 3.1 Drie fouten in mijn eigen werk, gevonden tijdens deze fase

Deze horen bovenaan, niet onderaan.

**(a) Mijn synthetische prijsreeks had een drift, en daardoor won élke instap.** De stap was
`prijs × (1 + u)` met `u` uit `uniform(−0,04, +0,045)`. Gemeten logdrift: **+0,0022 per
stap**, en over een etmaal met 4320 stappen is dat een factor **15.800**. De eerste H0-run
kwam uit op **+8,0R expectancy met een winrate van 100%** over 5 trades. Dat ziet er
geloofwaardig uit en berust op niets.

Opgelost door `prijs × exp(u)` met `u` symmetrisch om nul: de verwachte logbeweging is nul en
de mediaanprijs blijft staan. Er staat nu een test op
(`test_de_synthetische_bron_heeft_geen_drift`) die faalt bij een drift boven 0,0005 per stap.

Wat dit zegt over de opzet: de opdracht waarschuwt dat een H0 die geld verdient betekent dat
de kosten te laag staan. In dit geval was het de data, niet de kosten — maar het was precies
dezelfde waarschuwingsbel, en hij werkte.

**(b) Posities in een pool die stopte met ticken werden nooit gesloten.** Een pool bloedt
dood, er komen geen ticks meer, dus de stop wordt nooit geraakt — er is immers geen tick om
hem op te raken. De positie bleef hangen tot het eind van het corpus en werd dan afgerekend
tegen een prijs van uren eerder. Trades verloren zo **meer dan 3R terwijl de stop op −1R
stond.**

Opgelost met dezelfde gedachte als de dead-man switch uit fase 1: hoort het lab een kwartier
niets van een pool, dan gaat de positie dicht op de laatst bekende prijs, met reden
`stale_data`, apart geteld. Stilte is geen rust. Twee tests op
(`test_een_positie_in_een_stille_pool_gaat_dicht` en
`test_geen_enkele_trade_verliest_veel_meer_dan_1r`).

**(c) De gedwongen sluiting aan het eind van het corpus faalde stil.** Hij ging door het
normale fill-pad, dat de prijs ná de vertraging opzoekt — en die bestaat niet voorbij het
eind van het corpus. De fill mislukte, de opbrengst werd niet geboekt, en de trade werd
afgerekend alsof hij voor niets was verkocht. Dit was de werkelijke oorzaak van de −21R die
ik in de eerste proef zag.

Opgelost met `FillModel.mark_to_market()`: een expliciete **waardering** zonder vertraging en
zonder kans op falen, wél met slippage en haircut, apart gemarkeerd in de boekhouding. Doen
alsof er een order is verstuurd die we hebben zien landen, zou een getal opleveren dat
nergens op berust.

### 3.2 Twee prestatiefouten, en wat ze kostten

**De ingest deed één query per event.** `store_events` zocht per event of dezelfde payload al
bestond. Bij 155.000 events zijn dat 155.000 losse SELECT's; het opnemen van drie dagen data
liep na tien minuten nog. Nu één query per batch van 5000 hashes:

```
155756 events in 39.7s = 3926 events/s
```

Daarbij liep ik tegen iets dat SQLite nooit had laten zien: **PostgreSQL staat hoogstens
32767 parameters per query toe.** Eén `IN`-clausule met alle hashes klapte eruit. Nu in
stukken, en `record()` schrijft in batches van 2000 weg. Hetzelfde gold voor het opruimen:
dat gebruikt nu een subquery in plaats van een lijst met id's.

**`normalize_pending()` las bij elke batch de hele tickstabel.** De `NOT IN`-subquery is
vervangen door een grens op het hoogste al genormaliseerde id — dat kan, omdat er altijd in
volgorde wordt genormaliseerd.

Dit is ook de reden dat het naschrift boven `phase2-report.md` staat: de afdrukken in dat
rapport horen bij de oude bron en komen er nu anders uit. De conclusie van fase 2 (een
opgenomen uur is bit-voor-bit herhaalbaar) staat nog; de getallen zijn verouderd.

### 3.3 Keuzes die de opdracht openliet

1. **`stop_distance_pct: 0.25` is mijn getal, niet het jouwe.** De opdracht noemt "harde stop
   op −1R" maar geen afstand, en een afstand moet er zijn: samen met 1R bepaalt die de
   positiegrootte. 25% is een ongetuned startwaarde voor een token van minuten oud. Hij staat
   in het hypothese-bestand en telt mee in de hash, dus veranderen = nieuwe versie = teller
   opnieuw. **Zie open vraag 1.**

2. **`trailing_stop_pct: 0.20` en `max_hold_minutes: 240` idem.**

3. **De equity groeit niet mee tijdens een run.** 1R blijft dus constant. Dat is bewust: het
   maakt de vier stressvarianten vergelijkbaar, en compounding bij N onder de 150 voegt
   variantie toe zonder informatie. Bij een langere reeks hoort dit wel mee te groeien.

4. **Geen `Strategy` voor H1.** Fase 3 is "paper broker en H0"; de Screener die H1's
   entry-trigger uitvoert staat in fase 4. H1_v1 is wel geregistreerd en gehasht.

5. **Eén bestaande test aangepast:** `tests/test_sanitization.py`. Die weigert velden waarvan
   de naam naar een geheim ruikt, en ving `content_hash` (op `_hash`) en `token_address` (op
   `token`). Beide zijn openbaar — een pre-registratiehash hóórt na te kijken te zijn, en een
   tokenadres staat op elke blockexplorer. Met een reden in de bestaande uitzonderingenlijst
   gezet; dat is waar die lijst voor is, en dat de test ze ving is een goed teken.

---

## 4. Bekende problemen en risico's

1. **Niets hiervan is tegen echte data getest, en dat blijft het hoofdprobleem.** Het
   netwerk is nog dicht (fase 2 §4.1). Een fill-model dat alleen tegen synthetische
   pooldiepte is getest, zegt niets over echte slippage. De vorm van het model is nu wel
   verdedigbaar; de hoogte van de kosten is dat niet.

2. **Geen enkele van de acht kostenparameters is geverifieerd.** Ze staan met hun herkomst in
   het hypothese-bestand, en de stresstest laat zien hoeveel ze uitmaken: twee keer slippage
   halveert de opbrengst van H0. Bij H1 zal dat harder aankomen, want een sniper handelt
   vaker.

3. **De latency-stress is bij 20-seconden-data zinloos** (§2.6). Dat is nu gemeten en niet
   vermoed, en het is een harde eis aan de databron: trade-events, geen snapshots.

4. **De pooldiepte is afgeleid uit de gerapporteerde liquiditeit,** niet uit de werkelijke
   reserves. Dat is één afleiding meer dan nodig. Heeft de bron de reserves, gebruik die.

5. **De engine leest het hele corpus in het geheugen.** 155.000 ticks gaat; een maand gaat
   niet. Dan moet `load_ticks` een generator worden die per dag leest. Niet nu opgelost, want
   een voorbarige optimalisatie op een corpus dat nog niet bestaat.

6. **De stresstest draait seriëel en herhaalt het werk vier keer.** Drie dagen × vier
   varianten duurde ongeveer vier minuten. Bij een maand is dat een uur. Oplosbaar, maar pas
   als het pijn doet.

7. **`already_in_position` sloeg 375 signalen af.** Dat is correct — één positie per pool —
   maar het betekent dat de instapkans in een krap universum vooral door bezetting wordt
   bepaald en niet door de strategie. Bij een echte feed met honderden nieuwe pools per uur
   is dat minder nijpend; bij H1 moet er bij de evaluatie naar gekeken worden.

8. **De synthetische bron blijft in de code staan.** Nu met drift-test en een waarschuwing in
   het kwaliteitsrapport. Zodra er echte data is, hoort een hypothese-run te **weigeren** op
   een corpus met synthetische events. Dat is één regel en hij staat op de lijst voor de fase
   waarin dat kan.

9. **H0's `attempts_per_hour` staat in het hypothese-bestand op 6, maar de proef draaide met
   30** (via een override). Dat is een steekproefgrootte en geen edge-parameter, maar het is
   wel een afwijking van het geregistreerde bestand. Voor een echte H0-run hoort die waarde
   in het bestand te staan en dus in de hash.

---

## 5. Open vragen voor Stef

1. **De stopafstand van 25% — klopt dat ongeveer?** Dit is het enige getal in de hypothese
   dat de positiegrootte bepaalt, en het is van mij. Bij 1R = €7,50 (de huidige papieren
   inleg) betekent 25% een positie van €30. Zet je de stop op 15%, dan wordt de positie €50
   en raakt hij vaker. Ik heb geen reden om 25% boven 15% of 35% te verkiezen; jij hebt meer
   gevoel voor hoe hard een memecoin van tien minuten oud beweegt.

2. **De netwerkpolicy.** Nog steeds de vraag die alles blokkeert. En nu met een extra eis:
   de bron moet **trade-events met sub-seconde-timestamps** geven, niet prijs-snapshots per
   20 seconden — anders is de latency-stresstest zinloos (§2.6).

3. **Heb je ergens een opname van echte data?** Een export in JSONL of CSV met trades en
   pooldiepte zou genoeg zijn om fase 3 te valideren zonder op het netwerk te wachten. De
   `jsonl`-bron uit fase 2 leest hem zo in.

4. **De papieren inleg.** Nog steeds €1.000 en dus 1R = €7,50. Dit staat nu voor de derde
   keer in een rapport; het bepaalt of het filter "liquiditeit ≥ 50× de positiegrootte" iets
   betekent.

5. **De vragen uit fase 1 staan nog open:** de prijs van JEV.ai, en of de €200 per maand
   exclusief de bouwkosten is.

---

## Hoe je dit zelf nakijkt

```bash
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt

# alles
.venv/bin/python -m pytest -q

# alleen het fill-model (de unit tests uit de acceptatie-eis)
.venv/bin/python -m pytest tests/test_quant_fills.py -v

# alleen de paper broker en H0
.venv/bin/python -m pytest tests/test_quant_paper.py -v

# H0 end-to-end tegen een echte database (schrijft rijen, ruimt ze daarna op)
createdb ganz_proef
export GANZ_DATABASE_URL=postgresql+asyncpg://ganz:ganz@localhost:5432/ganz_proef
.venv/bin/python -m alembic upgrade head
.venv/bin/python -m scripts.quant_paper_proof
```

---

Fase 3 is hiermee af, voor zover het zonder echte data af kan. Ik wacht op **"Start Fase 4"**.

Eén ding om mee te nemen: de drie fouten in §3.1 zijn gevonden doordat een getal te mooi
was. +8R met een winrate van 100% op willekeurige instappen is niet geloofwaardig, en dat was
de aanleiding om te gaan zoeken. Als er in een later rapport een cijfer staat dat te mooi
lijkt, is dat precies de reactie die ik ervan verwacht.

---

# Naschrift: dollars, en de stop per trade

Na jouw antwoord op "is 25% aanbevolen?" zijn er drie dingen gewijzigd. **504 tests groen,
17 nieuw.**

## 1. Alles in dollars

De papieren rekening staat nu in dollars (`GANZ_QUANT_PAPER_EQUITY_USD`, standaard $1000,
dus 1R = $7,50). In het hele handelspad wordt niets meer omgerekend.

Dat is geen cosmetische wijziging: de omrekening die er zat, ging de verkeerde kant op (zie
§3.2 hierboven). De oplossing is niet een betere omrekening maar géén omrekening — elke
omrekening in het handelspad is een plek waar een koers kan omkeren zonder dat het opvalt.
`one_r_eur()` heet nu `one_r_amount()`, want de functie rekent een percentage en hoort niet
te weten in welke valuta.

Het maandbudget voor de modellen blijft in euro's (€200, sectie 12), en daar blijft
`quant_usd_eur_rate` voor bestaan. De twee zijn nu strikt gescheiden: de handel in dollars,
het modelbudget in euro's, en geen koers die tussen die twee door het handelspad loopt.

## 2. De stop volgt per trade uit de structuur

`app/quantlab/stops.py`. Niet langer één percentage voor elk token, maar: **de stop komt
onder de bodem van het venster waar de koers uit kwam.** In één zin — de trade is weerlegd
als de koers terugvalt door het bereik waar hij uit kwam.

Een rustig token krijgt daarmee een krappe stop en een grote positie, een wild token het
omgekeerde, en in beide gevallen staat er precies 1R op het spel.

**Deterministische code, geen taalmodel.** Dat is geen keuze van mij maar sectie 6 van je
eigen opdracht: geen LLM-aanroep in het pad waarin een trade tot stand komt. De "agent" die
dit per trade bepaalt, is de Screener — en die is code.

Twee grenzen eromheen, en het verschil tussen die twee is belangrijk:

**De ondergrens van 20% is afgeleid, niet gekozen.** Bij een pool die precies aan het filter
"liquiditeit ≥ 50× de positie" voldoet, is de quote-kant 25× de positie, dus de price impact
van een constant-product pool is ongeveer 1/25 = 4%. De positie is 1R/stopafstand, dus de
slippage kost **0,04/stopafstand** van je 1R. Wil je daar hoogstens 20% van 1R aan
kwijtraken, dan moet de stop minstens 20% zijn. Bij 10% zou je 40% van je risicobudget aan
slippage verliezen voordat de trade iets heeft gedaan.

Die som staat in de code (`MIN_DISTANCE_DERIVATION`) met een test die hem naloopt, niet
alleen in dit rapport.

**De bovengrens van 50% is wél een gok.** Hij houdt tegen dat de helft pas bij een
verdubbeling eruit gaat (+2R is twee keer de stopafstand). Wat hier redelijk is, hangt af
van hoe hard een token van minuten oud werkelijk beweegt — en dat is niet gemeten.

Elke trade legt nu vast waar zijn stop vandaan kwam (`stop_basis`, `stop_distance_pct`,
`stop_clamped`). Zonder dat kun je bij een verlies niet nagaan waarom de positie zo groot
was.

`H0_v2.yaml` en `H1_v2.yaml` gebruiken deze vorm. `H0_v1` en `H1_v1` blijven bestaan en
blijven laadbaar, want **een structurele stop is alleen beter als je kunt laten zien dát hij
beter is** — en daarvoor moet je ertegen kunnen vergelijken.

## 3. En dat vergelijk valt niet uit zoals bedoeld

`backend/scripts/quant_stop_compare.py`, twee dagen synthetische data, hetzelfde zaad, dus
exact dezelfde instappen:

```
  hypothese  | stop                   | signalen | trades |         R |  drawdown |     slip $
  H0_v1      | vast 25%               |     1405 |    234 |   13.0655 |   24.2574 |  77.701355
  H0_v2      | per trade (structuur)  |     1405 |    254 |    9.3602 |   30.0660 | 113.223909

  H0_v1: stopafstand 0.2500-0.2500 (gemiddeld 0.2500) — tegen een grens aangelopen: 0 van 234
  H0_v2: stopafstand 0.2000-0.2989 (gemiddeld 0.2031) — tegen een grens aangelopen: 236 van 254
```

**236 van de 254 trades liepen tegen de ondergrens aan.** De structuur komt dus bijna nooit
aan het woord: de 10-minutenbodem lag meestal 3 tot 15% onder de instap, en dat is krapper
dan de afgeleide ondergrens van 20%. Op deze data is de "structurele" stop in de praktijk
een vaste stop van 20%.

Twee eerlijke lezingen, en ik weet niet welke het is:

1. **Mijn synthetische data beweegt te weinig.** Een echte memecoin van tien minuten oud
   doet meer dan 3% in tien minuten. Dan zou de bodem vaak onder de 20% liggen en krijgt de
   regel wel ruimte. In dat geval is dit resultaat een eigenschap van mijn random walk, niet
   van de regel.
2. **Het liquiditeitsfilter is de echte beperking.** Zolang "liquiditeit ≥ 50× de positie"
   geldt, kan een stop economisch niet krapper dan 20% — en dan maakt de structuur minder
   uit dan de pooldiepte. Dat zou betekenen dat de interessante knop het filter is en niet
   de stop.

Welke van de twee het is, is te beantwoorden met één uur echte data en niet met nog een
run op verzonnen data.

Verder uit dit vergelijk, en dit is gewoon de rekenkunde die je hebt goedgekeurd: de
gemiddelde positie ging van $30,00 naar $37,06 (krappere stop = grotere positie), en de
slippage ging daarmee van $77,70 naar $113,22. Slippage loopt op de liquiditeitsgrens
recht mee met de positie, dus dat hoort zo.

## 4. Nog twee dingen die ik onderweg vond

**Ik las bijna een verkeerd getal voor.** In het proefscript liepen twee kolommen aan elkaar
vast (`30.066113.223909`), en ik las de slippage eerst als $13,22 in plaats van $113,22 — een
factor 8,5 de verkeerde kant op, en in de richting die het resultaat mooier maakte. Ik heb
het nagerekend tegen de database voordat ik het opschreef, en toen bleek het de opmaak. De
kolommen hebben nu een scheidingsteken. Dat is geen grote fout, maar het is wel precies de
route waarlangs een verzonnen cijfer in een rapport belandt.

**Het liquiditeitsfilter en de uitstap-haircut zijn niet op elkaar afgestemd.** Het filter
zegt "liquiditeit ≥ 50× de positie", dus de positie is 2% van de pool. De haircut gaat aan
boven 1% van de pool. Die twee samen betekenen dat de haircut bij élke trade op de
liquiditeitsgrens afgaat. Ik heb dat **niet** gewijzigd, en dat is een keuze: de haircut
vaker laten afgaan is de conservatieve kant, en conservatief is bij een paper broker de
juiste kant om fout te zitten. Maar het is geen bewuste afstemming, en als je wil dat
posities onder 1% van de pool blijven, moet het filter naar 100×. Zeg het als je dat wil.

## 5. Wat dit betekent voor de open vragen

Vraag 1 uit §5 hierboven ("klopt de stopafstand van 25%?") is hiermee vervallen: er is geen
vast percentage meer. Wat ervoor in de plaats komt:

1. **De bovengrens van 50% is nu de enige gok in de stopregel.** Hij bepaalt wanneer een
   token te wild is om te handelen. Heb je een gevoel voor waar die grens hoort te liggen?
2. **Wil je het liquiditeitsfilter op 50× houden of naar 100×?** Zie §4. Op 50× gaat de
   haircut altijd af; op 100× blijft de positie onder de haircut-drempel maar vallen er meer
   pools af.
3. Het netwerk, en de twee vragen uit fase 1 (JEV-prijs, en of de €200 exclusief bouwkosten
   is) staan nog open.
