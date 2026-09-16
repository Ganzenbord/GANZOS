# To do

De dagelijkse takenlijst. Het paneel linksboven in het command center, en een volledig
scherm op `/todos`.

## De belangrijkste afspraak

**Alleen jij vinkt af.** Er is geen enkele weg waarlangs een integratie een taak op
voltooid zet — ook niet als YouTube meldt dat de video is geplaatst en de taak
toevallig "YouTube controleren" heet. Dat de lijst alleen jouw bevestiging bevat, is
precies wat hem bruikbaar maakt: je kunt erop vertrouwen dat wat afgevinkt staat, ook
echt door jou is gedaan.

## Stand per dag

De stand hoort bij een dag, niet bij de taak. Elke dag krijgt een eigen rij:

| Datum | Kat eten |
| --- | --- |
| 15 september | voltooid |
| 16 september | nog niet voltooid |
| 17 september | nog niet begonnen |

Let op het verschil tussen de laatste twee. "Nog niet voltooid" betekent dat er die dag
iets is gebeurd (aangevinkt en weer uitgezet). "Nog niet begonnen" betekent dat er niets
is geregistreerd. In `GET /todos/{id}/history` zie je beide.

## Herhaling

| Waarde | Wanneer hij op de lijst staat |
| --- | --- |
| `daily` | elke dag |
| `weekdays` | maandag tot en met vrijdag |
| `weekends` | zaterdag en zondag |
| `weekly` | elke dag, tot hij die week is afgevinkt |
| `once` | tot hij is afgevinkt; daarna weg |

`weekly` werkt zo omdat "één keer per week" iets anders is dan "elke dinsdag". De taak
blijft staan tot hij die week gedaan is, en verschijnt de week erna opnieuw.

Een `once`-taak blijft op de dag zelf nog zichtbaar (afgevinkt), zodat je ziet dát je
hem hebt gedaan. De dag erna is hij weg.

## Subtaken

Een taak kan subtaken hebben: *Katten eten geven* → *Pip*, *Johann*. Die hebben hun eigen
stand per dag, dus "Pip gevoerd" staat morgen weer open.

Op het dashboard staan ze ingesprongen onder de taak. Subtaken afvinken vinkt de
hoofdtaak niet automatisch af — ook dat blijft aan jou.

## Wat je kunt instellen

Naam, omschrijving, categorie, prioriteit, herhaling, tijdstip, volgorde en of de taak
actief is. Op `/todos` kun je alles beheren: toevoegen, wijzigen, verwijderen, subtaken
toevoegen en de volgorde veranderen met de pijltjes.

Het tijdstip is alleen een tijd (`08:00`), geen datum — de datum komt uit de herhaling.

## Op het dashboard

```
TO DO LIST                    4 / 7 voltooid
────────────────────────────────────────────
☑ Katten eten geven                    08:00
   ☑ Pip
   ☐ Johann
☑ Back-up controleren                  09:00
☐ YouTube statistieken controleren     10:00
                       Alles bekijken ›
```

Onderaan kun je meteen een nieuwe dagelijkse taak toevoegen.

## Eindpunten

Zie `docs/api.md`. Alle mutaties komen in het activiteitenlog als `TODO_CREATED`,
`TODO_UPDATED`, `TODO_COMPLETED`, `TODO_REOPENED`, `TODO_DELETED` en de
`TODO_SUBTASK_*`-varianten.
