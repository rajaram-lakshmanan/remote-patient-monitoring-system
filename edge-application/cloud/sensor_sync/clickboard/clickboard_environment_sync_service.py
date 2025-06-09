#!/usr/bin/env python3
# -----------------------------------------------------------------------------
# Filename: click_board_environment_sync_service.py
# Author: Rajaram Lakshmanan
# Description: Sync service for ClickBoard environment sensors
# License: MIT (see LICENSE)
# -----------------------------------------------------------------------------

import logging
import math
from typing import Dict, Any, Optional

from config.models.cloud.azure_iot_hub_config import AzureIoTHubConfig
from config.models.cloud.cloud_sensor_sync_config import SensorSyncServiceConfig
from event_bus.models.sensor.sensor_data_event import SensorDataEvent
from cloud.sensor_sync.base_sensor_sync_service import BaseSensorSyncService
from event_bus.redis_stream_bus.redis_stream_bus import RedisStreamBus

logger = logging.getLogger("ClickBoardEnvironmentSyncService")

class ClickBoardEnvironmentSyncService(BaseSensorSyncService):
    """
    Sync service for Click Board environment sensors.
    Handles temperature, humidity, pressure, and VOC measurements.
    """

    DEFAULT_LOCATION = "unknown"

    def __init__(self,
                 event_bus: RedisStreamBus,
                 sensor_sync_service_config: SensorSyncServiceConfig,
                 azure_iot_hub_config: AzureIoTHubConfig):
        """
        Initialize the Clickboard Environment sensor sync service.

        Args:
            event_bus: Redis event bus for subscribing to events
            sensor_sync_service_config: Configuration for the sensor sync service
            azure_iot_hub_config: Azure IoT Hub configuration
        """
        super().__init__(event_bus, sensor_sync_service_config, azure_iot_hub_config)

        # Environment-specific attributes
        sync_options = sensor_sync_service_config.sync_options
        self._thresholds = sync_options.get_custom_param('alert_thresholds', {
            "temperature_high": 30.0,
            "temperature_low": 15.0,
            "humidity_high": 70.0,
            "humidity_low": 30.0,
            "pressure_high": 1050.0,
            "pressure_low": 970.0
        })
        self._location = sync_options.get_custom_param('location',
                                                       ClickBoardEnvironmentSyncService.DEFAULT_LOCATION)

        logger.info(f"Environment sync service initialized for {self._sensor_id}")

    def _process_sensor_data(self, event: SensorDataEvent) -> Optional[Dict[str, Any]]:
        """
        Process environment sensor data.

        Args:
            event: The sensor data event

        Returns:
            Dict[str, Any]: The processed data
        """
        # Extract data from the event
        timestamp = event.data.get('timestamp', 0)
        values = event.data.get('values', {})

        nan = float('nan')
        temperature = float(values.get('Environment Temperature', nan))
        humidity = float(values.get('Environment Humidity', nan))
        pressure = float(values.get('Environment Pressure', nan))
        gas_resistance = float(values.get('Environment Gas Resistance', nan))

        # Skip processing if all values are NaN
        if all(math.isnan(v) for v in (temperature, humidity, pressure, gas_resistance)):
            logger.warning("All environment values are NaN, skipping")
            return None

        # Check for alerts
        alerts = []

        # Check temperature thresholds
        if not math.isnan(temperature):
            if temperature > self._thresholds.get("temperature_high", 30.0):
                alerts.append("HighTemperature")
            elif temperature < self._thresholds.get("temperature_low", 15.0):
                alerts.append("LowTemperature")

        # Check humidity thresholds
        if not math.isnan(humidity):
            if humidity > self._thresholds.get("humidity_high", 70.0):
                alerts.append("HighHumidity")
            elif humidity < self._thresholds.get("humidity_low", 30.0):
                alerts.append("LowHumidity")

        # Check pressure thresholds
        if not math.isnan(pressure):
            if pressure > self._thresholds.get("pressure_high", 1050.0):
                alerts.append("HighPressure")
            elif pressure < self._thresholds.get("pressure_low", 970.0):
                alerts.append("LowPressure")

        # Calculate air quality index (simplified)
        air_quality = None
        air_quality_category = None

        if not math.isnan(gas_resistance):
            # Convert gas resistance to air quality index (simplified)
            # Higher resistance = better air quality
            if gas_resistance > 50000:
                air_quality = 1
                air_quality_category = "Excellent"
            elif gas_resistance > 30000:
                air_quality = 2
                air_quality_category = "Good"
            elif gas_resistance > 10000:
                air_quality = 3
                air_quality_category = "Moderate"
            else:
                air_quality = 4
                air_quality_category = "Poor"
                alerts.append("PoorAirQuality")

        # Build the processed data structure
        processed_data = {
            "timestamp": timestamp,
            "environment": {
                "temperature": None if math.isnan(temperature) else temperature,
                "humidity": None if math.isnan(humidity) else humidity,
                "pressure": None if math.isnan(pressure) else pressure,
                "gasResistance": None if math.isnan(gas_resistance) else gas_resistance,
                "airQualityIndex": air_quality,
                "airQualityCategory": air_quality_category
            },
            "alerts": alerts if alerts else None,
            "deviceType": "ClickBoard",
            "location": self._location
        }

        return processed_data

    def _get_message_properties(self, event: SensorDataEvent) -> Dict[str, str]:
        """
        Get message properties for environment data.

        Args:
            event: The sensor data event

        Returns:
            Dict[str, str]: Message properties for routing
        """
        properties = {
            "type": "environmentData",
            "deviceType": "ClickBoard",
            "sensorId": self._sensor_id,
            "location": self._location
        }

        # Extract values to check for alerts
        values = event.data.get('values', {})

        # Check for any alerts to add as properties
        alerts = []

        # Check temperature thresholds
        temperature = float(values.get('Environment Temperature', float('nan')))
        if not math.isnan(temperature):
            if temperature > self._thresholds.get("temperature_high", 30.0):
                alerts.append("HighTemperature")
            elif temperature < self._thresholds.get("temperature_low", 15.0):
                alerts.append("LowTemperature")

        # Check humidity thresholds
        humidity = float(values.get('Environment Humidity', float('nan')))
        if not math.isnan(humidity):
            if humidity > self._thresholds.get("humidity_high", 70.0):
                alerts.append("HighHumidity")
            elif humidity < self._thresholds.get("humidity_low", 30.0):
                alerts.append("LowHumidity")

        # Check for air quality alert
        gas_resistance = float(values.get('Environment Gas Resistance', float('nan')))
        if not math.isnan(gas_resistance) and gas_resistance <= 10000:
            alerts.append("PoorAirQuality")

        if alerts:
            properties["hasAlerts"] = "true"
            properties["alertTypes"] = ",".join(alerts)

        return properties

    def _get_batch_type(self) -> str:
        """
        Get the batch type for environment data.

        Returns:
            str: The batch type
        """
        return "environmentBatch"

    def _extend_metadata_properties(self, properties: Dict[str, Any], event: object) -> None:
        """
        Add environment-specific metadata properties.

        Args:
            properties: The properties dictionary to extend
            event: The original metadata event
        """
        # Add environment-specific monitoring thresholds
        properties["monitoringThresholds"] = self._thresholds
        properties["location"] = (
            properties.get("sensorInfo", {}).get("location", ClickBoardEnvironmentSyncService.DEFAULT_LOCATION)
            if self._location == ClickBoardEnvironmentSyncService.DEFAULT_LOCATION
            else self._location
        )