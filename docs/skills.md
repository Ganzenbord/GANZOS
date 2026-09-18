# Skills en taken

Een **taak** is iets wat je Ganz vraagt. Een **skill** is iets wat Ganz kan. De SkillMatcher
zoekt erbij welke skill bij welke taak hoort, en de SkillExecutor loopt de stappen langs.

```
opdracht → planned → matching → skill gevonden?
                                 ├── ja  → running → done | failed | waiting
                                 └── nee → planned, mét uitleg waarom niet
```

Die laatste tak is belangrijk: als er niets past, blijft de taak gewoon staan en staat er
precies bij waarom er geen skill was. Dat is het moment waarop je er een maakt.

## Een skill

```json
{
  "name": "Video uploaden",
  "description": "Een afgeronde video publiceren naar YouTube",
  "trigger_pattern": "upload|publiceer|zet online",
  "steps": [
    { "tool": "youtube.upload", "action": "upload" },
    { "tool": "activity.log", "action": "success" }
  ],
  "required_permission": null
}
```

| Veld | Waarvoor |
| --- | --- |
| `trigger_pattern` | extra woorden waarop hij aanslaat, met `\|` ertussen. Leeg = alleen naam en omschrijving |
| `steps` | de stappen. Elke stap noemt een `tool`; wat er verder in staat is aan het gereedschap |
| `required_permission` | het recht dat nodig is om hem te draaien. Leeg = afgeleid uit de stappen |
| `version` | loopt op zodra de stappen veranderen, niet bij een naamswijziging |
| `success_count` / `failure_count` | hoe vaak het lukte en hoe vaak niet |

## Matchen: twee manieren, altijd met uitleg

| Manier | Hoe | Nodig |
| --- | --- | --- |
| **woorden** | telt hoeveel woorden de opdracht deelt met naam, omschrijving en trigger_pattern | niets |
| **betekenis** | sentence-transformers, lokaal: begrijpt dat "zet de video online" en "upload naar YouTube" hetzelfde bedoelen | `pip install -r backend/requirements-skills.txt` |

Er gaat **nooit** iets naar een externe dienst om te matchen.

Staat het model er niet, dan matcht Ganz op woorden. Dat gebeurt niet stilletjes: in elk
antwoord staat welke van de twee het werd (`"backend": "woorden"`), en er komt één
waarschuwing in het logboek. Anders zou je je afvragen waarom het matchen ineens slechter is
zonder dat iets dat zegt.

Elke uitslag draagt een reden mee, en die komt ook in de taak te staan:

```json
{ "matched": true,  "confidence": 0.67, "backend": "woorden",
  "reason": "'Weerbericht' met 0.67 (gedeelde woorden: weer, morgen)." }

{ "matched": false, "confidence": 0.12, "backend": "woorden",
  "reason": "Beste was 'Weerbericht' met 0.12 (gedeelde woorden: niets), onder de drempel van 0.45." }
```

### De drempel

`GANZ_SKILL_MATCH_THRESHOLD`, standaard `0.45`. **Let op:** de twee manieren tellen niet
hetzelfde. Woorden-overlap komt zelden boven 0,7; betekenis-gelijkenis zit vaak al rond 0,5
voor zinnen die niets met elkaar te maken hebben. Zet je het model aan, kijk dan opnieuw naar
deze waarde.

Te laag → Ganz pakt de verkeerde skill. Te hoog → hij zegt steeds dat hij het niet kan. Het
eerste is vervelender, dus begin liever te streng.

## Uitvoeren: nu nog een stub, maar met het juiste koppelvlak

De stappen worden nagelopen, gecontroleerd en gelogd — er gebeurt nog **niets** in de
buitenwereld. Dat staat in elk antwoord (`"simulated": true`) en per gereedschap
(`GET /api/skills/tools`).

Dat is met opzet zo. Een halve upload is erger dan geen upload. Wat nu al goed staat is het
koppelvlak: een gereedschap is een naam plus een functie, en die gaan in een `ToolRegistry`.
Straks een echte YouTube-upload aansluiten is één `register()` erbij — de Task-API, de
statussen en de manier waarop resultaten worden opgeslagen veranderen daar niet van.

```python
registry.register(Tool(
    "youtube.upload",
    "Een video publiceren naar YouTube",
    echte_upload_functie,
    sensitive=True,
    simulated=False,
))
```

Drie dingen die het koppelvlak nu al afdwingt, omdat ze later niet meer in te bouwen zijn
zonder alles om te gooien:

1. **Een stap met een onbekend gereedschap laat de hele taak falen vóór er iets gebeurt.**
   Bij stap drie stoppen laat een halve handeling achter die niemand heeft aangevraagd. Om
   dezelfde reden weigert `POST /api/skills` een skill met een onuitvoerbare stap meteen.
2. **Een gereedschap zegt zelf of het gevoelig is.** Is het dat, dan weigert de uitvoering
   zonder bevestiging.
3. **De uitvoering stopt bij de eerste fout en draait niets terug.** Wat wél gelukt is staat
   in het resultaat, zodat je weet waar je moet kijken. Terugdraaien kan pas zinnig als de
   gereedschappen echt iets doen en zelf weten hoe ze dat ongedaan maken.

### De gereedschappen nu

`activity.log`, `todo.create`, `weather.read`, `calendar.read`, `mail.read`,
`smart_home.control`, `finance.read`, en als gevoelig: `mail.send`, `youtube.upload`.
Allemaal nog gesimuleerd.

## Rechten en bevestiging

Twee verschillende dingen, en ze zitten op twee plekken:

- **Het recht** zegt of je het mág. `tasks.execute` (tier 2) om überhaupt iets te draaien, en
  zit er gevoelig gereedschap in de stappen, dan bovendien het recht dat daarbij hoort —
  standaard `upload.execute` (tier 1), of wat er in `required_permission` staat.
- **De bevestiging** zegt of je het nú wilt. Die hangt niet aan het endpoint maar aan de
  stappen: één skill haalt het weer op, de volgende publiceert een video. Zit er iets
  gevoeligs bij, dan is er een bevestiging nodig (`428` zonder). Zie
  [security.md](security.md).

Een taak die op een bevestiging wacht gaat naar `waiting`, niet naar `failed` — en telt dus
ook niet als mislukking van de skill.

## De statussen

| In de architectuurprompt | Hier | Betekent |
| --- | --- | --- |
| `pending` | `planned` | aangemaakt, nog niets mee gedaan |
| `matching` | `matching` | de matcher is bezig |
| `executing` | `running` | de stappen lopen |
| `completed` | `done` | klaar |
| `waiting_confirmation` | `waiting` | wacht op een bevestiging |
| `failed` | `failed` | misgegaan, met de reden in `error` |
| `cancelled` | `cancelled` | afgebroken |

De woorden links komen uit de prompt, die rechts stonden al in de frontend. Ze betekenen
hetzelfde; hernoemen zou de bestaande tijdlijn breken zonder dat er iets voor terugkomt.

## De endpoints

| Endpoint | Wat het doet | Recht |
| --- | --- | --- |
| `GET /api/skills` | je skills | `skills.read` |
| `GET /api/skills/tools` | waar een skill uit kan bestaan | `skills.read` |
| `POST /api/skills` | er een maken | `skills.write` |
| `PATCH /api/skills/{id}` | wijzigen | `skills.write` |
| `DELETE /api/skills/{id}` | weghalen | `skills.write` |
| `GET /api/tasks` | je taken | `tasks.read` |
| `POST /api/tasks` | een taak aanmaken | `tasks.write` |
| `POST /api/tasks/{id}/match` | zoek de skill erbij | `tasks.write` |
| `POST /api/tasks/{id}/execute` | uitvoeren | `tasks.execute` (+ bevestiging bij gevoelig) |
| `POST /api/tasks/{id}/cancel` | afbreken | `tasks.write` |

## Wat er nog niet is

- **Geen enkel gereedschap doet echt iets.** Dat is fase 7 (YouTube) en verder.
- **Geen automatische koppeling van opdracht naar uitvoering.** Je matcht en voert los uit.
  Dat is bewust: zolang de executor een stub is, is een knop per stap duidelijker dan een
  ketting die vanzelf doorloopt.
- **Geen terugdraaien.** Zie hierboven.
- **De drempel is nooit met echte opdrachten getest.** Reken erop dat hij bijgesteld moet
  worden, zeker als je het taalmodel aanzet.
- **Skills worden niet automatisch geleerd.** Ze worden aangemaakt. "Onthoud dit als skill"
  komt later.
