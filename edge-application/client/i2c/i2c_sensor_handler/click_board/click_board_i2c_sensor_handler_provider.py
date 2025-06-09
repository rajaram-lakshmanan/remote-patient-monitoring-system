#!/usr/bin/env python3
# -----------------------------------------------------------------------------
# Filename: click_board_i2c_sensor_handler_provider.py
# Author: Rajaram Lakshmanan
# Description: Sensor handler provider for Click board I2C sensors from MikroE.
# License: MIT (see LICENSE)
# -----------------------------------------------------------------------------

import logging
from typing import Optional

from client.common.base_client import BaseClient
from client.common.base_sensor_handler_provider import BaseSensorHandlerProvider
from client.common.device_sensor_classification_types import ClickBoardI2CSensorType
from client.i2c.i2c_sensor_handler.base_i2c_sensor_handler import BaseI2CSensorHandler
from client.i2c.i2c_sensor_handler.click_board.ecg7.ecg7_i2c_sensor_handler import Ecg7I2CSensorHandler
from client.i2c.i2c_sensor_handler.click_board.environment.environment_i2c_sensor_handler import EnvironmentI2CSensorHandler
from client.i2c.i2c_sensor_handler.click_board.oximeter5.oximeter5_i2c_sensor_handler import Oximeter5I2CSensorHandler
from event_bus.redis_stream_bus.redis_stream_bus import RedisStreamBus

logger = logging.getLogger("ClickBoardI2CSensorHandlerProvider")

class ClickBoardI2CSensorHandlerProvider(BaseSensorHandlerProvider):
    """
    Sensor handler provider for Click board I2C sensors from MikroE.
    """

    def __init__(self, event_bus: RedisStreamBus):
        """
        Initialize the (MikroE) Click board I2C sensor provider.

        Args:
           event_bus (RedisStreamBus): The event bus for publishing events
        """
        self._event_bus = event_bus
        logger.info("Click board I2C Sensor Handler Provider initialized")

    def get_handler(self,
                    client: BaseClient,
                    is_enabled: bool,
                    sensor_id: str,
                    sensor_name: str,
                    sensor_type: str,
                    patient_id: str,
                    location: str) -> Optional[BaseI2CSensorHandler]:
        """
        Create a handler for the specified sensor type.

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
            Handler instance or None if creation failed
        """
        try:
            click_board_sensor_type = ClickBoardI2CSensorType(sensor_type)
        except ValueError:
            raise ValueError(f"Sensor type '{sensor_type}' is not supported.")

        if click_board_sensor_type == ClickBoardI2CSensorType.ECG_7:
            return Ecg7I2CSensorHandler(self._event_bus,
                                        client,
                                        is_enabled,
                                        sensor_id,
                                        sensor_name,
                                        sensor_type,
                                        patient_id,
                                        location)
        elif click_board_sensor_type == ClickBoardI2CSensorType.ENVIRONMENT:
            return EnvironmentI2CSensorHandler(self._event_bus,
                                               client,
                                               is_enabled,
                                               sensor_id,
                                               sensor_name,
                                               sensor_type,
                                               patient_id,
                                               location)
        elif click_board_sensor_type == ClickBoardI2CSensorType.OXIMETER_5:
            return Oximeter5I2CSensorHandler(self._event_bus,
                                             client,
                                             is_enabled,
                                             sensor_id,
                                             sensor_name,
                                             sensor_type,
                                             patient_id,
                                             location)

        # Fallback: this should almost never happen unless the sensor type enum was extended but not handled
        raise ValueError(f"Sensor type '{sensor_type}' is not supported.")