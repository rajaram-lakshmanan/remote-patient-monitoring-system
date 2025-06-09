#!/usr/bin/env python3
# -----------------------------------------------------------------------------
# Filename: galaxy_watch_accelerometer_sync_service.py
# Author: Rajaram Lakshmanan
# Description: Specialized sync service for Galaxy Watch accelerometer sensors
# License: MIT (see LICENSE)
# -----------------------------------------------------------------------------

import logging
from typing import Dict, Any, Optional

from config.models.cloud.azure_iot_hub_config import AzureIoTHubConfig
from config.models.cloud.cloud_sensor_sync_config import SensorSyncServiceConfig
from event_bus.models.sensor.sensor_data_event import SensorDataEvent
from cloud.sensor_sync.base_sensor_sync_service import BaseSensorSyncService
from event_bus.redis_stream_bus.redis_stream_bus import RedisStreamBus

logger = logging.getLogger("GalaxyWatchAccelerometerSyncService")


class GalaxyWatchAccelerometerSyncService(BaseSensorSyncService):
    """
    Specialized sync service for Galaxy Watch accelerometer sensors.
    Handles high-frequency 3-axis motion data.
    """

    def __init__(self,
                 event_bus: RedisStreamBus,
                 sensor_sync_service_config: SensorSyncServiceConfig,
                 azure_iot_hub_config: AzureIoTHubConfig):
        """
        Initialize the Galaxy watch Accelerometer sensor sync service.

        Args:
            event_bus: Redis event bus for subscribing to events
            sensor_sync_service_config: Configuration for the sensor sync service
            azure_iot_hub_config: Azure IoT Hub configuration
        """
        super().__init__(event_bus, sensor_sync_service_config, azure_iot_hub_config)

        # Accelerometer-specific attributes
        sync_options = sensor_sync_service_config.sync_options
        self._motion_threshold = sync_options.get_custom_param('motion_threshold', 1.5)  # g-force
        self._data_reduction_factor = sync_options.get_custom_param('data_reduction_factor', 2)

        # Ensure batch size is appropriate for high-frequency accelerometer data
        if self._batch_size < 250:
            self._batch_size = 250

        logger.info(f"Accelerometer sync service initialized for {self._sensor_id}")

    def _process_sensor_data(self, event: SensorDataEvent) -> Optional[Dict[str, Any]]:
        """
        Process accelerometer data and detect motion events.

        Args:
            event: The sensor data event

        Returns:
            Dict[str, Any]: The processed data
        """
        # Extract data from the event
        timestamp = event.data.get('timestamp', 0)
        values = event.data.get('values', {})
        x_accel = values.get('x', 0)
        y_accel = values.get('y', 0)
        z_accel = values.get('z', 0)

        # Calculate magnitude of acceleration
        magnitude = (x_accel ** 2 + y_accel ** 2 + z_accel ** 2) ** 0.5

        # Detect significant motion
        motion_detected = magnitude > self._motion_threshold

        # Calculate orientation
        orientation = self._determine_orientation(x_accel, y_accel, z_accel)

        return {
            "timestamp": timestamp,
            "accelerometer": {
                "x": x_accel,
                "y": y_accel,
                "z": z_accel,
                "magnitude": magnitude
            },
            "motion": {
                "detected": motion_detected,
                "orientation": orientation
            },
            "deviceType": "GalaxyWatch"
        }

    def _get_message_properties(self, event: SensorDataEvent) -> Dict[str, str]:
        """
        Get message properties for accelerometer data.

        Args:
            event: The sensor data event

        Returns:
            Dict[str, str]: Message properties for routing
        """
        properties = {
            "type": "accelerometerData",
            "deviceType": "GalaxyWatch",
            "sensorId": self._sensor_id
        }

        # Add motion detection property if available
        values = event.data.get('values', {})
        x_accel = values.get('x', 0)
        y_accel = values.get('y', 0)
        z_accel = values.get('z', 0)

        # Calculate magnitude and check if motion is detected
        magnitude = (x_accel ** 2 + y_accel ** 2 + z_accel ** 2) ** 0.5
        if magnitude > self._motion_threshold:
            properties["motionDetected"] = "true"

        return properties

    def _get_batch_type(self) -> str:
        """
        Get the batch type for accelerometer data.

        Returns:
            str: The batch type
        """
        return "accelerometerBatch"

    def _extend_metadata_properties(self, properties: Dict[str, Any], event: object) -> None:
        """
        Add accelerometer-specific metadata properties.

        Args:
            properties: The properties dictionary to extend
            event: The original metadata event
        """
        # Add accelerometer-specific properties
        properties["sensorInfo"]["samplingRate"] = "25Hz"
        properties["monitoringThresholds"] = {
            "motionThreshold": self._motion_threshold
        }

    @staticmethod
    def _determine_orientation(x: float, y: float, z: float) -> str:
        """
        Determine device orientation based on accelerometer values.

        Args:
            x: X-axis acceleration
            y: Y-axis acceleration
            z: Z-axis acceleration

        Returns:
            str: Orientation description
        """
        # Simplified orientation detection
        if abs(z) > abs(x) and abs(z) > abs(y):
            if z > 0:
                return "FaceUp"
            else:
                return "FaceDown"
        elif abs(y) > abs(x):
            if y > 0:
                return "TopDown"
            else:
                return "TopUp"
        else:
            if x > 0:
                return "RightSide"
            else:
                return "LeftSide"

    def _perform_maintenance(self) -> None:
        """
        Perform accelerometer specific maintenance.

        For accelerometer data, we may want to apply data reduction during
        maintenance to avoid excessive data transmission.
        """
        super()._perform_maintenance()

        # Check if our batch buffer is getting too large
        if len(self._batch_buffer) > self._batch_size * 2:
            logger.info(f"Batch buffer is large ({len(self._batch_buffer)} items), applying data reduction")

            # Apply simple data reduction by keeping every Nth item
            if self._data_reduction_factor > 1:
                self._batch_buffer = self._batch_buffer[::self._data_reduction_factor]
                logger.info(f"Reduced batch buffer to {len(self._batch_buffer)} items")