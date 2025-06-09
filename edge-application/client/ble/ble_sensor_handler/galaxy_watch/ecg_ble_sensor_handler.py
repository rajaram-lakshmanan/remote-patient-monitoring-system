#!/usr/bin/env python3
# -----------------------------------------------------------------------------
# Filename: ecg_ble_sensor_handler.py
# Author: Rajaram Lakshmanan
# Description: Handler for ECG BLE service for the Health monitoring app
# deployed in Samsung Galaxy Watch 7.
# License: MIT (see LICENSE)
# -----------------------------------------------------------------------------

import threading
import time
from datetime import datetime, timezone
import logging
import struct
from typing import Dict, Any

from client.ble.ble_sensor_handler.base_ble_sensor_handler import BaseBleSensorHandler
from client.common.base_client import BaseClient
from client.common.sensor_metadata import SensorMetadata
from event_bus.models.sensor.sensor_trigger_event import SensorTriggerEvent
from event_bus.redis_stream_bus.redis_stream_bus import RedisStreamBus

logger = logging.getLogger("EcgBleSensorHandler")

# ECG Constants
ECG_SERVICE_UUID = "8899b3b0-38fb-42f5-9955-59c52b5d53f2"
ECG_DATA_UUID = "8899b3b1-38fb-42f5-9955-59c52b5d53f2"
ECG_TRIGGER_UUID = "8899b3b3-38fb-42f5-9955-59c52b5d53f2"

# Status codes. Anything other than 0 means the device is not in contact
ECG_STATUS = {
    0: "Normal"
}

class EcgBleSensorHandler(BaseBleSensorHandler):
    """Handler for ECG BLE service for the Health monitoring app deployed in Samsung Galaxy Watch 7."""
    
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
        Initialize the ECG BLE sensor handler.
        
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

        # Initialize ECG sensor data
        self._ecg_mv = 0.0
        self._ecg_status = 0
        self._ecg_sequence = 0
        self._ecg_timestamp = 0

        # Initialize the ECG sensor metadata, generate a unique ID with the prefix
        self._sensor_metadata = SensorMetadata(self._sensor_id,
                                               self._sensor_name,
                                               self._sensor_type,
                                               "Samsung Electronics",
                                               "Samsung Galaxy Watch 7 SM-L300",
                                               "14.0",
                                               "N/A",
                                               "Single-lead electrocardiogram sensor for measuring heart electrical activity",
                                               "mV",
                                               self._location)

        # Register notification handler(s)
        self._register_notification_handler(ECG_DATA_UUID, self._handle_ecg_data)

        # Register for the trigger stream
        self._event_bus.register_stream(self.sensor_trigger_stream_name, SensorTriggerEvent)

        logger.info("ECG BLE sensor handler initialized")
    
    @property
    def service_uuid(self) -> str:
        """Return the UUID of the ECG service."""
        return ECG_SERVICE_UUID
    
    @property
    def characteristic_uuids(self) -> Dict[str, str]:
        """Return a dictionary of characteristic names to UUIDs."""
        return {
            'ecg_data': ECG_DATA_UUID,
            'ecg_trigger': ECG_TRIGGER_UUID
        }
    
    @property
    def sensor_metadata(self) -> SensorMetadata:
        """Return metadata for ECG BLE sensor."""
        return self._sensor_metadata

    # === Public API Functions ===

    def read_initial_data(self) -> None:
        """Read initial values from characteristics."""
        # Prior to reading the initial sensor data from the BLE server, publish the sensor metadata
        super().read_initial_data()

        logger.debug("ECG measurement is based on trigger. No sensor data will be available "
                     "until the measurement is triggered.")

    def get_data(self) -> Dict[str, Any]:
        """
        Return the current ECG sensor data as a dictionary.
        
        Returns:
            dict: Dictionary containing ECG sensor data.
        """
        return {
            'timestamp': self._ecg_timestamp,
            'values': {
                'mv': self._ecg_mv,
                'sequence': self._ecg_sequence,
                'status': ECG_STATUS.get(self._ecg_status, "Unknown"),
                'status_code': self._ecg_status
            }
        }

    def subscribe_to_events(self) -> None:
        """Subscribe to the trigger event for the ECG sensor."""
        self._event_bus.subscribe(self.sensor_trigger_stream_name,
                                  "ecg_trigger_consumer",
                                  lambda event: self._trigger_measurement(event))

    # === Local Functions ===

    def _handle_ecg_data(self, data: bytes) -> None:
        """
        Handle ECG measurement notification.

        Args:
            data (bytes): ECG sensor data received from the device.
        """
        try:
            # ECG notification will occur until the measurement is active
            if len(data) >= 16:  # Need at least 8 bytes for timestamp + 4 for ecg value + 2 for status +
                # 2 for sequence number
                self._ecg_timestamp, self._ecg_mv, self._ecg_status, self._ecg_sequence = struct.unpack("<Qfhh", data)
                status_text = ECG_STATUS.get(self._ecg_status, "Unknown")
                logger.debug(f"Timestamp: {self._ecg_timestamp}, ECG: {self._ecg_mv} mV, "
                            f"Sequence: {self._ecg_sequence}, Status: {status_text}")

                self._last_data_timestamp = datetime.now(timezone.utc)

                # Publish sensor data; when status is received, all the registry is available.
                # Publish the registry to all the subscribers
                self._publish_sensor_data(self.get_data())
        except struct.error as e:
            logger.error(f"Error unpacking ECG sensor data structure: {e}")
        except Exception as e:
            logger.error(f"Error processing ECG sensor data: {e}")

    def _trigger_measurement(self, sensor_trigger_event: SensorTriggerEvent) -> None:
        """
        Trigger a ECG measurement.
        """
        logger.debug(f"Received sensor trigger event: {sensor_trigger_event}")

        # Use a separate thread to avoid blocking the Redis callback
        def trigger_thread():
            if 'ecg_trigger' in self.characteristics:
                try:
                    # Small delay to avoid immediate conflict
                    time.sleep(0.2)

                    logger.info("Triggering ECG measurement...")
                    from client.ble.ble_client.ble_client import BleClient
                    if isinstance(self.client, BleClient):
                        # Use the safe write method
                        logger.debug(f"Thread ID {threading.get_ident()} starting trigger operation")
                        success = self.client.write_characteristic(
                            self.characteristics['ecg_trigger'],
                            b"\x01",
                            True  # with response
                        )
                        logger.debug(f"Thread ID {threading.get_ident()} completed trigger operation")

                        if success:
                            logger.info("ECG measurement triggered")
                        else:
                            logger.error("Failed to trigger ECG measurement")
                except Exception as e:
                    logger.error(f"Error triggering ECG measurement: {e}")
            else:
                logger.error("ECG trigger characteristic not found")

        # Start the thread
        thread = threading.Thread(target=trigger_thread)
        thread.daemon = True
        thread.start()