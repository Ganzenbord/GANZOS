# De server echt veilig maken — en wat een beveiligingsagent wel en niet kan

Geschreven op 10 oktober 2026. Ik ben langs elke plek gegaan waar in GANZ een geheim wordt
gecontroleerd of bewaard, en heb één gat gevonden en gedicht. Hieronder wat er goed staat,
wat er nog moet, en een eerlijk antwoord op "er moet een cybersecurity agent draaien".

---

## 1. Wat er al goed staat

Dit is geen complimentenlijstje: het is de basis waarop de rest rust, en het is beter dan
bij de meeste zelfbouw.

| | |
| --- | --- |
| **Niet op internet** | De Caddy-opzet gebruikt een Tailscale-certificaat. GANZ staat op een privénetwerk tussen je eigen apparaten, niet op een openbaar adres. Dit is de grootste enkele winst die er is — wat niet bereikbaar is, wordt niet aangevallen. |
| **Database niet naar buiten** | In `deploy/docker-compose.yml` heeft de database met opzet geen `ports:`. Alleen de backend ernaast komt erbij. |
| **Sleutels versleuteld** | Provider-tokens staan als Fernet-versleuteld blok in de database. Wie de database leest, heeft daarmee nog geen toegang tot je accounts. |
| **Sleutels komen er nooit uit** | Er is geen enkel endpoint dat een opgeslagen sleutel teruggeeft, en een test zoekt in élk antwoordmodel naar een veld dat naar een geheim ruikt. |
| **Het geheimenbestand** | `/etc/ganz/ganz.env` met rechten 0600, eigendom van root, buiten de repository en buiten het image. |
| **Productie weigert dev-sleutels** | `check_production_secrets()` laat de app niet starten met de standaard sleutel. |
| **Tweede bevestiging** | Gevoelige handelingen vragen een pincode of wachtwoord, met een token dat vijf minuten geldig is en één keer werkt. |
| **Sessies zijn in te trekken** | Elk ingelogd apparaat is een rij. Telefoon kwijt? Die ene eruit, zonder iedereen uit te loggen. Een hergebruikt vernieuwingstoken sluit de hele sessie — dat is het enige moment waarop je diefstal van een token kunt zien. |

En één ding dat echt goed is gedaan en dat vaak fout gaat: de bevestigingslaag telt
mispogingen **over een tijdvenster heen**, niet per verzoek. In de code staat waarom, en het
is precies de omzeiling die je zou verwachten: elke poging is een nieuw verzoek, dus een
grens per verzoek houdt niemand tegen die een pincode van vier cijfers zit door te proberen.

---

## 2. Het gat dat ik vond, en heb gedicht

**Inloggen had die rem niet.** Onbeperkt wachtwoorden proberen, geen teller, geen pauze. Dat
is voor een computer geen werk, en wat erachter zit zijn de sleutels van twintig kanalen,
straks je mail en misschien de telefoon.

Nu staat er een rem met drie grenzen, in dezelfde vorm als de bevestigingslaag
(`app/services/login_guard.py`):

| Grens | Standaard | Waarom niet alleen deze |
| --- | --- | --- |
| per adres **én** IP | 5 per kwartier | houdt de gewone aanval tegen: één bron die doorprobeert |
| per IP | 25 per kwartier | houdt één bron tegen die veel adressen langsgaat |
| per adres, alle IP's | 50 per kwartier | houdt een verdeelde aanval tegen: veel bronnen, één account |

Drie keuzes daarin die uitleg verdienen:

**De strenge grens geldt per paar en niet per adres.** Zou vijf keer mis jouw account een
kwartier dichtzetten, dan kan iedereen die je e-mailadres kent jou buitensluiten wanneer hij
wil. De ruime grens per adres vangt het verdeelde geval alsnog.

**Het e-mailadres staat in de database als afdruk, niet als tekst.** Wie mis tikt is meestal
de eigenaar, maar wie aan het proberen is, vult adressen in van mensen die hier geen
gebruiker zijn. Die bewaren zou betekenen dat GANZ gegevens verzamelt over mensen die er
niets te zoeken hebben. Een sha256 met het servergeheim ervoor is wél te tellen en niet
terug te lezen.

**De rem verraadt niet of een account bestaat.** Een onbekend adres gedraagt zich precies
hetzelfde. Zou de rem alleen bij bestaande accounts aangaan, dan is hij zelf een manier om
te ontdekken wie hier een account heeft.

De rijen worden elk uur opgeruimd en na een dag weggegooid. Een rem met een tijdvenster van
kwartieren die rijen maanden bewaart, is stilletjes een archief van IP-adressen geworden.

Elf tests, waarvan de belangrijkste dat het gedrag bij een onbekend adres niet afwijkt. Ik
heb twee mutaties geprobeerd (de strenge grens per adres in plaats van per paar, en de
afdruk zonder servergeheim) en beide laten een test omvallen.

---

## 3. Wat er nog moet, op volgorde van opbrengst

Dit is het werk dat ik zou doen, en het is bijna allemaal saai. Dat is geen toeval: saaie
maatregelen werken, en opwindende maatregelen zijn meestal een nieuw aanvalsoppervlak.

1. **Automatische beveiligingsupdates op de server** (`unattended-upgrades`). De meeste
   inbraken gaan via iets wat al maanden gepatcht was.
2. **Back-ups van de database, versleuteld, en één keer echt teruggezet.** Een back-up die
   nooit is teruggezet is geen back-up. Dit is ook je enige antwoord op ransomware.
3. **SSH alleen met een sleutel, geen wachtwoord, geen root-login.** En met Tailscale ervoor
   hoeft poort 22 helemaal niet open te staan.
4. **De containers krapper zetten.** Nu staat er geen `no-new-privileges`, geen `cap_drop`
   en geen `read_only` in de compose-opzet. Dat zijn drie regels per dienst en het beperkt
   wat een inbraak in één container verder kan.
5. **Afhankelijkheden scannen.** Python- en npm-pakketten met bekende lekken; dit kan een
   taak worden die eens per week kijkt en het meldt.
6. **Een logboek dat je ook echt leest.** Daar is nu de eerste aanleiding voor: mislukte en
   afgeremde inlogpogingen staan sinds vandaag in het logboek.

---

## 4. Een beveiligingsagent: wat hij wel en niet moet mogen

Je vroeg om een agent die de server veilig houdt. Ik wil daar eerlijk over zijn, want de
vorm waarin dit meestal wordt bedacht maakt een server **onveiliger**.

**Het probleem.** Een agent die de beveiliging kan *aanpassen*, heeft daarvoor rechten op de
server nodig — root, of iets wat erop lijkt. Dan heb je een onderdeel gemaakt dat met
taalmodellen praat, van buiten komende tekst leest (logregels, foutmeldingen, pakketnamen)
én je firewall kan wijzigen. Dat is precies de combinatie die je nergens anders in dit
project toestaat. Het Quant Lab heeft dezelfde regel al: **modellen adviseren,
deterministische code beslist.** Hier geldt hij harder, niet zachter.

**Wat een agent wél goed kan**, en wat echt waarde heeft:

- **Kijken en melden.** Mislukte inlogpogingen, afgeremde pogingen, nieuwe apparaten,
  rechten die iemand erbij krijgt. Niet "dit is een aanval" roepen, maar: dit is wat er
  gebeurde, en dit is waarom het opvalt.
- **Controleren of de maatregelen er nog staan.** Dat is het nuttigste en het meest
  onderschatte: staat SSH nog op sleutels, draaien de updates, is er deze week een back-up
  geweest, is de database nog niet naar buiten open. Dingen verschuiven, en niemand merkt
  het tot het misgaat. Een lijst met verwachtingen die elke dag wordt nagelopen, is
  deterministisch, te testen, en vangt het meeste.
- **De afhankelijkheden langsgaan** en een lijst maken van wat bijgewerkt moet worden.
- **Een voorstel schrijven** voor wat er veranderd moet worden — in dezelfde vorm als de
  Reviewer in het Quant Lab: het voorstel komt in een inbox en jij keurt het goed.

**Wat hij niet mag:** zelf de firewall, SSH-config, rechten, containers of
omgevingsvariabelen aanpassen. Niet omdat ik hem niet vertrouw, maar omdat de schade bij een
fout of een misleide agent onherstelbaar is en de winst klein: die wijzigingen doe je een
paar keer per jaar.

**En één ding dat een agent nooit vervangt:** dat GANZ niet op internet staat. Als die keuze
ooit verandert, is dat een grotere beslissing dan alles in dit document.
