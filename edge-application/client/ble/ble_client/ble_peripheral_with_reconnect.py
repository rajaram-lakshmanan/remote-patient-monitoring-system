#!/usr/bin/env python3
# -----------------------------------------------------------------------------
# Filename: ble_peripheral_with_reconnect.py
# Author: Rajaram Lakshmanan
# Description: Extension of bluepy's Peripheral class that handles
# disconnection.
# License: MIT (see LICENSE)
# -----------------------------------------------------------------------------

import logging
from typing import Optional

from bluepy import btle

from client.ble.ble_client.ble_client import BleClient

logger = logging.getLogger("BlePeripheralWithReconnect")

class BlePeripheralWithReconnect(btle.Peripheral):
    """
    Extension of bluepy's Peripheral class that handles disconnections better.

    This wrapper adds automatic disconnect detection and notifies the client
    when a disconnection occurs.
    """

    def __init__(self, device_addr: str, ble_client: BleClient):
        """
        Initialize the peripheral with capabilities to reconnect.

        Args:
            device_addr (str): MAC address of the device.
            ble_client (BleClient): Reference to the BleClient that owns this peripheral.
        """
        self._ble_client = ble_client
        super().__init__(device_addr)

    # === Protected API Functions ===

    def _getResp(self, wantType, timeout: Optional[float] = None):  # noqa
        """
        Override _getResp to handle disconnections.

        This method is called internally by bluepy when communicating with the device.
        By overriding it, we can detect disconnections and notify the client.

        Args:
            wantType (int): The expected response type.
            timeout (float): Optional timeout in seconds.

        Returns:
            The response from the device.

        Raises:
            btle.BTLEDisconnectError: If the device disconnects.
        """
        try:
            # noinspection PyProtectedMember
            return super()._getResp(wantType, timeout)
        except btle.BTLEDisconnectError:
            logger.info(f"Disconnection detected for device {self.addr}")
            # Notify the client of the disconnection
            try:
                self._ble_client.handle_disconnect()
            except Exception as e:
                logger.error(f"Error in handle_disconnect: {e}")
            # Re-raise the exception
            raise
        except btle.BTLEException as e:
            # CRITICAL: Invalid handle errors should not trigger disconnect handling
            if "Invalid handle" in str(e):
                logger.warning(f"Invalid handle error (not treating as disconnect): {e}")
            else:
                logger.warning(f"BLE exception (not treating as disconnect): {e}")
            raise
        except Exception as e:
            # Log unexpected errors but allow them to propagate
            logger.warning(f"Unexpected error in BLE communication: {e}")
            raise
