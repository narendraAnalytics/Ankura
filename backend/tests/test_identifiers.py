"""PAN / GSTIN checksum / Udyam validator tests. Implemented in Phase 1 Step 5.

Covers valid + invalid PAN, a GSTIN with a bad checksum digit, and Udyam
edge cases — see phase1.txt Step 5 PROVE IT.

"27AAPFU0939F1ZV" is a widely-published example GSTIN used to test Mod-36
checksum implementations; its embedded PAN "AAPFU0939F" is used as the
valid-PAN fixture below (4th char 'F' = Firm/LLP, a real entity-type code).
"""

from __future__ import annotations

import pytest

from ankura.validators.identifiers import validate_gstin, validate_pan, validate_udyam

VALID_PAN = "AAPFU0939F"
VALID_GSTIN = "27AAPFU0939F1ZV"
VALID_UDYAM = "UDYAM-MH-19-0000001"


# --- PAN -------------------------------------------------------------------


def test_valid_pan_passes() -> None:
    assert validate_pan(VALID_PAN) == VALID_PAN


@pytest.mark.parametrize(
    "value",
    ["AAPFU093F", "AAPFU0939FX", ""],
    ids=["9-chars", "11-chars", "empty"],
)
def test_pan_wrong_length_is_rejected(value: str) -> None:
    with pytest.raises(ValueError, match="exactly 10 characters"):
        validate_pan(value)


def test_pan_lowercase_is_rejected() -> None:
    with pytest.raises(ValueError, match="uppercase"):
        validate_pan(VALID_PAN.lower())


@pytest.mark.parametrize(
    "value",
    ["AAPF10939F", "1APFU0939F", "AAPFU0939 "],
    ids=["digit-where-letter", "letter-order-wrong", "trailing-space-not-letter"],
)
def test_pan_bad_structure_is_rejected(value: str) -> None:
    with pytest.raises(ValueError, match="AAAAA9999A"):
        validate_pan(value)


def test_pan_invalid_entity_type_letter_is_rejected() -> None:
    # 4th character (index 3) is the entity-type letter; 'X' is not one of
    # {A,B,C,F,G,H,J,L,P,T}.
    with pytest.raises(ValueError, match="entity-type letter"):
        validate_pan("AAPXU0939F")


def test_pan_entity_type_letters_are_all_individually_valid() -> None:
    for letter in "ABCFGHJLPT":
        pan = f"AA{letter}FU0939F"
        assert validate_pan(pan) == pan


# --- GSTIN -------------------------------------------------------------------


def test_valid_gstin_passes() -> None:
    assert validate_gstin(VALID_GSTIN) == VALID_GSTIN


@pytest.mark.parametrize(
    "value",
    ["27AAPFU0939F1Z", "27AAPFU0939F1ZVV", ""],
    ids=["14-chars", "16-chars", "empty"],
)
def test_gstin_wrong_length_is_rejected(value: str) -> None:
    with pytest.raises(ValueError, match="exactly 15 characters"):
        validate_gstin(value)


def test_gstin_lowercase_is_rejected() -> None:
    with pytest.raises(ValueError, match="uppercase"):
        validate_gstin(VALID_GSTIN.lower())


def test_gstin_bad_checksum_is_rejected() -> None:
    # Last character flipped from the correct 'V' to 'A'.
    tampered = VALID_GSTIN[:14] + "A"
    with pytest.raises(ValueError, match="checksum mismatch"):
        validate_gstin(tampered)


@pytest.mark.parametrize("bad_state_code", ["25", "28", "00", "39", "99"])
def test_gstin_discontinued_or_unknown_state_code_is_rejected(bad_state_code: str) -> None:
    tampered = bad_state_code + VALID_GSTIN[2:]
    with pytest.raises(ValueError, match="state/UT code"):
        validate_gstin(tampered)


def test_gstin_embedded_pan_must_be_structurally_valid() -> None:
    # Break the embedded PAN's entity-type letter (position 5 of the GSTIN,
    # which is the 4th character of the embedded PAN).
    broken = VALID_GSTIN[:5] + "X" + VALID_GSTIN[6:]
    with pytest.raises(ValueError, match="entity-type letter"):
        validate_gstin(broken)


def test_gstin_checksum_matches_hand_verified_example() -> None:
    # Regression pin: this exact value was hand-computed (Mod-36, factor
    # alternating 1/2 from the left) against "27AAPFU0939F1ZV" while
    # implementing this validator — see identifiers.py's docstring.
    from ankura.validators.identifiers import _gstin_checksum_char

    assert _gstin_checksum_char(VALID_GSTIN[:14]) == "V"


# --- Udyam -------------------------------------------------------------------


def test_valid_udyam_passes() -> None:
    assert validate_udyam(VALID_UDYAM) == VALID_UDYAM


@pytest.mark.parametrize(
    "value",
    ["UDYAM-MH-19-000001", "UDYAM-MH-19-00000011", ""],
    ids=["18-chars", "20-chars", "empty"],
)
def test_udyam_wrong_length_is_rejected(value: str) -> None:
    with pytest.raises(ValueError, match="exactly 19 characters"):
        validate_udyam(value)


def test_udyam_lowercase_is_rejected() -> None:
    with pytest.raises(ValueError, match="uppercase"):
        validate_udyam(VALID_UDYAM.lower())


@pytest.mark.parametrize(
    "value",
    ["UDYAM_MH-19-0000001", "UDYAM-M1-19-0000001", "UDYAM-MH-1A-0000001"],
    ids=["wrong-separator", "digit-in-state-code", "letter-in-district-code"],
)
def test_udyam_bad_structure_is_rejected(value: str) -> None:
    with pytest.raises(ValueError, match="UDYAM-XX-00-0000000"):
        validate_udyam(value)
