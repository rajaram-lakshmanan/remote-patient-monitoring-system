
#!/usr/bin/env python3
# -----------------------------------------------------------------------------
# Filename: system_audit_collector_event.py
# Author: Rajaram Lakshmanan
# Description: Event model for Edge gateway audit logs registry.
# License: MIT (see LICENSE)
# -----------------------------------------------------------------------------

from datetime import datetime, timezone
from typing import List
import uuid

from pydantic import BaseModel, Field

class AuditLogEntry(BaseModel):
    """Information about a single audit log entry."""
    timestamp: str
    event_type: str
    severity: str
    source: str
    action: str
    username: str
    result: str
    ip_address: str
    details: str

class SystemAuditCollectorEvent(BaseModel):
    """Event model for audit logs collected from the Edge gateway."""
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    logs: List[AuditLogEntry]
    last_collection_time: str = Field(default_factory=lambda: datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"))
    version: str = "1.0"