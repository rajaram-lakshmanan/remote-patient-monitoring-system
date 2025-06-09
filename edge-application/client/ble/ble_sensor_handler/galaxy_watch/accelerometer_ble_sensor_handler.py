#!/usr/bin/env python3
# -----------------------------------------------------------------------------
# Filename: accelerometer_ble_sensor_handler.py
# Author: Rajaram Lakshmanan
# Description: Handler for Accelerometer BLE service for the Health monitoring
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

logger = logging.getLogger("AccelerometerBleSensorHandler")

# Accelerometer Constants
ACCELEROMETER_SERVICE_UUID = "8899b3a3-38fb-42f5-9955-59c52b5d53f2"
# Data UUID include accelerometer x,y, and z axes values incl. timestamp
ACCELEROMETER_DATA_UUID = "8899b3a4-38fb-42f5-9955-59c52b5d53f2"

# Note: There are no status codes associated with the accelerometer service

class AccelerometerBleSensorHandler(BaseBleSensorHandler):
    """Handler for Accelerometer BLE service for the Health monitoring app deployed in Samsung Galaxy Watch 7.

    Note: This can be made generic Accelerometer for any BLE device, only if all the configurations are loaded, this
    requires minimal effort. For this project, it has been decided to tightly couple this class with the Galaxy
    watch App."""
    
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
        Initialize the accelerometer BLE sensor handler.
        
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

        # Initialize accelerometer data
        self._accel_x = 0.0
        self._accel_y = 0.0
        self._accel_z = 0.0
        self._accel_timestamp = 0

        # Initialize the accelerometer sensor metadata, generate a unique ID with the prefix
        self._sensor_metadata = SensorMetadata(self._sensor_id,
                                               self._sensor_name,
                                               self._sensor_type,
                                               "Samsung Electronics",
                                               "Samsung Galaxy Watch 7 SM-L300",
                                               "14.0",
                                               "N/A",
                                               "3-axis accelerometer for motion detection (25 Hz)",
                                               "Raw Value",
                                               self._location)

        # Register notification handler(s)
        self._register_notification_handler(ACCELEROMETER_DATA_UUID, self._handle_accel)
        logger.info("Accelerometer BLE sensor handler initialized")

    @property
    def service_uuid(self) -> str:
        """Return the UUID of the accelerometer service."""
        return ACCELEROMETER_SERVICE_UUID

    @property
    def characteristic_uuids(self) -> Dict[str, str]:
        """Return a dictionary of characteristic names to UUIDs."""
        return {
            'accelerometer_data': ACCELEROMETER_DATA_UUID
        }

    @property
    def sensor_metadata(self) -> SensorMetadata:
        """Return metadata for accelerometer BLE sensor."""
        return self._sensor_metadata

    # === Public API Functions ===
    
    def read_initial_data(self) -> None:
        """Read initial values from characteristics."""
        # Prior to reading the initial sensor data from the BLE server, publish the sensor metadata
        super().read_initial_data()

        try:
            # Read accelerometer data - x,y, and z axis
            if 'accelerometer_data' in self.characteristics:
                try:
                    char = self.characteristics['accelerometer_data']
                    data = char.read()
                    self._handle_accel(data)
                except Exception as e:
                    # Just log and continue - don't let this stop the connection
                    logger.warning(f"Error reading initial accelerometer data: {e}")
        except Exception as e:
            logger.warning(f"Error reading initial accelerometer data: {e}")
    
    def get_data(self) -> Dict[str, Any]:
        """
        Return the current accelerometer sensor data as a dictionary.
        
        Returns:
            dict: Dictionary containing accelerometer sensor data.
        """
        return {
            'timestamp': self._accel_timestamp,
            'values': {
                'x': self._accel_x,
                'y': self._accel_y,
                'z': self._accel_z
            }
        }

    # === Local Functions ===

    def _handle_accel(self, data: bytes) -> None:
        """
        Handle accelerometer sensor data notification.

        Args:
            data (bytes): Accelerometer X, Y, and Z axis sensor data received from the device.
        """
        try:
            if len(data) >= 20:  # Need at least 8 bytes for timestamp + 4 (x-axis) + 4 (y-axis) + 4 (z-axis)
                self._accel_timestamp, self._accel_x, self._accel_y, self._accel_z = struct.unpack("<Qiii", data)
                logger.debug(f"Timestamp: {self._accel_timestamp}, Accelerometer X: {self._accel_x}, "
                            f"Accelerometer Y: {self._accel_y}, Accelerometer Z: {self._accel_z}")

                self._last_data_timestamp = datetime.now(timezone.utc)

                # Publish sensor data event
                self._publish_sensor_data(self.get_data())
        except struct.error as e:
            logger.error(f"Error unpacking Accelerometer sensor data structure: {e}")
        except Exception as e:
            logger.error(f"Error processing the accelerometer sensor data: {e}")

