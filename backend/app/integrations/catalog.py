"""Welke functie welke sleutel nodig heeft, en waar die sleutel staat.

Dit bestand bestaat omdat die kennis eerst nergens stond. Je kon in Ganz wel een sleutel
toevoegen — de kluis en het koppelscherm werkten — maar nergens stond welke *functie* er
iets aan had. Het gevolg: `integration_service.credentials_for()` werd door geen enkele
functie aangeroepen. Een parkeerplaats, geen leiding.

Twee regels die dit bestand bruikbaar houden:

- **`wired` is een feit, geen belofte.** Het staat alleen op `True` als er code is die deze
  sleutel echt gebruikt. Alles op `False` is een plek die klaarstaat, en dat hoort de
  gebruiker te zien in plaats van te ontdekken als er niets gebeurt.
- **`store` zegt wáár de sleutel woont.** Ganz heeft drie bewaarplaatsen die om een goede
  reden naast elkaar bestaan, en een scherm dat dat verschil verzwijgt, stuurt mensen naar
  het verkeerde formulier.

De drie bewaarplaatsen:

| `store` | Waar | Waarom daar |
| --- | --- | --- |
| `integration` | kluis per gebruiker (`/api/integrations`) | sleutels van diensten die je zelf aanmeldt |
| `channel` / `account` | bij het kanaal of de rekening zelf | tien kanalen hebben tien tokens, geen gedeelde |
| `server` | omgevingsvariabele op de server | geldt voor iedereen, hoort niet in een database per gebruiker |

Een nieuwe functie toevoegen betekent: hier een regel erbij, en in de functie zelf
`integration_service.require_credentials()` aanroepen. Dan verschijnt hij automatisch in
het koppeloverzicht, inclusief wat er nog mist.

Eén ding dat hier nog niet goed staat en dat je moet weten: de kluis is **per gebruiker**.
Een abonnement van het bedrijf — VidRush, Nexlev — hoort bij de werkruimte en niet bij één
persoon, want dan moet de ander hem opnieuw invullen en betaal je twee keer. Die laag
bestaat nog niet (zie `docs/ganz-als-bedrijf.md`, "Samen in één bedrijf"). Tot die er is
staan deze sleutels bij degene die ze invult, en dat is een bewuste tussenstand en geen
ontwerp.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Store(StrEnum):
    INTEGRATION = "integration"
    CHANNEL = "channel"
    ACCOUNT = "account"
    SERVER = "server"


WAAR_UITLEG: dict[Store, str] = {
    Store.INTEGRATION: "Bij Instellingen → Koppelingen, met je eigen sleutel.",
    Store.CHANNEL: "Per kanaal, bij het kanaal zelf (Kanalen → kanaal → koppelen).",
    Store.ACCOUNT: "Per rekening, bij de rekening zelf (Financiën → rekening).",
    Store.SERVER: "Als omgevingsvariabele op de server (deploy/ganz.env).",
}


@dataclass(frozen=True, slots=True)
class CredentialField:
    """Eén veld dat ingevuld moet worden.

    `name` is de sleutel in het opgeslagen object en moet lettergelijk kloppen met wat de
    provider uitleest — anders lijkt de koppeling gelukt en werkt hij niet.
    """

    name: str
    label: str
    # Niet "secret": dit veld is geen geheim, het zegt tegen het scherm dat hij de invoer
    # moet maskeren. De waakhond in tests/test_sanitization.py pakt elk responsemodel met
    # een veld dat naar een geheim ruikt, en die waakhond heeft gelijk — een uitzondering
    # maken zou hem leren dat hij soms mag zwijgen.
    masked: bool = True
    hint: str | None = None


@dataclass(frozen=True, slots=True)
class Capability:
    key: str
    name: str
    category: str
    purpose: str
    store: Store
    fields: tuple[CredentialField, ...] = ()
    docs_url: str | None = None
    wired: bool = False
    note: str | None = None


# De categorieën, in de volgorde waarin ze op het scherm horen te staan.
CATEGORIES: tuple[str, ...] = ("kanalen", "productie", "assistent", "modellen", "geld", "lab")


CATALOG: tuple[Capability, ...] = (
    # --- Kanalen: wat er nu al echt werkt -----------------------------------
    Capability(
        key="youtube",
        name="YouTube",
        category="kanalen",
        purpose=(
            "Kanaalgegevens, weergaven, abonnees, recente video's, omzet per maand en het "
            "uploaden van een video."
        ),
        store=Store.CHANNEL,
        fields=(
            CredentialField("channel_id", "Kanaal-ID", masked=False,
                            hint="Begint met UC…"),
            CredentialField("api_key", "API-sleutel",
                            hint="Alleen voor openbare cijfers; voor omzet en uploaden is "
                                 "OAuth nodig."),
            CredentialField("oauth_access_token", "OAuth-token",
                            hint="Komt automatisch van de knop 'Koppel met YouTube'."),
        ),
        docs_url="https://console.cloud.google.com/apis/credentials",
        wired=True,
    ),
    Capability(
        key="youtube_oauth_app",
        name="YouTube: het Google-project",
        category="kanalen",
        purpose="Nodig voordat één kanaal kan koppelen. Eén keer instellen, voor alle kanalen.",
        store=Store.SERVER,
        fields=(
            CredentialField("youtube_client_id", "Client-ID", masked=False),
            CredentialField("youtube_client_secret", "Client secret"),
        ),
        docs_url="https://console.cloud.google.com/apis/credentials",
        wired=True,
        note=(
            "Staat het OAuth-scherm nog op 'Testing', dan moet je eigen account als "
            "testgebruiker toegevoegd zijn en verloopt de toestemming na zeven dagen."
        ),
    ),
    Capability(
        key="tiktok",
        name="TikTok",
        category="kanalen",
        purpose="Volgers, weergaven en recente video's van een TikTok-kanaal.",
        store=Store.CHANNEL,
        fields=(CredentialField("access_token", "Access token"),),
        wired=True,
    ),
    Capability(
        key="instagram",
        name="Instagram",
        category="kanalen",
        purpose="Volgers en recente berichten van een Instagram-account.",
        store=Store.CHANNEL,
        fields=(
            CredentialField("ig_user_id", "Instagram-gebruikers-ID", masked=False),
            CredentialField("access_token", "Access token"),
        ),
        wired=True,
    ),
    Capability(
        key="ayrshare",
        name="Ayrshare",
        category="kanalen",
        purpose="Eén sleutel om naar meerdere platforms te publiceren, TikTok inbegrepen.",
        store=Store.INTEGRATION,
        fields=(CredentialField("api_key", "API-sleutel"),),
        docs_url="https://www.ayrshare.com/",
        note="Nog niets aangesloten. Ganz praat nu rechtstreeks met de eigen API van TikTok "
             "(open.tiktokapis.com) met een token per kanaal. Ayrshare zou dat kunnen "
             "vervangen door een sleutel voor meerdere platforms tegelijk; dat is een keuze, "
             "geen half werk.",
    ),

    # --- Productie: de videofabriek ------------------------------------------
    Capability(
        key="vidrush",
        name="VidRush",
        category="productie",
        purpose="Het beeld bij een script. Dit is de duurste stap van de hele fabriek.",
        store=Store.INTEGRATION,
        fields=(
            CredentialField("api_key", "API-sleutel"),
            CredentialField("workspace_id", "Werkruimte- of project-ID", masked=False,
                            hint="Alleen als VidRush daarmee werkt; anders leeg laten."),
        ),
        docs_url="https://docs.vidrush.ai/",
        note="Nog niets aangesloten; er is nog geen client in Ganz. Twee dingen om bij het "
             "invullen na te kijken, want ik kon hun site vanuit de server niet bereiken: "
             "hoe de velden écht heten, en of er een API is. VidRush rekent per afgeleverde "
             "minuut, dus de lengte per kanaal bepaalt de rekening.",
    ),
    Capability(
        key="nexlev",
        name="Nexlev",
        category="productie",
        purpose=(
            "Niche- en kanaalonderzoek: wat werkt in een niche, welke kanalen groeien, "
            "welke video's het boven verwachting doen, en wat een niche per 1.000 "
            "weergaven opbrengt."
        ),
        store=Store.INTEGRATION,
        fields=(CredentialField("api_key", "API-sleutel"),),
        docs_url="https://nexlev.io/",
        note="Nog niets aangesloten. Dit is de bron waarmee de keuze van een niche een "
             "meting wordt in plaats van een gevoel — en daarmee het tegengif tegen het "
             "probleem uit het Quant Lab: met tien video's weet je nog niets over een "
             "kanaal, maar over een niche is er wél data van anderen.",
    ),
    Capability(
        key="web_onderzoek",
        name="Scriptonderzoek (feiten en bronnen)",
        category="productie",
        purpose="Feiten en bronnen opzoeken voor de inhoud van een script.",
        store=Store.INTEGRATION,
        fields=(CredentialField("api_key", "API-sleutel"),),
        note="Iets anders dan Nexlev: dat gaat over wat werkt, dit over wat waar is. "
             "Aanbieder nog te kiezen. Zonder dit kan Ganz alleen schrijven wat het model al "
             "weet, en dat is per definitie oud nieuws.",
    ),
    Capability(
        key="stem_generatie",
        name="Voice-over",
        category="productie",
        purpose="Een stem bij het script, voor een kanaal zonder gezicht.",
        store=Store.INTEGRATION,
        fields=(CredentialField("api_key", "API-sleutel"),),
        docs_url="https://elevenlabs.io/",
        note="Nog niets aangesloten. Let op de lengte: bij video's van een kwartier is dit "
             "per video een flink stuk tekst, en de meeste aanbieders rekenen per teken.",
    ),
    Capability(
        key="thumbnails",
        name="Thumbnails",
        category="productie",
        purpose="Het plaatje waarop iemand klikt.",
        store=Store.INTEGRATION,
        fields=(CredentialField("api_key", "API-sleutel"),),
        note="Nog niets aangesloten, en goedkoop vergeleken met de rest: een plaatje kost "
             "centen waar een minuut video dollars kost. Bij twintig kanalen met elk een "
             "eigen beeldtaal is dit wel twintig keer een andere stijl.",
    ),
    Capability(
        key="muziek_licentie",
        name="Muziek met licentie",
        category="productie",
        purpose="Audio waarvan je de rechten kunt aantonen.",
        store=Store.INTEGRATION,
        fields=(CredentialField("api_key", "API-sleutel"),),
        note="Nog niets aangesloten. Dit is geen luxe maar de verzekering voor de "
             "muziekkanalen: Content ID herkent opnames automatisch, en een claim kan de "
             "opbrengst van een video naar de rechthebbende laten gaan zonder dat je het "
             "merkt. Een licentie die je kunt aantonen is het enige antwoord.",
    ),

    # --- Assistent: praten met Ganz, en de rest ------------------------------
    Capability(
        key="slack",
        name="Slack",
        category="assistent",
        purpose="Met Ganz praten vanaf je telefoon, en de dagelijkse feed ontvangen.",
        store=Store.INTEGRATION,
        fields=(
            CredentialField("bot_token", "Bot token", hint="Begint met xoxb-"),
            CredentialField("signing_secret", "Signing secret",
                            hint="Waarmee Ganz controleert dat een bericht echt van Slack komt."),
            CredentialField("app_token", "App-level token", hint="Begint met xapp-, voor "
                            "Socket Mode; dan hoeft Ganz niet van buiten bereikbaar te zijn."),
        ),
        docs_url="https://api.slack.com/apps",
        note="Nog niets aangesloten: er is geen Slack-code in Ganz.",
    ),
    Capability(
        key="telegram",
        name="Telegram",
        category="assistent",
        purpose="Hetzelfde als Slack, met een bot in een privégesprek.",
        store=Store.INTEGRATION,
        fields=(CredentialField("bot_token", "Bot token", hint="Van @BotFather"),),
        docs_url="https://core.telegram.org/bots",
        note="Nog niets aangesloten. Eenvoudiger dan Slack: één token, geen app-installatie.",
    ),
    Capability(
        key="mail",
        name="E-mail",
        category="assistent",
        purpose="Mail lezen, antwoorden voorstellen en spam opruimen.",
        store=Store.INTEGRATION,
        fields=(
            CredentialField("client_id", "Client-ID", masked=False),
            CredentialField("client_secret", "Client secret"),
            CredentialField("refresh_token", "Refresh token"),
        ),
        docs_url="https://console.cloud.google.com/apis/credentials",
        note="Nog niets aangesloten. Let op het verschil tussen lezen en versturen: lezen is "
             "terug te draaien, een verzonden mail niet.",
    ),
    Capability(
        key="agenda",
        name="Agenda",
        category="assistent",
        purpose="Je dag kennen, en een afspraak of reservering erin zetten.",
        store=Store.INTEGRATION,
        fields=(
            CredentialField("client_id", "Client-ID", masked=False),
            CredentialField("client_secret", "Client secret"),
            CredentialField("refresh_token", "Refresh token"),
        ),
        docs_url="https://console.cloud.google.com/apis/credentials",
        note="Nog niets aangesloten. Zelfde Google-project als de mail kan, maar het is een "
             "aparte toestemming: lezen van je agenda en erin schrijven zijn twee dingen.",
    ),
    Capability(
        key="telefonie",
        name="Telefoneren",
        category="assistent",
        purpose="Een reservering maken door echt te bellen.",
        store=Store.INTEGRATION,
        fields=(
            CredentialField("api_key", "API-sleutel"),
            CredentialField("from_number", "Telefoonnummer om vanaf te bellen", masked=False),
        ),
        note="Nog niets aangesloten, en van alles op deze lijst het lastigst: een telefoontje "
             "is niet terug te draaien en in Nederland moet de andere kant weten dat hij met "
             "een computer praat.",
    ),

    # --- Modellen: het brein -------------------------------------------------
    Capability(
        key="anthropic",
        name="Claude (Anthropic)",
        category="modellen",
        purpose=(
            "Het model dat leest, schrijft en beslist. Zonder dit kan Ganz gegevens "
            "ophalen en tonen, maar niets zelf bedenken."
        ),
        store=Store.SERVER,
        fields=(CredentialField("anthropic_api_key", "API-sleutel"),),
        docs_url="https://platform.claude.com/",
        note="Nog niets aangesloten: er is nergens in Ganz een aanroep naar een taalmodel. "
             "Dit is de grootste ontbrekende schakel.",
    ),

    # --- Geld ---------------------------------------------------------------
    Capability(
        key="crypto_koers",
        name="Cryptokoersen",
        category="geld",
        purpose="De waarde van een cryptobezitting in euro's.",
        store=Store.ACCOUNT,
        fields=(
            CredentialField("asset_id", "Munt", masked=False, hint="Bijvoorbeeld 'bitcoin'"),
            CredentialField("amount", "Hoeveelheid", masked=False),
        ),
        wired=True,
        note="Geen API-sleutel nodig: de koers komt van een openbaar adres. Wat je hier "
             "invult is je bezit, niet een sleutel.",
    ),

    # --- Lab ----------------------------------------------------------------
    Capability(
        key="vybe",
        name="Vybe Network",
        category="lab",
        purpose="Solana-trades voor het Quant Lab: de markt waar hypothese H1 over gaat.",
        store=Store.INTEGRATION,
        fields=(CredentialField("api_key", "API-sleutel"),),
        docs_url="https://vybe.fyi/api-pricing",
        note="De adapter staat er (app/quantlab/sources/vybe.py) maar leest deze sleutel nog "
             "niet; hij krijgt zijn client van buiten.",
    ),
    Capability(
        key="binance_bulk",
        name="Binance bulkdata",
        category="lab",
        purpose="Gratis historische candles en trades voor het Quant Lab.",
        store=Store.SERVER,
        fields=(),
        wired=True,
        note="Geen sleutel nodig, alleen netwerktoegang naar data.binance.vision. "
             "Zie docs/quant-lab/databronnen.md.",
    ),
)


_PER_KEY = {c.key: c for c in CATALOG}


def capability(key: str) -> Capability | None:
    return _PER_KEY.get(key)


def capabilities_in(category: str) -> tuple[Capability, ...]:
    return tuple(c for c in CATALOG if c.category == category)
