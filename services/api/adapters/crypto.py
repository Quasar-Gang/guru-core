"""TokenCipherPort implementations: `FernetTokenCipher` for real, `PlainTokenCipher` for tests."""

from cryptography.fernet import Fernet

__all__ = ["FernetTokenCipher", "PlainTokenCipher"]


class FernetTokenCipher:
    """Authenticated symmetric encryption (AES-128-CBC + HMAC) from `cryptography.fernet`.

    The key is a urlsafe base64-encoded 32-byte value, read from `OAUTH_TOKEN_ENC_KEY`.
    Generate one with `Fernet.generate_key().decode()`.
    """

    def __init__(self, key: str) -> None:
        if not key:
            raise ValueError("FernetTokenCipher needs a non-empty key")
        self._fernet = Fernet(key.encode())

    def encrypt(self, plaintext: str) -> bytes:
        return self._fernet.encrypt(plaintext.encode())

    def decrypt(self, ciphertext: bytes) -> str:
        return self._fernet.decrypt(ciphertext).decode()


class PlainTokenCipher:
    """Test double that stores the token as-is. Never wire this into production."""

    def encrypt(self, plaintext: str) -> bytes:
        return plaintext.encode()

    def decrypt(self, ciphertext: bytes) -> str:
        return ciphertext.decode()
