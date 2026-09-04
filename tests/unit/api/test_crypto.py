from cryptography.fernet import Fernet

from services.api.adapters.crypto import FernetTokenCipher, PlainTokenCipher


def test_fernet_cipher_roundtrip() -> None:
    cipher = FernetTokenCipher(Fernet.generate_key().decode())
    assert cipher.decrypt(cipher.encrypt("refresh-abc")) == "refresh-abc"


def test_fernet_cipher_does_not_store_plaintext() -> None:
    cipher = FernetTokenCipher(Fernet.generate_key().decode())
    assert b"refresh-abc" not in cipher.encrypt("refresh-abc")


def test_fernet_cipher_ciphertext_differs_between_keys() -> None:
    first = FernetTokenCipher(Fernet.generate_key().decode())
    second = FernetTokenCipher(Fernet.generate_key().decode())
    assert first.encrypt("refresh-abc") != second.encrypt("refresh-abc")


def test_plain_cipher_roundtrip() -> None:
    cipher = PlainTokenCipher()
    assert cipher.decrypt(cipher.encrypt("refresh-abc")) == "refresh-abc"
