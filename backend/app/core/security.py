import base64
import os
from cryptography.fernet import Fernet
from app.core.config import settings

_cipher = None

def get_cipher() -> Fernet:
    global _cipher
    if _cipher is not None:
        return _cipher

    key = settings.TOKEN_ENCRYPTION_KEY
    if not key:
        if settings.ENVIRONMENT == "production":
            raise RuntimeError("Production mode requires TOKEN_ENCRYPTION_KEY environment variable to be set.")
        # Fallback to local stored key file in scratch/dev directory
        key_file = os.path.join(os.path.dirname(__file__), "..", "..", ".secret.key")
        if os.path.exists(key_file):
            with open(key_file, "rb") as f:
                key = f.read().decode().strip()
        else:
            new_key = Fernet.generate_key().decode()
            with open(key_file, "w") as f:
                f.write(new_key)
            key = new_key

    _cipher = Fernet(key.encode() if isinstance(key, str) else key)
    return _cipher

def encrypt_token(token: str) -> str:
    """Encrypts a token string. Tokens are never logged."""
    if not token:
        return ""
    cipher = get_cipher()
    return cipher.encrypt(token.encode()).decode()

def decrypt_token(encrypted_token: str) -> str:
    """Decrypts an encrypted token string. Never logs the decrypted value."""
    if not encrypted_token:
        return ""
    cipher = get_cipher()
    return cipher.decrypt(encrypted_token.encode()).decode()
