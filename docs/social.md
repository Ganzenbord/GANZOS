# Social media stats

De gecombineerde cijfers van **alle** kanalen die Ganz beheert — niet één kanaal, maar
het totaal.

## Wat er wordt opgeteld

Alleen kanalen die actief zijn én de status `connected` hebben. Kanalen die opnieuw
ingelogd moeten worden tellen niet mee, maar worden wel apart gemeld. Anders lijkt een
dalend totaal een probleem met het kanaal, terwijl het een probleem met de koppeling is.

## Lege metrieken

Niet elk platform levert hetzelfde:

| | Volgers | Views | Likes | Reacties | Berichten | Omzet |
| --- | --- | --- | --- | --- | --- | --- |
| YouTube | ✓ | ✓ | – | – | ✓ | alleen met OAuth |
| Instagram | ✓ | – | – | – | ✓ | – |
| TikTok | ✓ | – | ✓ | – | ✓ | – |

Een streepje betekent: dat platform heeft er geen eindpunt voor. In de API is de waarde
dan `null`, en het dashboard toont een streepje. **Leeg is iets anders dan nul**, en dat
verschil blijft zichtbaar in plaats van weggerekend te worden.

Instagram heeft bijvoorbeeld geen levenslang totaal aan weergaven. Ganz zou dat kunnen
benaderen door losse berichten bij elkaar te schrapen, maar dat is dan geen totaal meer —
dus doet hij het niet.

## Groei

Het groeipercentage vergelijkt het aantal volgers van nu met dat van een week geleden.
Het wordt alleen getoond als er voor **alle** meegetelde kanalen een meting van een week
terug is. Anders zou een net gekoppeld kanaal als groei tellen.

## Omzet

Levert een platform omzet, dan staat er een bedrag met "deze maand" erbij. Levert geen
enkel platform omzet, dan staat er **"Niet beschikbaar"** — niet € 0,00. Inkomsten
worden nooit verzonnen.

Voor YouTube is er een OAuth-token met de yt-analytics-monetary scope nodig; een gewone
API-sleutel is niet genoeg. Instagram en TikTok hebben er geen eindpunt voor.

## Verlopen koppeling

Loopt een token af, dan krijgt het kanaal de status `reauth_required` en verschijnt er
op het dashboard:

```
TikTok Kanaal 1
● Opnieuw inloggen
```

Ganz crasht daar niet op en de andere kanalen blijven gewoon meetellen.

## Metingen

Bij elke synchronisatie komt er een nieuwe meetrij bij; oude worden nooit overschreven.
Daardoor kan de groei uit twee echte metingen worden berekend, en is er later een
grafiek te maken zonder dat er gegevens ontbreken.

## Een platform toevoegen

```python
# app/integrations/social/mijn_platform.py
from app.integrations.base import ChannelInfo, ChannelStats, ProviderAuthError

class MijnPlatformProvider:
    platform = "mijn_platform"
    display_name = "Mijn Platform"

    def is_configured(self, credentials): ...
    async def get_channel(self, credentials) -> ChannelInfo: ...
    async def get_stats(self, credentials) -> ChannelStats: ...
    async def get_recent_content(self, credentials, limit=5): ...
    async def get_revenue(self, credentials):
        return None      # geen omzet-eindpunt? Geef None, geen 0.
```

Registreren in `app/integrations/social/registry.py`. Laat metrieken die het platform
niet levert op `None` staan.

Gooi `ProviderAuthError` bij een 401 of 403; dan zet Ganz de status op
`reauth_required` in plaats van het als een storing te behandelen.

## Sleutels aanmaken

Die maak je zelf aan; Ganz kan dat niet voor je doen:

- **YouTube** — Google Cloud Console → YouTube Data API v3 → API-sleutel. Voor omzet
  bovendien een OAuth-client met de yt-analytics-monetary scope.
- **Instagram** — Meta for Developers → Instagram Graph API → toegangstoken, plus het
  account-ID van je zakelijke Instagram-account.
- **TikTok** — TikTok for Developers → Display API → OAuth-token.

Vul ze in bij *Kanaal koppelen*. Ze gaan versleuteld de database in en komen nooit terug
op het scherm.

## Bijwerken

De scheduler haalt elke `GANZ_SOCIAL_SYNC_MINUTES` minuten alles op (standaard 30). Niet
lager zetten dan nodig: deze API's hebben stevige rate limits.
