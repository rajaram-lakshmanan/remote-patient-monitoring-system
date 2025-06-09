#!/usr/bin/env python3
# -----------------------------------------------------------------------------
# Filename: base_i2c_sensor_handler.py
# Author: Rajaram Lakshmanan
# Description:  Base class for all I2C sensor handlers.
# License: MIT (see LICENSE)
# -----------------------------------------------------------------------------

import logging
import threading
from abc import abstractmethod

from client.common.base_client import BaseClient
from client.common.base_sensor_handler import BaseSensorHandler
from smbus2 import SMBus

from event_bus.redis_stream_bus.redis_stream_bus import RedisStreamBus

logger = logging.getLogger("BaseI2CSensorHandler")

class BaseI2CSensorHandler(BaseSensorHandler):
    """
    Base class for all I2C sensor handlers.
    
    This abstract class defines the interface for all I2C sensor handlers.
    Concrete implementations must provide sensor-specific logic.
    """
    
    def __init__(self,
                 event_bus: RedisStreamBus,
                 client: BaseClient,
                 is_enabled: bool,
                 sensor_id: str,
                 sensor_name: str,
                 sensor_type: str,
                 patient_id: str,
                 location: str):
        """
        Initialize the base I2C sensor handler.
        
        Args:
            event_bus (RedisStreamBus): The event bus for publishing events.
            client: Client to which the sensor handler belongs.
            is_enabled (bool): Flag indicating whether the sensor is enabled or not.
            sensor_id (str): ID of the sensor, this ID shall be unique in the application.
            Follows the format: <interfaceType_shortenedClientId_sensorType> e.g., ble_c1_heart_rate.
            sensor_name (str): Name of the sensor, this does not need to be unique.
            sensor_type (str): Type of the sensor, this is used to determine the sensor-specific logic.
            patient_id (str): ID of the patient associated (wearing or using) with the sensors.
            location (str): Location or placement of the sensors.

        Raises:
            TypeError: If 'bus' is not an instance of SMBus.
        """
        # There is no concept of an i2c device connect or disconnect. When the connection is active, time_series will be
        # polled from the ecg sensor based on the configured polling interval.
        # Event to control thread termination
        self.stop_event = threading.Event()
        self._data_lock = threading.Lock()

        # Create the polling thread
        self.poll_thread = threading.Thread(target=self._poll_sensor_data, daemon=True)

        # Call parent constructor
        super().__init__(event_bus, client, is_enabled, sensor_id, sensor_name, sensor_type, patient_id, location)

    def start_data_acquisition(self, bus: SMBus, address: int, poll_interval: float) -> None:
        """ Start the acquisition of the time_series from the sensor based on a pre-defined polling interval.

        Args:
            bus (SMBus): The I2C bus to use for communication with the sensor.
            address (int): Address of the sensor.
            poll_interval (float): Polling interval for the sensor in seconds.

        Raises:
            RuntimeError: If the sensor is not enabled. This must be enabled in the application configuration.
        """
        # Before starting the time_series acquisition, publish the sensor metadata
        self._publish_sensor_metadata()

        if not self._is_enabled:
            raise RuntimeError("Sensor is not enabled. Data acquisition cannot be started.")

        if self.poll_thread.is_alive():
            logger.warning("Polling thread is already running.")
            return
        self.stop_event.clear()
        self.poll_thread = threading.Thread(
            target=self._poll_sensor_data,
            args=(bus, address, poll_interval),
            daemon=True
        )
        self.poll_thread.start()
        logger.info(f"{self.sensor_metadata.sensor_name} time_series acquisition has started.")

    def stop_data_acquisition(self) -> None:
        """ Stop the acquisition of the time_series from the sensor."""
        self.stop_event.set()  # Signal the thread to stop
        logger.info("Data acquisition stopped.")
        # Stop the polling thread
        if self.poll_thread:
            self.poll_thread.join(1.0)
        logger.info(f"{self.sensor_metadata.sensor_name} time_series acquisition has stopped.")

    @abstractmethod
    def _poll_sensor_data(self, bus: SMBus, address: int, poll_interval: float) -> None:
        """ Poll time_series from the sensor.

        Args:
            bus (SMBus): The I2C bus to use for communication with the sensor.
            address (int): Address of the sensor.
            poll_interval (float): Polling interval for the sensor in seconds.
        """
        # Default implementation - should be overridden by subclasses
        pass