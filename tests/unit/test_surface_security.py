from __future__ import annotations

import pytest

from foliotone.surface.security import (
    SurfaceSecurityError,
    hash_password,
    normalize_password,
    validate_username,
    verify_password,
)


def test_password_is_nfc_normalized_and_argon2id_hashed() -> None:
    password = "ein-sehr-langes-passwort-mit-e\u0301"
    stored = hash_password(password)

    assert stored.startswith("$argon2id$")
    assert verify_password(stored, "ein-sehr-langes-passwort-mit-é")
    assert not verify_password(stored, "ein-sehr-langes-passwort-mit-e")


def test_password_is_neither_trimmed_nor_casefolded() -> None:
    password = "  Ein sehr langes Passwort  "
    assert normalize_password(password) == password
    assert normalize_password(password.casefold()) != password


def test_username_preserves_original_and_has_casefold_key() -> None:
    assert validate_username("Märta") == ("Märta", "märta")


@pytest.mark.parametrize("value", ["ab", " name", "name ", "bad\nname"])
def test_invalid_username_is_rejected(value: str) -> None:
    with pytest.raises(SurfaceSecurityError):
        validate_username(value)
