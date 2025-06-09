#!/usr/bin/env python3
# -----------------------------------------------------------------------------
# Filename: galaxy_watch_ble_sensor_handler_provider.py
# Author: Rajaram Lakshmanan
# Description: Sensor handler provider for Samsung Galaxy Watch 7.
# License: MIT (see LICENSE)
# -----------------------------------------------------------------------------

import logging
from typing import Optional

from client.ble.ble_sensor_handler.base_ble_sensor_handler import BaseBleSensorHandler
from client.common.base_client import BaseClient
from client.common.base_sensor_handler_provider import BaseSensorHandlerProvider
from client.common.device_sensor_classification_types import GalaxyWatchBleSensorType
from event_bus.redis_stream_bus.redis_stream_bus import RedisStreamBus
from client.ble.ble_sensor_handler.galaxy_watch.accelerometer_ble_sensor_handler import AccelerometerBleSensorHandler
from client.ble.ble_sensor_handler.galaxy_watch.ecg_ble_sensor_handler import EcgBleSensorHandler
from client.ble.ble_sensor_handler.galaxy_watch.heart_rate_ble_sensor_handler import HeartRateBleSensorHandler
from client.ble.ble_sensor_handler.galaxy_watch.ppg_ble_sensor_handler import PpgBleSensorHandler
from client.ble.ble_sensor_handler.galaxy_watch.spo2_ble_sensor_handler import Spo2BleSensorHandler
from client.ble.ble_sensor_handler.galaxy_watch.temperature_ble_sensor_handler import TemperatureBleSensorHandler

logger = logging.getLogger("GalaxyWatchBleSensorHandlerProvider")

class GalaxyWatchBleSensorHandlerProvider(BaseSensorHandlerProvider):
    """
    Sensor handler provider for Samsung Galaxy Watch 7.
    """

    def __init__(self, event_bus: RedisStreamBus):
        """
        Initialize the Samsung Galaxy Watch sensor provider.

        Args:
            event_bus (RedisStreamBus): The event bus for publishing events.
        """
        self._event_bus = event_bus
        logger.info("Galaxy Watch BLE Sensor Initialization Service initialized")

    # === Public API Functions ===

    def get_handler(self,
                    client: BaseClient,
                    is_enabled: bool,
                    sensor_id: str,
                    sensor_name: str,
                    sensor_type: str,
                    patient_id: str,
                    location: str) -> Optional[BaseBleSensorHandler]:
        """
        Create a handler for the specified sensor type.

        Args:
            client: Client for which the sensor handlers are to be created.
            is_enabled (bool): Flag indicating whether the sensor is enabled or not.
            sensor_id (str): ID of the sensor, this ID shall be unique in the application.
            Follows the format: <interfaceType_shortenedClientId_sensorType> e.g., ble_c1_heart_rate.
            sensor_name (str): Name of the sensor, this does not need to be unique.
            sensor_type (str): Type of the sensor, this is used to determine the sensor-specific logic.
            patient_id (str): ID of the patient associated (wearing or using) with the sensors.
            location (str): Location or placement of the sensors.

        Returns:
            Handler instance or None if creation failed.
        """
        try:
            galaxy_watch_sensor_type = GalaxyWatchBleSensorType(sensor_type)
        except ValueError:
            raise ValueError(f"Sensor type '{sensor_type}' is not supported.")

        if galaxy_watch_sensor_type == GalaxyWatchBleSensorType.ACCELEROMETER:
            return AccelerometerBleSensorHandler(self._event_bus,
                                                 client,
                                                 is_enabled,
                                                 sensor_id,
                                                 sensor_name,
                                                 sensor_type,
                                                 patient_id,
                                                 location)
        elif galaxy_watch_sensor_type == GalaxyWatchBleSensorType.ECG:
            return EcgBleSensorHandler(self._event_bus,
                                       client,
                                       is_enabled,
                                       sensor_id,
                                       sensor_name,
                                       sensor_type,
                                       patient_id,
                                       location)
        elif galaxy_watch_sensor_type == GalaxyWatchBleSensorType.HEART_RATE:
            return HeartRateBleSensorHandler(self._event_bus,
                                             client,
                                             is_enabled,
                                             sensor_id,
                                             sensor_name,
                                             sensor_type,
                                             patient_id,
                                             location)
        elif galaxy_watch_sensor_type == GalaxyWatchBleSensorType.PPG:
            return PpgBleSensorHandler(self._event_bus,
                                       client,
                                       is_enabled,
                                       sensor_id,
                                       sensor_name,
                                       sensor_type,
                                       patient_id,
                                       location)
        elif galaxy_watch_sensor_type == GalaxyWatchBleSensorType.SPO2:
            return Spo2BleSensorHandler(self._event_bus,
                                        client,
                                        is_enabled,
                                        sensor_id,
                                        sensor_name,
                                        sensor_type,
                                        patient_id,
                                        location)
        elif galaxy_watch_sensor_type == GalaxyWatchBleSensorType.TEMPERATURE:
            return TemperatureBleSensorHandler(self._event_bus,
                                               client,
                                               is_enabled,
                                               sensor_id,
                                               sensor_name,
                                               sensor_type,
                                               patient_id,
                                               location)

        # Fallback: this should almost never happen unless the sensor type enum was extended but not handled
        raise ValueError(f"Sensor type '{sensor_type}' is not supported.")