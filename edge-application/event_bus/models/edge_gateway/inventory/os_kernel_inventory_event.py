#!/usr/bin/env python3
# -----------------------------------------------------------------------------
# Filename: os_kernel_inventory_event.py
# Author: Rajaram Lakshmanan
# Description:  Event model for Edge gateway OS and Kernel inventory.
# License: MIT (see LICENSE)
# -----------------------------------------------------------------------------

from datetime import datetime, timezone
from typing import List
import uuid

from pydantic import BaseModel, Field

class LoggedInUserInfo(BaseModel):
    """Information about a single user who has logged in to the system."""
    user: str
    terminal: str
    login_time: str
    host: str

class OsKernelInventoryEvent(BaseModel):
    """Event model for OS and Kernel registry."""
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    os_name: str
    os_version: str
    os_id: str
    uptime: str
    logged_in_users: List[LoggedInUserInfo]
    kernel_name: str
    kernel_version: str
    kernel_build_date: str
    version: str = "1.0"
