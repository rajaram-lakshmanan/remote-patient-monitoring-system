#!/usr/bin/env python3
# -----------------------------------------------------------------------------
# Filename: base_sensor_handler_provider.py
# Author: Rajaram Lakshmanan
# Description:  Base class for the sensor handler provider.
# License: MIT (see LICENSE)
# -----------------------------------------------------------------------------

import logging
from abc import ABC, abstractmethod

from client.common.base_client import BaseClient
from client.common.base_sensor_handler import BaseSensorHandler

logger = logging.getLogger("BaseSensorHandlerProvider")


class BaseSensorHandlerProvider(ABC):
    """
    Base class for the sensor handler provider.

    This class defines the interface that all sensor handler providers
    must implement. Concrete implementations can create handlers for different
    device types.
    """

    @abstractmethod
    def get_handler(self,
                    client: BaseClient,
                    is_enabled: bool,
                    sensor_id: str,
                    sensor_name: str,
                    sensor_type: str,
                    patient_id: str,
                    location: str) -> BaseSensorHandler:
        """
        Get sensor handlers for the specified sensor types.

        Args:
            client: Client for which the sensor handlers are to be created.
            is_enabled (bool): Flag indicating whether the sensor is enabled or not.
            sensor_id (str): ID of the sensor, this ID shall be unique in the application
            Follows the format: <interfaceType_shortenedClientId_sensorType> e.g., ble_c1_heart_rate
            sensor_name (str): Name of the sensor, this does not need to be unique
            sensor_type (str): Type of the sensor, this is used to determine the sensor-specific logic
            patient_id (str): ID of the patient associated (wearing or using) with the sensors
            location (str): Location or placement of the sensors

        Returns:
           Sensor handler instance for the specified sensor type
        """
        pass

