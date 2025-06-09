#!/usr/bin/env python3
# -----------------------------------------------------------------------------
# Filename: hardening_information_event.py
# Author: Rajaram Lakshmanan
# Description: Event model for Edge gateway security hardening registry.
# License: MIT (see LICENSE)
# -----------------------------------------------------------------------------

from datetime import datetime, timezone
from typing import List
import uuid

from pydantic import BaseModel, Field

class HardeningMeasure(BaseModel):
    """Information about a single security hardening measure."""
    category: str
    description: str
    implementation_date: str
    # "implemented", "partial", "needed", or "not_applicable"
    status: str
    # "command check", "config check", etc.
    verification_method: str
    last_verified: str
    # "CIS", etc.
    compliance_standard: str

class HardeningInformationEvent(BaseModel):
    """Event model for security hardening registry from the Edge gateway."""
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    hardening_info: List[HardeningMeasure]
    version: str = "1.0"