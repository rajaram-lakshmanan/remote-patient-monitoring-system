#!/usr/bin/env python3
# -----------------------------------------------------------------------------
# Filename: cloud_sync_manager_config.py
# Author: Rajaram Lakshmanan
# Description: Configuration for the cloud sync manager.
# License: MIT (see LICENSE)
# ------------------------------------------------------------------------------

from pydantic import BaseModel, field_validator

from config.models.cloud.azure_iot_hub_config import AzureIoTHubConfig
from config.models.cloud.cloud_edge_gateway_sync_config import CloudEdgeGatewaySyncConfig
from config.models.cloud.cloud_sensor_sync_config import CloudSensorSyncConfig

class CloudSyncManagerConfig(BaseModel):
    """Configuration for the cloud sync manager."""
    is_enabled: bool = True
    azure_iot_hub: AzureIoTHubConfig
    cloud_sensor_sync: CloudSensorSyncConfig
    cloud_edge_gateway_sync: CloudEdgeGatewaySyncConfig

    model_config = {
        "extra": "ignore"
    }