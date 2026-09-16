# Finance

Het totale vermogen in euro's, opgeteld uit alles wat je koppelt.

**Alleen tier 1.** Wijzigen vraagt bovendien om je wachtwoord.

## Wat er wordt opgeteld

Alleen accounts die actief zijn, gekoppeld zijn, én een betrouwbare waarde in euro
hebben. De rest valt er zichtbaar buiten, met de reden erbij:

| Reden | Wat er aan de hand is |
| --- | --- |
| `reauth_required` | de koppeling is verlopen, opnieuw inloggen |
| `sync_failed` | de laatste poging mislukte |
| `fx_unavailable` | er was geen wisselkoers voor die valuta |
| `no_value` | er is nog nooit een bedrag opgehaald |

Liever een account dat zichtbaar niet meetelt dan een totaalbedrag dat stiekem op een
gegokte koers gebaseerd is.

## Soorten accounts

`bank`, `savings`, `crypto_wallet`, `exchange`, `broker`, `investment`, `other`.

## Valuta

Alles wordt omgerekend naar euro voor het dashboard, maar de oorspronkelijke valuta en
het oorspronkelijke bedrag blijven bewaard. Koersen komen van
[frankfurter.app](https://frankfurter.app) — de dagkoersen van de Europese Centrale
Bank, gratis en zonder sleutel. Ze worden zes uur bewaard; de ECB publiceert toch maar
één keer per werkdag.

Lukt het ophalen niet, dan komt er géén koers terug en telt het account niet mee.

## Providers

Ganz levert er twee mee:

**`manual` — handmatig bijgehouden.** Jij vult het bedrag in. Dat is echte data; hij
komt alleen niet automatisch binnen. Het dashboard laat daarom eerlijk zien wanneer hij
voor het laatst is bijgewerkt. Voor de meeste Nederlandse banken is dit de enige
praktische route: die hebben geen API die je als particulier zomaar mag gebruiken.

**`crypto_price` — crypto op marktprijs.** Jij vult in wát je hebt (munt en aantal), de
koers komt van CoinGecko. Het bedrag is dus echt en actueel, en er is geen sleutel of
exchange-koppeling voor nodig. De munt geef je op als CoinGecko-id, bijvoorbeeld
`bitcoin` of `ethereum`.

## Een provider toevoegen

```python
# app/integrations/finance/mijn_bank.py
from app.integrations.base import Balance, ProviderAuthError, ProviderNotConfigured

class MijnBankProvider:
    key = "mijn_bank"
    display_name = "Mijn Bank"
    read_only = True          # Ganz hoeft nooit geld te verplaatsen

    def is_configured(self, credentials):
        return bool((credentials or {}).get("access_token"))

    async def fetch_balance(self, credentials):
        if not self.is_configured(credentials):
            raise ProviderNotConfigured("Koppel eerst je bank.")
        # ... haal het saldo op ...
        # bij een 401: raise ProviderAuthError("Opnieuw inloggen")
        return Balance(value=Decimal("1234.56"), currency="EUR")
```

Registreren in `app/integrations/finance/registry.py`. Verder verandert er niets: de
service, de API en het dashboard werken er meteen mee.

Gebruik bij een exchange of broker altijd een sleutel **zonder** handels- of
opnamerechten.

## Bijwerken

De scheduler haalt elke `GANZ_FINANCE_SYNC_MINUTES` minuten alles op (standaard 15) en
legt daarna een momentopname vast voor de grafiek en de trend. Handmatig bijwerken kan
met `POST /finance/sync`.

Is er langer dan `GANZ_STALE_AFTER_MINUTES` niets opgehaald, dan meldt het paneel dat de
gegevens verouderd zijn, met de werkelijke laatste tijd erbij.

## Trend

Het percentage naast het totaal vergelijkt met de laatste momentopname van meer dan een
week geleden. Is die er niet, dan staat er "nog geen trend" — geen verzonnen cijfer.

## Niets gekoppeld

```
FINANCE

€ 0,00
Totaal vermogen

Nog geen financiële accounts gekoppeld
                 Accounts koppelen ›
```

Het paneel doet nooit alsof er een rekening hangt die er niet is.
