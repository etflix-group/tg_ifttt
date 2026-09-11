import pytest

from tg_ifttt.storage.crypto import SecretBox


def test_secret_round_trip():
    box = SecretBox(b"x" * 32)
    ciphertext = box.encrypt(b"telegram-session")
    assert ciphertext != b"telegram-session"
    assert box.decrypt(ciphertext) == b"telegram-session"


def test_wrong_key_fails():
    box = SecretBox(b"x" * 32)
    other = SecretBox(b"y" * 32)
    ciphertext = box.encrypt(b"secret")
    with pytest.raises(Exception):
        other.decrypt(ciphertext)


def test_invalid_master_key_is_rejected():
    with pytest.raises(ValueError):
        SecretBox(b"too-short")
