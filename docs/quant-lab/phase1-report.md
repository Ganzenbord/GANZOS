# Quant Lab — Fase 1: risicolaag, kostenledger en tests

**Kort:** de risicolaag (sectie 9) en de budget governor (sectie 12) staan er, met de tests
eerst geschreven. De hele backend-testsuite is groen: **357 tests, waarvan 78 nieuw**. Elke
grens uit sectie 9 heeft een test die hem bewust overtreedt en die faalt als de grens
wegvalt. De LLM-off modus is getest met een leeg budget, zowel met een nagemaakte governor
als met een echt volgeboekte maand in PostgreSQL.

Er is in dit project geen live handel. Er is geen wallet, geen sleutel en geen code-pad naar
een echte order — ook niet "voor later".

---

## 1. Wat is gebouwd

### De risicolaag (sectie 9)

| Bestand | Wat erin staat |
| --- | --- |
| `backend/app/quantlab/risk_limits.py` | De grenzen als constanten. Geen import behalve `decimal`, geen functie, geen aanroep behalve `Decimal(...)` — en daar is een test op. |
| `backend/app/quantlab/risk.py` | De Risk Officer als pure functies: `one_r_eur`, `position_units`, `evaluate_entry`. Geen database, geen netwerk, geen taalmodel. |
| `backend/app/services/quant_risk_service.py` | Dezelfde beslissing met de database eronder: de stand opbouwen, de noodstop, de hartslag, en elke beslissing vastleggen. |

De grenzen, letterlijk zoals in de opdracht:

| Grens | Waarde | Herstelt zichzelf |
| --- | --- | --- |
| 1R | 0,75% van de papieren equity | — |
| Per trade | hoogstens 1R | — |
| Open risico | hoogstens 5R bij elkaar | als er iets sluit |
| Dagstop | −3R | ja, bij de volgende UTC-dag |
| Weekstop | −8R | **nee**, alleen Stef zet hem opnieuw |
| Dead-man switch | 120 seconden stilte | ja, bij de volgende hartslag |
| Noodstop | knop | nee, alleen met een bevestiging eruit |

Drie keuzes die uitleg verdienen:

**Geen martingale, en dat is geen afspraak maar een signatuur.** `one_r_eur(equity)` heeft
precies één parameter. Er is geen plek waar "ik heb net drie keer verloren" in past. Een
test leest de signatuur en valt om zodra er een tweede parameter bij komt — dan is dat een
gesprek, niet een commit.

**De weekreset zet de teller niet op nul, hij schuift de grens.** Resetten op −8R zet de
weekgrens op −16R: het verlies van deze week blijft in de cijfers staan, alleen de stop is
opnieuw gezet. Elke reset koopt dus precies 8R nieuwe ruimte, en bij de volgende maandag
staat de grens weer op −8R. Op nul zetten zou betekenen dat je na een slechte week je eigen
cijfers kwijt bent, en dat is precies het cijfer dat je wilde zien.

**De volgorde van de controles is onderdeel van het ontwerp.** Noodstop, dan hartslag, dan
week, dan dag, dan de rest. Zouden er twee grenzen tegelijk gelden en meldde hij de
lichtste, dan denk je dat je er morgen weer in mag.

### Het kostenledger en de budget governor (sectie 12)

| Bestand | Wat erin staat |
| --- | --- |
| `backend/app/quantlab/pricing.py` | De modelprijzen, mét bron-URL en verificatiedatum. Een model dat er niet in staat, kan niet geboekt worden en draait dus niet. |
| `backend/app/quantlab/budget_limits.py` | Het maandplafond, de waarschuwingsgrens, de startverdeling en de reserve. |
| `backend/app/quantlab/budget.py` | De governor als pure functies: `evaluate_call` en `status_from`. |
| `backend/app/services/quant_cost_service.py` | Boeken en optellen, plus `BudgetGovernor` die precies op het beslismodel past. |

De verdeling uit de opdracht, met een test die controleert dat hij optelt tot het plafond:

| | Maand | Daggrens |
| --- | --- | --- |
| Reviewer | € 70 | € 4,51 |
| Analyst | € 50 | € 3,22 |
| Classifier | € 10 | € 0,64 |
| Reserve (van niemand) | € 70 | — |
| **Plafond** | **€ 200** (waarschuwing bij € 150) | |

De daggrenzen staan niet in de opdracht; die heb ik als rekenregel ingevuld in plaats van
als verzonnen getal: **tweemaal het pro-rata deel van die maand** (€ 70 / 31 × 2 = € 4,51 in
oktober, € 5,00 in februari). Precies pro rata zou betekenen dat een zuinige week je geen
ruimte geeft voor een drukke dag; zonder daggrens kan één doorgedraaide dag de hele maand
opeten. De factor 2 is de enige keuze hierin en staat als losse constante in de code.

Twee dingen die ik expliciet anders heb gedaan dan de makkelijke weg:

**De reserve is niet automatisch beschikbaar.** De Reviewer die door zijn € 70 heen is,
stopt — ook al is er van de € 200 nog € 130 over. Die reserve uitgeven is een beslissing
van Stef, niet van een agent die aan het werk is.

**Het boek rekent met zes decimalen, niet met centen.** Eén aanroep van de Classifier kost
een fractie van een cent. Zou het boek op centen afronden, dan kosten duizend kleine
aanroepen samen nul euro en doet het plafond niets. Een test beschermt dit expliciet.

### Het beslismodel-contract en de LLM-off modus (sectie 7 en 10)

`backend/app/quantlab/decision.py`:

- **`RulesOnly`** — het vangnet. Geen netwerk, geen sleutel, geen budget. De standaard, en
  dat blijft het: een model neemt het over als het in de schaduw heeft bewezen dat het beter
  is, niet omdat het nieuwer is.
- **`JevClassifier`** — de plek voor JEV.ai. Zie §3 en §5 hieronder.
- **`LlmClassifier`** — een Claude-model, ook alleen voor een score.
- **`GuardedDecisionModel`** — het budget, de klok en het schema eromheen. Vier dingen kunnen
  misgaan en alle vier leiden tot hetzelfde: terugvallen op `RulesOnly` en het resultaat
  markeren als `degraded`. Er zijn aparte tellers voor budget, timeout, weggegooide
  antwoorden en fouten, want "het lab draait" en "het lab draait op het vangnet" zien er in
  de uitkomsten hetzelfde uit.
- **`ShadowDecisionModel`** — een model laten meelopen zonder het iets te laten bepalen.
  `SHADOW_DECISIONS_REQUIRED = 100`, zoals sectie 7 vraagt. Klapt het schaduwmodel eruit,
  dan verandert dat niets aan het besluit; dat is het hele punt van schaduwdraaien.

Een antwoord buiten het schema wordt **weggegooid, gelogd en geteld — nooit gerepareerd**.
Van een score van 1,7 een 1,0 maken is het ergste wat je kunt doen: dan ziet niemand ooit
dat het model iets anders zei dan afgesproken. Er is een test per vorm van onzin (1,7, −0,2,
NaN, oneindig), en elke test controleert ook dat de verkeerde waarde níét in de uitkomst
terugkomt.

### Database, rechten en API

Vijf nieuwe tabellen in migratie `0006_quant_lab_risk_en_kosten`:

| Tabel | Waarvoor |
| --- | --- |
| `quant_risk_bookings` | Wat een gesloten papieren trade opleverde, in R. De dag- en weekstand worden hieruit opgeteld en nergens bewaard. |
| `quant_risk_events` | Elke beslissing van de Risk Officer, ook — vooral — de geweigerde. |
| `quant_risk_controls` | De noodstop en de handmatige resets, als logboek. De huidige stand is de laatste rij per rem. |
| `quant_heartbeats` | De dead-man switch: één rij per onderdeel. |
| `quant_llm_calls` | Het kostenboek: tokens, dollars, euro's en de koers waarmee is gerekend. |

Twee afwijkingen van de rest van Ganz, met reden:

- **Geen `user_id`** op vier van de vijf tabellen. Dit is één lab, niet een lab per
  gebruiker. Bij `quant_risk_controls` staat wél een gebruiker — daar gaat het erom wie op de
  knop heeft gedrukt — en die blijft bewaard als het account verdwijnt (`SET NULL`), zodat
  het logboek geen gat krijgt.
- **Alleen `created_at`, geen `updated_at`** op de logboeken. Deze rijen worden nooit
  gewijzigd. Bij risico en geld is "wat stond er gisteren" de belangrijkste vraag die je kunt
  stellen, en een logboek dat je kunt bijwerken is geen logboek.

Nieuwe rechten in het bestaande register (`app/core/permissions.py`), geen if-jes in de
endpoints:

| Recht | Tier | Tweede bevestiging |
| --- | --- | --- |
| `quant.read` | 2 | nee |
| `quant.costs.read` | 1 | nee |
| `quant.run.stop` | 2 | **nee, met opzet** |
| `quant.run.start` | 1 | **ja** |
| `quant.risk.reset` | 1 | **ja** |

Let op de richting van de twee knoppen. **Stilzetten mag vanaf tier 2 en zonder
bevestiging**: stoppen is de veilige kant, en een pincode intikken terwijl je ziet dat het
misgaat kost seconden die je niet hebt. De noodstop eruit halen is wél gevoelig. Het
precedent hiervoor staat in fase 2: een apparaat uitloggen vraagt ook niets.

Zeven endpoints onder `/api/quant`, allemaal met een expliciet responsemodel:

```
GET    /api/quant/risk              de risicostand en alles wat op dit moment tegenhoudt
GET    /api/quant/risk/events       het logboek van de Risk Officer
POST   /api/quant/risk/kill-switch  noodstop aan        (quant.run.stop)
DELETE /api/quant/risk/kill-switch  noodstop uit        (quant.run.start + bevestiging)
POST   /api/quant/risk/week-reset   weekgrens opnieuw   (quant.risk.reset + bevestiging)
GET    /api/quant/costs             de budgetstand per agent
GET    /api/quant/costs/calls       het kostenboek zelf
```

De module is geregistreerd met één regel in `API_MODULES`, precies zoals fase 0 beschreef.
Geen bestaande module aangeraakt behalve die regel, het rechtenregister, drie nieuwe
regels in het activiteitenlog en twee instellingen.

---

## 2. Bewijs

### Testoutput

```
$ cd backend && .venv/bin/python -m pytest -q
357 passed in 110.60s (0:01:50)

$ .venv/bin/python -m pytest tests/test_quant_risk.py tests/test_quant_budget.py -q
78 passed in 6.98s
```

Voor fase 1 waren het 279 tests; er zijn er 78 bij gekomen en geen enkele bestaande test is
aangepast behalve één uitzonderingenlijst (zie §3).

### De grenzen tegen een echte PostgreSQL

`backend/scripts/quant_lab_proof.py` draait de bewuste overtredingen tegen PostgreSQL 16 en
drukt af wat er in de tabellen komt. Uitvoer van zojuist:

```
1. De risicolaag: acht pogingen, waarvan zeven bewuste overtredingen
  geen hartslag                      GEBLOKKEERD (heartbeat_stale)
  gezonde stand                      TOEGESTAAN
  1,5R gevraagd                      GEBLOKKEERD (risk_per_trade_exceeded)
  al 5R open                         GEBLOKKEERD (open_risk_exceeded)
  stop op de instapprijs             GEBLOKKEERD (invalid_stop)
  -3R vandaag                        GEBLOKKEERD (day_loss_halt)
  -8R deze week                      GEBLOKKEERD (week_loss_stop)
  na een handmatige weekreset        weekgrens staat nu op -16.0000R (weekstand -8.0000R)
  noodstop aan                       GEBLOKKEERD (kill_switch_active)

2. Wat er in quant_risk_events staat
  toegestaan  veto                        aantal
  False       open_risk_exceeded          1
  False       invalid_stop                1
  False       risk_per_trade_exceeded     1
  False       heartbeat_stale             1
  False       kill_switch_active          1
  False       day_loss_halt               1
  False       week_loss_stop              1
  True        -                           1

3. Het kostenboek
  reviewer     geboekt: $0.800000 = EUR 0.736000
  classifier   geboekt: $0.002000 = EUR 0.001840
  risk_officer geweigerd: agent_without_budget

  stand: normal — deze maand EUR 0.737840 van EUR 200
    reviewer     maand EUR 0.736000 van 70, dag EUR 0.736000 van 4.51
    analyst      maand EUR 0 van 50, dag EUR 0 van 3.22
    classifier   maand EUR 0.001840 van 10, dag EUR 0.001840 van 0.64

4. Drie standen
  EUR   150.737840 deze maand -> warning
  EUR   200.737840 deze maand -> llm_off

5. Een leeg budget: het lab draait door op de regels
  budgetstand:  llm_off (EUR 200.737840)
  model:        rules_only
  degraded:     True
  reden:        Budget: Deze aanroep zou het maandplafond van 200 euro doorbreken. De
                taalmodellen gaan uit; het lab gaat door op de regels. Teruggevallen op
                rules_only.
```

Dat `risk_officer` wordt geweigerd met `agent_without_budget` is geen storing: de Risk
Officer is pure code en heeft geen budget. Een aanroep van een taalmodel namens hem is een
fout in de code, niet een tekort aan geld.

### De migratie

```
$ .venv/bin/python -m alembic upgrade head
Running upgrade 0005_sessions_and_permissions -> 0006_quant_lab_risk_en_kosten

$ .venv/bin/python -m alembic check
No new upgrade operations detected.

$ .venv/bin/python -m alembic downgrade 0005_sessions_and_permissions && alembic upgrade head
(beide zonder fout)
```

`alembic check` zonder verschillen betekent dat de tabellen in de migratie en de modellen in
de code precies hetzelfde zeggen. De `downgrade` is ook echt gedraaid, niet alleen
opgeschreven.

### De acceptatie-eisen van fase 1, per stuk

| Eis | Bewijs |
| --- | --- |
| Testsuite groen | 357 tests, hierboven |
| Bewuste overtredingen worden geblokkeerd | 7 van de 7 in het proefscript, en een test per grens in `test_quant_risk.py` |
| LLM-off modus getest met een gesimuleerd leeg budget | `test_met_een_leeg_budget_valt_het_lab_terug_op_de_regels` (nagemaakte governor) en `test_het_echte_budget_met_een_volgeboekte_maand` (echte governor, € 200 in het boek), plus stap 5 van het proefscript |

### Geen taalmodel in het pad naar een trade

`test_de_risicolaag_praat_met_geen_enkel_taalmodel` leest de importboom van `risk.py` en
`risk_limits.py`. Zou iemand de Analyst erbij halen "om nog even te kijken", dan valt die
test om. `test_de_grenzen_staan_in_code_en_niet_in_een_instelling` doet hetzelfde voor de
grenzen: geen import behalve `decimal`, geen functie, geen aanroep behalve `Decimal(...)`.

---

## 3. Afwijkingen van de prompt, en waarom

1. **De daggrens per agent is een rekenregel, geen getal uit de opdracht.** Sectie 12 vraagt
   een dagcap per agent maar noemt geen bedrag. Ik heb er een regel van gemaakt (tweemaal
   pro rata) in plaats van een getal te verzinnen. De factor staat als losse constante in de
   code, dus hij is in één regel bij te stellen.

2. **De dollarkoers staat in de instellingen, niet in de code.** De risicogrenzen en het
   plafond zijn beleid en staan daarom hard in de code. Een wisselkoers is een feit over de
   buitenwereld en hoort niet in een commit. `GANZ_QUANT_USD_EUR_RATE` staat voorlopig op
   **0,92**, en dat is een geschat getal: ik kan vanuit deze omgeving geen koers ophalen
   (zie de netwerkpolicy in het fase 0-rapport). Elke boeking bewaart de koers waarmee
   gerekend is, dus het boek blijft narekenbaar als deze waarde niet klopt.

3. **De papieren inleg staat ook in de instellingen,** op voorlopig € 1.000
   (`GANZ_QUANT_PAPER_EQUITY_EUR`). Dit is het antwoord op openstaande vraag 8 uit fase 0 en
   dus eigenlijk aan jou. 1R is er 0,75% van, dus bij € 1.000 is 1R € 7,50 — dat getal
   bepaalt straks of het filter "liquiditeit ≥ 50× de positiegrootte" iets betekent.

4. **`quant.hypothesis.write` is er nog niet.** Fase 0 stelde dat recht voor, maar er is in
   fase 1 nog geen hypothese-register om te beschermen. Een recht in het register dat nergens
   geldt, verbergt de volgende; het komt in de fase waarin hypotheses echt worden
   vastgelegd.

5. **Eén bestaande test is aangepast,** `tests/test_sanitization.py`. Die test weigert elk
   veld in een antwoord waarvan de naam naar een geheim ruikt, en `input_tokens` bevat het
   woord "token". Ik heb de drie tokenvelden van het kostenboek met een reden in de
   bestaande uitzonderingenlijst gezet — dat is precies waar die lijst voor is. Het gaat om
   rekeneenheden van een taalmodel, geen sleutels.

6. **Geen scherm.** Fase 1 is risicolaag, kostenledger en tests; de schermen van de module
   staan in een latere fase. De endpoints en het recht `quant.read` zijn er al, dus de
   frontend kan er straks tegenaan gebouwd worden zonder dat de backend verandert.

7. **`RulesOnly` geeft nog geen echte score.** De regelset die er nu in zit geeft 0,0 met de
   uitleg "nog geen regels geregistreerd". De filters horen bij hypothese H1 en komen in een
   latere fase; een verzonnen score zou precies het soort cijfer zijn waar deze opdracht
   tegen waarschuwt. Het contract en het vangnet zijn wél af en getest.

---

## 4. Bekende problemen en risico's

1. **De grens van 5R open risico doet op dit moment niets.** Er zijn nog geen open posities,
   dus `open_risk_r` is altijd nul tenzij een aanroeper hem meegeeft. De grens zelf is
   getest, maar hij gaat pas echt werken als de papieren posities bestaan. Dat is geen
   nalatigheid maar wel iets om niet te vergeten: op dit moment is het een grens die klaar
   staat, niet een grens die bewaakt.

2. **Hetzelfde geldt voor de dag- en weekstand.** Die worden opgeteld uit
   `quant_risk_bookings`, en daar schrijft nog niemand in. Tot de papieren handel bestaat
   staan de dagstop en de weekstop dus op nul — correct, maar niet betekenisvol.

3. **De equity groeit nog niet mee.** 1R is 0,75% van de equity, en de equity is nu de vaste
   instelling. In de fase met papieren posities moet dat "inleg plus gerealiseerd resultaat"
   worden, anders blijft 1R staan terwijl de rekening beweegt.

4. **De dead-man switch kijkt naar de jongste hartslag van álle onderdelen.** Eén levend
   onderdeel is genoeg om de instap door te laten. Als straks de Scout stilvalt maar de
   Screener blijft kloppen, ziet de risicolaag dat niet. Dat is op te lossen door per
   onderdeel een eis te stellen; dat hoort bij de fase waarin die onderdelen bestaan en ik
   wilde hier geen eis verzinnen voor een proces dat er nog niet is.

5. **De budget governor telt per aanroep opnieuw op uit het boek.** Dat is met opzet (een
   governor die zijn eigen totaal bijhoudt, loopt uiteen zodra er twee processen draaien),
   maar het is wel een extra query per modelaanroep. Bij de aantallen van een Classifier die
   per kandidaat draait, wordt dat merkbaar. Als dat gebeurt is de oplossing een korte cache
   met een harde controle bij het boeken, niet het totaal in het geheugen zetten.

6. **Twee processen kunnen hetzelfde plafond tegelijk doorbreken.** Twee aanroepen die
   allebei net onder de € 200 meten, mogen allebei. In de praktijk gaat het om centen, maar
   wil je het dicht, dan moet het boeken en het controleren in één transactie met een lock.
   Dat is een afweging die bij fase 2 hoort, als het lab een eigen proces krijgt.

7. **De prijzen zijn van 5 oktober 2026.** Verandert Anthropic ze, dan rekent het boek stil
   verkeerd. De bron en de datum staan bij elke prijs, dus het is te zien — maar niemand
   krijgt er een melding van. Een halfjaarlijkse controle hoort op de lijst.

8. **JEV kan nog niet draaien, en dat is bewust.** De klasse staat er, maar zolang het model
   niet met prijs en bron in `pricing.py` staat, weigert het boek de aanroep. Zie §5 vraag 1.

---

## 5. Open vragen voor Stef

1. **JEV.ai: wat kost het, en waar staat dat zwart op wit?** Je wil het gebruiken en de plek
   staat klaar (`JevClassifier`, met de schaduwmodus eromheen). Wat ik nodig heb is: de
   prijspagina of de factuur, en of het per token afrekent of een vast abonnement is. Zolang
   dat er niet is, weigert het kostenboek de aanroep — en dat is beter dan nul euro boeken
   voor iets dat wel geld kost. Ik kan de prijs niet zelf opzoeken: de netwerkpolicy van deze
   omgeving laat alleen `docs.claude.com` door (fase 0, §5). Stuur je de pagina of zet je de
   netwerkpolicy open, dan is dit tien minuten werk.

2. **Hoe groot is de papieren inleg?** Nu € 1.000, dus 1R = € 7,50. Dit was al openstaande
   vraag 8 uit fase 0 en het blijft de belangrijkste: zonder dit getal is het filter
   "liquiditeit ≥ 50× de positiegrootte" niet te berekenen en het slippagemodel niet te
   maken.

3. **Dollarkoers: mag die automatisch?** Nu een vaste 0,92 in de instellingen. Een koers
   ophalen is één API-aanroep per dag, maar dat is wel weer een bron die kan uitvallen. Vast
   getal dat jij af en toe bijstelt is ook goed — dan wil ik dat weten, zodat ik er geen
   koppeling voor bouw.

4. **Is € 200 per maand exclusief de bouwkosten van Claude Code?** Dit stond ook in fase 0 en
   is nog niet beantwoord. Het maakt uit of het plafond het lab beschermt of ook mijn eigen
   werk eraan.

5. **Mag de daggrens van tweemaal pro rata zo blijven?** Dat is mijn rekenregel, niet jouw
   keuze. Voor de Reviewer komt het uit op € 4,51 per dag, en één dagrapport op Fable kost
   ongeveer € 0,74 — dus er is ruim zes keer zoveel ruimte als één rapport nodig heeft. Wil
   je de Reviewer vaker laten draaien, dan moet die factor omhoog.

6. **Krijgt je broer toegang tot het Quant Lab?** Met de rechten zoals ze nu staan kan een
   tier 2 het lab bekijken en de noodstop aanzetten, maar niet weer uitzetten en niet bij de
   kosten. Dat leek me de juiste verdeling — stoppen moet iedereen kunnen die meekijkt — maar
   het is jouw keuze.

7. **De netwerkpolicy.** Dit blokkeert fase 2 volledig: zonder netwerk is er geen Scout en
   geen datacorpus. Het is de eerste knop die om moet voordat de volgende fase zinvol is.

---

## Hoe je dit zelf nakijkt

```bash
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt

# alle tests
.venv/bin/python -m pytest -q

# alleen het Quant Lab
.venv/bin/python -m pytest tests/test_quant_risk.py tests/test_quant_budget.py -v

# de grenzen tegen een echte database (schrijft rijen, ruimt ze daarna op)
createdb ganz_proef
GANZ_DATABASE_URL=postgresql+asyncpg://ganz:ganz@localhost:5432/ganz_proef \
  .venv/bin/python -m alembic upgrade head
GANZ_DATABASE_URL=postgresql+asyncpg://ganz:ganz@localhost:5432/ganz_proef \
  .venv/bin/python -m scripts.quant_lab_proof
```

---

Fase 1 is hiermee af. Ik wacht op **"Start Fase 2"** — en op het antwoord over de
netwerkpolicy, want zonder netwerk heeft fase 2 geen data om mee te beginnen.
