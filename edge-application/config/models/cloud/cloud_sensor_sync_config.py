#!/usr/bin/env python3
# -----------------------------------------------------------------------------
# Filename: cloud_sensor_sync_config.py
# Author: Rajaram Lakshmanan
# Description: Configuration required to perform the synchronization of the
# sensor time_series from the sensors connected to the Edge device, to the Cloud.
# License: MIT (see LICENSE)
# ------------------------------------------------------------------------------

from typing import List

from pydantic import BaseModel, Field

class SensorSyncOptions(BaseModel):
    """Configuration for an individual sensor's sync option"""
    sync_interval: int = 60 # If set to 0, sync immediately
    # Flag to indicate if the message is sent in batches If batch sync is enabled, sync interval will be
    # discarded, as the updates are only in batch based on the batch buffer size
    batch_enabled: bool = False
    batch_size: int = 100 # Size of the processed message buffer
    maintenance_interval: int = 30 # Default interval to check the IoT connection and sending batched data, if enabled

    model_config = {
        "extra": "allow"  # Retain any additional custom parameters, this could be sensor-specific parameters
    }

    def get_custom_param(self, key: str, default=None):
        return self.model_extra.get(key, default)

class SensorSyncServiceConfig(BaseModel):
    """Configuration for an individual sensor's sync service"""
    sensor_id: str
    device_type: str  # Will be validated against DeviceTypes enum
    sensor_type: str  # Will be validated against the appropriate sensor type enum
    is_enabled: bool = False # Enable cloud sync automatically when the application is initialized
    sync_options: SensorSyncOptions = Field(default_factory=SensorSyncOptions)

class CloudSensorSyncConfig(BaseModel):
    """Configuration required to perform the synchronization of the sensor time_series from
    the sensors connected to the Edge device, to the Cloud."""
    is_enabled: bool = True
    sensors: List[SensorSyncServiceConfig]

    model_config = {
        "extra": "ignore"
    }