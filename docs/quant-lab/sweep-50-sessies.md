# Vijftig sessies, en wat de beste tien waard zijn

Gevraagd: vijftig sessies met verschillende parameters, de beste tien eruit, alle data
bewaren. Dat is gedaan. Er staat één stap extra in, en die stap is het antwoord op de
vraag of die tien iets betekenen: **ze zijn ook op verse data gedraaid.**

Reproduceerbaar met `backend/scripts/quant_sweep.py`. De data is synthetisch en geen
kostenparameter is geverifieerd.

---

## De opzet

- 50 parameterstellen uit een raster van stopafstand × winstneming × trailing stop ×
  maximale houdtijd. Reproduceerbare steekproef (zaad 20261006) uit de 336 mogelijke
  combinaties.
- Elk stel is een eigen **voorgeregistreerde versie** — de pre-registratie dwingt dat af:
  hetzelfde label met andere inhoud wordt geweigerd. Elk experiment moest dus een naam
  hebben voordat het draaide.
- Alle 50 op **corpus A** (12 uur, 25.436 ticks). Rangschikken op expectancy. Top 10 eruit.
- Diezelfde 50 op **corpus B** — andere data, zelfde generator.

Het beslissende gegeven vooraf: H0 stapt **willekeurig** in. Er is per constructie geen
edge. Alles wat de selectie vindt, is dus ruis — en dat is hier een zekerheid, geen
vermoeden.

---

## De gevraagde top 10 — en waar ze op B staan

```
    # |  stop | half | trail | hold |    N |    exp A | plek B |    exp B
   39 |  0.30 |  2.5 |  0.15 |  240 |   65 |   0.2451 |     38 |   0.0383
   46 |  0.30 |  2.5 |  0.30 |   60 |   65 |   0.2451 |     39 |   0.0382
    7 |  0.30 |  2.0 |  0.20 |   60 |   65 |   0.2358 |     25 |   0.0823
   11 |  0.30 |  2.0 |  0.20 |  120 |   65 |   0.2358 |     26 |   0.0823
   34 |  0.30 |  2.0 |  0.30 |   60 |   65 |   0.2358 |     27 |   0.0643
   42 |  0.30 |  2.0 |  0.30 |  240 |   65 |   0.2358 |     28 |   0.0643
   19 |  0.30 |  2.0 |  0.15 |   60 |   65 |   0.2191 |     40 |   0.0369
   29 |  0.35 |  3.0 |  0.25 |   60 |   64 |   0.2140 |     29 |   0.0580
   33 |  0.35 |  3.0 |  0.30 |   60 |   64 |   0.2140 |     30 |   0.0580
   35 |  0.35 |  3.0 |  0.30 |  120 |   64 |   0.2140 |     31 |   0.0580
```

**Gemiddelde plek op B: 31,3 van 50.**

- Waren de winnaars echt beter, dan hoort dat rond **5,5** te liggen.
- Puur toeval geeft **25,5**.
- Het is 31,3.

De rangschikking van A draagt dus geen bruikbare informatie over naar B. De
Spearman-rangcorrelatie tussen beide lijsten is **−0,40**: in deze ene steekproef wijst hij
zelfs de verkeerde kant op. Ik zou daar niet te veel in lezen — bij één steekproef met veel
gelijke uitkomsten kan dat toeval zijn — maar van "de top 10 is beter" is niets over.

---

## Hoe goed ziet de beste van vijftig eruit zonder edge?

Dit is de berekening die het hele idee van "de beste eruit halen" ondergraaft.

Met 4.949 gemeten trades is de spreiding **0,956R per trade**, bij gemiddeld 33 trades per
sessie. De standaardfout van een gemiddelde is dan 0,956/√33 = 0,166R. Het maximum van 50
trekkingen ligt gemiddeld ongeveer √(2·ln 50) = 2,8 standaardfouten boven nul.

> **Verwachte expectancy van de beste van 50, als er geen enkele edge is: +0,473R.**
>
> Wat de beste op A werkelijk haalde: **+0,245R.**

De beste van vijftig haalde dus niet eens de helft van wat puur kiezen al oplevert. Er is
niets gevonden — en dat is het juiste antwoord.

Praktisch: **hoe meer varianten je probeert, hoe beter de winnaar eruit ziet zonder dat er
iets gebeurd is.** Bij 50 varianten moet je +0,47R al wegstrepen voordat je iets gelooft.
Bij 500 varianten wordt die drempel +0,60R. Dat is geen reden om niet te zoeken; het is de
reden dat je altijd op verse data moet toetsen.

---

## Nog iets dat opviel: vijftig parameterstellen zijn geen vijftig gedragingen

Van de 50 stellen gaven er maar **19 een ander resultaat**. De overige 31 waren
functioneel identiek aan een van die 19 — dezelfde uitkomst tot op vier decimalen.

De oorzaak: de trailing stop en de maximale houdtijd komen vaak helemaal niet aan bod. Een
positie die op zijn stop of op +2R eindigt, merkt niets van `max_hold_minutes: 240` tegen
`60`. Vier van de zes "beste" stellen verschillen alleen in parameters die in die runs geen
enkele trade hebben geraakt.

Dat is een eigenschap van het raster en niet van de code, maar het is wel iets om te weten
voordat je conclusies verbindt aan "deze combinatie werkt beter": soms is het precies
dezelfde strategie met een andere naam.

---

## Alle data

| | |
| --- | --- |
| Voorgeregistreerde versies | 50 (`H0SWEEP_s001` … `s050`) |
| Runs | 100 (50 op A, 50 op B) |
| Trades | 4.949 |
| Corpora | beide bewaard, naast elkaar (eigen tijdvenster en pool-voorvoegsel) |
| Corpusafdruk A | `aae9b060a70de17b…` |
| Corpusafdruk B | `a179a85ecffe3e83…` |

Alles staat in de database `ganz_sweep`: de hypotheses met hun hash, de runs met hun
corpusafdruk, alle trades, alle fills en alle overgeslagen signalen met reden. Daarnaast
een CSV met één regel per sessie per corpus (`sweep.csv`), inclusief
betrouwbaarheidsinterval, drawdown, kosten en het aantal keren dat de risicolaag blokkeerde.

De corpora zijn ook zonder de database te herbouwen: de synthetische bron is
deterministisch, en de afdruk in elke run bewijst welk corpus erbij hoorde.

---

## Wat ik hiermee zou doen

Niet: deze tien parameters aanhouden. Ze zijn aantoonbaar niets waard.

Wel: deze sweep bewaren als **nulmeting**. Zodra er een echte hypothese met een echte
entry-trigger draait op echte data, is dit de vergelijking die ertoe doet — niet "is mijn
beste variant positief" maar "verslaat mijn beste variant de beste variant van een
strategie die willekeurig instapt". Die laatste staat nu vast op +0,245R op A en +0,082R
op B, met alle onderliggende data erbij.

Dat is wat een nulmeting is, en dat is wat deze vijftig sessies hebben opgeleverd.
