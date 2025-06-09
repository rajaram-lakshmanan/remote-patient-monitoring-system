#!/usr/bin/env python3
# -----------------------------------------------------------------------------
# Filename: account_security_monitor_event.py
# Author: Rajaram Lakshmanan
# Description: Event model for Edge gateway user account security registry.
# License: MIT (see LICENSE)
# -----------------------------------------------------------------------------

import uuid
from datetime import datetime, timezone
from typing import List

from pydantic import BaseModel, Field

class AccountInfo(BaseModel):
    """Event model for user account registry on Edge gateway."""
    username: str
    account_type: str
    creation_date: str
    last_password_change: str
    login_attempts: int
    sudo_privileges: int
    last_login: str
    account_status: str
    user_groups: List[str]
    ssh_activity: bool
    ssh_key_fingerprints: list

class AccountSecurityMonitorEvent(BaseModel):
    """Event model for monitoring configured user accounts to assess security on the Edge gateway."""
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    accounts_info: List[AccountInfo]
    version: str = "1.0"