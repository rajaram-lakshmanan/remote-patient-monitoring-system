#!/usr/bin/env python3
# -----------------------------------------------------------------------------
# Filename: base_sensor_handler.py
# Author: Rajaram Lakshmanan
# Description:  Base class for all sensor handlers.
# License: MIT (see LICENSE)
# -----------------------------------------------------------------------------

import logging
from abc import ABC, abstractmethod
from datetime import datetime, timezone, timedelta
from typing import Dict, Any

from client.common.base_client import BaseClient
from client.common.sensor_metadata import SensorMetadata
from event_bus.models.sensor.sensor_data_event import SensorDataEvent
from event_bus.models.sensor.sensor_metadata_event import SensorMetadataEvent
from event_bus.models.sensor.sensor_state_event import SensorStateEvent
from event_bus.redis_stream_bus.redis_stream_bus import RedisStreamBus
from event_bus.stream_name import StreamName

logger = logging.getLogger("BaseSensorHandler")

class BaseSensorHandler(ABC):
    """
    Base class for all sensor handlers.
    
    This abstract class defines the interface for all sensor handlers.
    Concrete implementations must provide sensor-specific logic.
    """
    
    def __init__(self,
                 event_bus: RedisStreamBus,
                 client: BaseClient,
                 is_enabled: bool,
                 sensor_id: str,
                 sensor_name: str,
                 sensor_type: str,
                 patient_id: str,
                 location: str):
        """
        Initialize the base sensor handler.
        
        Args:
            client: Client to which the sensor handler belongs.
            event_bus (RedisStreamBus): The event bus for publishing events.
            is_enabled (bool): Flag indicating whether the sensor is enabled or not.
            sensor_id (str): ID of the sensor, this ID shall be unique in the application.
            Follows the format: <interfaceType_shortenedClientId_sensorType> e.g., ble_c1_heart_rate.
            sensor_name (str): Name of the sensor, this does not need to be unique.
            sensor_type (str): Type of the sensor, this is used to determine the sensor-specific logic.
            patient_id (str): ID of the patient associated (wearing or using) with the sensors.
            location (str): Location or placement of the sensors.
        """
        # Store the event bus for publishing sensor time_series
        self._event_bus = event_bus
        self._client = client

        self._sensor_id = sensor_id
        self._is_enabled = is_enabled
        self._sensor_name = sensor_name
        self._sensor_type = sensor_type
        self._patient_id = patient_id
        self._location = location

        # Initialize inactivity tracking
        self._last_data_timestamp = datetime.now(timezone.utc)
        # Sensor is marked inactive if it's not enabled
        self._inactive = not self._is_enabled
        self._inactivity_threshold = timedelta(minutes=1)  # Default 1-minute threshold
        self._last_inactive_check = datetime.now(timezone.utc)
        self._check_interval = timedelta(seconds=5)  # Check every 5 seconds

        # Register for sensor-specific streams:
        # Sensor status stream
        self._event_bus.register_stream(self.sensor_status_stream_name, SensorStateEvent)

        # Sensor time_series stream
        self._event_bus.register_stream(self.sensor_data_stream_name, SensorDataEvent)

    @property
    @abstractmethod
    def sensor_metadata(self) -> SensorMetadata:
        """Return metadata for this sensor."""
        # Default implementation - should be overridden by subclasses
        pass
    
    @abstractmethod
    def get_data(self) -> Dict[str, Any]:
        """Return current sensor time_series as a dictionary."""
        pass

    @property
    def client(self):
        """Return the client to which the sensor handler belongs."""
        return self._client

    @property
    def is_enabled(self):
        """Return the flag to indicate whether the sensor is enabled or not."""
        return self._is_enabled

    @property
    def sensor_status_stream_name(self):
        """Return the Redis stream name for sensor status updates."""
        return StreamName.get_sensor_stream_name(StreamName.SENSOR_STATUS_PREFIX.value,
                                                 self._sensor_id)

    @property
    def sensor_data_stream_name(self):
        """Return the Redis stream name for sensor time_series updates."""
        return StreamName.get_sensor_stream_name(StreamName.SENSOR_DATA_PREFIX.value,
                                                 self._sensor_id)

    @property
    def sensor_trigger_stream_name(self):
        """Return the Redis stream name for sensor trigger."""
        # For applicable sensors, trigger will be implemented
        return StreamName.get_sensor_stream_name(StreamName.SENSOR_TRIGGER_PREFIX.value,
                                                 self._sensor_id)

    def check_activity_status(self) -> None:
        """
        Check sensor activity status and publish event if inactive.
        Should be called periodically by the main application loop.
        """
        logger.debug(f"Checking activity status for sensor {self._sensor_id}. Current Inactive State: {self._inactive}")
        current_time = datetime.now(timezone.utc)

        # Only check periodically to avoid too frequent checks
        if current_time - self._last_inactive_check < self._check_interval:
            return

        self._last_inactive_check = current_time
        time_since_last_data = current_time - self._last_data_timestamp

        # Check if the status changed from active to inactive
        if not self._inactive and time_since_last_data > self._inactivity_threshold:
            logger.debug(f"Inactivity threshold elapsed for sensor {self._sensor_id}")
            self._inactive = True
            self._publish_sensor_status(time_since_last_data)

    def subscribe_to_events(self) -> None:
        """Subscribe to the events required by the sensor handler."""
        # Will be implemented in the supported sensors
        pass

    def _set_inactivity_threshold(self, minutes: int) -> None:
        """
        Set the inactivity threshold for the sensor.

        Args:
            minutes (int): Number of minutes after which the sensor is considered inactive.
        """
        self._inactivity_threshold = timedelta(minutes=minutes)
        logger.info(f"Set inactivity threshold to {minutes} minutes for sensor {self._sensor_id}")

    def _publish_sensor_metadata(self) -> None:
        """Publish sensor metadata to the event bus."""
        if not self._event_bus:
            return

        try:
            # Create a metadata event for Redis
            metadata = self.sensor_metadata
            metadata_event = SensorMetadataEvent(
                sensor_id = self._sensor_id,
                is_enabled = self._is_enabled,
                patient_id = self._patient_id,
                sensor_name = self._sensor_name,
                sensor_type = self._sensor_type,
                manufacturer = metadata.manufacturer,
                model = metadata.model,
                firmware_version = metadata.firmware_version,
                hardware_version = metadata.hardware_version,
                description = metadata.description,
                measurement_units = metadata.measurement_units,
                location = metadata.location
            )

            # Publish to Redis Stream
            if not self._event_bus.shutdown_active:
                self._event_bus.publish(StreamName.SENSOR_METADATA_CREATED.value, metadata_event)
        except Exception as e:
            logger.error(f"Error publishing sensor metadata to Redis Stream: {e}")

    def _publish_sensor_data(self, data: Dict[str, Any]) -> None:
        """
        Publish sensor time_series to the event bus.

        Args:
            data (dict): The sensor time_series to publish.
        """
        if not self._event_bus:
            return

        try:
            event = SensorDataEvent(
                sensor_id=self._sensor_id,
                patient_id=self._patient_id,
                sensor_name=self._sensor_name,
                sensor_type=self._sensor_type,
                data=data
            )

            # Publish to Redis Stream
            if not self._event_bus.shutdown_active:
                self._event_bus.publish(self.sensor_data_stream_name, event, 10000, True)
        except Exception as e:
            logger.error(f"Error publishing sensor time_series to Redis Stream: {e}")

    def _publish_sensor_status(self, inactive_duration: timedelta) -> None:
        """
        Publish inactivity event to the event bus.

        Args:
            inactive_duration (timedelta): Duration for which the sensor has been inactive.
        """
        try:
            inactive_minutes = inactive_duration.total_seconds() / 60
            event = SensorStateEvent(
                sensor_id=self._sensor_id,
                sensor_name=self._sensor_name,
                sensor_type=self._sensor_type,
                is_active = not self._inactive,
                inactive_minutes = inactive_minutes
            )

            # Publish to Redis Stream
            if not self._event_bus.shutdown_active:
                self._event_bus.publish(self.sensor_status_stream_name, event)
        except Exception as e:
            logger.error(f"Error publishing sensor status to Redis Stream: {e}")