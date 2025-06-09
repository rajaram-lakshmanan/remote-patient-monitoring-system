#!/usr/bin/env python3
# -----------------------------------------------------------------------------
# Filename: temperature_ble_sensor_handler.py
# Author: Rajaram Lakshmanan
# Description: Handler for Temperature BLE service for the Health monitoring
# app deployed in Samsung Galaxy Watch 7.
# License: MIT (see LICENSE)
# -----------------------------------------------------------------------------

from datetime import datetime, timezone
import logging
import struct
from typing import Dict, Any

from client.ble.ble_sensor_handler.base_ble_sensor_handler import BaseBleSensorHandler
from client.common.base_client import BaseClient
from client.common.sensor_metadata import SensorMetadata
from event_bus.redis_stream_bus.redis_stream_bus import RedisStreamBus

logger = logging.getLogger("TemperatureBleSensorHandler")

# Temperature Constants
TEMPERATURE_SERVICE_UUID = "00001809-0000-1000-8000-00805f9b34fb"
# UUID to represent the characteristic to hold Object, Ambient temperature values and their status incl. timestamp
TEMPERATURE_DATA_UUID = "00002a1c-0000-1000-8000-00805f9b34fb"

# Status codes
TEMPERATURE_STATUS = {
     0: "Normal",
    -1: "Error"
}

class TemperatureBleSensorHandler(BaseBleSensorHandler):
    """Handler for Temperature BLE service for the Health monitoring app deployed in Samsung Galaxy Watch 7."""

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
        Initialize the temperature BLE sensor handler.

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
        """
        # Call parent constructor
        super().__init__(event_bus, client, is_enabled, sensor_id, sensor_name, sensor_type, patient_id, location)

        # Initialize temperature sensor data
        self._object_temperature = 0.0
        self._ambient_temperature = 0.0
        self._temperature_status = 0
        self._temperature_timestamp = 0

        # Initialize the temperature sensor metadata, generate a unique ID with the prefix
        self._sensor_metadata = SensorMetadata(self._sensor_id,
                                               self._sensor_name,
                                               self._sensor_type,
                                               "Samsung Electronics",
                                               "Samsung Galaxy Watch 7 SM-L300",
                                               "14.0",
                                               "N/A",
                                               "Dual-sensor temperature monitor for skin and ambient readings",
                                               "Deg Celsius",
                                               self._location)

        # Register notification handler(s)
        self._register_notification_handler(TEMPERATURE_DATA_UUID, self._handle_temperature_data)
        logger.info("Temperature BLE sensor handler initialized")

    @property
    def service_uuid(self) -> str:
        """Return the UUID of the temperature service."""
        return TEMPERATURE_SERVICE_UUID
    
    @property
    def characteristic_uuids(self) -> Dict[str, str]:
        """Return a dictionary of characteristic names to UUIDs."""
        return {
            'temperature_data': TEMPERATURE_DATA_UUID
        }
    
    @property
    def sensor_metadata(self) -> SensorMetadata:
        """Return metadata for temperature BLE sensor."""
        return self._sensor_metadata

    # === Public API Functions ===

    def read_initial_data(self) -> None:
        """Read initial values from characteristics."""
        # Prior to reading the initial sensor data from the BLE server, publish the sensor metadata
        super().read_initial_data()

        try:
            # Read temperature sensor data
            if 'temperature_data' in self.characteristics:
                try:
                    char = self.characteristics['temperature_data']
                    data = char.read()
                    self._handle_temperature_data(data)
                except Exception as e:
                    logger.warning(f"Error reading temperature data: {e}")
        except Exception as e:
            logger.warning(f"Error reading initial temperature data: {e}")
    
    def get_data(self) -> Dict[str, Any]:
        """
        Return current temperature sensor data as a dictionary.
        
        Returns:
            dict: Dictionary containing temperature sensor data.
        """
        return {
            'timestamp': self._temperature_timestamp,
            'values': {
                'skin': self._object_temperature,
                'ambient': self._ambient_temperature,
                'status': TEMPERATURE_STATUS.get(self._temperature_status, "Unknown"),
                'status_code': self._temperature_status
            }
        }

    # === Local Functions ===

    def _handle_temperature_data(self, data: bytes) -> None:
        """
        Handle temperature sensor data notification.

        Args:
            data (bytes): Temperature sensor data received from the device.
        """
        try:
            # All the temperature sensor data (Timestamp, Object & Ambient temperature values, and status) are
            # part of one characteristic
            if len(data) >= 18:  # Need at least 8 bytes for timestamp + 4 for object (skin) temperature value +
                #  4 for ambient temperature value + 2 for status
                (self._temperature_timestamp, self._object_temperature, self._ambient_temperature,
                 self._temperature_status) = (struct.unpack("<Qffh", data))

                status_text = TEMPERATURE_STATUS.get(self._temperature_status, "Unknown")
                logger.debug(f"Timestamp: {self._temperature_timestamp}, "
                            f"Object Temperature: {self._object_temperature:.2f}°C, "
                            f"Ambient Temperature: {self._ambient_temperature:.2f}°C, "
                            f"Status: {status_text}")

                self._last_data_timestamp = datetime.now(timezone.utc)

                # Publish sensor data event
                self._publish_sensor_data(self.get_data())
        except struct.error as e:
            logger.error(f"Error unpacking Temperature sensor data structure: {e}")
        except Exception as e:
            logger.error(f"Error processing Temperature sensor data: {e}")