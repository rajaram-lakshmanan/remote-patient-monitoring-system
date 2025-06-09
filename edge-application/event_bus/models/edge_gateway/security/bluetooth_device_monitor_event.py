#!/usr/bin/env python3
# -----------------------------------------------------------------------------
# Filename: bluetooth_device_monitor_event.py
# Author: Rajaram Lakshmanan
# Description: Event model for Edge gateway Bluetooth security registry.
# License: MIT (see LICENSE)
# -----------------------------------------------------------------------------

from datetime import datetime, timezone
from typing import List
import uuid

from pydantic import BaseModel, Field

class BluetoothDeviceInfo(BaseModel):
    """Information about a single Bluetooth device."""
    device_id: str
    device_name: str
    device_type: str
    mac_address: str
    pairing_status: str
    encryption_type: str
    last_connected: str
    connection_strength: int
    trusted_status: int
    authorized_services: str

class BluetoothDeviceMonitorEvent(BaseModel):
    """Event model for the list of Bluetooth device registry from the Edge gateway."""
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    devices: List[BluetoothDeviceInfo]
    version: str = "1.0"