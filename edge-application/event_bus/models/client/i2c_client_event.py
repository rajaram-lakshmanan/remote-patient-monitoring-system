#!/usr/bin/env python3
# -----------------------------------------------------------------------------
# Filename: i2c_client_event.py
# Author: Rajaram Lakshmanan
# Description:  Event model for the I2C client.
# License: MIT (see LICENSE)
# -----------------------------------------------------------------------------

from typing import Literal

from event_bus.models.client.base_client_event import BaseClientEvent

class I2CClientEvent(BaseClientEvent):
    """
    Event model for the I2C Client

    Note: For I2C 'is_connected' represents whether the I2C bus is active or not
    """
    client_type: Literal["I2C"] = "I2C"
    i2c_bus_id: int