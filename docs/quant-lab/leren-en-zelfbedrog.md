# Een AI die aldoende leert — wat dat hier wel en niet kan betekenen

Dit stuk is voor jou, niet voor een programmeur. Je zei dat je geen trader bent en daarom
een AI wil die van papieren trades leert. Dat is een goed uitgangspunt, maar het woord
"leren" betekent in traden iets anders dan bij bijna alles waar je het verder op zou
toepassen — en dat verschil is de reden dat je eigen opdracht automatische
parameteraanpassing door agents op de verbodenlijst heeft gezet (sectie 3).

Je had dus al gelijk toen je die prompt schreef. Je had het alleen nog niet verbonden met
het woord "leren".

---

## 1. Wat er misgaat, met je eigen systeem gemeten

Ik heb een proef gedraaid die je zelf kunt herhalen
(`backend/scripts/quant_overfit_demo.py`). De opzet:

- Twee datasets met dezelfde generator, alleen een ander toevalsgetal. Noem ze A en B.
- Zes varianten van H0 — de controlegroep die **willekeurig** instapt — met alleen een
  andere stopafstand.
- Alle zes op A. Pak de beste. Dat is precies wat "leren van de resultaten" doet.
- Daarna dezelfde zes op B, en kijken waar de winnaar van A terechtkomt.

Het beslissende punt vooraf: **H0 stapt willekeurig in, dus er is per constructie geen
edge.** Elk verschil dat we vinden, is dus ruis. Dat is hier geen vermoeden maar een
zekerheid.

### Op dataset A

```
    stop | trades |  expectancy |  totaal R | door risicolaag geblokkeerd
    0.15 |     12 |     -0.5800 |   -6.9605 |                        1005
    0.20 |     13 |     -0.4442 |   -5.7749 |                         999
    0.25 |     14 |     -0.2250 |   -3.1498 |                         992
    0.30 |     98 |      0.1774 |   17.3822 |                         685
    0.35 |     97 |      0.1414 |   13.7129 |                         714
    0.40 |     18 |     -0.2213 |   -3.9828 |                         973
```

Een lerend systeem kiest hier stop 0,30: +0,18R per trade, en +17R in totaal, tegenover
−0,58R voor de slechtste. Een verschil van 0,76R per trade. Dat ziet eruit als een vondst.

### Op dataset B — alleen een ander toevalsgetal

```
    stop | trades |  expectancy |  totaal R
    0.15 |    145 |     -0.0373 |   -5.4060
    0.20 |    124 |      0.0065 |    0.8121
    0.25 |    103 |      0.0779 |    8.0272
    0.30 |    103 |     -0.0176 |   -1.8148   <- de winnaar van A
    0.35 |     80 |     -0.0607 |   -4.8558
    0.40 |     93 |      0.0590 |    5.4839
```

De winnaar van A staat op B op **plek 4 van 6**, met een negatieve uitkomst. Over alle
twaalf runs samen komt de expectancy uit op −0,09R: ongeveer nul, precies waar willekeurig
instappen hoort uit te komen.

### En er zit nog een val in

Kijk naar de laatste kolom van dataset A. De varianten met twaalf tot achttien trades zijn
ongeveer duizend keer door de risicolaag geblokkeerd; de "winnaars" zevenhonderd keer. Wat
daar gebeurde: die varianten liepen vroeg op een slechte dag tegen de dagstop van −3R aan
en werden daarna voor de rest van de dataset op slot gezet. Ze kregen niet alleen pech, ze
kregen ook geen kans meer om die pech uit te vlakken.

Een lerend systeem leest dat als "die stopafstand is slecht". Het is in werkelijkheid "die
stopafstand had op dag één net even pech".

**Dit is geen fout in de code.** De risicolaag doet exact wat hij moet doen. Maar het laat
zien hoe makkelijk een systeem dat van uitkomsten leert, iets leert wat er niet staat.

---

## 2. Hoeveel bewijs heb je eigenlijk nodig?

Dit is het nuttigste getal in dit hele stuk. Uit 648 gemeten papieren trades blijkt de
spreiding van de uitkomsten **1,06R per trade**. Daaruit volgt hoeveel trades je nodig hebt
voordat je een echte edge van nul kunt onderscheiden:

| edge per trade | trades nodig |
| --- | --- |
| 0,05R | 1225 |
| 0,10R | 306 |
| 0,15R | 136 |
| 0,20R | 77 |
| 0,30R | 34 |
| 0,50R | 12 |

Bij de drempel van 150 trades uit je eigen opdracht kun je een edge van ongeveer **0,14R
per trade** zien. Alles wat kleiner is, is op dat moment niet te onderscheiden van nul.

Wat dat praktisch betekent: een systeem dat na elke trade bijstelt, beslist op een
steekproef van één. Dat is niet "langzaam leren" — dat is ruis volgen. En omdat de
uitkomsten scheef verdeeld zijn (veel kleine verliezen, af en toe een grote winst), voelt
het nog overtuigender dan het is.

---

## 3. Waar leren hier wél hoort — en dat is drie dingen

Je wil geen systeem dat niets leert. Je wil een systeem dat leert op de plekken waar leren
betrouwbaar kan. Die zijn er, en twee ervan staan al in je architectuur.

### A. Leren hoe duur de werkelijkheid is — nu al, doorlopend, veilig

Dit is het ene geval waarin "aldoende leren" zonder voorbehoud werkt. Elke papieren order
legt vast wat hij verwachtte en wat hij kreeg: de prijs waarop werd gemikt, de prijs na de
vertraging, de prijs die eruit kwam, de kosten. Daar kun je direct van leren, want de
feedback is onmiddellijk en niet door ruis gedomineerd: als de werkelijke vertraging
steeds 2 seconden is en je model zegt 0,8 seconde, dan is je model fout — dat heb je niet
honderd trades nodig om te zien.

Op dit moment staat bij alle acht kostenparameters "niet geverifieerd". Zodra er echte data
is, zijn dat de eerste acht getallen die van gok naar meting gaan. **Dat is leren, en het
is de meest waardevolle vorm die je nu kunt krijgen**, want een strategie die winstgevend
lijkt bij verkeerde kosten is het hele project waardeloos.

### B. Leren welke kandidaat iets waard is — de Classifier, met een examen

Hier komt JEV. Een model dat kandidaten een score geeft, kan echt leren — maar het mag
alleen meebeslissen als het eerst heeft bewezen dat het beter is dan de regels. Daarom
staat in je opdracht: eerst 100 beslissingen in de schaduw (wel loggen, niets bepalen), dan
een betrouwbaarheidsanalyse en een Brier-score tegen `RulesOnly`, en verbetert het niets,
dan gaat het uit.

Dat is de kern: **leren mag, zolang het resultaat van het leren meetbaar is tegen een
alternatief dat niet leert.**

### C. Leren welk experiment je hierna doet — de Reviewer, met jou als poort

Dit is waar "aldoende leren" op systeemniveau zit, en het is fase 4 van je opdracht. De
Reviewer leest de resultaten, vindt patronen, en schrijft **voorstellen** in een inbox. Hij
mag niets veranderen. Jij keurt een voorstel goed, en dan ontstaat een nieuwe
hypothese-versie — H1_v2 — met een teller die op nul begint.

Het leren zit dus in de **reeks experimenten**, niet in het verdraaien van knoppen tijdens
één experiment. Dat lijkt langzaam, en dat is het ook. Het is ook het enige tempo waarop je
achteraf nog kunt zeggen welke regels bij welke trades hoorden.

### Wat nooit mag leren

- De risicogrenzen. Die staan hardcoded in de code, buiten bereik van elke agent.
- De positiegrootte op basis van recente uitkomsten. Daar staat een test op die de
  signatuur van de functie controleert: hij kán de laatste uitslagen niet zien.
- Parameters tijdens een lopende run. Dat is het verschil tussen een experiment en een
  verhaal.

---

## 4. Wat je hier dan eigenlijk aan hebt

Het eerlijkste antwoord op "ik ben een leek en wil een AI die leert traden" is dit: **wat je
bouwt is geen trader maar een meetinstrument.** Zijn taak is om je te vertellen of een idee
een edge heeft, en het eerlijke antwoord zal meestal "niet aantoonbaar" zijn.

Dat klinkt als een magere opbrengst. Het is het niet, om twee redenen.

De eerste is dat de meeste mensen die hier geld verliezen, dat doen omdat ze geen manier
hadden om "dit werkt" van "ik had geluk" te onderscheiden. Jij bouwt die manier eerst.

De tweede is wat je er zelf van leert. De tabel in §2 is een vaardigheid, niet een getal:
weten hoeveel bewijs een bewering nodig heeft voordat je hem gelooft. Dat is overdraagbaar
naar alles waar je iets mee gaat doen, met of zonder dit lab.

En er is een duidelijk alarm ingebouwd. Als het lab op een dag zegt dat H1 een edge heeft,
is de eerste vraag niet "hoeveel kan ik ermee verdienen" maar "wat heb ik verkeerd
gemeten". De controlegroep H0 is er precies daarvoor: komt H0 ook in de plus, dan staan de
kosten te laag en betekent het hele resultaat niets. Dat is één keer gebeurd tijdens het
bouwen — H0 kwam uit op +8R met een winrate van 100% — en dat was een fout in mijn eigen
datageneratie, niet een vondst.

---

## 5. Als je dit zelf wil nakijken

```bash
cd backend
createdb ganz_proef
export GANZ_DATABASE_URL=postgresql+asyncpg://ganz:ganz@localhost:5432/ganz_proef
.venv/bin/python -m alembic upgrade head
.venv/bin/python -m scripts.quant_overfit_demo
```

Let op: de data in deze proef is synthetisch. Dat maakt de demonstratie **sterker** en niet
zwakker, want we weten zeker dat er geen edge in zit. Alles wat het "leren" vindt, is
daarmee bewijsbaar ruis.
