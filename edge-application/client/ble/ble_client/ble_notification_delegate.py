#!/usr/bin/env python3
# -----------------------------------------------------------------------------
# Filename: ble_notification_delegate.py
# Author: Rajaram Lakshmanan
# Description: Delegate for handling BLE notifications.
# License: MIT (see LICENSE)
# -----------------------------------------------------------------------------

import re
import time
import logging
import threading
from typing import Callable

from bluepy import btle

logger = logging.getLogger("BleNotificationDelegate")

class BleNotificationDelegate(btle.DefaultDelegate):
    """Base delegate for handling BLE notifications."""

    def __init__(self):
        btle.DefaultDelegate.__init__(self)

        self._lock = threading.RLock()
        self._handle_to_uuid = {}
        self._uuid_handlers = {}

        # Initialize with the current time
        self._last_update_time = time.time()

    @property
    def last_update_time(self) -> float:
        """Return the time of the last update."""
        return self._last_update_time

    # === Public API Functions ===

    def register_characteristic(self, char_uuid: str, handle: int):
        """Register a characteristic UUID with its handle for notification processing.

        Args:
            char_uuid (str): The UUID of the characteristic to register.
            handle (int): The handle ID associated with the characteristic.

        Returns:
            bool: True if registration was successful, False otherwise.
        """
        if not char_uuid or not BleNotificationDelegate._is_valid_uuid(char_uuid):
            logger.warning(f"Invalid UUID format: {char_uuid}")
            return False

        with self._lock:
            self._handle_to_uuid[handle] = char_uuid.lower()
        logger.debug(f"Registered characteristic: {char_uuid} with handle: {handle}")
        return True

    def register_handler(self, uuid: str, handler_func: Callable):
        """Register a handler function for a specific UUID.

        Args:
            uuid (str): The UUID of the characteristic to handle.
            handler_func (Callable): Function that will be called with notification sensor data.

        Returns:
            bool: True if registration was successful, False otherwise.
        """
        if not uuid or not BleNotificationDelegate._is_valid_uuid(uuid):
            logger.warning(f"Invalid UUID format: {uuid}")
            return False

        if not handler_func or not callable(handler_func):
            logger.warning("Handler function is not callable")
            return False

        with self._lock:
            self._uuid_handlers[uuid.lower()] = handler_func
        logger.info(f"Registered handler for UUID: {uuid}")
        return True

    def handleNotification(self, handle: int, data: bytes):
        """Handle notifications from all characteristics.

        Note: This method is an override of a method from the parent class.

        Args:
            handle (int): The handle ID that triggered the notification.
            data (bytes): The payload data from the notification.
        """
        logger.debug(f"Received data from handle {handle}: {data.hex()}")

        handler = None
        char_uuid = None
        with self._lock:
            char_uuid = self._handle_to_uuid.get(handle)

            if not char_uuid:
                logger.debug(f"Received notification from unknown handle: {handle}")
                return

            # Update the last update time
            self._last_update_time = time.time()

            # Find and call the appropriate handler
            handler = self._uuid_handlers.get(char_uuid.lower())

        if handler:
            try:
                logger.debug(f"Invoking handler for UUID {char_uuid}")
                handler(data)
            except Exception as e:
                logger.error(f"Error in notification handler for {char_uuid}: {e}")
        else:
            logger.info(f"No handler for UUID: {char_uuid}, data: {data.hex()}")

    # === Local Functions ===

    @staticmethod
    def _is_valid_uuid(uuid: str) -> bool:
        """Validate the format of a UUID string.

        Args:
            uuid (str): The UUID string to validate.

        Returns:
            bool: True if the UUID is in a valid format, False otherwise.
        """
        # Basic UUID validation - can be expanded for more specific formats
        if not uuid:
            return False

        # Check for standard UUID format (8-4-4-4-12 hexadecimal digits)
        uuid_pattern = re.compile(r'^[0-9a-fA-F]{8}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{12}$')

        # Also allow short form UUIDs that might be used in BLE (e.g., 16-bit UUIDs)
        short_uuid_pattern = re.compile(r'^[0-9a-fA-F]{4,8}$')

        return bool(uuid_pattern.match(uuid) or short_uuid_pattern.match(uuid))