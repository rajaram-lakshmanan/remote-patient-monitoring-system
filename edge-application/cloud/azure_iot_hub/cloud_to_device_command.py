#!/usr/bin/env python3
# -----------------------------------------------------------------------------
# Filename: cloud_to_device_command.py
# Author: Rajaram Lakshmanan
# Description:  List of supported cloud to device commands.
# with X.509 authentication.
# License: MIT (see LICENSE)
# -----------------------------------------------------------------------------

from enum import Enum

class CloudToDeviceCommand(Enum):
    """
    List of commands supported by the Cloud to Device (Sensor or Edge Gateway).
    """
    TRIGGER_VULN_SCAN = "trigger_vulnerability_scan"
    # Add more commands as needed