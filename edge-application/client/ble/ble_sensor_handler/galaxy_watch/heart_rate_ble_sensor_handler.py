#!/usr/bin/env python3
# -----------------------------------------------------------------------------
# Filename: heart_rate_ble_sensor_handler.py
# Author: Rajaram Lakshmanan
# Description: Handler for Heart Rate BLE service for the Health monitoring
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

logger = logging.getLogger("HeartRateBleSensorHandler")

# Heart Rate Constants
HEART_RATE_SERVICE_UUID = "0000180d-0000-1000-8000-00805f9b34fb"
# Data UUID include heart rate measurement value (BPM) and status incl. timestamp
HEART_RATE_DATA_UUID = "00002a37-0000-1000-8000-00805f9b34fb"

# Status codes
HEART_RATE_STATUS = {
     0: "Initial measurement",
     1: "Success",
    -2: "Movement detected",
    -3: "Device detached",
    -8: "Weak signal",
    -10: "Too much movement",
    -99: "No Sensor data",
    -999: "Higher priority sensor active"
}

class HeartRateBleSensorHandler(BaseBleSensorHandler):
    """Handler for Heart Rate BLE service for the Health monitoring app deployed in Samsung Galaxy Watch 7."""

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
        Initialize the heart rate BLE sensor handler.

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

        # Initialize heart rate sensor data
        self._heart_rate = 0
        self._hr_status = 0
        self._hr_timestamp = 0

        # Initialize the Heart rate sensor metadata, generate a unique ID with the prefix
        self._sensor_metadata = SensorMetadata(self._sensor_id,
                                               self._sensor_name,
                                               self._sensor_type,
                                               "Samsung Electronics",
                                               "Samsung Galaxy Watch 7 SM-L300",
                                               "14.0",
                                               "N/A",
                                               "Optical heart rate sensor for measuring beats per minute",
                                               "BPM",
                                               self._location)

        # Register notification handler(s)
        self._register_notification_handler(HEART_RATE_DATA_UUID, self._handle_heart_rate)
        logger.info("Heart Rate BLE sensor handler initialized")

    @property
    def service_uuid(self) -> str:
        """Return the UUID of the heart rate service."""
        return HEART_RATE_SERVICE_UUID

    @property
    def characteristic_uuids(self) -> Dict[str, str]:
        """Return a dictionary of characteristic names to UUIDs."""
        return {
            'heart_rate_data': HEART_RATE_DATA_UUID
        }

    @property
    def sensor_metadata(self) -> SensorMetadata:
        """Return metadata for heart rate BLE sensor."""
        return self._sensor_metadata

    # === Public API Functions ===

    def read_initial_data(self) -> None:
        """Read initial values from characteristics."""
        # Prior to reading the initial sensor data from the BLE server, publish the sensor metadata
        super().read_initial_data()

        try:
            # Read heart rate value
            if 'heart_rate_data' in self.characteristics:
                logger.debug("Reading initial heart rate sensor data")
                try:
                    char = self.characteristics['heart_rate_data']
                    data = char.read()
                    self._handle_heart_rate(data)
                except Exception as e:
                    logger.warning(f"Error reading heart rate sensor data: {e}")
        except Exception as e:
            logger.warning(f"Error reading initial heart rate sensor data: {e}")

    def get_data(self) -> Dict[str, Any]:
        """
        Return current heart rate sensor data as a dictionary.

        Returns:
            dict: Dictionary containing heart rate sensor data.
        """
        return {
            'timestamp': self._hr_timestamp,
            'values': {
                'heart_rate': self._heart_rate,
                'status_code': self._hr_status,
                'status': HEART_RATE_STATUS.get(self._hr_status, "Unknown")
            }
        }

    # === Local Functions ===

    def _handle_heart_rate(self, data: bytes) -> None:
        """
        Handle heart rate measurement notification.

        Args:
            data (bytes): Heart rate sensor data received from the device.
        """
        try:
            # All the heart rate measurement sensor data (Timestamp, Heart rate measurement value, and status) are
            # part of one characteristic
            if len(data) >= 14:  # Need at least 8 bytes for timestamp + 4 for value + 2 for status
                self._hr_timestamp, self._heart_rate, self._hr_status = struct.unpack("<Qih", data)
                status_text = HEART_RATE_STATUS.get(self._hr_status, "Unknown")
                logger.debug(f"Timestamp: {self._hr_timestamp}, Heart Rate: {self._heart_rate} BPM, Status: {status_text}")

                self._last_data_timestamp = datetime.now(timezone.utc)

                # Publish sensor data event
                self._publish_sensor_data(self.get_data())
        except struct.error as e:
            logger.error(f"Error unpacking heart rate sensor data structure: {e}")
        except Exception as e:
            logger.error(f"Error processing heart rate sensor data: {e}")