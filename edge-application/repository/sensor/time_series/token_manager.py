#!/usr/bin/env python3
# -----------------------------------------------------------------------------
# Filename: sensor_time_series_repository.py
# Author: Rajaram Lakshmanan
# Description: Handles secure storage and retrieval of API tokens.
# License: MIT (see LICENSE)
# -----------------------------------------------------------------------------

import os
import logging
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger("TokenManager")


class TokenManager:
    """
    Handles secure storage and retrieval of API tokens.

    This class provides methods for encrypting, storing, and retrieving
    API tokens using Fernet symmetric encryption.
    """

    def __init__(self,
                 token_file: str = 'config/influx_token.enc',
                 key_file: str = 'config/influx_token.key'):
        """
        Initialize the Token Manager.

        Args:
            token_file (str): Path to store the encrypted token
            key_file (str): Path to the encryption key file
        """
        self.token_file = token_file
        self.key_file = key_file

    def save_token(self, token: str) -> bool:
        """
        Save the token to an encrypted file.

        Args:
            token (str): The token to encrypt and save

        Returns:
            bool: True if successful, False otherwise
        """
        try:
            # Verify the token is not empty
            if not token:
                logger.error("Cannot save empty token")
                return False

            # Create a directory if it doesn't exist
            os.makedirs(os.path.dirname(self.token_file), exist_ok=True)

            # Load the key from the file
            key = self.load_key()
            if not key:
                logger.error("Cannot save token: No encryption key available")
                return False

            # Create Fernet cipher
            cipher = Fernet(key)

            # Encrypt token
            encrypted_token = cipher.encrypt(token.encode())

            # Save encrypted token to file
            with open(self.token_file, 'wb') as f:
                f.write(encrypted_token)

            # Set proper permissions
            os.chmod(self.token_file, 0o600)

            logger.info(f"Token saved to {self.token_file}")
            return True

        except Exception as e:
            logger.error(f"Error saving token to file: {e}")
            return False

    def load_token(self) -> Optional[str]:
        """
        Load the token from an encrypted file.

        Returns:
            str: The loaded token, or None if loading failed
        """
        try:
            # Check if the token file exists
            if not os.path.exists(self.token_file):
                logger.warning(f"Token file {self.token_file} not found")
                return None

            # Load the key from the file
            key = self.load_key()
            if not key:
                logger.error("Cannot load token: No encryption key available. Please check that key file exists.")
                return None

            # Create Fernet cipher
            cipher = Fernet(key)

            # Load encrypted token from file
            with open(self.token_file, 'rb') as f:
                encrypted_token = f.read()

            # Decrypt token
            try:
                decrypted_token = cipher.decrypt(encrypted_token)
                token = decrypted_token.decode()

                # Validate token isn't empty
                if not token:
                    logger.error("Decrypted token is empty")
                    return None

                return token
            except InvalidToken:
                logger.error(
                    "Invalid token file or incorrect key. The token file may be corrupted or the key doesn't match.")
                return None

        except Exception as e:
            logger.error(f"Error loading token from file: {e}")
            return None

    def load_key(self) -> Optional[bytes]:
        """
        Load the encryption key from a file.

        Returns:
            bytes: The encryption key, or None if loading failed
        """
        try:
            # Check if the key file exists
            if not os.path.exists(self.key_file):
                logger.error(f"Key file {self.key_file} not found")
                return None

            # Load the key from the file
            with open(self.key_file, 'rb') as f:
                key = f.read()

            return key

        except Exception as e:
            logger.error(f"Error loading key from file: {e}")
            return None