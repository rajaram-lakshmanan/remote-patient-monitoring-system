#!/usr/bin/env python3
# -----------------------------------------------------------------------------
# Filename: redis_config.py
# Author: Rajaram Lakshmanan
# Description: Configuration for the Redis (Event bus).
# License: MIT (see LICENSE)
# ------------------------------------------------------------------------------

from pydantic import BaseModel, field_validator
from pydantic_core.core_schema import FieldValidationInfo


class RedisConfig(BaseModel):
    """Configuration for the Redis (Event bus)."""
    host: str = "localhost"
    port: int = 6379
    db: int = 0

    @field_validator('port') # noqa
    @staticmethod
    def validate_port(v, info: FieldValidationInfo): # noqa
        if not 1 <= v <= 65535:
            raise ValueError("Port must be between 1 and 65535")
        return v

    model_config = {
        "extra": "ignore"
    }

class EventBusConfig(BaseModel):
    """Event bus configuration."""
    redis: RedisConfig

    model_config = {
        "extra": "ignore"
    }