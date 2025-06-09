#!/usr/bin/env python3
# -----------------------------------------------------------------------------
# Filename: ble_client_manager_config.py
# Author: Rajaram Lakshmanan
# Description: BLE client configuration.
# License: MIT (see LICENSE)
# -----------------------------------------------------------------------------

from typing import List

from pydantic import BaseModel

from config.models.ble.ble_client_config import BleClientConfig

class BleClientManagerConfig(BaseModel):
    """BLE client manager configuration."""
    is_enabled: bool = True
    auto_reconnect: bool = True
    reconnect_interval: int = 60
    reconnect_attempts: int = 3
    notification_timeout: int = 0
    scan_timeout: int = 30
    clients: List[BleClientConfig]

    model_config = {
        "extra": "ignore"
    }