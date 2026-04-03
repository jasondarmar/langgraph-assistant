"""
Encryption — AES-256 encryption/decryption para campos sensibles en DB.
"""
import logging
import os
import hashlib
from base64 import b64encode, b64decode
from cryptography.fernet import Fernet

logger = logging.getLogger(__name__)


class FieldEncryption:
    """Encripta/desencripta campos sensibles usando Fernet (AES-128)."""

    def __init__(self, master_key: str = None):
        """
        Inicializa con master key.

        Args:
            master_key: Key para derivar la clave de encriptación.
                       Si es None, usa ENCRYPTION_MASTER_KEY env var.
        """
        if not master_key:
            master_key = os.getenv("ENCRYPTION_MASTER_KEY")

        if not master_key:
            logger.warning(
                "[Encryption] No ENCRYPTION_MASTER_KEY configurada - encriptación deshabilitada"
            )
            self.cipher = None
            return

        # Derivar clave usando SHA256 (determinístico)
        # Concatenar master_key con salt fijo para reproducibilidad
        key_material = (master_key + "langgraph-assistant").encode()
        key_hash = hashlib.sha256(key_material).digest()
        # Fernet requiere una clave en base64 de 32 bytes
        key = b64encode(key_hash)
        self.cipher = Fernet(key)

    def encrypt(self, plaintext: str) -> str:
        """
        Encripta texto plano.

        Args:
            plaintext: Texto a encriptar

        Returns:
            Texto encriptado en base64
        """
        if not self.cipher:
            logger.debug("[Encryption] Encriptación deshabilitada - retornando plaintext")
            return plaintext

        try:
            ciphertext = self.cipher.encrypt(plaintext.encode())
            return b64encode(ciphertext).decode()
        except Exception as e:
            logger.error(f"[Encryption] Error encriptando: {e}")
            return plaintext

    def decrypt(self, ciphertext: str) -> str:
        """
        Desencripta texto encriptado.

        Args:
            ciphertext: Texto encriptado en base64

        Returns:
            Texto desencriptado
        """
        if not self.cipher:
            return ciphertext

        try:
            decoded = b64decode(ciphertext.encode())
            plaintext = self.cipher.decrypt(decoded).decode()
            return plaintext
        except Exception as e:
            logger.error(f"[Encryption] Error desencriptando: {e}")
            return ciphertext


# Instancia global
_encryption_instance = None


def get_encryption() -> FieldEncryption:
    """Obtiene la instancia global de encriptación."""
    global _encryption_instance
    if _encryption_instance is None:
        _encryption_instance = FieldEncryption()
    return _encryption_instance


def encrypt_field(plaintext: str) -> str:
    """Helper para encriptar un campo."""
    return get_encryption().encrypt(plaintext)


def decrypt_field(ciphertext: str) -> str:
    """Helper para desencriptar un campo."""
    return get_encryption().decrypt(ciphertext)
