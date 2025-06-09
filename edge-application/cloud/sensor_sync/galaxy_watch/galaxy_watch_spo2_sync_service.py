#!/usr/bin/env python3
# -----------------------------------------------------------------------------
# Filename: galaxy_watch_spo2_sync_service.py
# Author: Rajaram Lakshmanan
# Description: Specialized sync service for Galaxy Watch SpO2 sensors
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

logger = logging.getLogger("GalaxyWatchSpo2SyncService")


class GalaxyWatchSpo2SyncService(BaseSensorSyncService):
    """
    Specialized sync service for Galaxy Watch SPO2 sensors.
    Handles data processing, IoT Hub telemetry sending, and trigger handling.
    """

    def __init__(self,
                 event_bus: RedisStreamBus,
                 sensor_sync_service_config: SensorSyncServiceConfig,
                 azure_iot_hub_config: AzureIoTHubConfig):
        """
        Initialize the Galaxy watch Spo2 sensor sync service.

        Args:
            event_bus: Redis event bus for subscribing to events
            sensor_sync_service_config: Configuration for the sensor sync service
            azure_iot_hub_config: Azure IoT Hub configuration
        """
        super().__init__(event_bus, sensor_sync_service_config, azure_iot_hub_config)

        # SPO2 specific attributes
        self._last_measurement_time = 0

        # SPO2 specific thresholds (with defaults)
        sync_options = sensor_sync_service_config.sync_options
        self._alert_low = sync_options.get_custom_param('alert_thresholds', {}).get('low', 94.0)
        self._alert_critical = sync_options.get_custom_param('alert_thresholds', {}).get('critical', 90.0)

        # Measurement cooldown to prevent excessive triggering (default: 1 minute)
        self._measurement_cooldown = sync_options.get_custom_param('measurement_cooldown', 60)

        # Get the trigger stream name
        self._trigger_stream = StreamName.get_sensor_stream_name(StreamName.SENSOR_TRIGGER_PREFIX.value,
                                                                 self._sensor_id)

        logger.info(f"SpO2 sync service initialized for {self._sensor_id}")

    def _initialize_iot_client(self) -> bool:
        """Initialize IoT Hub client with method handlers"""
        if not super()._initialize_iot_client():
            return False

        try:
            # Register method handler for triggering SPO2 measurement
            self._iot_client.register_method_handler("triggerMeasurement", self._handle_trigger_measurement_method)
            logger.info(f"Registered C2D method handlers for {self._sensor_id}")
            return True

        except Exception as e:
            logger.error(f"Error registering method handlers for {self._sensor_id}: {e}", exc_info=True)
            return False

    def _process_sensor_data(self, event: SensorDataEvent) -> Optional[Dict[str, Any]]:
        """
        Process SPO2 data.

        Args:
            event: The sensor data event

        Returns:
            Dict[str, Any]: The processed data
        """
        # Extract data from the event
        timestamp = event.data.get('timestamp', 0)
        values = event.data.get('values', {})
        spo2_value = values.get('value', 0)
        status_code = values.get('status_code', 0)

        # Update last measurement time
        self._last_measurement_time = time.time()

        # Convert Galaxy Watch status codes to standardized format
        status_mapping = {
            -6: "Timeout",
            -5: "LowSignalQuality",
            -4: "MovementDuringMeasurement",
            0: "Calculating",
            2: "MeasurementComplete"
        }

        standardized_status = status_mapping.get(status_code, "Unknown")

        # Determine if the reading is valid
        is_valid = status_code == 2

        # Check alert thresholds
        alert = None
        if is_valid and spo2_value < self._alert_critical:
            alert = "CriticalLowSpo2"
        elif is_valid and spo2_value < self._alert_low:
            alert = "LowSpo2"

        # Calculate confidence based on status code
        confidence = 100 if status_code == 2 else 0
        if status_code == 0:  # Calculating
            confidence = 50
        elif status_code == -5:  # Low signal quality
            confidence = 30
        elif status_code == -4:  # Movement
            confidence = 20

        # Calculate health status based on SPO2 value
        if spo2_value >= 95:
            health_status = "Normal"
        elif spo2_value >= 90:
            health_status = "Mild Hypoxemia"
        else:
            health_status = "Severe Hypoxemia"

        # Build the processed data structure
        processed_data = {
            "timestamp": timestamp,
            "spo2": spo2_value,
            "status": standardized_status,
            "rawStatusCode": status_code,
            "isValid": is_valid,
            "alert": alert,
            "confidence": confidence,
            "healthStatus": health_status,
            "deviceType": "GalaxyWatch"
        }

        return processed_data

    def _get_message_properties(self, event: SensorDataEvent) -> Dict[str, str]:
        """
        Get message properties for SPO2 data.

        Args:
            event: The sensor data event

        Returns:
            Dict[str, str]: Message properties for routing
        """
        properties = {
            "type": "spo2Data",
            "deviceType": "GalaxyWatch",
            "sensorId": self._sensor_id
        }

        # Check if this contains an alert and add it to properties
        values = event.data.get('values', {})
        spo2_value = values.get('value', 0)
        status_code = values.get('status_code', 0)
        is_valid = status_code == 2

        if is_valid and spo2_value < self._alert_critical:
            properties["alert"] = "CriticalLowSpo2"
        elif is_valid and spo2_value < self._alert_low:
            properties["alert"] = "LowSpo2"

        return properties

    def _get_batch_type(self) -> str:
        """
        Get the batch type for SPO2 data.

        Returns:
            str: The batch type
        """
        return "spo2Batch"

    def _extend_metadata_properties(self, properties: Dict[str, Any], event: object) -> None:
        """
        Add SPO2 specific metadata properties.

        Args:
            properties: The properties dictionary to extend
            event: The original metadata event
        """
        # Add SPO2 specific properties
        properties["sensorInfo"]["isOnDemand"] = True
        properties["monitoringThresholds"] = {
            "spo2Low": self._alert_low,
            "spo2Critical": self._alert_critical
        }

    def _handle_trigger_measurement_method(self, method_name: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Handle the triggerMeasurement direct method call from IoT Hub.

        Args:
            method_name: The name of the method (should be "triggerMeasurement")
            payload: Any method parameters

        Returns:
            Dict: Response to the method call
        """
        logger.info(f"Received {method_name} direct method call for {self._sensor_id}")

        try:
            # Check if we can trigger a measurement (cooldown period)
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

            # Create a trigger event
            trigger_event = SensorTriggerEvent(
                sensor_id=self._sensor_id,
                trigger_source="cloud",
                request_id=payload.get("requestId", str(int(time.time()))),
                user_id=payload.get("userId")
            )

            # Publish to trigger stream
            self._event_bus.publish(self._trigger_stream, trigger_event)

            logger.info(f"Triggered SPO2 measurement for {self._sensor_id}")

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