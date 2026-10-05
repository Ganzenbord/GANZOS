"""Wat een geldige score is.

Eigen bestandje, omdat zowel de Screener (pure code) als de laag met beslismodellen dit
nodig heeft. De Screener mag de modellaag niet importeren — dan zou pure code ineens aan
een taalmodel vastzitten — en de modellaag mag de risicolaag niet vervuilen.
"""

from __future__ import annotations

import math


def is_valid_score(waarde: object) -> bool:
    """Een score is een getal tussen 0 en 1. Alles anders is geen score.

    `True` is in Python ook een int, en zou hier als score 1,0 door kunnen glippen. Dat is
    precies het soort stilzwijgende reparatie dat sectie 10 verbiedt, dus booleans vallen
    er expliciet buiten.
    """
    if isinstance(waarde, bool) or not isinstance(waarde, (int, float)):
        return False
    getal = float(waarde)
    if math.isnan(getal) or math.isinf(getal):
        return False
    return 0.0 <= getal <= 1.0
