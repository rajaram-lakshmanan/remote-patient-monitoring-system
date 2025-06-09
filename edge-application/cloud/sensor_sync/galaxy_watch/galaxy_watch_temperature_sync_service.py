#!/usr/bin/env python3
# -----------------------------------------------------------------------------
# Filename: galaxy_watch_temperature_sync_service.py
# Author: Rajaram Lakshmanan
# Description: Specialized sync service for Galaxy Watch temperature sensors
# License: MIT (see LICENSE)
# -----------------------------------------------------------------------------

import logging
from typing import Dict, Any, Optional

from config.models.cloud.azure_iot_hub_config import AzureIoTHubConfig
from config.models.cloud.cloud_sensor_sync_config import SensorSyncServiceConfig
from event_bus.models.sensor.sensor_data_event import SensorDataEvent
from cloud.sensor_sync.base_sensor_sync_service import BaseSensorSyncService
from event_bus.redis_stream_bus.redis_stream_bus import RedisStreamBus

logger = logging.getLogger("GalaxyWatchTemperatureSyncService")


class GalaxyWatchTemperatureSyncService(BaseSensorSyncService):
    """
    Specialized sync service for Galaxy Watch temperature sensors.
    Handles skin (object) and ambient temperature measurements.
    """

    def __init__(self,
                 event_bus: RedisStreamBus,
                 sensor_sync_service_config: SensorSyncServiceConfig,
                 azure_iot_hub_config: AzureIoTHubConfig):
        """
        Initialize the Galaxy watch Temperature sensor sync service.

        Args:
            event_bus: Redis event bus for subscribing to events
            sensor_sync_service_config: Configuration for the sensor sync service
            azure_iot_hub_config: Azure IoT Hub configuration
        """
        super().__init__(event_bus, sensor_sync_service_config, azure_iot_hub_config)

        # Temperature-specific thresholds (with defaults)
        sync_options = sensor_sync_service_config.sync_options
        self._skin_temp_high = sync_options.get_custom_param('alert_thresholds',
                                                             {}).get('skin_high', 38.0)
        self._skin_temp_low = sync_options.get_custom_param('alert_thresholds',
                                                            {}).get('skin_low', 35.0)
        self._ambient_temp_high = sync_options.get_custom_param('alert_thresholds',
                                                                {}).get('ambient_high', 40.0)
        self._ambient_temp_low = sync_options.get_custom_param('alert_thresholds',
                                                               {}).get('ambient_low', 10.0)

        logger.info(f"Temperature sync service initialized for {self._sensor_id}")

    def _process_sensor_data(self, event: SensorDataEvent) -> Optional[Dict[str, Any]]:
        """
        Process temperature data.

        Args:
            event: The sensor data event

        Returns:
            Dict[str, Any]: The processed data
        """
        # Extract data from the event
        timestamp = event.data.get('timestamp', 0)
        values = event.data.get('values', {})
        skin_temp = values.get('skin', 0.0)
        ambient_temp = values.get('ambient', 0.0)
        status_code = values.get('status_code', 0)

        # Convert status codes to standardized format
        status_mapping = {
            0: "Normal",
            -1: "Error"
        }

        standardized_status = status_mapping.get(status_code, "Unknown")

        # Check for temperature alerts
        alerts = []

        if skin_temp > self._skin_temp_high:
            alerts.append("HighSkinTemperature")
        elif self._skin_temp_low > skin_temp > 0:  # Avoid false alerts for zero values
            alerts.append("LowSkinTemperature")

        if ambient_temp > self._ambient_temp_high:
            alerts.append("HighAmbientTemperature")
        elif self._ambient_temp_low > ambient_temp > -273:  # Avoid absolute zero false alerts
            alerts.append("LowAmbientTemperature")

        # Temperature difference analysis (potential fever detection)
        temp_difference = skin_temp - ambient_temp
        if temp_difference > 5.0 and skin_temp > 37.5:
            alerts.append("PotentialFever")

        # Build the processed data structure
        processed_data = {
            "timestamp": timestamp,
            "temperature": {
                "skin": skin_temp,
                "ambient": ambient_temp,
                "difference": temp_difference
            },
            "status": standardized_status,
            "rawStatusCode": status_code,
            "alerts": alerts if alerts else None,
            "deviceType": "GalaxyWatch"
        }

        return processed_data

    def _get_message_properties(self, event: SensorDataEvent) -> Dict[str, str]:
        """
        Get message properties for temperature data.

        Args:
            event: The sensor data event

        Returns:
            Dict[str, str]: Message properties for routing
        """
        properties = {
            "type": "temperatureData",
            "deviceType": "GalaxyWatch",
            "sensorId": self._sensor_id
        }

        # Check for temperature alerts
        values = event.data.get('values', {})
        skin_temp = values.get('skin', 0.0)
        ambient_temp = values.get('ambient', 0.0)

        alerts = []

        if skin_temp > self._skin_temp_high:
            alerts.append("HighSkinTemperature")
        elif self._skin_temp_low > skin_temp > 0:
            alerts.append("LowSkinTemperature")

        if ambient_temp > self._ambient_temp_high:
            alerts.append("HighAmbientTemperature")
        elif self._ambient_temp_low > ambient_temp > -273:
            alerts.append("LowAmbientTemperature")

        # Temperature difference analysis (potential fever detection)
        temp_difference = skin_temp - ambient_temp
        if temp_difference > 5.0 and skin_temp > 37.5:
            alerts.append("PotentialFever")

        if alerts:
            properties["hasAlerts"] = "true"
            properties["alertTypes"] = ",".join(alerts)

        return properties

    def _get_batch_type(self) -> str:
        """
        Get the batch type for temperature data.

        Returns:
            str: The batch type
        """
        return "temperatureBatch"

    def _extend_metadata_properties(self, properties: Dict[str, Any], event: object) -> None:
        """
        Add temperature-specific metadata properties.

        Args:
            properties: The properties dictionary to extend
            event: The original metadata event
        """
        # Add temperature specific properties
        properties["monitoringThresholds"] = {
            "skinTemperatureHigh": self._skin_temp_high,
            "skinTemperatureLow": self._skin_temp_low,
            "ambientTemperatureHigh": self._ambient_temp_high,
            "ambientTemperatureLow": self._ambient_temp_low
        }