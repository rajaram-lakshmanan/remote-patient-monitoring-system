#!/usr/bin/env python3
# -----------------------------------------------------------------------------
# Filename: ble_client_event.py
# Author: Rajaram Lakshmanan
# Description:  Event model for the BLE client.
# License: MIT (see LICENSE)
# -----------------------------------------------------------------------------

from typing import Literal

from event_bus.models.client.base_client_event import BaseClientEvent

class BleClientEvent(BaseClientEvent):
    """Event model for the BLE client"""
    client_type: Literal["BLE"] = "BLE"
    target_device_name: str
    target_device_type: str
    target_device_mac_address: str