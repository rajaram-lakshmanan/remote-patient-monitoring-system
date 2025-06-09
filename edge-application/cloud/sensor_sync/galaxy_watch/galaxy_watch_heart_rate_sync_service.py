#!/usr/bin/env python3
# -----------------------------------------------------------------------------
# Filename: galaxy_watch_heart_rate_sync_service.py
# Author: Rajaram Lakshmanan
# Description: Specialized sync service for Galaxy Watch heart rate sensors
# License: MIT (see LICENSE)
# -----------------------------------------------------------------------------

import logging
from typing import Dict, Any, Optional

from config.models.cloud.azure_iot_hub_config import AzureIoTHubConfig
from config.models.cloud.cloud_sensor_sync_config import SensorSyncServiceConfig
from event_bus.models.sensor.sensor_data_event import SensorDataEvent
from cloud.sensor_sync.base_sensor_sync_service import BaseSensorSyncService
from event_bus.redis_stream_bus.redis_stream_bus import RedisStreamBus

logger = logging.getLogger("GalaxyWatchHeartRateSyncService")


class GalaxyWatchHeartRateSyncService(BaseSensorSyncService):
    """
    Specialized sync service for Galaxy Watch heart rate sensors.
    Handles data processing and sending telemetry to IoT Hub.
    """

    def __init__(self,
                 event_bus: RedisStreamBus,
                 sensor_sync_service_config: SensorSyncServiceConfig,
                 azure_iot_hub_config: AzureIoTHubConfig):
        """
        Initialize the Galaxy watch Heart rate sensor sync service.

        Args:
            event_bus: Redis event bus for subscribing to events
            sensor_sync_service_config: Configuration for the sensor sync service
            azure_iot_hub_config: Azure IoT Hub configuration
        """
        super().__init__(event_bus, sensor_sync_service_config, azure_iot_hub_config)

        # Heart-rate-specific thresholds (with defaults)
        sync_options = sensor_sync_service_config.sync_options
        self._alert_high = sync_options.get_custom_param('alert_thresholds', {}).get('high', 150)
        self._alert_low = sync_options.get_custom_param('alert_thresholds', {}).get('low', 40)

        logger.info(f"Heart Rate sync service initialized for {self._sensor_id}")

    def _process_sensor_data(self, event: SensorDataEvent) -> Optional[Dict[str, Any]]:
        """
        Process heart rate data and add calculated values.

        Args:
            event: The sensor data event

        Returns:
            Dict[str, Any]: The processed data
        """
        # Extract heart rate data from the event
        timestamp = event.data.get('timestamp', 0)
        values = event.data.get('values', {})
        heart_rate = values.get('heart_rate', 0)
        status_code = values.get('status_code', 0)

        # Skip processing if heart rate is invalid
        if heart_rate <= 0:
            logger.debug(f"Skipping invalid heart rate: {heart_rate}")
            return None

        # Convert Galaxy Watch status codes to standardized format
        status_mapping = {
            0: "Initial",
            1: "Success",
            -2: "MovementDetected",
            -3: "DeviceDetached",
            -8: "WeakSignal",
            -10: "TooMuchMovement",
            -99: "NoData",
            -999: "HigherPrioritySensorActive"
        }

        standardized_status = status_mapping.get(status_code, "Unknown")

        # Calculate heart rate zone
        zone = self._calculate_heart_rate_zone(heart_rate)

        # Check alert thresholds
        alert = None
        if heart_rate > self._alert_high:
            alert = "HighHeartRate"
        elif 0 < heart_rate < self._alert_low:
            alert = "LowHeartRate"

        # Calculate confidence based on status code
        confidence = 100
        if status_code < 0:
            confidence = max(0, 100 + status_code * 10)  # Lower confidence for negative status codes

        # Build the processed data structure
        processed_data = {
            "timestamp": timestamp,
            "heartRate": heart_rate,
            "status": standardized_status,
            "rawStatusCode": status_code,
            "zone": zone,
            "alert": alert,
            "confidence": confidence,
            "deviceType": "GalaxyWatch"
        }

        return processed_data

    def _get_message_properties(self, event: SensorDataEvent) -> Dict[str, str]:
        """
        Get message properties for heart rate data.

        Args:
            event: The sensor data event

        Returns:
            Dict[str, str]: Message properties for routing
        """
        properties = {
            "type": "heartRateData",
            "deviceType": "GalaxyWatch",
            "sensorId": self._sensor_id
        }

        # Check if this contains an alert and add it to properties
        values = event.data.get('values', {})
        heart_rate = values.get('heart_rate', 0)

        if heart_rate > self._alert_high:
            properties["alert"] = "HighHeartRate"
        elif 0 < heart_rate < self._alert_low:
            properties["alert"] = "LowHeartRate"

        return properties

    def _get_batch_type(self) -> str:
        """
        Get the batch type for heart rate data.

        Returns:
            str: The batch type
        """
        return "heartRateBatch"

    def _extend_metadata_properties(self, properties: Dict[str, Any], event: object) -> None:
        """
        Add heart-rate-specific metadata properties.

        Args:
            properties: The properties dictionary to extend
            event: The original metadata event
        """
        # Add heart rate specific monitoring thresholds
        properties["monitoringThresholds"] = {
            "heartRateHigh": self._alert_high,
            "heartRateLow": self._alert_low
        }

    @staticmethod
    def _calculate_heart_rate_zone(heart_rate: int) -> str:
        """
        Calculate the heart rate zone based on the heart rate value.

        Args:
            heart_rate: Heart rate in BPM

        Returns:
            str: Heart rate zone
        """
        if heart_rate <= 0:  # Invalid or zero heart rate
            return "Unknown"

        # Use simple heart rate zones
        if heart_rate < 60:
            return "Rest"
        elif heart_rate < 100:
            return "Light"
        elif heart_rate < 140:
            return "Moderate"
        elif heart_rate < 170:
            return "Vigorous"
        else:
            return "Maximum"