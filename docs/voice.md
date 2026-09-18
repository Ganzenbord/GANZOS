# Stemherkenning

Ganz kan een spreker herkennen aan zijn stem. Wat je daarna mag, bepaalt je tier — en voor
gevoelige handelingen is een stem nooit genoeg.

## Hoe het werkt

1. **Inschrijven** — `POST /api/voice/enroll` met een WAV-opname en een `user_id`. Het model
   maakt er een vingerafdruk van (een rij getallen) en die komt in `voice_profiles` te staan,
   samen met de lengte ervan en de naam van het model. Meerdere opnames per persoon mag en
   maakt het herkennen betrouwbaarder.
2. **Herkennen** — `POST /api/voice/identify` met een opname. Die wordt met alle ingeschreven
   stemmen vergeleken; de beste die boven de drempel uitkomt, wint. Je krijgt een gewoon
   inlogtoken terug, hetzelfde soort dat `/api/auth/login` geeft.
3. **Gebruiken** — dat token gaat als `Authorization: Bearer …` mee. Vanaf dat moment werkt
   de rest van Ganz precies zoals bij inloggen met een wachtwoord.

Het antwoord van `identify`:

```json
{
  "result": "identified",
  "user_id": 1,
  "display_name": "Stef",
  "tier": 1,
  "confidence": 0.81,
  "threshold": 0.25,
  "runner_up_confidence": 0.12,
  "strong": true,
  "access_token": "…"
}
```

Kent Ganz de stem niet, dan is `result` `"unknown"`, is `user_id` leeg en komt er **geen**
token.

## Een stem is geen wachtwoord

Dit is de kern van het ontwerp, en het staat op drie plaatsen vast:

- Het token dat uit een herkenning komt draagt zijn herkomst mee (`origin: "voice"`) plus de
  gelijkenis.
- **Gevoelige handelingen vragen altijd een tweede bevestiging**, ook van de eigenaar, ook
  met een perfecte stemmatch. Zie [security.md](security.md).
- Was de herkenning **zwakker dan `GANZ_VOICE_STRONG_THRESHOLD`** (standaard 0,45), dan kan
  er met dat token helemaal niets bevestigd worden — ook niet met de juiste pincode. Ganz
  zegt dan: log in met je wachtwoord. Een opname van iemands stem is te makkelijk gemaakt om
  daar een betaling of een upload aan op te hangen.

`tests/test_access.py` houdt alle drie vast.

## Wat de cijfers betekenen

`confidence` is de cosinus tussen twee vingerafdrukken: 1 is identiek, 0 is niets gemeen.
Het is **geen kans**. "0,7" betekent niet "70% zeker".

Twee drempels:

| Instelling | Standaard | Betekent |
| --- | --- | --- |
| `GANZ_VOICE_MATCH_THRESHOLD` | 0,25 | hieronder: "ik ken je niet" |
| `GANZ_VOICE_STRONG_THRESHOLD` | 0,45 | hieronder: herkend, maar niet voor gevoelige dingen |

0,25 is de waarde die SpeechBrain zelf aanhoudt. Die is **nooit met jullie stemmen getest**,
dus stel hem bij:

- word je te vaak niet herkend → drempel omlaag;
- wordt iemand anders voor jou aangezien → drempel omhoog. Dat is het ergere geval van de twee.

Het antwoord bevat ook `runner_up_confidence`: hoe dicht de op één na beste erbij zat. Liggen
die twee vlak bij elkaar, dan is de uitslag minder stellig dan het cijfer doet vermoeden.

## Het model

SpeechBrain met ECAPA-TDNN (`speechbrain/spkrec-ecapa-voxceleb`). Dat brengt torch mee, samen
ruim een gigabyte, en zit daarom in een aparte installatiestap:

```bash
pip install -r backend/requirements-voice.txt
```

Zonder die stap start Ganz gewoon; alleen `/api/voice/enroll` en `/api/voice/identify` geven
dan een `503` met de installatieregel erin. Het model wordt pas geladen bij het eerste
gebruik, niet bij het opstarten, en daarna hergebruikt. Het rekenwerk gaat naar een aparte
draad, anders staat de hele app stil zolang het duurt.

**Wissel je van model, dan moet iedereen opnieuw worden ingeschreven.** Afdrukken van twee
modellen zijn onvergelijkbaar. Daarom staat bij elk profiel welk model hem maakte, en worden
afdrukken van een andere lengte bij het vergelijken overgeslagen in plaats van dat de hele
vergelijking strandt.

Alles loopt via `SpeakerEncoder` in `app/integrations/voice/encoder.py`. Daardoor kan er later
een ander model (pyannote) naast zonder dat `voice_service` verandert, en schuiven de tests er
een voorspelbare namaakversie in.

## Twee gaten die met opzet openstaan

**`/api/voice/identify` is voor iedereen bereikbaar.** Dat kan niet anders: het ís de
controle, dus er kan niets vóór zitten. Wat je ermee kunt is beperkt — je krijgt alleen een
token als je stem al is ingeschreven.

**De allereerste inschrijving staat open.** Zolang er nog geen enkele stem bekend is, kan
niemand herkend worden en zou niemand ooit kunnen beginnen. Die eerste keer mag daarom zonder
controle, met een waarschuwing in het logboek. Zet `GANZ_VOICE_ENROLLMENT_OPEN_WHEN_EMPTY=false`
zodra iedereen erin staat.

> **Let op:** gooi je later alle stemprofielen weg terwijl die instelling nog op `true` staat,
> dan gaat de deur weer open.

Daarna vraagt inschrijven om het recht `voice.enroll` (tier 1) **en** een tweede bevestiging —
inschrijven is immers de handeling waarmee je toegang uitdeelt.

## Opnames aanleveren

Alleen WAV. Omzetten kan met ffmpeg:

```bash
ffmpeg -i opname.m4a -ac 1 -ar 16000 opname.wav
```

Een opname duurt minstens 1 en hoogstens 30 seconden (`GANZ_VOICE_MIN_SECONDS`,
`GANZ_VOICE_MAX_SECONDS`) en is hoogstens 10 MB. Een andere bemonsteringsfrequentie mag: het
model rekent zelf om naar 16 kHz. Stereo wordt tot één spoor samengevoegd.

## Wat de tests wel en niet controleren

De tests draaien **zonder model**: ze schuiven een namaak-herkenner in die per opname een
vaste afdruk teruggeeft. Wat ze bewaken is of de toegangsregels kloppen — niet of het model
goed luistert. Dat laatste is aan SpeechBrain, en moet met echte opnames worden geprobeerd.

## Wat er nog niet is

- **Er is nog nooit een echte stem doorheen gegaan.** De drempelwaarden zijn standaardwaarden;
  reken erop dat ze bijgesteld moeten worden.
- **`voice_profiles.embedding` staat onversleuteld in de database.** Een vingerafdruk is geen
  opname en niet terug te draaien tot spraak, maar het blijft biometrie.
- **Geen limiet op het aantal aanroepen van `/api/voice/identify`.** Op een thuisnetwerk niet
  dringend; staat Ganz ooit open op internet, dan wel.
- **Geen endpoint om een stemprofiel te verwijderen.** Het recht `voice.delete` staat al in
  het register.
