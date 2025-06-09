#!/usr/bin/env python3
# -----------------------------------------------------------------------------
# Filename: cloud_edge_gateway_sync_config.py
# Author: Rajaram Lakshmanan
# Description: Configuration required to perform the synchronization of the
# security time_series from the Edge device to the Cloud.
# License: MIT (see LICENSE)
# ------------------------------------------------------------------------------


from pydantic import BaseModel

class CloudEdgeGatewaySyncConfig(BaseModel):
    """
    Configuration required to perform the synchronization of
    the security time_series from the Edge device to the Cloud.

    Note: This configuration is mainly used to enable the Sync to the cloud. This can be
    extended in the future with other cloud sync configuration required for the Edge gateway.
    """
    is_enabled: bool = True

    model_config = {
        "extra": "ignore"
    }


