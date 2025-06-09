#!/usr/bin/env python3
# -----------------------------------------------------------------------------
# Filename: click_board_oximeter_sync_service.py
# Author: Rajaram Lakshmanan
# Description: Sync service for ClickBoard Oximeter 5 sensors
# License: MIT (see LICENSE)
# -----------------------------------------------------------------------------

import logging
from typing import Dict, Any, Optional

from config.models.cloud.azure_iot_hub_config import AzureIoTHubConfig
from config.models.cloud.cloud_sensor_sync_config import SensorSyncServiceConfig
from event_bus.models.sensor.sensor_data_event import SensorDataEvent
from cloud.sensor_sync.base_sensor_sync_service import BaseSensorSyncService
from event_bus.redis_stream_bus.redis_stream_bus import RedisStreamBus

logger = logging.getLogger("ClickBoardOximeterSyncService")


class ClickBoardOximeterSyncService(BaseSensorSyncService):
    """
    Sync service for Click Board Oximeter 5 sensors.
    Handles heart rate and SpO2 measurements from the MAX30102 sensor.
    """

    DEFAULT_LOCATION = "finger"

    def __init__(self,
                 event_bus: RedisStreamBus,
                 sensor_sync_service_config: SensorSyncServiceConfig,
                 azure_iot_hub_config: AzureIoTHubConfig):
        """
        Initialize the Clickboard Oximeter sensor sync service.

        Args:
            event_bus: Redis event bus for subscribing to events
            sensor_sync_service_config: Configuration for the sensor sync service
            azure_iot_hub_config: Azure IoT Hub configuration
        """
        super().__init__(event_bus, sensor_sync_service_config, azure_iot_hub_config)

        # Oximeter-specific attributes
        sync_options = sensor_sync_service_config.sync_options
        self._hr_alert_high = sync_options.get_custom_param('alert_thresholds',
                                                            {}).get('heart_rate_high', 150)
        self._hr_alert_low = sync_options.get_custom_param('alert_thresholds',
                                                           {}).get('heart_rate_low', 40)
        self._spo2_alert_low = sync_options.get_custom_param('alert_thresholds',
                                                             {}).get('spo2_low', 94.0)
        self._spo2_alert_critical = sync_options.get_custom_param('alert_thresholds',
                                                                  {}).get('spo2_critical', 90.0)
        self._location = sync_options.get_custom_param('location',
                                                       ClickBoardOximeterSyncService.DEFAULT_LOCATION)

        logger.info(f"Oximeter sync service initialized for {self._sensor_id}")

    def _process_sensor_data(self, event: SensorDataEvent) -> Optional[Dict[str, Any]]:
        """
        Process oximeter data.

        Args:
            event: The sensor data event

        Returns:
            Dict[str, Any]: The processed data
        """
        # Extract data from the event
        timestamp = event.data.get('timestamp', 0)
        values = event.data.get('values', {})

        # Get heart rate and SpO2 values
        heart_rate = values.get('Heart Rate', 0.0)
        spo2 = values.get('SpO2', 0.0)

        # Skip processing if both values are zero
        if heart_rate <= 0 and spo2 <= 0:
            logger.warning("Both heart rate and SpO2 are zero or negative, skipping")
            return None

        # Check for alerts
        alerts = []

        # Check heart rate thresholds
        if heart_rate > 0:  # Only check if the heart rate is valid
            if heart_rate > self._hr_alert_high:
                alerts.append("HighHeartRate")
            elif heart_rate < self._hr_alert_low:
                alerts.append("LowHeartRate")

        # Check SpO2 thresholds
        if spo2 > 0:  # Only check if SpO2 is valid
            if spo2 < self._spo2_alert_critical:
                alerts.append("CriticalLowSpo2")
            elif spo2 < self._spo2_alert_low:
                alerts.append("LowSpo2")

        # Calculate health status based on SpO2 value
        health_status = None
        if spo2 > 0:  # Only calculate if SpO2 is valid
            if spo2 >= 95:
                health_status = "Normal"
            elif spo2 >= 90:
                health_status = "Mild Hypoxemia"
            else:
                health_status = "Severe Hypoxemia"

        # Calculate heart rate zone
        hr_zone = None
        if heart_rate > 0:  # Only calculate if heart rate is valid
            hr_zone = self._calculate_heart_rate_zone(heart_rate)

        # Build the processed data structure
        processed_data = {
            "timestamp": timestamp,
            "heartRate": heart_rate if heart_rate > 0 else None,
            "spo2": spo2 if spo2 > 0 else None,
            "heartRateZone": hr_zone,
            "healthStatus": health_status,
            "alerts": alerts if alerts else None,
            "deviceType": "ClickBoard",
            "location": self._location
        }

        return processed_data

    def _get_message_properties(self, event: SensorDataEvent) -> Dict[str, str]:
        """
        Get message properties for oximeter data.

        Args:
            event: The sensor data event

        Returns:
            Dict[str, str]: Message properties for routing
        """
        properties = {
            "type": "oximeterData",
            "deviceType": "ClickBoard",
            "sensorId": self._sensor_id,
            "location": self._location
        }

        # Extract values to check for alerts
        values = event.data.get('values', {})
        heart_rate = values.get('Heart Rate', 0.0)
        spo2 = values.get('SpO2', 0.0)

        # Check for alerts to add as properties
        alerts = []

        if heart_rate > 0:
            if heart_rate > self._hr_alert_high:
                alerts.append("HighHeartRate")
            elif heart_rate < self._hr_alert_low:
                alerts.append("LowHeartRate")

        if spo2 > 0:
            if spo2 < self._spo2_alert_critical:
                alerts.append("CriticalLowSpo2")
            elif spo2 < self._spo2_alert_low:
                alerts.append("LowSpo2")

        if alerts:
            properties["hasAlerts"] = "true"
            properties["alertTypes"] = ",".join(alerts)

        return properties

    def _get_batch_type(self) -> str:
        """
        Get the batch type for oximeter data.

        Returns:
            str: The batch type
        """
        return "oximeterBatch"

    def _extend_metadata_properties(self, properties: Dict[str, Any], event: object) -> None:
        """
        Add oximeter-specific metadata properties.

        Args:
            properties: The properties dictionary to extend
            event: The original metadata event
        """
        # Add oximeter-specific monitoring thresholds
        properties["monitoringThresholds"] = {
            "heartRateHigh": self._hr_alert_high,
            "heartRateLow": self._hr_alert_low,
            "spo2Low": self._spo2_alert_low,
            "spo2Critical": self._spo2_alert_critical
        }
        properties["location"] = (
            properties.get("sensorInfo", {}).get("location", ClickBoardOximeterSyncService.DEFAULT_LOCATION)
            if self._location == ClickBoardOximeterSyncService.DEFAULT_LOCATION
            else self._location
        )

    @staticmethod
    def _calculate_heart_rate_zone(heart_rate: float) -> str:
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