#!/usr/bin/env python3
# -----------------------------------------------------------------------------
# Filename: package_inventory_event.py
# Author: Rajaram Lakshmanan
# Description:  Event model for Edge gateway Package(s) inventory.
# License: MIT (see LICENSE)
# -----------------------------------------------------------------------------

from typing import List
from datetime import datetime, timezone
import uuid

from pydantic import BaseModel, Field

class PackageInfo(BaseModel):
    """Information about a single package (name and version)."""
    name: str
    version: str

class PackageInventoryEvent(BaseModel):
    """Event model for package inventory, including all, security, and Python packages."""
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    all_packages: List[PackageInfo]
    security_packages: List[PackageInfo]
    python_packages: List[PackageInfo]
    version: str = "1.0"
