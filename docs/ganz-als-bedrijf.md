# GANZ een bedrijf laten runnen: wat er staat, wat er mist, en in welke volgorde

Geschreven op 10 oktober 2026, na een meting en niet na een inschatting. Het doel dat je
beschreef: met GANZ praten vanaf elke plek op aarde, **twintig YouTube-kanalen** die hij
zelf onderhoudt — elk met een eigen niche, format en beeldtaal, van muziek tot innovatie,
elk twee tot drie keer per week een video — en daarnaast een persoonlijke assistent die mail
doet, coacht en kan bellen.

Dat is **50 uploads per week** en ongeveer **217 per maand**. Dat getal staat in dit hele
stuk onder elke rekensom.

Dit stuk gaat over de afstand tussen dat doel en vandaag. Niet om te remmen — om de
volgorde te kunnen kiezen.

---

## 1. Wat ik vandaag heb gemeten

| | |
| --- | --- |
| API-routes | 109 |
| Routes zonder parameters die ik heb aangeroepen | 51, allemaal een antwoord, 0 serverfouten |
| Testsuite | groen |
| Echte bugs gevonden | 1, hieronder |
| Functies die een sleutel nodig hebben | 16, waarvan **6 echt aangesloten** |

De proef staat als `backend/scripts/ganz_smoke.py` in de repo, dus je kunt hem zelf draaien:

```bash
cd backend
GANZ_ALLOW_SEED_DATA=true GANZ_DATABASE_URL="sqlite+aiosqlite:///../smoke.db" \
  python -m scripts.ganz_smoke
```

**De bug.** `/api/memory` gaf een harde 500 bij élke aanroep: het endpoint beloofde in zijn
antwoordmodel alleen twee aantallen, maar gaf aantallen *én* de notities terug. Geen enkele
test raakte dat endpoint aan — de bestaande tests gingen alleen over `/memory/overview`, dat
er net naast zit. Opgelost, met een test erbij.

Twee dingen die ik daarvan heb geleerd en die in de proef zijn ingebouwd:

- **Een lege database bewijst niets.** Een leeg lijstje valideert ook tegen een verkeerd
  itemschema. Pas met voorbeelddata erin kwam deze bug boven.
- **Groene tests zijn niet hetzelfde als een werkende app.** 655 tests waren groen terwijl
  dit endpoint stuk was. De proef loopt daarom langs de buitenkant.

En één gat dat ik heb gedicht: de **koppelingen hadden nul tests**, op de gevoeligste plek
van GANZ — daar komen de sleutels binnen waarmee hij daarna namens jou mag handelen. Nu
vijftien, waarvan de belangrijkste zoekt of een geheim ooit in een antwoord opduikt.

---

## 2. De grootste ontbrekende schakel: er zit nog geen brein in

Dit is het eerlijkste dat ik je over GANZ kan vertellen: **er staat nergens in de code een
aanroep naar een taalmodel.** Geen Claude, geen enkel model. Ik heb er specifiek op gezocht.

Dat is geen kritiek op wat er is, want wat er is, is het chassis — en het is een goed
chassis:

- inloggen, rechten per niveau, en een tweede bevestiging voor gevoelige acties;
- een kluis die sleutels versleuteld bewaart en ze nooit teruggeeft;
- een register waar een nieuwe dienst in één klasse bij kan;
- een planner die op tijd dingen kan doen;
- YouTube echt werkend: cijfers, recente video's, **omzet per maand** en uploaden;
- TikTok en Instagram voor de cijfers;
- een uploadschema, een logboek, een geheugen, taken;
- het Quant Lab met vier afgeronde fases.

Maar "met GANZ praten" heeft nu nog niets om tegen te praten. En de uitvoering van skills is
met opzet nog een stub: de stappen worden nagelopen en gelogd, er gebeurt niets in de
buitenwereld. Dat staat zo in de code, met de reden erbij: een halve upload is erger dan
geen upload.

---

## 3. De sleutelkast staat nu klaar

Je vroeg of elke functie een plek krijgt om een API aan toe te voegen. Die is er nu, en het
was nodig: de kluis bestond al, maar nergens stond wélke functie er iets aan had — met als
gevolg dat de functie die sleutels opvraagt (`credentials_for`) door **geen enkele** functie
werd aangeroepen. Een parkeerplaats, geen leiding.

Wat er nu is:

- **`app/integrations/catalog.py`** — één bestand waarin per functie staat: wat hij kan,
  welke velden hij nodig heeft, waar ze horen, waar je de sleutel haalt, en of er al code is
  die hem gebruikt.
- **`GET /api/integrations/catalog`** — datzelfde overzicht, aangevuld met jouw situatie:
  gekoppeld, half ingevuld (met de namen van de lege velden) of nog niets. Er komt nooit een
  sleutel uit; alleen welk veld leeg is.
- **`require_credentials()`** — wat een functie aanroept in plaats van zelf in de database
  te kijken. Die weigert een half ingevulde koppeling en zegt in gewone taal wat er mist en
  waar je het invult.

Een nieuwe functie aansluiten is nu: één regel in de catalogus, één aanroep in de functie.
Dan staat hij automatisch in het overzicht.

**En het koppelscherm is gerepareerd.** Dat was geen opsmuk: het oude formulier stuurde
álles wat je invulde als `{api_key: ...}`. Voor Slack (`bot_token`, `signing_secret`) of
mail (`client_id`, `client_secret`, `refresh_token`) zijn dat de verkeerde veldnamen — de
koppeling leek dan gelukt en werkte niet. Het scherm leest nu de catalogus en toont per
functie precies de velden die hij nodig heeft, met waar je de sleutel haalt, en de melding
"nog niet aangesloten" als invullen nog niets doet.

**GANZ heeft drie bewaarplaatsen, en dat is met opzet:**

| Waar | Wat daar hoort | Waarom |
| --- | --- | --- |
| de kluis per gebruiker | diensten die je zelf aanmeldt (Slack, Telegram, mail) | versleuteld, per persoon |
| bij het kanaal of de rekening | tokens van een kanaal | twintig kanalen hebben twintig tokens |
| omgevingsvariabele op de server | wat voor iedereen geldt (het Google-project, de modelsleutel) | hoort niet in een database per gebruiker |

Een scherm dat dat verschil verzwijgt, stuurt mensen naar het verkeerde formulier. Daarom
zegt elke regel in het overzicht waar hij hoort.

---

## 4. De kanaalfabriek: wat er al kan en wat niet

Je noemde zeven stappen. Dit is waar ze staan:

| Stap | Vandaag |
| --- | --- |
| Nieuwe video-ideeën | mist het brein (§2) |
| Scriptonderzoek | mist het brein **en** een zoek-API |
| Script schrijven | mist het brein |
| Videocreatie | mist alles — en dit is de duurste en onzekerste stap |
| Uploadschema | **bestaat al** en werkt |
| Dagelijkse feed naar jou | planner bestaat, het kanaal om het heen te sturen mist |
| YouTube-statistieken per kanaal | **bestaat al**, omzet per maand inbegrepen |
| Zeggen wanneer een kanaal niet rendabel is | een meetprobleem, zie §6 |

Dat is beter nieuws dan het lijkt: de twee stappen die het meeste gemier zijn — publiceren
op schema en de cijfers ophalen — zijn precies de twee die al werken.

---

## 5. Wat er van buiten vastligt — opgezocht en niet verzonnen

### a. De uploadquota: hoe je plant, bepaalt hoeveel projecten je nodig hebt

Twintig kanalen die elk twee tot drie keer per week publiceren is **50 uploads per week**,
dus ongeveer **217 per maand** en gemiddeld **7,1 per dag**.

De YouTube Data API rekent met punten. Een video uploaden kost **1.600 punten**, en een
Google Cloud-project krijgt standaard **10.000 punten per dag**: dat is **zes uploads per
dag per project**, en dan heb je nog niets opgevraagd.

| Hoe je het inplant | Per dag | Punten | Projecten nodig |
| --- | --- | --- | --- |
| gespreid over alle zeven dagen | 7,1 | 11.400 | **2** |
| geclusterd op twee vaste dagen | 25 | 40.000 | **4** |

Daar zit een gratis besparing: **spreiden over de week scheelt de helft van je projecten.**
Het uploadschema dat er al in zit is precies de plek om dat te regelen, en het is de plek
waar ook een puntenbudget per project hoort te zitten — een upload die het dagbudget zou
overschrijden moet worden uitgesteld en niet geprobeerd.

Cijfers ophalen is bijna gratis (een paar punten per kanaal), op één uitzondering:
**zoeken kost 100 punten per aanroep.** Dat is 1/16 van een upload per zoekopdracht, dus
zoeken hoort niet in een lus.

Eén ding moet je zelf in je console nakijken voor je hierop bouwt: één versie van Google's
documentatie noemt óók een aparte grens van **100 uploads per dag**, los van de punten. De
andere versies noemen die niet. Bij 50 per week zit je daar ruim onder, maar kijk het na in
plaats van mij te vertrouwen.

Een quotaverhoging aanvragen kan ook (er is een formulier voor) en scheelt het gedoe met
meerdere projecten. Reken er niet op dat het meteen rond is.

### b. Het beleid rond "inauthentic content", en waar het risico bij jouw opzet zit

Op 15 juli 2025 heeft YouTube zijn regel "repetitious content" omgedoopt naar
**"inauthentic content"**. YouTube zelf noemt het een verduidelijking van bestaand beleid,
geen nieuwe regel. Waar het om gaat: massaal geproduceerde of herhalende content — video's
die eruitzien alsof ze uit een template komen met weinig variatie, of die makkelijk op
schaal te repliceren zijn — komt niet in aanmerking voor uitbetaling. Genoemde voorbeelden:
kanalen met voorgelezen verhalen die alleen oppervlakkig verschillen, of slideshows met
identieke voice-over.

En in dezelfde regel staat het goede nieuws: **AI mag.** Wie AI in het productieproces
gebruikt kan gewoon monetiseren, zolang het eindresultaat origineel is en waarde heeft voor
de kijker.

**Bij twintig kanalen met elk een eigen niche, format en beeldtaal valt het grootste deel
van dit risico weg.** Dit is niet één fabriek die twintig keer hetzelfde uitpoept; het zijn
twintig verschillende dingen die één fabriek maakt. Wat overblijft is smaller en zit
*binnen* een kanaal: als de video's van kanaal 7 onderling nauwelijks verschillen, is dat
kanaal het probleem — niet de twintig samen. Dat is een eis aan de variatie per kanaal, en
die moet dus in het format van dat kanaal zitten (zie §5c).

### c. Muziek is de enige niche in je lijst met een eigen risico

Je noemde "van muziek tot innovatie". Op één na zijn dat allemaal gewone niches, maar
**muziek is op YouTube de risicovolste die er is**, en niet door het beleid hierboven:
door Content ID. Dat systeem herkent opnames automatisch, en een claim van een
rechthebbende kan de video blokkeren, het geluid dempen of de opbrengst naar hem laten
gaan. Dat is geen strike en je kanaal gaat er niet aan, maar je verdient niets en je hebt
het pas na het uploaden door.

Twee werkbare vormen: audio waarvan je de licentie kunt aantonen (of zelf laat genereren),
of een kanaal dat *over* muziek gaat — geschiedenis, analyse, productie — in plaats van
muziek te bevatten. Het verschil kost niets vooraf en alles achteraf.

---

## 6. Twee dingen die de code nog niet kan, en die hier direct uit volgen

Nagekeken op 10 oktober 2026, niet aangenomen.

**1. Een kanaal kan geen eigen format vastleggen.** `SocialChannel` heeft een platform, een
naam, een extern ID, een status en de sleutels — en verder niets. Geen niche, geen
scriptvorm, geen beeldtaal, geen stem, geen publicatiedagen. Twintig kanalen die elk iets
eigens zijn, kan het model dus nog niet uitdrukken.

Dit is de eerste tabel die erbij moet, en het is goedkoop werk: één rij per kanaal met
datgene waar de productie zich aan moet houden. Zonder die rij is er geen pijplijn *per
kanaal* maar één pijplijn voor alles — en dan heb je precies de fabriek waar §5b over gaat.
Dit is ook de plek waar "hoe verschillen de video's binnen dit kanaal van elkaar" hoort te
staan, want dat is de eis die uit §5b overblijft.

**2. Het Google-project is één instelling voor de hele server.** `youtube_client_id` en
`youtube_client_secret` staan als één waarde in de instellingen. Voor de twee tot vier
projecten uit §5a moeten die per groep kanalen kunnen verschillen, en elk kanaaltoken hoort
bij het project waarmee het gekoppeld is.

Dat is nu een kleine verandering en later een vervelende: een token van project A werkt niet
onder project B, dus wie dit achteraf splitst, laat elk kanaal opnieuw toestemming geven.

---

## 7. De kosten, met de getallen die ik wél heb

Bij 217 video's per maand.

**De tekst is bijna gratis.** Met de modelprijzen die in `app/quantlab/pricing.py` staan
(met bron, geverifieerd op 5 oktober 2026 — dus toe aan een controle), gerekend met 30.000
tekens context in en een script van 2.500 tokens uit:

| Model | Per script | Per maand |
| --- | --- | --- |
| het goedkope model | $0,04 | **$9** |
| het dure model | $0,43 | **$92** |

**De video bepaalt alles, en de lengte bepaalt de video.** De generator wordt VidRush.
Belangrijkste ding dat ik daarover vond: **VidRush rekent per afgeleverde minuut, niet per
video** — 55 credits per minuut eindproduct bij hun zwaarste stand, en de duur van de
*afgeleverde* video telt, niet de gevraagde duur. Dat verandert de rekensom wezenlijk: niet
"217 video's" maar "217 × de lengte".

Met de prijs die ik kon vinden (ongeveer $1,83 tot $2,72 per afgeleverde minuut):

| Lengte per video | Minuten per maand | Per maand |
| --- | --- | --- |
| 1 minuut | 217 | **$397 – $589** |
| 2 minuten | 433 | $793 – $1.179 |
| 3 minuten | 650 | $1.190 – $1.768 |
| 5 minuten | 1.083 | $1.983 – $2.947 |
| 8 minuten | 1.733 | **$3.172 – $4.715** |

Daar staat de belangrijkste keuze van het hele plan in één tabel: **korte video's zijn een
bedrijf, lange video's op deze schaal zijn een rekening van vier- tot vijfduizend dollar per
maand.** En het is een keuze die je per kanaal kunt maken.

Twee eerlijke waarschuwingen bij die getallen:

1. **Het is geen officiële API-prijs.** De credits per minuut komen uit hun eigen
   documentatie, het bedrag per minuut uit een schatting van derden. Reken het na bij het
   afrekenen, en vraag of er een staffel is: bij 200+ video's per maand is dat een gesprek
   waard.
2. **Ik weet niet of VidRush een API heeft.** Hun site en documentatie zijn vanuit deze
   omgeving onbereikbaar (de naam lost niet eens op), dus ik kon het niet nakijken. Dat is
   geen detail maar de **belangrijkste openstaande vraag van dit hele plan**: zonder API kan
   GANZ de fabriek niet draaien en blijft er bij elke video een mens nodig om op een knop te
   drukken. Bij 217 video's per maand is dat het verschil tussen automatisch en een baan.

**Daarom blijft "één kanaal helemaal rond" stap vier en niet stap tien:** die stap levert
het werkelijke bedrag per video, en dat bedrag bepaalt of twintig kanalen een bedrijf is of
een hobby met een rekening.

Let op het verschil met het maandplafond van €200 dat in de labafspraak staat: dat gaat over
de agents van het lab. De videofabriek is een ander bedrag, en in de tabel hierboven zie je
waarom dat een echte beslissing is en geen formaliteit.

---

## 8. Samen in één bedrijf, apart in je eigen leven

Je wil dat jij en je broer elk een eigen inlog hebben, samen in het YouTube-project zitten,
en dat de sport- en voedingscoach gescheiden blijft. Zakelijke modules samen, persoonlijke
modules bij je account.

**Het inlogscherm bestaat al** en kan meer dan je denkt: eigen account per persoon, vier
niveaus van rechten, rechten per persoon aan of uit te zetten los van het niveau, een
tweede bevestiging voor gevoelige handelingen, en ingetrokken-kunnen-worden per apparaat.
Je broer een account geven kan vandaag.

**Wat er niet is, is het samen.** Alle achtendertig tabellen hangen aan één `user_id`. Als
je broer vandaag inlogt, ziet hij geen enkel kanaal — niet omdat het verboden is, maar omdat
die kanalen aan jóuw account hangen. Het is nu dus precies omgekeerd aan wat je wil: alles
apart, niets samen.

Wat erbij moet is een laag ertussen — noem het een werkruimte. Eén regel bepaalt de rest:

> **Een module hangt óf aan de werkruimte, óf aan de persoon. Nooit aan beide, en nooit aan
> geen van beide.**

Zo valt het uiteen:

| Samen (werkruimte) | Bij jezelf (account) |
| --- | --- |
| kanalen, hun cijfers en hun tokens | sport- en voedingscoach |
| video's, scripts, uploadschema | je eigen mail |
| de koppelingen van het bedrijf (video, stem, onderzoek) | je eigen geheugen en gesprekken met GANZ |
| het logboek van wat er in het bedrijf gebeurde | je eigen takenlijst |
| het Quant Lab | je pincode, je apparaten, je stemprofiel |

Twee dingen die in geen van beide kolommen vanzelf thuishoren en waar jij over moet
beslissen:

- **Financiën.** De omzet van de kanalen is zakelijk, maar een privérekening in hetzelfde
  overzicht is dat niet. Mijn voorstel: de rekening krijgt een vlag en hoort óf bij het
  bedrijf óf bij jou, per rekening.
- **De takenlijst.** Een klus voor een kanaal is zakelijk, "tandarts bellen" niet. Dezelfde
  oplossing: per taak.

En één regel die ik erbij zou zetten omdat hij later niet meer in te bouwen is: **wat in de
persoonlijke kolom staat, is voor de ander niet te zien — ook niet voor de eigenaar van de
werkruimte.** Anders is "gescheiden" een woord zonder inhoud. Dat betekent dat de hoogste
rechten in het bedrijf je nog steeds niet bij het voedingsschema van je broer brengen, en
dat is precies de bedoeling.

Dit is een echte verbouwing: een tabel erbij, een kolom op de zakelijke tabellen, en elke
query die nu op `user_id` filtert moet meeverhuizen. Het is goed te doen en het is beter om
het te doen met twee accounts en twintig kanalen dan later met meer. Maar het is geen
middagje.

---

## 9. Meerdere Google-projecten tegelijk: ja, en zo

Dat kan, en het is klein werk vergeleken met het vorige punt. Vandaag staan
`youtube_client_id` en `youtube_client_secret` als één waarde in de instellingen — één
project voor de hele server, terwijl §5a er twee tot vier vraagt.

Wat er moet gebeuren:

1. **Een project wordt een rij** in plaats van een instelling: naam, client-ID en secret
   (versleuteld, zoals alle andere sleutels).
2. **Elk kanaal wijst naar het project waarmee het gekoppeld is.** Dit is het punt waar het
   fout kan gaan: een OAuth-token van project A werkt niet onder project B. Wie dit later
   splitst, laat elk kanaal opnieuw toestemming geven — dus dit moet erin voordat de twintig
   kanalen gekoppeld worden, niet erna.
3. **Een puntenteller per project per dag**, en het uploadschema dat weigert te publiceren
   als het dagbudget vol is. Zonder die teller merk je de grens pas als een upload mislukt,
   en dan staat de video wel klaar en het schema niet meer.

Dat derde punt is de reden dat dit nú eenvoudig is en later lastig: een puntenteller die je
achteraf inbouwt, moet ook kunnen uitleggen waarom er gisteren drie video's niet de deur uit
zijn gegaan.

---

## 10. "Wanneer is een kanaal niet meer rendabel" — hier is al machinerie voor

Dit is dezelfde vraag als die van het Quant Lab, en daar is hij al een paar keer fout
gegaan op manieren die ik kan laten zien:

- Uit 648 papieren trades bleek: om een voordeel van 0,15R te kunnen zien heb je **136
  trades** nodig, voor 0,10R al **306**. Onder die aantallen meet je ruis.
- In vijftig sessies met verschillende instellingen stonden de beste tien van het ene
  corpus op het andere corpus gemiddeld op plek **31,3 van de 50**. De winnaars waren geen
  winnaars; het was toeval dat zich als inzicht voordeed.

Reken dat om naar kanalen. Met tien video's per kanaal is "kanaal 7 is de beste" vrijwel
zeker ruis — en "stop met kanaal 3" net zo goed. Het gevaar is niet dat je niets meet, maar
dat je te vroeg iets meet en je er dan naar gaat gedragen.

Wat er al ligt en één op één hergebruikt kan worden:

- **`app/quantlab/metrics.py`** — verwachtingswaarde met een 90%-betrouwbaarheidsinterval
  via bootstrap, werkt op elke reeks uitkomsten. Dus ook op "winst per video".
- **`app/quantlab/budget.py` en het kostenboek** — een maandplafond in euro's, een plafond
  per onderdeel per dag, en een stand waarin hij doorgaat zonder model in plaats van te
  stoppen. Dat is nu gebouwd voor het lab, maar het is precies wat je voor de hele
  videofabriek nodig hebt: **kosten per video naast omzet per video**, met een grens die
  ingrijpt voordat de rekening komt.

Mijn voorstel voor het oordeel over een kanaal: geen percentage en geen onderbuik, maar
kosten per video tegenover omzet per video **met de onzekerheidsmarge erbij**, en een
"stoppen"-advies alleen als die hele marge onder de kostenlijn ligt. Tot dat moment is het
eerlijke antwoord "nog te vroeg" — en dat is een echt antwoord.

---

## 11. De persoonlijke assistent

| Wat | Hoe moeilijk | Waar ik op zou letten |
| --- | --- | --- |
| Sport- en voedingscoach | het makkelijkst | Model plus het geheugen dat er al is. Vrijwel gratis. Wel een grens: dit is geen medisch advies, en dat moet GANZ ook zeggen. |
| Mail lezen en samenvatten | makkelijk | Alleen lezen is terug te draaien. |
| Mail beantwoorden | riskant | **Begin met concepten, niet met verzenden.** Een verzonden mail is niet terug te nemen. De bevestigingslaag die er al is (`require_confirmation`) is hier precies voor gemaakt. |
| Spam opruimen | riskant | Label in plaats van verwijderen. Eén verkeerd weggegooide mail van een klant is duurder dan duizend handmatig weggeklikte spammetjes. |
| Telefonisch reserveren | het moeilijkst | Als laatste, en niet alleen om techniek. Een telefoontje is niet terug te draaien, in Europa moet de ander weten dat hij met een computer praat, en een gesprek opnemen mag niet zonder toestemming. Zoek dat uit vóór je het bouwt, niet erna. |

---

## 12. De volgorde die ik zou aanhouden

1. **Het brein aansluiten.** Een modelclient, met het kostenboek dat er al staat eraan
   vastgeknoopt — dus vanaf de eerste aanroep weet je wat het kost. Zonder deze stap heeft
   geen enkele andere stap zin.
2. **Eén kanaal om mee te praten.** Ik zou met **Telegram** beginnen en niet met Slack: één
   token, geen app-installatie, en het werkt achter Tailscale zonder dat GANZ van buiten
   bereikbaar hoeft te zijn. Slack kan daarna, met Socket Mode om dezelfde reden.
3. **De dagelijkse feed.** De planner bestaat, de cijfers bestaan, het kanaal is er dan
   ook. Dit is de eerste dag waarop GANZ iets naar jóu stuurt in plaats van andersom.
4. **Eén kanaal helemaal rond. Niet twintig.** Van idee tot upload, en dan meten wat één
   video werkelijk kost en opbrengt. Dat getal is het fundament onder al het andere, en
   niemand kent het nu.
5. **Opschalen pas als dat getal bekend is.** Twintig verschillende niches is al de goede
   vorm (§5b); let bij het opschalen op de variatie *binnen* elk kanaal, want dat is het
   stukje risico dat overblijft.
6. **Mail**, eerst alleen concepten. Dan de coaches, die bijna niets kosten.
7. **Telefoon** als laatste, als je het dan nog wil.

Stap 1 tot 3 maken van GANZ iets waar je dagelijks iets aan hebt. Stap 4 is de stap die
bepaalt of twintig kanalen een bedrijf is of een hobby met een rekening — en dat is beter om
in week vier te weten dan in maand acht. Zie de tabel in §7: tussen €108 en €4.333 per maand
zit maar één onbekend getal.

---

## 13. Wat ik van jou nodig heb

1. **Een `ANTHROPIC_API_KEY` op de server.** Dit is de grootste ontgrendeling van de hele
   lijst: hij maakt stap 1 mogelijk, en daarmee alles erna.
2. **Telegram of Slack?** Mijn advies is Telegram eerst, maar het is jouw werkdag.
3. **Twee tot vier Google Cloud-projecten**, afhankelijk van hoe je de week inplant (§5a) —
   of één project plus een quotaverhoging. Kijk daar meteen die grens van 100 uploads per
   dag na. En laat mij dan die ene instelling per groep kanalen maken in plaats van één voor
   de hele server; achteraf splitsen kost elk kanaal een nieuwe toestemming.
4. **Van VidRush: heeft het een API?** Kijk in hun documentatie of er endpoints en een
   API-sleutel zijn (ik kan er vanuit hier niet bij). Zonder API kan GANZ de fabriek niet
   draaien. Vraag er meteen naar een staffel bij 200+ video's per maand.
5. **Een lengte per kanaal.** Zie de tabel in §7: dat is bij VidRush het verschil tussen
   ongeveer $400 en $4.700 per maand, en het is de goedkoopste knop die je hebt.
6. **Een account voor je broer, en een beslissing over financiën en taken** — zakelijk of
   persoonlijk, zie §8.

Nog iets wat openstaat uit het Quant Lab en hier nu ook speelt: het maandplafond van €200
dat in de labafspraak staat, gaat over de agents van het lab. Als het brein straks ook de
videofabriek en de assistent bedient, is dat een ander bedrag. Dat moeten we een keer
afspreken, want het plafond grijpt echt in — dat is de bedoeling.
