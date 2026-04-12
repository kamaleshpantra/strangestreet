import os
from cryptography.fernet import Fernet
from dotenv import load_dotenv

load_dotenv()

class EncryptionService:
    def __init__(self):
        # Fallback for local dev if .env isn't loaded
        key = os.getenv("ENCRYPTION_KEY")
        if not key:
            # Generate a temporary key for local dev warning only
            print("WARNING: ENCRYPTION_KEY not found in .env. Using temporary key (MESSAGES WILL BE UNREADABLE AFTER RESTART)")
            self.key = Fernet.generate_key()
        else:
            self.key = key.encode()
        
        self.fernet = Fernet(self.key)

    def encrypt(self, text: str) -> str:
        """Encrypts plain text to a symmetric ciphertext string."""
        if not text:
            return ""
        return self.fernet.encrypt(text.encode()).decode()

    def decrypt(self, token: str) -> str:
        """
        Decrypts a ciphertext string back to plain text.
        Includes a fallback to return original text if decryption fails 
        (essential for legacy unencrypted messages).
        """
        if not token:
            return ""
        try:
            return self.fernet.decrypt(token.encode()).decode()
        except Exception:
            # Decryption failed - likely an old plain-text message
            return token

# Global instance for easy use across routers
cipher = EncryptionService()
