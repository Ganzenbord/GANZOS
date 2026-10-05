"""De grenzen van de risicolaag (sectie 9 van de opdracht).

Deze waarden staan hier als constanten en niet in de instellingen, en dat is met opzet.
Een grens die uit een omgevingsvariabele komt, is een grens die je om half drie 's nachts
"even" verzet omdat het deze keer anders is. Een grens in code verzet je met een commit,
en dat ziet iemand.

Even belangrijk: geen enkele agent kan hier bij. Er staat geen setter, geen laadfunctie en
geen verwijzing naar `Settings`. Wie dit wil wijzigen, wijzigt dit bestand.

Er is in dit project geen live handel. Alle bedragen gaan over papieren equity.
"""

from __future__ import annotations

from decimal import Decimal

# 1R is de inzet van één trade: 0,75% van de papieren equity. Dit is het enige getal dat
# de positiegrootte bepaalt. Niet de laatste uitslag, niet het aantal verliezen achter
# elkaar, niet het gevoel van de dag.
RISK_PER_TRADE_PCT = Decimal("0.0075")

# Hoogstens 1R per trade. Hoger kan niet door een hypothese worden "aangevraagd".
MAX_RISK_PER_TRADE_R = Decimal("1")

# Hoogstens 5R aan open risico bij elkaar. Vijf posities van 1R, of minder posities met
# minder risico — maar nooit meer dan vijf keer de inzet van één trade tegelijk aan tafel.
MAX_OPEN_RISK_R = Decimal("5")

# Dagverlies van 3R: geen nieuwe posities meer tot de volgende UTC-dag. Dit herstelt
# zichzelf, want de dagstand wordt per UTC-dag opnieuw opgeteld.
DAY_LOSS_HALT_R = Decimal("-3")

# Weekverlies van 8R: alles stil. Dit herstelt zich níét vanzelf — alleen Stef kan de
# grens opnieuw zetten, en dan schuift hij 8R mee (zie `quant_risk_service.reset_week_stop`).
WEEK_LOSS_STOP_R = Decimal("-8")

# De dead-man switch. Hoort het lab niets meer van het proces dat de markt in de gaten
# houdt, dan gaan er geen nieuwe posities open. Stilte betekent hier niet "rustig" maar
# "ik weet niet wat de markt doet".
HEARTBEAT_MAX_AGE_SECONDS = 120

# De weekstand loopt van maandag 00:00 UTC. Eén vaste tijdzone voor alles, zodat een
# dagstop niet per ongeluk twee keer per etmaal vervalt.
WEEK_STARTS_ON_ISO_WEEKDAY = 1
