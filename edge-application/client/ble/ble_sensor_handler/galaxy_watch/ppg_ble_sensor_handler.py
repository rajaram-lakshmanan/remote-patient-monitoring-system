#!/usr/bin/env python3
# -----------------------------------------------------------------------------
# Filename: ppg_ble_sensor_handler.py
# Author: Rajaram Lakshmanan
# Description: Handler for PPG (Photoplethysmogram) BLE service for the Health
# monitoring app deployed in Samsung Galaxy Watch 7.
# License: MIT (see LICENSE)
# -----------------------------------------------------------------------------

from datetime import datetime, timezone
import logging
import struct
import threading
import time
from typing import Dict, Any

from client.ble.ble_sensor_handler.base_ble_sensor_handler import BaseBleSensorHandler
from client.common.base_client import BaseClient
from client.common.sensor_metadata import SensorMetadata
from event_bus.redis_stream_bus.redis_stream_bus import RedisStreamBus

logger = logging.getLogger("PpgBleSensorHandler")

# PPG Constants
PPG_SERVICE_UUID = "8899b3a7-38fb-42f5-9955-59c52b5d53f2"
# Data characteristic includes the value of the PPG and the status incl. timestamp
PPG_GREEN_DATA_UUID = "8899b3a8-38fb-42f5-9955-59c52b5d53f2"
PPG_RED_DATA_UUID = "8899b3ac-38fb-42f5-9955-59c52b5d53f2"
PPG_IR_DATA_UUID = "8899b3aa-38fb-42f5-9955-59c52b5d53f2"

# Status codes
PPG_STATUS = {
    0: "Normal value",
    -1: "Higher priority sensor active"
}

# Minimum interval between publications when not all data is available
PUBLISH_INTERVAL_MS = 1000

class PpgBleSensorHandler(BaseBleSensorHandler):
    """Handler for PPG (Photoplethysmogram) BLE service for the Health monitoring app deployed in
     Samsung Galaxy Watch 7."""

    def __init__(self,
                 event_bus: RedisStreamBus,
                 client: BaseClient,
                 is_enabled: bool,
                 sensor_id: str,
                 sensor_name: str,
                 sensor_type: str,
                 patient_id: str,
                 location: str,
                 publish_interval_ms: int = PUBLISH_INTERVAL_MS):
        """
        Initialize the PPG BLE sensor handler.

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
            publish_interval_ms (int): The minimum interval between publishing data in milliseconds.
        """
        # Call parent constructor
        super().__init__(event_bus, client, is_enabled, sensor_id, sensor_name, sensor_type, patient_id, location)

        # Initialize PPG data
        self._ppg_green = 0
        self._green_status = 0
        self._ppg_red = 0
        self._red_status = 0
        self._ppg_ir = 0
        self._ir_status = 0
        self._ppg_timestamp = 0

        # Data tracking for consolidated publishing
        self._green_updated = False
        self._red_updated = False
        self._ir_updated = False
        self._last_publish_time = 0
        self._publish_interval_ms = publish_interval_ms
        self._data_lock = threading.Lock()

        # Initialize the PPG sensor metadata, generate a unique ID with the prefix
        self._sensor_metadata = SensorMetadata(self._sensor_id,
                                               self._sensor_name,
                                               self._sensor_type,
                                               "Samsung Electronics",
                                               "Samsung Galaxy Watch 7 SM-L300",
                                               "14.0",
                                               "N/A",
                                               "Multi-wavelength optical sensor (green, red, IR) for blood volume changes",
                                               "Raw Value",
                                               self._location)

        # Register notification handler(s)
        self._register_notification_handler(PPG_GREEN_DATA_UUID, self._handle_ppg_green)
        self._register_notification_handler(PPG_RED_DATA_UUID, self._handle_ppg_red)
        self._register_notification_handler(PPG_IR_DATA_UUID, self._handle_ppg_ir)
        logger.info("PPG BLE sensor handler initialized")

    @property
    def service_uuid(self) -> str:
        """Return the UUID of the PPG service."""
        return PPG_SERVICE_UUID

    @property
    def characteristic_uuids(self) -> Dict[str, str]:
        """Return a dictionary of characteristic names to UUIDs."""
        return {
            'ppg_green': PPG_GREEN_DATA_UUID,
            'ppg_red': PPG_RED_DATA_UUID,
            'ppg_ir': PPG_IR_DATA_UUID
        }

    @property
    def sensor_metadata(self) -> SensorMetadata:
        """Return metadata for PPG BLE sensor."""
        return self._sensor_metadata

    # === Public API Functions ===

    def read_initial_data(self) -> None:
        """Read initial values from characteristics."""
        # Prior to reading the initial data from the BLE server, publish the sensor metadata
        super().read_initial_data()

        try:
            # Read PPG green value and status
            if 'ppg_green' in self.characteristics:
                try:
                    char = self.characteristics['ppg_green']
                    data = char.read()
                    self._handle_ppg_green(data)
                except Exception as e:
                    logger.warning(f"Error reading initial PPG green data: {e}")

            # Read PPG red value and status
            if 'ppg_red' in self.characteristics:
                try:
                    char = self.characteristics['ppg_red']
                    data = char.read()
                    self._handle_ppg_red(data)
                except Exception as e:
                    logger.warning(f"Error reading initial PPG red data: {e}")

            # Read PPG IR value and status
            if 'ppg_ir' in self.characteristics:
                try:
                    char = self.characteristics['ppg_ir']
                    data = char.read()
                    self._handle_ppg_ir(data)
                except Exception as e:
                    logger.warning(f"Error reading initial PPG red data: {e}")

        except Exception as e:
            logger.warning(f"Error reading initial PPG data: {e}")

    def get_data(self) -> Dict[str, Any]:
        """
        Return the current PPG (Green, Red, and IR) data as a dictionary.

        Returns:
            dict: Dictionary containing PPG data.
        """
        with self._data_lock:
            return {
                'timestamp': self._ppg_timestamp,
                'values': {
                    'green': self._ppg_green,
                    'red': self._ppg_red,
                    'ir': self._ppg_ir,
                    'green_status': PPG_STATUS.get(self._green_status, "Unknown"),
                    'red_status': PPG_STATUS.get(self._red_status, "Unknown"),
                    'ir_status': PPG_STATUS.get(self._ir_status, "Unknown")
                }
            }

    # === Local Functions ===

    def _handle_ppg_data(self, data: bytes, color: str) -> None:
        """
        Generic handler for PPG notifications of any color.

        Args:
            data (bytes): PPG data received from the device.
            color (str): Color of the PPG data ('green', 'red', or 'ir').
        """
        try:
            # Make sure we have enough data (at least 8 bytes for timestamp + 4 for value + 2 for status)
            if len(data) < 14:
                logger.warning(f"Insufficient data length for PPG {color}: {len(data)} bytes")
                return

            # Unpack the data structure
            timestamp, ppg_val, status = struct.unpack("<Qih", data)

            with self._data_lock:
                # Update the appropriate color's data
                self._ppg_timestamp = timestamp

                if color == 'green':
                    self._ppg_green = ppg_val
                    self._green_status = status
                    self._green_updated = True
                    status_text = PPG_STATUS.get(self._green_status, "Unknown")
                    value_for_log = self._ppg_green
                elif color == 'red':
                    self._ppg_red = ppg_val
                    self._red_status = status
                    self._red_updated = True
                    status_text = PPG_STATUS.get(self._red_status, "Unknown")
                    value_for_log = self._ppg_red
                elif color == 'ir':
                    self._ppg_ir = ppg_val
                    self._ir_status = status
                    self._ir_updated = True
                    status_text = PPG_STATUS.get(self._ir_status, "Unknown")
                    value_for_log = self._ppg_ir
                else:
                    logger.error(f"Unknown PPG color: {color}")
                    return

                # Set the last data timestamp for connection monitoring
                self._last_data_timestamp = datetime.now(timezone.utc)

                # Log data
                logger.info(f"Timestamp: {self._ppg_timestamp}, PPG {color.capitalize()} Value: {value_for_log}, "
                            f"PPG {color.capitalize()} Status: {status_text}")

                # Check if we should publish consolidated data
                self._check_and_publish()

        except struct.error as e:
            logger.error(f"Error unpacking PPG {color} data structure: {e}")
        except Exception as e:
            logger.error(f"Error processing PPG {color} data: {e}")

    def _handle_ppg_green(self, data: bytes) -> None:
        """
        Handle PPG green notification.

        Args:
            data (bytes): PPG green data received from the device.
        """
        self._handle_ppg_data(data, 'green')

    def _handle_ppg_red(self, data: bytes) -> None:
        """
        Handle PPG red notification.

        Args:
            data (bytes): PPG red data received from the device.
        """
        self._handle_ppg_data(data, 'red')

    def _handle_ppg_ir(self, data: bytes) -> None:
        """
        Handle PPG IR notification.

        Args:
            data (bytes): PPG IR data received from the device.
        """
        self._handle_ppg_data(data, 'ir')

    def _check_and_publish(self) -> None:
        """Check if all PPG data has been updated and publish if so."""
        # This should be called with the data lock held
        current_time = time.time() * 1000  # Convert to milliseconds

        # Publish if all data updated, or if enough time has elapsed since last publishing of the data
        if (self._all_data_updated() or
                (self._any_data_updated() and
                 (current_time - self._last_publish_time >= self._publish_interval_ms))):
            self._publish_consolidated_data()

    def _all_data_updated(self) -> bool:
        """Check if all PPG data sources have been updated."""
        return self._green_updated and self._red_updated and self._ir_updated

    def _any_data_updated(self) -> bool:
        """Check if any PPG data sources have been updated."""
        return self._green_updated or self._red_updated or self._ir_updated

    def _reset_update_flags(self) -> None:
        """Reset all update flags."""
        self._green_updated = False
        self._red_updated = False
        self._ir_updated = False

    def _publish_consolidated_data(self) -> None:
        """Publish all PPG data in a single consolidated event."""
        # This should be called with the data lock held
        try:
            # Get the consolidated data
            data = self.get_data()

            # Publish the data
            self._publish_sensor_data(data)

            # Update the time of the last publishing of the data
            self._last_publish_time = time.time() * 1000  # Convert to milliseconds

            # Reset update flags
            self._reset_update_flags()

            logger.debug("Published consolidated PPG data")
        except Exception as e:
            logger.error(f"Error publishing consolidated PPG data: {e}")