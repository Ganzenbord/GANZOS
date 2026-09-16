"""Rekenen met geld.

Alles gebeurt in Decimal. Met floats loopt een optelling van twintig rekeningen
tientallen centen uit de pas, en dat valt precies op bij het bedrag dat het grootst
in beeld staat.
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

CENTS = Decimal("0.01")


def quantize_money(value: Decimal | float | int | str) -> Decimal:
    return Decimal(str(value)).quantize(CENTS, rounding=ROUND_HALF_UP)


def to_eur(value: Decimal | None, currency: str, rate: Decimal | None) -> Decimal | None:
    """Rekent om naar euro's.

    Geeft None als er geen koers is. Dat is met opzet: liever een account dat zichtbaar
    niet meetelt dan een totaalbedrag dat stiekem op een verzonnen koers gebaseerd is.
    """
    if value is None:
        return None
    if currency.upper() == "EUR":
        return quantize_money(value)
    if rate is None or rate <= 0:
        return None
    return quantize_money(Decimal(value) * Decimal(rate))
