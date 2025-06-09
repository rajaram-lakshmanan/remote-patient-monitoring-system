#!/usr/bin/env python3
# -----------------------------------------------------------------------------
# Filename: ble_client_config.py
# Author: Rajaram Lakshmanan
# Description: BLE client configuration.
# License: MIT (see LICENSE)
# -----------------------------------------------------------------------------

import re
from typing import Optional, List

from pydantic import BaseModel, field_validator, model_validator
from pydantic_core.core_schema import FieldValidationInfo

from client.common.device_sensor_classification_types import DeviceTypes
from config.models.sensor.ble_sensor_config import BleSensorConfig
from config.models.sensor.sensor_type_registry import SensorTypeRegistry

class BleClientConfig(BaseModel):
    """BLE client configuration."""
    client_id: str
    is_enabled: bool = True
    device_type: str
    device_address: Optional[str] = None
    device_name: Optional[str] = None
    sensors: List[BleSensorConfig]

    @field_validator('device_type') # noqa
    @staticmethod
    def validate_device_type(v, info: FieldValidationInfo): # noqa
        try:
            DeviceTypes(v)
            return v
        except ValueError:
            valid_types = DeviceTypes.list_values()
            raise ValueError(f"Invalid device type: {v}. Valid types are: {', '.join(valid_types)}")

    @field_validator('device_address') # noqa
    @staticmethod
    def validate_mac_address(v, info: FieldValidationInfo): # noqa
        if v is None:
            return None

        # Simple MAC address format validation
        mac_pattern = re.compile(r'^([0-9A-Fa-f]{2}[:-]){5}([0-9A-Fa-f]{2})$')
        if not mac_pattern.match(v):
            raise ValueError("Invalid MAC address format. Expected format: XX:XX:XX:XX:XX:XX or XX-XX-XX-XX-XX-XX")
        return v

    @model_validator(mode='after')
    def validate_device_identifier(self):
        """Ensure that at least one of device_address or device_name is provided."""
        if not self.device_address and not self.device_name:
            raise ValueError("At least one of 'device_address' or 'device_name' must be specified")

        return self

    @model_validator(mode='after')
    def validate_sensors_device_compatibility(self):
        """Ensure all sensors are compatible with the device type."""
        if not self.device_type or not self.sensors:
            return self

        for sensor in self.sensors:
            SensorTypeRegistry.validate_sensor_type_for_device(sensor.sensor_type, self.device_type)

        return self

    @model_validator(mode='after')
    def validate_at_least_one_sensor(self):
        """Ensure at least one sensor is configured."""
        if not self.sensors:
            raise ValueError("At least one sensor must be configured for a BLE client")

        return self