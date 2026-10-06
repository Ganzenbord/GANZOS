# Data: wat er bereikbaar is, en waarom scrapen niet het antwoord is

Je vroeg of we ergens data kunnen scrapen. Ik heb het systematisch nagemeten in plaats van
gegokt. Het antwoord bestaat uit drie delen.

---

## 1. Vanuit deze omgeving: niets, behalve GitHub

Gemeten op 6 oktober 2026. `000` betekent dat de verbinding wordt geweigerd door de
egress-proxy (organisatiebeleid), niet dat de site stuk is.

| Host | | Wat het zou geven |
| --- | --- | --- |
| `data.binance.vision` | `000` | gratis bulk-historie, minuut- en seconde-candles |
| `api.binance.com` | `000` | klines, trades |
| `api.kraken.com` | `000` | OHLC, trades |
| `api.bybit.com` | `000` | OHLC, trades |
| `api.coinbase.com` | `000` | candles |
| `api.coingecko.com` | `000` | dagcandles, marktgegevens |
| `price.jup.ag` | `000` | Solana spotprijzen |
| `api.mainnet-beta.solana.com` | `000` | chaindata, pooldiepte, houders |
| `huggingface.co` | `000` | datasets |
| `kaggle.com` | `000` | datasets |
| `www.cryptodatadownload.com` | `000` | CSV-historie |
| **`github.com`** | **werkt** | repo's en bestanden |
| **`raw.githubusercontent.com`** | **werkt** | losse bestanden |
| `api.anthropic.com` | werkt | modellen (zonder sleutel) |
| `pypi.org` | werkt | pakketten |

**Scrapen is hier dus onmogelijk**, van welke bron ook. Niet omdat ik het niet zou willen
proberen, maar omdat er geen verbinding tot stand komt. Eén poort staat open en dat is
GitHub.

## 2. Via GitHub heb ik wél echte data gevonden — maar niet wat H1 nodig heeft

Twee datasets gecontroleerd en echt bevonden:

**`ErcinDedeoglu/crypto-market-data`** (CC BY 4.0, vandaag nog bijgewerkt). Ongeveer dertig
BTC-metrics op dagbasis: exchange netflow, whale ratio, funding rates, open interest,
liquidaties, MVRV, Coinbase-premium. Nagerekend: de funding rates hebben **1.404 dagpunten
van 2022-12-03 tot vandaag**. Echte data, netjes gedocumenteerd.

Waarom het niet genoeg is: er zit **geen prijsreeks in**. Het zijn indicatoren, geen OHLCV.
Je kunt er geen trade op simuleren, want er is geen prijs om tegen in te stappen. En het is
dagbasis, dus zelfs mét prijzen zou H1 er niet op kunnen draaien.

**`SystemsLab-Sapienza/pump-and-dump-dataset`** (peer-reviewed, ICCCN 2020). Gelabelde
pump-and-dump-gebeurtenissen van Telegram-groepen: symbool, groep, datum, uur, exchange. Dat
is echte grondwaarheid over marktmanipulatie, en inhoudelijk het naast bij wat H1 probeert
te vangen.

Waarom het niet genoeg is: de **labels** staan in de repo, de **transacties niet** — die
moet je bij Binance downloaden, en Binance is geblokkeerd. Ik heb dus de antwoorden zonder
de data. Bovendien gaat het om SYM/BTC-paren op centrale exchanges in 2017-2020, een andere
markt dan Solana-memecoins nu.

## 3. Wat ik wél heb gevonden, en dat is meer waard

Via GitHub vond ik **`vybenetwork/solana-ohlc-api`**: de referentie-implementatie van een
aanbieder die precies de markt van H1 bedient — Solana SPL en Token-2022, met Raydium,
Meteora, LaunchLab en pump.fun in de onderwerpen. Een gratis sleutel is er.

Ik kan de API niet bereiken (`api.vybenetwork.xyz` gaat ook door de proxy), maar ik kan de
**broncode van de leverancier zelf** lezen. Daarmee ken ik de endpoints, de parameters en de
responsevormen uit werkende code in plaats van uit mijn hoofd. Dat was de blokkade: ik kan
geen adapter schrijven tegen een vorm die ik nooit heb gezien, want dan bouw ik iets dat er
werkend uitziet en bij de eerste echte respons omvalt.

**Die adapter staat er nu**, met 19 tests: `app/quantlab/sources/vybe.py`.

### Drie valkuilen die ik vond door de code te lezen

Deze had ik met alleen documentatie gemist, en elk ervan zou het lab stilzwijgend verkeerd
hebben laten rekenen.

**1. Het candles-endpoint liegt standaard over gaten.** `/v4/tokens/{mint}/candles` heeft een
parameter `eliminateCloseToOpenGaps` die **standaard op `true`** staat. Die vult gaten op
door de vorige slotkoers als nieuwe openingskoers te gebruiken. Voor een chart is dat
netjes; voor dit lab poetst het precies de gaten weg die de datakwaliteitscontrole uit fase
2 moet vinden. **Daarom gebruikt de adapter `/v4/trades` en niet de candles.**

**2. De klok van een trade is de slot, niet de tijd.** `blockTime` is een Unix-tijd in
**seconden**, en binnen één seconde vallen meerdere trades. De exacte ordening is
`(slot, txIndex, ixOrdinal, interIxOrdinal, iixOrdinal)`. Dat is ook het antwoord op de eis
uit het fase 3-rapport: de latency-stresstest heeft sub-seconde-ordening nodig, en die zit
hier in de slot (ongeveer 400 ms) en niet in de tijdstempel.

**3. `price` is niet in dollars.** Het is de prijs van het basis-token in het **quote**-token.
Bij een pool tegen SOL is dat een prijs in SOL. De adapter boekt alleen een dollarprijs als
het quote-token een bekende dollarstablecoin is (USDC of USDT, op mint-adres en niet op
symbool — een token dat zich "USDX" noemt is geen dollar). Anders blijft de prijs leeg.

> Een prijs in de verkeerde eenheid is erger dan geen prijs: hij is plausibel, hij rekent
> door, en niemand ziet het.

En één gat dat blijft staan: **een trade zegt niets over de diepte van de pool.** H1 heeft
die nodig voor het filter "liquiditeit minstens 50× de positie". Die komt uit een ander
endpoint. Tot dat er is, blijft `liquidity_usd` leeg en blokkeert het filter elke instap —
dat is de juiste kant om fout te zitten.

---

## Waarom scrapen ook mét netwerk niet het antwoord is

Stel dat de policy opengaat. Dan nog zou ik niet scrapen, en niet uit braafheid:

- **Websites van aggregators renderen uit een API.** Je scrapet dus een omweg naar dezelfde
  gegevens, met HTML ertussen die morgen verandert. Een gedocumenteerde API met een sleutel
  is stabieler en sneller.
- **De voorwaarden verbieden het meestal**, terwijl diezelfde partij een gratis API-laag
  heeft. Je neemt een risico voor iets wat je gewoon mag krijgen.
- **Voor H1 bestaat de data niet op een pagina.** Nieuwe pools, pooldiepte, de verdeling over
  houders en trades per seconde — dat staat op geen enkele site die je kunt scrapen. Dat komt
  uit een API of uit een eigen chain-node.

Er is één uitzondering waar "scrapen" wel het juiste woord is: **je eigen Solana-node of een
streaming-aanbieder uitlezen**. Dat is geen scrapen van iemands website maar meelezen op de
chain, en dat is precies wat de Scout uit fase 2 doet — hij heeft alleen nog geen bron.

---

## Wat ik je concreet zou vragen

In volgorde van wat het meest oplevert:

1. **Een gratis Vybe-sleutel** (`vybe.fyi/api-pricing`) **plus `api.vybenetwork.xyz` open in
   de netwerkpolicy.** Dan draait de adapter die er nu staat, op de markt waar H1 over gaat,
   met trades op slot-niveau. Dit is de kortste weg van "verzonnen data" naar "echte data".
   Nog te verifiëren zodra dat kan: de rate limits, hoe diep de historie gaat, en of de
   gratis laag de trades-endpoint bevat.

2. **Of: `data.binance.vision` open.** Gratis, geen sleutel, bulk-ZIP's met minuut- en
   zelfs secondecandles van honderden paren. Dat test H1 niet (geen memecoins), maar het
   geeft wel **echte volatiliteit** om de hele machinerie tegen te meten in plaats van mijn
   random walk. Daarmee is ook de openstaande vraag uit fase 3 te beantwoorden: bindt die
   ondergrens van 20% in de stopregel ook op echte data bijna altijd, of alleen bij mijn te
   rustige generator?

3. **Of: exporteer zelf een bestand** op een machine waar het netwerk wel open is, en zet het
   in de repo of geef het aan mij. De `jsonl`-bron uit fase 2 leest het zo in. Eén uur echte
   trades van één pool is al genoeg om de replay en de datakwaliteitscontrole op echte data
   te laten zien.

Optie 1 is het antwoord op de lange termijn. Optie 2 of 3 is de snelste manier om deze week
iets echts te meten.

---

# Naschrift, 6 oktober 2026: de Binance-weg staat klaar

Je koos optie 2. Hieronder wat er nu staat, wat jij moet omzetten, en wat deze data wél en
niet kan beantwoorden.

## Wat er gebouwd is

| | |
| --- | --- |
| `app/quantlab/sources/binance.py` | de adapter: URL's, het lezen van een ZIP, candles en trades naar ticks |
| `scripts/quant_binance.py` | `download` (met checksumcontrole) en `import` (zonder netwerk) |
| `tests/test_quant_binance.py` | 37 tests, offline |

Alles is geverifieerd tegen Binance' **eigen** repo `binance/binance-public-data` — de
README, `python/utility.py` en `python/enums.py`, gelezen op 6 oktober 2026. Dat is een stap
verder dan bij de Vybe-adapter, waar ik de vorm uit een voorbeeldimplementatie moest halen.
De kolomindeling, de URL-opzet, de bestandsnamen, de intervallen en de checksum komen uit
hun documentatie, niet uit mijn hoofd.

Wat ik **niet** heb kunnen verifiëren: of een echt bestand ook werkelijk zo is. De host is
nog geblokkeerd, dus er is geen enkele regel echte Binance-data door deze code gegaan. De
vorm is geverifieerd, de werkelijkheid niet.

## Wat jij moet omzetten

Eén host erbij in de netwerkpolicy van deze omgeving: **`data.binance.vision`**.

In de Claude-app: het menu van de cloud-omgeving in de titelbalk → *Edit* → **Network
access**. Kies *Custom* en zet `data.binance.vision` bij **Allowed domains** (de
standaardlijst met pakketbronnen laat je staan), of kies een ruimere toegang. De stappen
staan bij https://code.claude.com/docs/en/cloud-environments#network-access — ik kan er zelf
niet bij.

Gemeten vandaag: `HTTP 403` van de proxy, dus nog steeds dicht. Zodra het open is:

```bash
cd backend
python -m scripts.quant_binance download --symbol BTCUSDT --interval 1m \
    --from 2026-09-01 --to 2026-09-30 --dir ../data/binance
python -m scripts.quant_binance import --symbol BTCUSDT --interval 1m --dir ../data/binance
```

Gaat het niet open, dan werkt de andere weg ook: download de ZIP's op je eigen Mac of pc
(een gewone `curl`, geen sleutel nodig), zet ze in een map, en `import` leest ze zonder
netwerk in. Het script controleert dan nog steeds de checksum.

## Wat deze data wel en niet kan beantwoorden

**Niet H1.** Binance-spot heeft geen nieuwe memecoinpools, geen pooldiepte en geen
houdersverdeling. De hypothese over tokens van tien minuten oud is hier niet te testen.

**Wel drie dingen die nu open staan:**

1. **Echte volatiliteit in plaats van mijn random walk.** De generator uit fase 2 is te
   rustig en dat heeft me al een keer genaaid: met een drift van 0,0022 per stap haalde H0
   +8,0R met honderd procent winrate. Op echte prijzen is zo'n uitkomst meteen verdacht.
2. **De openstaande vraag uit fase 3**: bindt de ondergrens van 20% in de stopregel ook op
   echte data bijna altijd, of was dat een artefact van mijn generator? Dat is met
   minuutcandles van een willekeurig paar te meten.
3. **De latency-stresstest werkt eindelijk.** Bij een cadans van twintig seconden doet hij
   niets, want 800 en 1600 milliseconden vallen op dezelfde volgende tick. Binance heeft
   `1s`-candles, en in de `trades`-bestanden staat elke trade met zijn eigen tijdstempel tot
   op de microseconde. Daarvoor staat er ook een `BinanceTradesNormalizer`.

## Drie valkuilen die in de code zitten omdat ze echt zijn

**1. De tijdstempels zijn vanaf 1 januari 2025 in MICROseconden, daarvoor in milliseconden.**
Binance zegt dat zelf in hun README. Reken je met de verkeerde eenheid, dan komt een bestand
uit 2024 in 1970 terecht en een bestand uit 2025 in het jaar 56000 — en in beide gevallen
zijn het nog steeds getallen die er plausibel uitzien. `to_datetime()` kiest de eenheid per
waarde op het aantal cijfers, en weigert een getal dat in geen van beide eenheden een
plausibel jaar oplevert. Dat is de eerste test in het bestand.

**2. De tick krijgt de slottijd van de candle, niet de openingstijd.** Dit had ik eerst
andersom en het was fout. De slotkoers was pas waar aan het eind van het interval; zou de
tick op de openingstijd staan, dan ziet de engine bij minuutcandles zestig seconden lang een
prijs die nog niet bestaat. Dat is gratis vooruitkijken, en precies het soort fout dat een
backtest mooi maakt en waardeloos. De test die dit vastlegt, zegt nu ook waarom.

**3. Een paar tegen BTC of ETH is geen dollarprijs.** `BTCUSDT` wel, `ETHBTC` niet. Is het
quote-token geen dollarstablecoin, dan blijft `price_usd` leeg — dezelfde regel als bij de
Vybe-adapter, en om dezelfde reden: een prijs in de verkeerde eenheid is erger dan geen
prijs, want hij is plausibel, hij rekent door, en niemand ziet het.

En net als bij Vybe blijft **`liquidity_usd` leeg**: volume is geen diepte. Het filter
"liquiditeit minstens 50× de positie" heeft orderboekdiepte nodig, en die staat niet in een
candle. Leeg laten blokkeert de instap, en dat is de juiste kant om fout te zitten.

## De checksum is wat echte data van nepdata onderscheidt

Ik heb de machinerie vandaag kunnen draaien door zelf een bestand te maken dat de **vorm**
van een Binance-bestand heeft, met verzonnen prijzen: 1.440 minuutcandles van een dag. Dat
ging er netjes door — 1.440 events, 1.440 ticks, ketting klopt, oordeel "ok", en de klok
liep van `00:00:59.999999` tot `23:59:59.999999`.

Wat daarbij opvalt en wat je moet weten: het kwaliteitsrapport meldde **"synthetische
events: 0"**, terwijl die data wel degelijk verzonnen was. De teller kijkt naar de naam van
de bron (`synthetic`), en een verzonnen bestand dat onder de naam `binance` binnenkomt, is
daarmee onzichtbaar. Dat is een blinde vlek en geen bug die ik kan wegprogrammeren: wat een
bestand bevat, is van buiten niet te zien.

Daarom is die `.CHECKSUM` meer dan netheid. **Het is het enige dat echte data van een
plausibel ogende nepversie onderscheidt**: alleen Binance kan een bestand publiceren
waarvan de SHA-256 overeenkomt met de SHA-256 die Binance ernaast publiceert. Het script
weigert daarom een bestand waarvan de hash niet klopt in plaats van het alsnog te bewaren,
en de hash van elk ingelezen bestand gaat mee in de ingest-run. Dat laatste is nodig omdat
Binance zelf zegt dat archiefbestanden later vervangen kunnen worden — dat is twee keer
gebeurd, op 2022-04-21 en 2022-08-08.

## Eén ding dat je moet weten voordat we hier veel op bouwen

De dataset staat onder **CC BY-NC-SA 4.0 — niet-commercieel**
(`TERMS_AND_CONDITIONS.md`, versie 1.0, bijgewerkt 26 augustus 2026). In gewone taal, met de
artikelnummers erbij zodat je het kunt nazoeken:

- **Mag wel** (4.1): "algorithmic historical backtesting for purely personal non-production
  research". Dat is precies wat dit lab is.
- **Mag niet** (4.2): gebruiken voor "live proprietary trading execution" of het verkopen
  van signalen. Dat raakt ons nu niet — er is in dit project geen live handel — maar het
  betekent wel dat een eventuele latere stap naar echt geld **een andere databron nodig
  heeft**, of een betaalde licentie bij Binance.
- **Mag niet** (4.4): verwerken in "commercial trading bot platforms" of betaalde
  producten. Deze data hoort dus **niet** in het commerciële deel van Broozing terecht te
  komen.
- **Verplicht** (4.5): deel je er iets van, dan met bronvermelding naar Binance Vision en
  onder dezelfde licentie.

De data zelf hoort hierom ook niet in de repository: hij blijft in een map ernaast
(`data/binance`, buiten git), net als `.env` en `tokens/`.

---

## Op de plank gelegd, 6 oktober 2026

Stef: *"oke leg maar op de plank dit."* Dit staat dus klaar en wacht; er wordt niet verder
aan gebouwd tot hij het weer oppakt.

**Wat er klaar ligt:** de adapter, het download- en importscript, 38 offline tests. De hele
testsuite is groen (654 tests). Niets hiervan heeft onderhoud nodig zolang het stilligt.

**Wat er ontbreekt:** één host in de netwerkpolicy, `data.binance.vision`. Dat is alles.

**De eerste drie stappen als het weer opgepakt wordt:**

1. Meet of de host open is (een GET op een `.CHECKSUM`-URL). Een 403 is ook een antwoord.
2. Controleer of de aannames nog kloppen — zie hieronder, ze hebben een houdbaarheidsdatum.
3. Eén dag echte minuutcandles van een liquide paar erdoor, en dan de drie vragen uit het
   naschrift beantwoorden (bindt de 20%-ondergrens, doet de latency-stresstest iets, hoe
   rustig was mijn generator eigenlijk).

**Wat er in de tussentijd kan verlopen.** Dit is de reden dat stap 2 niet overgeslagen mag
worden: alles hieronder is op één dag geverifieerd en kan daarna stil verschoven zijn.

| Wat | Geverifieerd op | Waar het staat |
| --- | --- | --- |
| Kolomindeling, URL's, intervallen, microseconderegel | 6 oktober 2026 | `binance/binance-public-data` |
| De licentie (CC BY-NC-SA 4.0, versie 1.0) | 6 oktober 2026 | hun `TERMS_AND_CONDITIONS.md` |
| De modelprijzen van Claude | 5 oktober 2026 | `app/quantlab/pricing.py` |

**De afspraak.** Er staat een eenmalige herinnering klaar die op **6 april 2027** een nieuwe
sessie start met de opdracht om hier precies die stappen te doorlopen en het resultaat in
gewone taal aan Stef te melden. Stef krijgt er een bericht van op zijn telefoon en per
e-mail. Wil hij ervan af of hem verzetten, dan kan dat bij *Routines* op claude.ai; de
herinnering heet "Binance-databron Quant Lab: terugkomen na zes maanden".
