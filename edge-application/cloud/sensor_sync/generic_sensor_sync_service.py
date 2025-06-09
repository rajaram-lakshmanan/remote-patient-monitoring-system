#!/usr/bin/env python3
# -----------------------------------------------------------------------------
# Filename: generic_sensor_sync_service.py
# Author: Rajaram Lakshmanan
# Description: Generic sync service for any sensor type
# License: MIT (see LICENSE)
# -----------------------------------------------------------------------------

import logging
from typing import Dict, Any, Optional

from config.models.cloud.azure_iot_hub_config import AzureIoTHubConfig
from config.models.cloud.cloud_sensor_sync_config import SensorSyncServiceConfig
from event_bus.models.sensor.sensor_data_event import SensorDataEvent
from cloud.sensor_sync.base_sensor_sync_service import BaseSensorSyncService
from event_bus.redis_stream_bus.redis_stream_bus import RedisStreamBus

logger = logging.getLogger("GenericSensorSyncService")


class GenericSensorSyncService(BaseSensorSyncService):
    """
    Generic sync service for any sensor type.

    This service sends sensor data to IoT Hub with minimal processing,
    preserving the original data structure. It's used when there is no
    specialized sync service for a sensor type.
    """

    def __init__(self,
                 event_bus: RedisStreamBus,
                 sensor_sync_service_config: SensorSyncServiceConfig,
                 azure_iot_hub_config: AzureIoTHubConfig):
        """
        Initialize the sensor sync service for any generic type of sensor.

        Args:
            event_bus: Redis event bus for subscribing to events
            sensor_sync_service_config: Configuration for the sensor sync service
            azure_iot_hub_config: Azure IoT Hub configuration
        """
        super().__init__(event_bus, sensor_sync_service_config, azure_iot_hub_config)

        logger.info(f"Generic sensor sync service initialized for {self._sensor_id}")

    def _process_sensor_data(self, event: SensorDataEvent) -> Optional[Dict[str, Any]]:
        """
        Process sensor data with minimal transformation.

        Args:
            event: The sensor data event

        Returns:
            Dict[str, Any]: The processed data
        """
        # Create a standardized envelope around the original data
        processed_data = {
            "sensorId": self._sensor_id,
            "patientId": event.patient_id,
            "sensorType": event.sensor_type,
            "event_timestamp": event.data.get('timestamp', 0),
            "data": event.data  # Preserve original data structure
        }

        # Add client context if available
        if self._client_info:
            processed_data["clientInfo"] = {
                "clientId": self._client_info.get("client_id", "unknown"),
                "clientType": self._client_info.get("client_type", "unknown"),
                "connectionStatus": self._client_info.get("connection_status", "unknown")
            }

        return processed_data

    def _get_message_properties(self, event: SensorDataEvent) -> Dict[str, str]:
        """
        Get standard message properties for routing.

        Args:
            event: The sensor data event

        Returns:
            Dict[str, str]: Message properties for routing
        """
        return {
            "type": "genericSensorData",
            "sensorType": event.sensor_type,
            "sensorId": self._sensor_id
        }

    def _get_batch_type(self) -> str:
        """
        Get the batch type for generic sensor data.

        Returns:
            str: The batch type
        """
        return "genericSensorBatch"

    def _extend_metadata_properties(self, properties: Dict[str, Any], event: object) -> None:
        """
        Add generic sensor-specific metadata properties.

        Args:
            properties: The properties dictionary to extend
            event: The original metadata event
        """
        # Add a flag to indicate this is a generic service
        properties["sensorInfo"]["handledBy"] = "GenericSyncService"