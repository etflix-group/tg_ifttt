import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class SecretBoxError(ValueError):
    """Raised when encrypted application data cannot be opened."""


class SecretBox:
    _PREFIX = b"TGIFTT1"
    _NONCE_SIZE = 12

    def __init__(self, master_key: bytes) -> None:
        if not isinstance(master_key, bytes) or len(master_key) != 32:
            raise ValueError("master key must be exactly 32 bytes")
        self._key = master_key
        self._cipher = AESGCM(master_key)

    @classmethod
    def is_encrypted(cls, value: bytes) -> bool:
        """Return whether a stored value has the application ciphertext marker."""
        return isinstance(value, bytes) and value.startswith(cls._PREFIX)

    def encrypt(self, plaintext: bytes) -> bytes:
        if not isinstance(plaintext, bytes):
            raise TypeError("plaintext must be bytes")
        nonce = os.urandom(self._NONCE_SIZE)
        encrypted = self._cipher.encrypt(nonce, plaintext, self._PREFIX)
        return self._PREFIX + nonce + encrypted

    def decrypt(self, ciphertext: bytes) -> bytes:
        if not isinstance(ciphertext, bytes):
            raise TypeError("ciphertext must be bytes")
        expected_minimum = len(self._PREFIX) + self._NONCE_SIZE + 16
        if len(ciphertext) < expected_minimum or not ciphertext.startswith(self._PREFIX):
            raise SecretBoxError("invalid encrypted value")
        offset = len(self._PREFIX)
        nonce = ciphertext[offset : offset + self._NONCE_SIZE]
        encrypted = ciphertext[offset + self._NONCE_SIZE :]
        try:
            return self._cipher.decrypt(nonce, encrypted, self._PREFIX)
        except InvalidTag as exc:
            raise SecretBoxError("encrypted value authentication failed") from exc
