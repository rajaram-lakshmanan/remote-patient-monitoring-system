#!/usr/bin/env python3
# -----------------------------------------------------------------------------
# Filename: galaxy_watch_ppg_sync_service.py
# Author: Rajaram Lakshmanan
# Description: Specialized sync service for Galaxy Watch PPG sensors
# License: MIT (see LICENSE)
# -----------------------------------------------------------------------------

import logging
from typing import Dict, Any, Optional

from config.models.cloud.azure_iot_hub_config import AzureIoTHubConfig
from config.models.cloud.cloud_sensor_sync_config import SensorSyncServiceConfig
from event_bus.models.sensor.sensor_data_event import SensorDataEvent
from cloud.sensor_sync.base_sensor_sync_service import BaseSensorSyncService
from event_bus.redis_stream_bus.redis_stream_bus import RedisStreamBus

logger = logging.getLogger("GalaxyWatchPpgSyncService")


class GalaxyWatchPpgSyncService(BaseSensorSyncService):
    """
    Specialized sync service for Galaxy Watch PPG (Photoplethysmogram) sensors.
    Handles green, red, and IR PPG signal data.
    """

    def __init__(self,
                 event_bus: RedisStreamBus,
                 sensor_sync_service_config: SensorSyncServiceConfig,
                 azure_iot_hub_config: AzureIoTHubConfig):
        """
        Initialize the Galaxy watch PPG sensor sync service.

        Args:
            event_bus: Redis event bus for subscribing to events
            sensor_sync_service_config: Configuration for the sensor sync service
            azure_iot_hub_config: Azure IoT Hub configuration
        """
        super().__init__(event_bus, sensor_sync_service_config, azure_iot_hub_config)

        # PPG-specific thresholds and config
        sync_options = sensor_sync_service_config.sync_options
        self._signal_strength_threshold = sync_options.get_custom_param('signal_strength_threshold', 30000)

        # Ensure batch size is appropriate for PPG data
        if self._batch_size < 200:
            self._batch_size = 200

        logger.info(f"PPG sync service initialized for {self._sensor_id}")

    def _process_sensor_data(self, event: SensorDataEvent) -> Optional[Dict[str, Any]]:
        """
        Process PPG data.

        Args:
            event: The sensor data event

        Returns:
            Dict[str, Any]: The processed data
        """
        # Extract data from the event
        timestamp = event.data.get('timestamp', 0)
        values = event.data.get('values', {})

        # Get PPG values for all wavelengths
        ppg_green = values.get('green', 0)
        ppg_red = values.get('red', 0)
        ppg_ir = values.get('ir', 0)

        # Get statuses
        green_status = values.get('green_status', 'Unknown')
        red_status = values.get('red_status', 'Unknown')
        ir_status = values.get('ir_status', 'Unknown')

        # Convert status codes to standardized format
        status_mapping = {
            "Normal value": "Normal",
            "Higher priority sensor active": "HigherPrioritySensorActive"
        }

        standardized_green_status = status_mapping.get(green_status, green_status)
        standardized_red_status = status_mapping.get(red_status, red_status)
        standardized_ir_status = status_mapping.get(ir_status, ir_status)

        # Check signal quality
        signal_quality = "Good"
        if (ppg_green < self._signal_strength_threshold and
                ppg_red < self._signal_strength_threshold and
                ppg_ir < self._signal_strength_threshold):
            signal_quality = "Poor"

        # Calculate signal strength as percentage (simplified)
        max_expected_value = 65535  # Typical max for PPG readings
        green_strength = min(100, int((ppg_green / max_expected_value) * 100)) if ppg_green > 0 else 0
        red_strength = min(100, int((ppg_red / max_expected_value) * 100)) if ppg_red > 0 else 0
        ir_strength = min(100, int((ppg_ir / max_expected_value) * 100)) if ppg_ir > 0 else 0

        # Build the processed data structure
        processed_data = {
            "timestamp": timestamp,
            "ppg": {
                "green": ppg_green,
                "red": ppg_red,
                "ir": ppg_ir,
                "greenStatus": standardized_green_status,
                "redStatus": standardized_red_status,
                "irStatus": standardized_ir_status
            },
            "signalQuality": signal_quality,
            "signalStrength": {
                "green": green_strength,
                "red": red_strength,
                "ir": ir_strength
            },
            "deviceType": "GalaxyWatch"
        }

        return processed_data

    def _get_message_properties(self, event: SensorDataEvent) -> Dict[str, str]:
        """
        Get message properties for PPG data.

        Args:
            event: The sensor data event

        Returns:
            Dict[str, str]: Message properties for routing
        """
        properties = {
            "type": "ppgData",
            "deviceType": "GalaxyWatch",
            "sensorId": self._sensor_id
        }

        # Check signal quality
        values = event.data.get('values', {})
        ppg_green = values.get('green', 0)
        ppg_red = values.get('red', 0)
        ppg_ir = values.get('ir', 0)

        if (ppg_green < self._signal_strength_threshold and
                ppg_red < self._signal_strength_threshold and
                ppg_ir < self._signal_strength_threshold):
            properties["signalQuality"] = "Poor"

        return properties

    def _get_batch_type(self) -> str:
        """
        Get the batch type for PPG data.

        Returns:
            str: The batch type
        """
        return "ppgBatch"

    def _extend_metadata_properties(self, properties: Dict[str, Any], event: object) -> None:
        """
        Add PPG-specific metadata properties.

        Args:
            properties: The properties dictionary to extend
            event: The original metadata event
        """
        # Add PPG-specific properties
        properties["sensorInfo"]["wavelengths"] = ["Green", "Red", "IR"]
        properties["monitoringThresholds"] = {
            "signalStrengthThreshold": self._signal_strength_threshold
        }