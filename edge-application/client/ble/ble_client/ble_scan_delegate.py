#!/usr/bin/env python3
# -----------------------------------------------------------------------------
# Filename: ble_scan_delegate.py
# Author: Rajaram Lakshmanan
# Description: Delegate for BLE Device scanning.
# License: MIT (see LICENSE)
# -----------------------------------------------------------------------------

import logging
from typing import Optional

from bluepy import btle

logger = logging.getLogger("BleScanDelegate")

class BleScanDelegate(btle.DefaultDelegate):
    """Delegate for BLE device scanning"""

    def __init__(self, name: Optional[str] = None):
        btle.DefaultDelegate.__init__(self)
        self._name = name
        self.found_devices = {}
        self.device_addr = None

    def handleDiscovery(self, dev: btle.ScanEntry, is_new_dev: bool, is_new_data: bool):
        """Handle discovery of BLE devices.

        Args:
            dev: The BLE device being discovered, which contains details like the MAC address and
            advertisement sensor data
            is_new_dev: A flag indicating if the device is newly discovered in this scan session
            is_new_data:  A flag indicating if the device has updated its advertisement sensor data
        """
        logger.info(f"Handle BLE discovery. New Device: {is_new_dev}, New or updated advertisement: {is_new_data}")
        if is_new_dev:
            name = dev.getValueText(9)  # Complete Local Name
            if not name:
                name = dev.getValueText(8)  # Shortened Local Name

            if name:
                self.found_devices[dev.addr] = name
                logger.info(f"Found device: {name} ({dev.addr})")

                # If this is our target device, we can stop scanning
                if self._name and self._name.lower() in name.lower():
                    logger.info(f"Found target device: {name}")
                    self.device_addr = dev.addr
                    # Raise exception to stop scanning
                    raise StopIteration(f"Target device found: {name} ({dev.addr})")