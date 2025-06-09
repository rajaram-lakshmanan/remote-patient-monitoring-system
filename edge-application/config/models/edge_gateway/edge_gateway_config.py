#!/usr/bin/env python3
# -----------------------------------------------------------------------------
# Filename: edge_gateway_config.py
# Author: Rajaram Lakshmanan
# Description: Configuration of the Edge Gateway.
# License: MIT (see LICENSE)
# ------------------------------------------------------------------------------

import re

from pydantic import BaseModel, field_validator, PrivateAttr, model_validator
from pydantic_core.core_schema import FieldValidationInfo


class EdgeGatewayConfig(BaseModel):
    """
    Configuration of the Edge Gateway and information required to perform the data collection
    and publishing of information, once available.
    """
    telemetry_schedule_interval: str
    security_schedule_interval: str
    inventory_schedule_interval: str

    # Private attributes to cache parsed seconds
    _telemetry_schedule_seconds: int = PrivateAttr()
    _security_schedule_seconds: int = PrivateAttr()
    _inventory_schedule_seconds: int = PrivateAttr()

    @property
    def telemetry_schedule_seconds(self) -> int:
        """Returns the telemetry schedule interval in seconds."""
        return self._telemetry_schedule_seconds

    @property
    def security_schedule_seconds(self) -> int:
        """Returns the security schedule interval in seconds."""
        return self._security_schedule_seconds

    @property
    def inventory_schedule_seconds(self) -> int:
        """Returns the inventory schedule interval in seconds."""
        return self._inventory_schedule_seconds

    @field_validator('telemetry_schedule_interval', # noqa
                     'security_schedule_interval',
                     'inventory_schedule_interval') # noqa
    @staticmethod
    def validate_interval(v, info: FieldValidationInfo): # noqa
        if isinstance(v, int):
            return str(v)
        if isinstance(v, str):
            return v.strip()
        raise ValueError(f"Invalid type {type(v)}")

    @model_validator(mode='after')
    def parse_and_cache_seconds(self):
        self._telemetry_schedule_seconds = self._parse_duration(self.telemetry_schedule_interval)
        self._security_schedule_seconds = self._parse_duration(self.security_schedule_interval)
        self._inventory_schedule_seconds = self._parse_duration(self.inventory_schedule_interval)
        return self

    model_config = {
        "extra": "ignore"
    }

    @staticmethod
    def _parse_duration(duration_str: str) -> int:
        """
        Parse a human-friendly duration string into seconds.
        Supported formats: "1 day", "2 weeks", "30 minutes", etc.
        """
        if not isinstance(duration_str, str):
            raise ValueError(f"Invalid input type. Expected string, got {type(duration_str)}")

        duration_str_lower = duration_str.strip().lower()
        match = re.match(
            r'^(\d+(?:\.\d+)?)\s*(second|seconds|minute|minutes|hour|hours|day|days|week|weeks|month|months)$',
            duration_str_lower)

        if not match:
            raise ValueError(f"Invalid duration format: '{duration_str_lower}'")

        number = float(match.group(1))
        unit = match.group(2)

        unit_seconds = {
            "second": 1,
            "seconds": 1,
            "minute": 60,
            "minutes": 60,
            "hour": 3600,
            "hours": 3600,
            "day": 86400,
            "days": 86400,
            "week": 604800,
            "weeks": 604800,
            "month": 2629744,  # Average month
            "months": 2629744
        }

        return int(number * unit_seconds[unit])