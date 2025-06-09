#!/usr/bin/env python3
# -----------------------------------------------------------------------------
# Filename: galaxy_watch_ecg_sync_service.py
# Author: Rajaram Lakshmanan
# Description: Specialized sync service for Galaxy Watch ECG sensors
# License: MIT (see LICENSE)
# -----------------------------------------------------------------------------

import logging
import time
from typing import Dict, Any, Optional
from datetime import datetime, timezone

from config.models.cloud.azure_iot_hub_config import AzureIoTHubConfig
from config.models.cloud.cloud_sensor_sync_config import SensorSyncServiceConfig
from event_bus.models.sensor.sensor_data_event import SensorDataEvent
from event_bus.models.sensor.sensor_trigger_event import SensorTriggerEvent
from event_bus.redis_stream_bus.redis_stream_bus import RedisStreamBus
from event_bus.stream_name import StreamName
from cloud.sensor_sync.base_sensor_sync_service import BaseSensorSyncService

logger = logging.getLogger("GalaxyWatchEcgSyncService")


class GalaxyWatchEcgSyncService(BaseSensorSyncService):
    """
    Specialized sync service for Galaxy Watch ECG sensors.
    Handles high-frequency cardiac data and on-demand measurements.
    """

    def __init__(self,
                 event_bus: RedisStreamBus,
                 sensor_sync_service_config: SensorSyncServiceConfig,
                 azure_iot_hub_config: AzureIoTHubConfig):
        """
        Initialize the Galaxy watch ECG sensor sync service.

        Args:
            event_bus: Redis event bus for subscribing to events
            sensor_sync_service_config: Configuration for the sensor sync service
            azure_iot_hub_config: Azure IoT Hub configuration
        """
        super().__init__(event_bus, sensor_sync_service_config, azure_iot_hub_config)

        # ECG-specific attributes
        sync_options = sensor_sync_service_config.sync_options
        self._measurement_cooldown = sync_options.get_custom_param('measurement_cooldown', 60)

        self._last_measurement_time = 0
        self._measurement_in_progress = False
        self._current_session_id = None

        # Get the trigger stream name
        self._trigger_stream = StreamName.get_sensor_stream_name(
            StreamName.SENSOR_TRIGGER_PREFIX.value,
            self._sensor_id
        )

        logger.info(f"ECG sync service initialized for {self._sensor_id}")

    def _initialize_iot_client(self) -> bool:
        """Initialize IoT Hub client with method handlers"""
        if not super()._initialize_iot_client():
            return False

        try:
            # Register method handler for triggering ECG measurement
            self._iot_client.register_method_handler("triggerMeasurement", self._handle_trigger_measurement_method)
            logger.info(f"Registered C2D method handlers for {self._sensor_id}")
            return True

        except Exception as e:
            logger.error(f"Error registering method handlers for {self._sensor_id}: {e}", exc_info=True)
            return False

    def _process_sensor_data(self, event: SensorDataEvent) -> Optional[Dict[str, Any]]:
        """
        Process ECG data.

        Args:
            event: The sensor data event

        Returns:
            Dict[str, Any]: The processed data
        """
        # Extract data from the event
        timestamp = event.data.get('timestamp', 0)
        values = event.data.get('values', {})
        ecg_mv = values.get('mv', 0)
        status_code = values.get('status_code', 0)
        sequence = values.get('sequence', 0)

        # Update measurement state
        if not self._measurement_in_progress:
            self._measurement_in_progress = True
            self._current_session_id = f"ecg-{int(time.time())}"
            logger.info(f"ECG measurement started, session ID: {self._current_session_id}")

        self._last_measurement_time = time.time()

        # Convert status codes to standardized format
        status_mapping = {
            0: "Normal",
            1: "Success",
            -2: "MovementDetected",
            -3: "DeviceDetached"
        }

        standardized_status = status_mapping.get(status_code, "Unknown")

        # Create the processed data
        processed_data = {
            "timestamp": timestamp,
            "ecg": ecg_mv,
            "sequence": sequence,
            "status": standardized_status,
            "rawStatusCode": status_code,
            "sessionId": self._current_session_id,
            "deviceType": "GalaxyWatch"
        }

        # If measurement completed, update state
        if status_code == 2:  # Status 2 means measurement completed
            self._measurement_in_progress = False
            logger.info(f"ECG measurement completed, session ID: {self._current_session_id}")
            processed_data["measurementComplete"] = True

        return processed_data

    def _get_message_properties(self, event: SensorDataEvent) -> Dict[str, str]:
        """
        Get message properties for ECG data.

        Args:
            event: The sensor data event

        Returns:
            Dict[str, str]: Message properties for routing
        """
        properties = {
            "type": "ecgData",
            "deviceType": "GalaxyWatch",
            "sensorId": self._sensor_id,
            "sessionId": self._current_session_id or "unknown"
        }

        # Check if this is the end of a measurement
        values = event.data.get('values', {})
        status_code = values.get('status_code', 0)

        if status_code == 2:  # Measurement completed
            properties["measurementComplete"] = "true"

        return properties

    def _get_batch_type(self) -> str:
        """
        Get the batch type for ECG data.

        Returns:
            str: The batch type
        """
        return "ecgBatch"

    def _extend_metadata_properties(self, properties: Dict[str, Any], event: object) -> None:
        """
        Add ECG-specific metadata properties.

        Args:
            properties: The properties dictionary to extend
            event: The original metadata event
        """
        # Add ECG-specific properties
        properties["sensorInfo"]["isOnDemand"] = True
        properties["sensorInfo"]["samplingRate"] = "250Hz"

    def _handle_trigger_measurement_method(self, method_name: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Handle ECG measurement trigger from the cloud.

        Args:
            method_name: The method name (should be "triggerMeasurement")
            payload: The method payload

        Returns:
            Dict[str, Any]: The response
        """
        logger.info(f"Received {method_name} direct method call for {self._sensor_id}")

        try:
            # Check the cooldown period
            current_time = time.time()
            time_since_last = current_time - self._last_measurement_time

            if time_since_last < self._measurement_cooldown:
                remaining = int(self._measurement_cooldown - time_since_last)
                logger.warning(f"Measurement cooldown in effect, {remaining}s remaining")
                return {
                    "status": "error",
                    "message": f"Measurement cooldown in effect, please wait {remaining} seconds",
                    "remainingCooldown": remaining
                }

            # Check if a measurement is already in progress
            if self._measurement_in_progress:
                logger.warning("ECG measurement already in progress")
                return {
                    "status": "error",
                    "message": "ECG measurement already in progress",
                    "sessionId": self._current_session_id
                }

            # Create a trigger event
            trigger_event = SensorTriggerEvent(
                sensor_id=self._sensor_id,
                trigger_source="cloud",
                request_id=payload.get("requestId", str(int(time.time()))),
                user_id=payload.get("userId")
            )

            # Publish to trigger stream
            self._event_bus.publish(self._trigger_stream, trigger_event)

            logger.info(f"Triggered ECG measurement for {self._sensor_id}")

            return {
                "status": "success",
                "message": "Measurement triggered successfully",
                "requestId": trigger_event.request_id,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }

        except Exception as e:
            logger.error(f"Error handling trigger measurement method: {e}")
            return {
                "status": "error",
                "message": f"Internal error: {str(e)}"
            }