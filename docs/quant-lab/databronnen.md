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
