"""PAN / GSTIN / Udyam format and checksum validation.

Each `validate_*` function raises `ValueError` with a message naming the
*specific* thing wrong (wrong length, wrong case, bad structure, bad
checksum, unknown state code) rather than a generic "invalid PAN" — so a
caller entering "ABCDE123F" (9 characters) gets told it needs 10, not just
that it's wrong. Used by contracts/common.py to build the PAN/GSTIN/Udyam
Annotated types consumed everywhere else.

References (verified 2026-08-13, see phase1.txt Step 5 for search notes):
  - PAN: 10 chars, AAAAA9999A. The 10th character IS a checksum, but the
    Income Tax Department's algorithm is intentionally undisclosed — only
    structure (5 letters, entity-type letter, surname letter, 4 digits,
    trailing letter) can be validated client-side, not the checksum itself.
  - GSTIN: 15 chars — 2-digit state code, 10-char PAN, 1 alnum (entity
    number for that PAN in that state), fixed 'Z', 1 checksum char. The
    checksum IS publicly documented (Mod-36) and is verified below against
    a known-good GSTIN in tests/test_identifiers.py.
  - Udyam: UDYAM-XX-00-0000000 (2-letter state code, 2-digit district code,
    7-digit unique number). No public checksum digit; structure only.
"""

from __future__ import annotations

import re

# --- PAN -----------------------------------------------------------------

_PAN_PATTERN = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")

# 4th character of a PAN encodes the holder's entity type. This is the
# complete, fixed set the Income Tax Department uses.
_PAN_ENTITY_TYPE_LETTERS = frozenset("ABCFGHJLPT")
_PAN_ENTITY_TYPE_MEANING = {
    "A": "Association of Persons",
    "B": "Body of Individuals",
    "C": "Company",
    "F": "Firm / LLP",
    "G": "Government",
    "H": "Hindu Undivided Family",
    "J": "Artificial Juridical Person",
    "L": "Local Authority",
    "P": "Individual",
    "T": "Trust",
}


def validate_pan(value: str) -> str:
    if len(value) != 10:
        raise ValueError(f"PAN must be exactly 10 characters, got {len(value)}: {value!r}")
    if value != value.upper():
        raise ValueError(f"PAN must be uppercase, got {value!r}")
    if not _PAN_PATTERN.match(value):
        raise ValueError(
            f"PAN must match AAAAA9999A (5 letters, 4 digits, 1 letter), got {value!r}"
        )
    entity_letter = value[3]
    if entity_letter not in _PAN_ENTITY_TYPE_LETTERS:
        raise ValueError(
            f"PAN's 4th character {entity_letter!r} is not a recognised entity-type "
            f"letter (expected one of {sorted(_PAN_ENTITY_TYPE_LETTERS)})"
        )
    return value


# --- GSTIN -----------------------------------------------------------------

_GSTIN_PATTERN = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")

# Active GST state/UT codes as of 2026: 01-38 inclusive, minus 25 (former
# Daman & Diu, merged into 26) and 28 (former undivided Andhra Pradesh
# numbering, retired after the 2014 state reorganisation).
_VALID_GST_STATE_CODES = frozenset(
    f"{code:02d}" for code in range(1, 39) if code not in (25, 28)
)

# Mod-36 checksum alphabet: digits 0-9 (value = digit), then A-Z (value =
# 10-35). This is the same alphabet GSTN's own checksum uses.
_CHECKSUM_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def _gstin_checksum_char(first_14: str) -> str:
    """Mod-36 checksum over the first 14 characters of a GSTIN.

    Verified by hand against the known-good example GSTIN
    "27AAPFU0939F1ZV" in tests/test_identifiers.py — factor alternates
    1, 2, 1, 2... starting at 1 for the leftmost character; each product
    is folded into a single base-36 digit by adding its quotient and
    remainder on division by 36 (the same "double and reduce" shape as a
    Luhn check, adapted to base 36); the checksum character is whatever
    makes the total sum's remainder mod 36 come out to zero.
    """
    total = 0
    factor = 1
    for char in first_14:
        value = _CHECKSUM_ALPHABET.index(char)
        product = value * factor
        total += product // 36 + product % 36
        factor = 2 if factor == 1 else 1
    checksum_index = (36 - (total % 36)) % 36
    return _CHECKSUM_ALPHABET[checksum_index]


def validate_gstin(value: str) -> str:
    if len(value) != 15:
        raise ValueError(f"GSTIN must be exactly 15 characters, got {len(value)}: {value!r}")
    if value != value.upper():
        raise ValueError(f"GSTIN must be uppercase, got {value!r}")
    if not _GSTIN_PATTERN.match(value):
        raise ValueError(
            "GSTIN must match 99AAAAA9999A1Z1 (2-digit state code, PAN, entity "
            f"number, fixed 'Z', checksum), got {value!r}"
        )
    state_code = value[:2]
    if state_code not in _VALID_GST_STATE_CODES:
        raise ValueError(
            f"GSTIN state code {state_code!r} is not a currently active GST "
            "state/UT code"
        )
    # The 10 characters after the state code must themselves be a
    # structurally valid PAN (PAN has no public checksum, so only
    # validate_pan's structural checks apply — that's all we can reuse).
    validate_pan(value[2:12])
    expected_checksum = _gstin_checksum_char(value[:14])
    actual_checksum = value[14]
    if actual_checksum != expected_checksum:
        raise ValueError(
            f"GSTIN checksum mismatch: expected {expected_checksum!r}, "
            f"got {actual_checksum!r} in {value!r}"
        )
    return value


# --- Udyam -------------------------------------------------------------

_UDYAM_PATTERN = re.compile(r"^UDYAM-[A-Z]{2}-[0-9]{2}-[0-9]{7}$")


def validate_udyam(value: str) -> str:
    if len(value) != 19:
        raise ValueError(
            f"Udyam registration number must be exactly 19 characters, "
            f"got {len(value)}: {value!r}"
        )
    if value != value.upper():
        raise ValueError(f"Udyam registration number must be uppercase, got {value!r}")
    if not _UDYAM_PATTERN.match(value):
        raise ValueError(
            "Udyam registration number must match UDYAM-XX-00-0000000 "
            f"(2-letter state code, 2-digit district code, 7-digit number), got {value!r}"
        )
    return value
