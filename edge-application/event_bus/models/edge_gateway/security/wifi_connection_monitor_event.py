#!/usr/bin/env python3
# -----------------------------------------------------------------------------
# Filename: wifi_connection_monitor_event.py
# Author: Rajaram Lakshmanan
# Description: Event model for Edge gateway Wi-Fi connection registry.
# License: MIT (see LICENSE)
# -----------------------------------------------------------------------------

from datetime import datetime, timezone
import uuid

from pydantic import BaseModel, Field

class WifiConnectionInfo(BaseModel):
    """Information about the Wi-Fi connection and security."""
    ssid: str
    encryption: str
    signal_strength: int
    mac_address: str
    ip_address: str
    last_connected: str
    security_status: str

class WifiConnectionMonitorEvent(BaseModel):
    """Event model for Wi-Fi security registry from the Edge gateway."""
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    network_info: WifiConnectionInfo
    version: str = "1.0"