"""Adapters naar echte databronnen.

Eén bestand per bron. Elke adapter doet twee dingen en niet meer: events ophalen
(`FeedSource`) en ze omzetten naar ticks (`Normalizer`). De rest van het lab merkt niet
welke bron eronder zit — dat is wat "venue-agnostisch" betekent.
"""
