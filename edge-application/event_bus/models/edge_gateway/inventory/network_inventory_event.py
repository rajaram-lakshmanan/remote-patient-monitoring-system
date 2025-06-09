#!/usr/bin/env python3
# -----------------------------------------------------------------------------
# Filename: network_inventory_event.py
# Author: Rajaram Lakshmanan
# Description:  Event model for Edge gateway Network inventory.
# License: MIT (see LICENSE)
# -----------------------------------------------------------------------------

from datetime import datetime, timezone
from typing import List
import uuid

from pydantic import BaseModel, Field

class NetworkInterfaceInfo(BaseModel):
    """Data model for a network interface registry.

    This class represents the network interface's details that will be published as part of
    the network inventory event.
    """
    name: str
    ip_address: str
    mac_address: str
    state: str

class NetworkInventoryEvent(BaseModel):
    """Data model for Network Inventory Event.

    This class represents the network inventory time_series to be published to the event bus or a message broker.
    It includes registry about the host, fully qualified domain name (FQDN), DNS servers, and interfaces.
    """
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    hostname: str
    fqdn: str # Fully qualified domain name
    dns_servers: List[str]
    interfaces: List[NetworkInterfaceInfo]
    version: str = "1.0"