#!/usr/bin/env python3
# -----------------------------------------------------------------------------
# Filename: app_config.py
# Author: Rajaram Lakshmanan
# Description: Application configuration.
# License: MIT (see LICENSE)
# ------------------------------------------------------------------------------

from pydantic import BaseModel

class AppConfig(BaseModel):
    """Application configuration."""
    name: str
    version: str

    model_config = {
        "extra": "ignore"
    }