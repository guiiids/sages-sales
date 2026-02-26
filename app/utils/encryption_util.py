from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.backends import default_backend
import base64
import os

import config


# AES-256 encryption utility functions
class AESEncryptor:
    def __init__(self, key: bytes=None):
        self._key = key
        self.backend = default_backend()
        self.block_size = 128

    @property
    def key(self) -> bytes:
        if self._key is not None:
            return self._key
        if config.AES_KEY is None:
            # Fallback or raise error gracefully later instead of at import time
            raise ValueError("AES_KEY is not set in the environment or configuration.")
        return config.AES_KEY.encode()

    def encrypt(self, plaintext: str) -> str:
        iv = os.urandom(16)
        padder = padding.PKCS7(self.block_size).padder()
        padded_data = padder.update(plaintext.encode()) + padder.finalize()
        cipher = Cipher(algorithms.AES(self.key), modes.CBC(iv), backend=self.backend)
        encryptor = cipher.encryptor()
        ct = encryptor.update(padded_data) + encryptor.finalize()
        return base64.b64encode(iv + ct).decode()

    def decrypt(self, ciphertext: str) -> str:
        data = base64.b64decode(ciphertext.encode())
        iv = data[:16]
        ct = data[16:]
        cipher = Cipher(algorithms.AES(self.key), modes.CBC(iv), backend=self.backend)
        decryptor = cipher.decryptor()
        padded_data = decryptor.update(ct) + decryptor.finalize()
        unpadder = padding.PKCS7(self.block_size).unpadder()
        plaintext = unpadder.update(padded_data) + unpadder.finalize()
        return plaintext.decode()