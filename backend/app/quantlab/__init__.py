"""Broozing Quant Lab: onderzoek en papieren handel.

Er wordt in deze module niet live gehandeld. Er is geen wallet, geen sleutel en geen
code-pad naar een echte order — ook niet "voor later". Wat hier staat is de risicolaag,
het kostenboek en de beslismodellen; de rest komt in latere fases.

De indeling volgt de opdracht:

- `risk_limits.py`  — sectie 9: de grenzen, als constanten in code
- `risk.py`         — sectie 9: de Risk Officer als pure functies, zonder database
- `pricing.py`      — sectie 12: modelprijzen uit de officiële documentatie
- `budget_limits.py`— sectie 12: het maandplafond en de verdeling over de agents
- `budget.py`       — sectie 12: de budget governor als pure functies
- `agents.py`       — wie er in het lab werkt, en wie van code is
- `decision.py`     — sectie 7: het beslismodel-contract, met `RulesOnly` als vangnet
"""
