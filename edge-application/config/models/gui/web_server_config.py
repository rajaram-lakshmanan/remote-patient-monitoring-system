#!/usr/bin/env python3
# -----------------------------------------------------------------------------
# Filename: web_server_config.py
# Author: Rajaram Lakshmanan
# Description: Web server configuration.
# License: MIT (see LICENSE)
# -----------------------------------------------------------------------------

from pydantic import BaseModel

class WebServerConfig(BaseModel):
    """Web server configuration."""
    is_enabled: bool = True
    host: str = "0.0.0.0"
    port: int = 5000
    debug: bool = False

    model_config = {
        "extra": "ignore"
    }