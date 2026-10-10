# GANZ een bedrijf laten runnen: wat er staat, wat er mist, en in welke volgorde

Geschreven op 10 oktober 2026, na een meting en niet na een inschatting. Het doel dat je
beschreef: met GANZ praten vanaf elke plek op aarde, tien tot twintig YouTube-kanalen die
hij zelf onderhoudt, en daarnaast een persoonlijke assistent die mail doet, coacht en kan
bellen.

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

## 5. Twee harde grenzen van buiten, opgezocht en niet verzonnen

### a. Je kunt niet zomaar twintig keer per dag uploaden

De YouTube Data API rekent met punten. Een video uploaden kost **1.600 punten**, en een
Google Cloud-project krijgt standaard **10.000 punten per dag**. Dat is ongeveer **zes
uploads per dag per project** — en dan heb je nog niets opgevraagd, want cijfers ophalen
kost ook punten.

Twintig kanalen die elk dagelijks publiceren, is twintig uploads per dag en dus ruim
32.000 punten. Dat gaat niet zonder iets te regelen. Twee wegen:

1. een quotaverhoging aanvragen bij Google (daar is een formulier voor);
2. de kanalen over meerdere Cloud-projecten verdelen.

Eén ding moet je zelf in je console nakijken voor je hierop bouwt: één versie van Google's
documentatie noemt óók een aparte grens van **100 uploads per dag**, los van de punten. De
andere versies noemen die niet. Dat is precies het soort detail waar een plan op stukloopt,
dus kijk het na in plaats van mij te vertrouwen.

### b. Twintig kanalen van één template is precies wat YouTube demonetiseert

Op 15 juli 2025 heeft YouTube zijn regel "repetitious content" omgedoopt naar
**"inauthentic content"**. YouTube zelf noemt het een kleine verduidelijking van bestaand
beleid, geen nieuwe regel. Waar het om gaat: massaal geproduceerde of herhalende content —
video's die eruitzien alsof ze uit een template komen met weinig variatie, of die makkelijk
op schaal te repliceren zijn — komt niet in aanmerking voor uitbetaling. Genoemde
voorbeelden: kanalen met voorgelezen verhalen die alleen oppervlakkig verschillen, of
slideshows met identieke voice-over.

En het goede nieuws in dezelfde regel: **AI mag.** YouTube zegt expliciet dat wie AI in het
productieproces gebruikt, gewoon kan monetiseren — zolang het eindresultaat origineel is en
waarde heeft voor de kijker.

Daar zit de strategische kern van je plan in, en ik wil het scherp zeggen: **het risico is
niet dat GANZ te weinig video's maakt, het risico is dat twintig kanalen één sjabloon
delen.** Dan werkt de machine perfect en keert YouTube niets uit. Vijf kanalen met echte
variatie zijn dan meer waard dan twintig met dezelfde vorm.

---

## 6. "Wanneer is een kanaal niet meer rendabel" — hier is al machinerie voor

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

## 7. De persoonlijke assistent

| Wat | Hoe moeilijk | Waar ik op zou letten |
| --- | --- | --- |
| Sport- en voedingscoach | het makkelijkst | Model plus het geheugen dat er al is. Vrijwel gratis. Wel een grens: dit is geen medisch advies, en dat moet GANZ ook zeggen. |
| Mail lezen en samenvatten | makkelijk | Alleen lezen is terug te draaien. |
| Mail beantwoorden | riskant | **Begin met concepten, niet met verzenden.** Een verzonden mail is niet terug te nemen. De bevestigingslaag die er al is (`require_confirmation`) is hier precies voor gemaakt. |
| Spam opruimen | riskant | Label in plaats van verwijderen. Eén verkeerd weggegooide mail van een klant is duurder dan duizend handmatig weggeklikte spammetjes. |
| Telefonisch reserveren | het moeilijkst | Als laatste, en niet alleen om techniek. Een telefoontje is niet terug te draaien, in Europa moet de ander weten dat hij met een computer praat, en een gesprek opnemen mag niet zonder toestemming. Zoek dat uit vóór je het bouwt, niet erna. |

---

## 8. De volgorde die ik zou aanhouden

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
5. **Opschalen pas als dat getal bekend is** — en dan met variatie tussen de kanalen, om de
   reden in §5b.
6. **Mail**, eerst alleen concepten. Dan de coaches, die bijna niets kosten.
7. **Telefoon** als laatste, als je het dan nog wil.

Stap 1 tot 3 maken van GANZ iets waar je dagelijks iets aan hebt. Stap 4 is de stap die
bepaalt of het plan met twintig kanalen rendabel is of niet — en dat is beter om in week
vier te weten dan in maand acht.

---

## 9. Wat ik van jou nodig heb

1. **Een `ANTHROPIC_API_KEY` op de server.** Dit is de grootste ontgrendeling van de hele
   lijst: hij maakt stap 1 mogelijk, en daarmee alles erna.
2. **Telegram of Slack?** Mijn advies is Telegram eerst, maar het is jouw werkdag.
3. **Een Google Cloud-project per groep kanalen, plus een quotaverhoging aanvragen.** En
   kijk daar meteen die grens van 100 uploads per dag na.
4. **Een keuze voor de videoaanbieder, met een bedrag per video dat je acceptabel vindt.**
   Dat laatste getal is belangrijker dan de aanbieder: het bepaalt of de fabriek kan
   draaien.

Nog iets wat openstaat uit het Quant Lab en hier nu ook speelt: het maandplafond van €200
dat in de labafspraak staat, gaat over de agents van het lab. Als het brein straks ook de
videofabriek en de assistent bedient, is dat een ander bedrag. Dat moeten we een keer
afspreken, want het plafond grijpt echt in — dat is de bedoeling.
