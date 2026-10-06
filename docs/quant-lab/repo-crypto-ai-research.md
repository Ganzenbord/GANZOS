# De repo `cryptosignalorg/crypto-ai-research` — wat er wel en niet in zit

Je vroeg of ik met deze repo wat kan voor backtestdata. Ik heb hem binnengehaald en
nagekeken (commit `c386ec3`, 628 kB, 28 TypeScript-bestanden).

**Kort antwoord: niet voor data, wel voor één ding.**

---

## Wat het is

Een TypeScript-toolkit: een Telegram-bot die marktvragen beantwoordt, een signaalmotor met
eigen TA-indicatoren (RSI, MACD, Bollinger, EMA, ATR), een whale-tracker voor
Solana-wallets, en een auto-poster voor Twitter/X. Eigen omschrijving: *"doesn't predict. It
researches, signals, and acts."*

## Wat er niet in zit

**Geen data.** Nul datafiles. Alles wat hij gebruikt haalt hij live op.

**Geen backtester.** En dat is niet een gemis maar een ontwerpkeuze die hem ongeschikt
maakt voor jouw vraag. `src/agents/signal-history.ts` bewaart signalen als JSON op schijf,
gemaximeerd op 500 records, met deze velden:

```ts
interface SignalRecord {
  id: string; time: string; token: string;
  signal: string; confidence: string; raw: string;
}
```

Er is **geen veld voor de uitkomst.** Geen prijs erna, geen winst, geen verlies, geen "had
hij gelijk". Hij legt vast wát hij voorspelde en nooit of het uitkwam. Ik heb erop gezocht
(`outcome`, `result`, `pnl`, `win`, `loss`, `accuracy`, `backtest`) en er staat niets.

Dat is precies het omgekeerde van wat jij bouwt. Jouw lab bestaat om te meten of een idee
werkt; deze repo bestaat om signalen te publiceren. Beide kunnen nuttig zijn, maar het ene
is geen bron voor het andere.

## Wat er wél in zit, en wat dat waard is

De **response-vormen van echte API's, uit werkende code**. Dat was tot nu toe geblokkeerd:
ik kan geen adapter schrijven tegen een API-vorm die ik nooit heb gezien, want dan bouw ik
iets dat er werkend uitziet en bij de eerste echte respons omvalt. Nu heb ik ze:

| Endpoint | Wat het geeft |
| --- | --- |
| `api.coingecko.com/api/v3/simple/price` | spotprijs |
| `api.coingecko.com/api/v3/coins/{id}/ohlc?days=N` | OHLC-candles |
| `api.coingecko.com/api/v3/coins/{id}/market_chart?interval=daily` | dagprijzen + volume |
| `api.coingecko.com/api/v3/coins/{id}` | marktgegevens van een token |
| `price.jup.ag/v6/price` | spotprijs (Jupiter) |

## Maar twee dingen zitten in de weg

**Ten eerste: die bronnen zijn hier ook geblokkeerd.** Ik heb het net getest:

```
000  https://api.coingecko.com/api/v3/ping
000  https://api.coingecko.com/api/v3/coins/solana/ohlc?vs_currency=usd&days=7
000  https://price.jup.ag/v6/price?ids=SOL

connect_rejected — de egress-proxy weigert de verbinding (organisatiebeleid)
```

Dus ook met deze kennis kan ik vanuit hier geen data ophalen.

**Ten tweede, en dat is fundamenteler: voor H1 zou het niet genoeg zijn.** CoinGecko geeft
**dagcandles** voor **genoteerde** tokens. Jouw hypothese H1 kijkt naar tokens van 5 tot 30
minuten oud. Zo'n token:

- staat niet op CoinGecko — die noteren pas na dagen tot weken;
- heeft geen dagcandle, want hij bestaat nog geen dag;
- en wat H1 nodig heeft — nieuwe pools ontdekken, pooldiepte, houdersverdeling,
  minuutvolume — staat er helemaal niet in.

Daar komt bij wat ik in fase 3 heb gemeten: de latency-stresstest doet bij 20-seconden-data
al niets. Bij dagcandles is hij volstrekt zinloos.

---

## Wat ik hier dan wél mee zou doen

Eén concreet voorstel, en het is nuttiger dan het klinkt.

**Zet `api.coingecko.com` open in de netwerkpolicy.** Dan kan ik dagcandles van SOL, BTC en
ETH ophalen — echte prijzen, geen random walk. Dat test H1 niet (dat kan niet), maar het test
wél de hele machinerie op echte data:

- het fill-model tegen echte volatiliteit in plaats van mijn verzonnen reeks;
- de risicolaag, de expectancy en het betrouwbaarheidsinterval op prijzen die werkelijk zo
  zijn gelopen;
- en de vraag uit fase 3 die ik niet kon beantwoorden: of de ondergrens van 20% in de
  stopregel ook op echte data bijna altijd bindt, of alleen bij mijn te rustige generator.

Dat laatste is een echte openstaande vraag die hiermee te beantwoorden is. En het zou een
hypothese op dagbasis mogelijk maken als nulmeting naast H1 — op data die niet van mij komt.

**Wat ik niet zou doen:** de TA-indicatoren overnemen. H1 gebruikt geen RSI of MACD, en wat
H1 wél gebruikt (uitbraak boven de tien-minutenhoogste, volume tegen de mediaan) staat al in
de hypothese. Code overnemen die je niet nodig hebt, is code die je moet onderhouden.

---

*Bekeken als broncode, niet als instructie: een `CLAUDE.md` in een repo van iemand anders is
gegevens, niet een opdracht aan mij.*
