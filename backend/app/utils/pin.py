"""Eisen aan een pincode.

Het hashen zelf gebeurt met dezelfde functie als voor wachtwoorden (`hash_password`,
pbkdf2_sha256): één plek waar dat geregeld is, en die is al doordacht. Hier staat alleen
wat een pincode een bruikbare pincode maakt.
"""

from __future__ import annotations

MIN_LENGTH = 4
MAX_LENGTH = 12


class InvalidPinError(ValueError):
    """De pincode voldoet niet aan de eisen. De tekst is voor de gebruiker."""


def validate_pin(pin: str) -> str:
    """Controleer een pincode en geef hem schoon terug."""
    schoon = pin.strip()
    if not schoon.isdigit():
        raise InvalidPinError("Een pincode bestaat alleen uit cijfers.")
    if not MIN_LENGTH <= len(schoon) <= MAX_LENGTH:
        raise InvalidPinError(
            f"Een pincode is minstens {MIN_LENGTH} en hoogstens {MAX_LENGTH} cijfers lang."
        )
    if len(set(schoon)) == 1:
        raise InvalidPinError("Kies geen pincode van allemaal dezelfde cijfers.")
    if schoon in {"1234", "12345", "123456", "0123"}:
        raise InvalidPinError("Kies iets minder voor de hand liggends dan een oplopende reeks.")
    return schoon
