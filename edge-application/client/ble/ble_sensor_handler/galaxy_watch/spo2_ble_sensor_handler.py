#!/usr/bin/env python3
# -----------------------------------------------------------------------------
# Filename: spo2_ble_sensor_handler.py
# Author: Rajaram Lakshmanan
# Description: Handler for SpO2 BLE service for the Health monitoring app
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

logger = logging.getLogger("Spo2BleSensorHandler")

# SpO2 Constants
SPO2_SERVICE_UUID = "00001822-0000-1000-8000-00805f9b34fb"
# SpO2 sensor data characteristic will include the SpO2 value and the status of the blood oxygen measurement
SPO2_DATA_UUID = "00002a5e-0000-1000-8000-00805f9b34fb"
SPO2_TRIGGER_UUID = "00002a5f-0000-1000-8000-00805f9b34fb"

# Status codes
SPO2_STATUS = {
    -6: "Time out",
    -5: "Signal quality is low",
    -4: "Device moved during measurement",
     0: "Calculating SpO2",
     2: "SpO2 measurement was completed"
}

class Spo2BleSensorHandler(BaseBleSensorHandler):
    """Handler for SpO2 BLE service for the Health monitoring app deployed in Samsung Galaxy Watch 7."""
    
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
        Initialize the SpO2 BLE sensor handler.
        
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

        # Initialize SpO2 sensor data
        self._spo2_value = 0
        self._spo2_status = 0
        self._spo2_timestamp = 0

        # Initialize the SpO2 sensor metadata, generate a unique ID with the prefix
        self._sensor_metadata = SensorMetadata(self._sensor_id,
                                               self._sensor_name,
                                               self._sensor_type,
                                               "Samsung Electronics",
                                               "Samsung Galaxy Watch 7 SM-L300",
                                               "14.0",
                                               "N/A",
                                               "Optical blood oxygen saturation sensor using red and infrared light",
                                               "%",
                                               "Wrist")

        # Register notification handler(s)
        self._register_notification_handler(SPO2_DATA_UUID, self._handle_spo2_data)

        # Register for the trigger stream
        self._event_bus.register_stream(self.sensor_trigger_stream_name, SensorTriggerEvent)

        logger.info("SpO2 BLE sensor handler initialized")
    
    @property
    def service_uuid(self) -> str:
        """Return the UUID of the SpO2 service."""
        return SPO2_SERVICE_UUID
    
    @property
    def characteristic_uuids(self) -> Dict[str, str]:
        """Return a dictionary of characteristic names to UUIDs."""
        return {
            'spo2_data': SPO2_DATA_UUID,
            'spo2_trigger': SPO2_TRIGGER_UUID
        }
    
    @property
    def sensor_metadata(self) -> SensorMetadata:
        """Return metadata for SpO2 BLE sensor."""
        return self._sensor_metadata

    # === Public API Functions ===

    def read_initial_data(self) -> None:
        """Read initial values from characteristics."""
        # Prior to reading the initial sensor data from the BLE server, publish the sensor metadata
        super().read_initial_data()

        logger.debug("SpO2 measurement is based on trigger. No sensor data will be available "
                     "until the measurement is triggered.")
    
    def get_data(self) -> Dict[str, Any]:
        """
        Return the current SpO2 sensor data as a dictionary.
        
        Returns:
            dict: Dictionary containing SpO2 sensor data.
        """
        return {
            'timestamp': self._spo2_timestamp,
            'values': {
                'value': self._spo2_value,
                'status': SPO2_STATUS.get(self._spo2_status, "Unknown"),
                'status_code': self._spo2_status
            }
        }

    def subscribe_to_events(self) -> None:
        """Subscribe to the trigger event for the SpO2 sensor."""
        self._event_bus.subscribe(self.sensor_trigger_stream_name,
                                  "spo2_trigger_consumer",
                                  lambda event: self._trigger_measurement(event))

    # === Local Functions ===

    def _handle_spo2_data(self, data: bytes) -> None:
        """
        Handle SpO2 measurement notification.

        Args:
            data (bytes): SpO2 sensor data received from the device.
        """
        try:
            # SpO2 notification will occur until the measurement is active
            if len(data) >= 14:  # Need at least 8 bytes for timestamp + 4 for Spo2 value + 2 for status
                self._spo2_timestamp, self._spo2_value, self._spo2_status = struct.unpack("<Qih", data)
                status_text = SPO2_STATUS.get(self._spo2_status, "Unknown")
                logger.info(f"Timestamp: {self._spo2_timestamp}, SpO2: {self._spo2_value} %, Status: {status_text}")

                self._last_data_timestamp = datetime.now(timezone.utc)

                # Publish sensor data; when status is received, all the registry is available.
                # Publish the registry to all the subscribers
                self._publish_sensor_data(self.get_data())
        except struct.error as e:
            logger.error(f"Error unpacking SpO2 sensor data structure: {e}")
        except Exception as e:
            logger.error(f"Error processing SpO2 sensor data: {e}")

    def _trigger_measurement(self, sensor_trigger_event: SensorTriggerEvent) -> None:
        """
        Trigger a SpO2 measurement.
        """
        logger.debug(f"Received sensor trigger event: {sensor_trigger_event}")

        # Use a separate thread to avoid blocking the Redis callback
        def trigger_thread():
            if 'spo2_trigger' in self.characteristics:
                try:
                    # Small delay to avoid immediate conflict
                    time.sleep(0.2)

                    logger.info("Triggering SpO2 measurement...")
                    from client.ble.ble_client.ble_client import BleClient
                    if isinstance(self.client, BleClient):
                        # Use the safe write method
                        logger.debug(f"Thread ID {threading.get_ident()} starting trigger operation")
                        success = self.client.write_characteristic(
                            self.characteristics['spo2_trigger'],
                            b"\x01",
                            True  # with response
                        )
                        logger.debug(f"Thread ID {threading.get_ident()} completed trigger operation")

                        if success:
                            logger.info("SpO2 measurement triggered")
                        else:
                            logger.error("Failed to trigger SpO2 measurement")
                except Exception as e:
                    logger.error(f"Error triggering SpO2 measurement: {e}")
            else:
                logger.error("SpO2 trigger characteristic not found")

        # Start the thread
        thread = threading.Thread(target=trigger_thread)
        thread.daemon = True
        thread.start()