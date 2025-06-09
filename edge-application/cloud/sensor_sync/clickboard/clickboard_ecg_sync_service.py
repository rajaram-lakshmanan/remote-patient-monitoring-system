#!/usr/bin/env python3
# -----------------------------------------------------------------------------
# Filename: click_board_ecg_sync_service.py
# Author: Rajaram Lakshmanan
# Description: Sync service for ClickBoard ECG 7 sensors
# License: MIT (see LICENSE)
# -----------------------------------------------------------------------------

import logging
from typing import Dict, Any, Optional

from config.models.cloud.azure_iot_hub_config import AzureIoTHubConfig
from config.models.cloud.cloud_sensor_sync_config import SensorSyncServiceConfig
from event_bus.models.sensor.sensor_data_event import SensorDataEvent
from cloud.sensor_sync.base_sensor_sync_service import BaseSensorSyncService
from event_bus.redis_stream_bus.redis_stream_bus import RedisStreamBus

logger = logging.getLogger("ClickBoardEcgSyncService")

class ClickBoardEcgSyncService(BaseSensorSyncService):
    """
    Sync service for Click Board ECG 7 sensors.
    Handles high-frequency ECG data from the MCP6N16 sensor.
    """

    DEFAULT_LOCATION = "various (3 x electrodes)"

    def __init__(self,
                 event_bus: RedisStreamBus,
                 sensor_sync_service_config: SensorSyncServiceConfig,
                 azure_iot_hub_config: AzureIoTHubConfig):
        """
        Initialize the Clickboard ECG sensor sync service.

        Args:
            event_bus: Redis event bus for subscribing to events
            sensor_sync_service_config: Configuration for the sensor sync service
            azure_iot_hub_config: Azure IoT Hub configuration
        """
        super().__init__(event_bus, sensor_sync_service_config, azure_iot_hub_config)

        # ECG-specific attributes
        sync_options = sensor_sync_service_config.sync_options
        self._voltage_threshold_high = sync_options.get_custom_param("voltage_threshold_high", 2.0)  # mV
        self._voltage_threshold_low = sync_options.get_custom_param('voltage_threshold_low', -2.0)  # mV
        self._location = sync_options.get_custom_param('location', ClickBoardEcgSyncService.DEFAULT_LOCATION)
        self._data_reduction_factor = sync_options.get_custom_param('data_reduction_factor', 4)

        # Ensure batch size is appropriate for high-frequency ECG data
        if self._batch_size < 500:
            self._batch_size = 500

        logger.info(f"ECG sync service initialized for {self._sensor_id}")

    def _process_sensor_data(self, event: SensorDataEvent) -> Optional[Dict[str, Any]]:
        """
        Process ECG data.

        Args:
            event: The sensor data event

        Returns:
            Dict[str, Any]: The processed data
        """
        # Handle batch data differently from single points
        if 'batch' in event.data and event.data['batch']:
            return self._process_batch_data(event)

        # Extract data from the event (single point)
        timestamp = event.data.get('timestamp', 0)
        values = event.data.get('values', {})
        ecg_voltage = values.get('ECG', 0.0)

        # Detect signal characteristics
        is_above_threshold = ecg_voltage > self._voltage_threshold_high
        is_below_threshold = ecg_voltage < self._voltage_threshold_low
        possible_qrs = is_above_threshold or is_below_threshold

        # Build the processed data structure
        processed_data = {
            "timestamp": timestamp,
            "ecg": ecg_voltage,
            "signalProperties": {
                "aboveThreshold": is_above_threshold,
                "belowThreshold": is_below_threshold,
                "possibleQRS": possible_qrs
            },
            "deviceType": "ClickBoard",
            "location": self._location
        }

        return processed_data

    def _process_batch_data(self, event: SensorDataEvent) -> Optional[Dict[str, Any]]:
        """
        Process ECG batch data.

        Args:
            event: The sensor data event containing batch data

        Returns:
            Dict[str, Any]: The processed batch data
        """
        # ECG sends data in batches with multiple timestamps and values
        timestamps = event.data.get('timestamps', [])
        values_list = event.data.get('values_list', [])

        if not timestamps or not values_list or len(timestamps) != len(values_list):
            logger.warning("Invalid batch data format")
            return None

        # Process each reading and collect signal properties
        readings = []
        qrs_count = 0

        for i, ts in enumerate(timestamps):
            if i < len(values_list):
                ecg_voltage = values_list[i].get('ECG', 0.0)

                # Detect signal characteristics
                is_above_threshold = ecg_voltage > self._voltage_threshold_high
                is_below_threshold = ecg_voltage < self._voltage_threshold_low
                possible_qrs = is_above_threshold or is_below_threshold

                if possible_qrs:
                    qrs_count += 1

                readings.append({
                    "timestamp": ts,
                    "ecg": ecg_voltage,
                    "possibleQRS": possible_qrs
                })

        # Build the processed batch data structure
        processed_data = {
            "batchTimestamp": event.data.get('timestamp', 0),
            "readings": readings,
            "stats": {
                "count": len(readings),
                "qrsCount": qrs_count
            },
            "deviceType": "ClickBoard",
            "location": self._location
        }

        return processed_data

    def _get_message_properties(self, event: SensorDataEvent) -> Dict[str, str]:
        """
        Get message properties for ECG data.

        Args:
            event: The sensor data event

        Returns:
            Dict[str, str]: Message properties for routing
        """
        is_batch = 'batch' in event.data and event.data['batch']

        properties = {
            "type": "ecgData" if not is_batch else "ecgBatchData",
            "deviceType": "ClickBoard",
            "sensorId": self._sensor_id,
            "location": self._location
        }

        # For batch data, add batch-specific properties
        if is_batch:
            timestamps = event.data.get('timestamps', [])
            properties["count"] = str(len(timestamps))

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
        properties["sensorInfo"]["samplingRate"] = "250Hz"
        properties["monitoringThresholds"] = {
            "voltageThresholdHigh": self._voltage_threshold_high,
            "voltageThresholdLow": self._voltage_threshold_low
        }
        properties["location"] = (
            properties.get("sensorInfo", {}).get("location", ClickBoardEcgSyncService.DEFAULT_LOCATION)
            if self._location == ClickBoardEcgSyncService.DEFAULT_LOCATION
            else self._location
        )

    def _perform_maintenance(self) -> None:
        """
        Perform ECG-specific maintenance.

        For ECG data, we need to ensure we're not accumulating too much data due to the high sampling rate.
        """
        super()._perform_maintenance()

        # Check if our batch buffer is getting too large
        if len(self._batch_buffer) > self._batch_size * 2:
            logger.info(f"Batch buffer is very large ({len(self._batch_buffer)} items), applying data reduction")

            # Apply more aggressive data reduction for ECG data
            if self._data_reduction_factor > 1:
                self._batch_buffer = self._batch_buffer[::self._data_reduction_factor]
                logger.info(f"Reduced batch buffer to {len(self._batch_buffer)} items")