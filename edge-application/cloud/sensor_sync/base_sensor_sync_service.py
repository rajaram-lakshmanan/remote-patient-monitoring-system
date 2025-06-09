#!/usr/bin/env python3
# -----------------------------------------------------------------------------
# Filename: base_sensor_sync_service.py
# Author: Rajaram Lakshmanan
# Description: Abstract base class for all sensor sync services.
# License: MIT (see LICENSE)
# -----------------------------------------------------------------------------

import logging
import threading
import time
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
from datetime import datetime, timezone
from pathlib import Path

from cloud.azure_iot_hub.azure_iot_hub_client import AzureIoTHubClient
from config.models.cloud.azure_iot_hub_config import AzureIoTHubConfig
from config.models.cloud.cloud_sensor_sync_config import SensorSyncServiceConfig
from event_bus.models.sensor.sensor_data_event import SensorDataEvent
from event_bus.models.sensor.sensor_metadata_event import SensorMetadataEvent
from event_bus.models.sensor.sensor_state_event import SensorStateEvent
from event_bus.redis_stream_bus.redis_stream_bus import RedisStreamBus
from event_bus.stream_name import StreamName

logger = logging.getLogger("BaseSensorSyncService")

class BaseSensorSyncService(ABC):
    """
    Abstract base class for all sensor sync services.

    Handles IoT Hub communication, event subscriptions, and data synchronization.
    Provides template methods for common functionality while allowing
    specialized services to override sensor-specific processing.
    """

    def __init__(self,
                 event_bus: RedisStreamBus,
                 sensor_sync_service_config: SensorSyncServiceConfig,
                 azure_iot_hub_config: AzureIoTHubConfig):
        """
        Initialize the base sensor sync service.

        Args:
            event_bus: Redis event bus for subscribing to events
            sensor_sync_service_config: Configuration for the sensor sync service
            azure_iot_hub_config: Azure IoT Hub configuration
        """
        self._event_bus = event_bus
        self._sensor_id = sensor_sync_service_config.sensor_id
        self._sync_interval = sensor_sync_service_config.sync_options.sync_interval
        self._batch_enabled = sensor_sync_service_config.sync_options.batch_enabled
        self._batch_size = sensor_sync_service_config.sync_options.batch_size
        self.maintenance_interval = sensor_sync_service_config.sync_options.maintenance_interval

        self._azure_iot_hub_config = azure_iot_hub_config

        self._client_info = {}

        # Runtime state
        self._running = False
        self._iot_client = None
        self._stop_event = threading.Event()
        self._maintenance_thread = None
        self._sensor_metadata = None
        self._sensor_status = {
            "isActive": False,
            "inactiveMinutes": 0,
            "lastStatusChange": datetime.now(timezone.utc).isoformat()
        }

        # Batching configuration and state
        self._batch_buffer = []
        self._last_sync_time = time.time()

        # Add thread synchronization for the latest data
        self._latest_data_lock = threading.Lock()
        self._latest_data = None
        self._latest_properties = None

        self._metadata_stream = StreamName.SENSOR_METADATA_CREATED.value
        self._data_stream = StreamName.get_sensor_stream_name(StreamName.SENSOR_DATA_PREFIX.value,
                                                              self._sensor_id)
        self._status_stream = StreamName.get_sensor_stream_name(StreamName.SENSOR_STATUS_PREFIX.value,
                                                                self._sensor_id)

        logger.info(f"BaseSensorSyncService initialized for {self._sensor_id}")
        if self._batch_enabled:
            logger.info(f"Batching enabled with size={self._batch_size}, interval={self._sync_interval}s")

    @property
    def get_sensor_id(self) -> str:
        """
        Get the sensor ID.

        Returns:
            str: The sensor ID
        """
        return self._sensor_id

    def start(self) -> bool:
        """
        Start the sensor sync service.

        Returns:
            bool: True if started successfully, False otherwise
        """
        if self._running:
            logger.warning(f"Sync service for {self._sensor_id} is already running")
            return True

        try:
            # Initialize the IoT Hub client
            if not self._initialize_iot_client():
                logger.debug(f"Failed to initialize IoT Hub client for {self._sensor_id}")
                return False

            # Start the maintenance thread for connectivity checks and batch sending
            self._maintenance_thread = threading.Thread(target=self._maintenance_loop,
                                                        daemon=True)
            self._maintenance_thread.start()

            self._running = True
            logger.info(f"Sync service started for {self._sensor_id}")
            return True

        except Exception as e:
            logger.error(f"Error starting sync service for {self._sensor_id}: {e}", exc_info=True)
            self._cleanup()
            return False

    def stop(self) -> bool:
        """
        Stop the sensor sync service.

        Returns:
            bool: True if stopped successfully, False otherwise
        """
        if not self._running:
            logger.warning(f"Sync service for {self._sensor_id} is not running")
            return True

        try:
            logger.info(f"Stopping sync service for {self._sensor_id}")

            # Signal the maintenance thread to stop
            self._stop_event.set()

            # Wait for the maintenance thread to finish
            if self._maintenance_thread and self._maintenance_thread.is_alive():
                self._maintenance_thread.join(timeout=5.0)

            # Send any remaining batched data
            if self._batch_enabled and self._batch_buffer:
                self._send_batch_to_iot_hub()

            self._cleanup()

            self._running = False
            logger.info(f"Sync service stopped for {self._sensor_id}")
            return True

        except Exception as e:
            logger.error(f"Error stopping sync service for {self._sensor_id}: {e}", exc_info=True)
            self._running = False
            return False

    def update_client_status(self, status: str, additional_info: Optional[Dict[str, Any]] = None) -> None:
        """
        Update client status information when client events occur.

        Args:
            status: New status of the client (e.g., "connected", "disconnected")
            additional_info: Optional additional information about the client
        """
        logger.info(f"Updating client status for the sensor: {self._sensor_id}")
        if self._client_info is None:
            self._client_info = {}

        self._client_info["connection_status"] = status

        if additional_info:
            self._client_info.update(additional_info)

        # Report the updated client relationship to IoT Hub
        self._report_client_relationship()

        # If the status is changed to disconnected, report the sensor as inactive
        if status == "disconnected" and self._iot_client and self._iot_client.is_connected():
            self._sensor_status["isActive"] = False
            self._sensor_status["lastStatusChange"] = datetime.now(timezone.utc).isoformat()
            self._report_sensor_status()

    def send_message_to_iot_hub(self, data: Dict[str, Any], properties: Dict[str, str]) -> bool:
        """
        Send a message to IoT Hub with the provided data and properties.

        This is a helper method for derived classes to send messages.

        Args:
            data: The data to send
            properties: Message properties for routing

        Returns:
            bool: True if sent successfully, False otherwise
        """
        if not self._iot_client or not self._iot_client.is_connected():
            logger.warning(f"IoT client not connected, can't send message for {self._sensor_id}")
            return False

        try:
            # Send the message
            result = self._iot_client.send_message(data, properties)
            if result:
                logger.debug(f"Message sent to IoT Hub for {self._sensor_id}")
            else:
                logger.warning(f"Failed to send message to IoT Hub for {self._sensor_id}")
            return result
        except Exception as e:
            logger.error(f"Error sending message to IoT Hub: {e}")
            return False

    def subscribe_to_events(self, consumer_group_name: str) -> None:
        """Subscribe to relevant events for this sensor."""
        # Subscribe to sensor metadata events (global stream)
        self._event_bus.subscribe(self._metadata_stream,
                                  consumer_group_name,
                                  lambda event: self._handle_sensor_metadata_event(event))

        # Subscribe to sensor data events (sensor-specific stream)
        self._event_bus.subscribe(self._data_stream,
                                  consumer_group_name,
                                  lambda event: self._handle_sensor_data_event(event))

        # Subscribe to sensor status events (sensor-specific stream)
        self._event_bus.subscribe(self._status_stream,
                                  consumer_group_name,
                                  lambda event: self._handle_sensor_status_event(event))

        logger.info(f"Subscribed to events for {self._sensor_id}")

    def _initialize_iot_client(self) -> bool:
        """
        Initialize the Azure IoT Hub client.

        Returns:
            bool: True if initialized successfully, False otherwise
        """
        try:
            # Create the IoT Hub client
            cert_file = self._get_certificate_file_path()
            key_file = self._get_key_file_path()

            # Check if certificate and key files exist
            if not Path(cert_file).exists() or not Path(key_file).exists():
                logger.error(f"Certificate or key file not found for {self._sensor_id}")
                return False

            # Create the IoT Hub client
            self._iot_client = AzureIoTHubClient(
                host_name=self._azure_iot_hub_config.host_name,
                device_id=self._sensor_id,
                x509_cert_file=cert_file,
                x509_key_file=key_file,
                connection_timeout=self._azure_iot_hub_config.connection_timeout,
                retry_count=self._azure_iot_hub_config.retry_count
            )

            # Connect to IoT Hub
            if not self._iot_client.start():
                logger.error(f"Failed to connect to IoT Hub for {self._sensor_id}")
                return False

            logger.info(f"Connected to IoT Hub for {self._sensor_id}")
            return True

        except Exception as e:
            logger.error(f"Error initializing IoT Hub client for {self._sensor_id}: {e}", exc_info=True)
            return False

    def _cleanup(self) -> None:
        """Clean up resources used by the sync service."""
        if self._iot_client:
            try:
                self._iot_client.stop()
                logger.info(f"IoT Hub client for {self._sensor_id} stopped")
            except Exception as e:
                logger.error(f"Error stopping IoT Hub client for {self._sensor_id}: {e}")

            self._iot_client = None

    def _maintenance_loop(self) -> None:
        """
        Maintenance loop for checking connectivity and sending batched data.
        This runs in a separate thread.
        """
        # Get the maintenance interval - use a shorter interval for both the checking
        check_interval = min(self.maintenance_interval, int(self._sync_interval / 2))

        # Ensure the check interval is at least 1 second but not more than 30 seconds
        check_interval = max(1, min(check_interval, 30))

        while not self._stop_event.is_set():
            try:
                # Check IoT Hub connectivity
                if self._iot_client and not self._iot_client.is_connected():
                    logger.warning(f"IoT Hub client for {self._sensor_id} is disconnected, reconnecting...")
                    self._iot_client.start()

                # Timer-based sending - only applicable when batching is disabled and sync interval > 0
                if not self._batch_enabled and self._sync_interval > 0:
                    current_time = time.time()
                    time_since_last = current_time - self._last_sync_time

                    # If the sync interval has elapsed, check if we have data to send
                    if time_since_last >= self._sync_interval:
                        # Thread-safe access to the latest data
                        data_to_send = None
                        properties_to_send = None

                        with self._latest_data_lock:
                            if self._latest_data is not None:
                                data_to_send = self._latest_data
                                properties_to_send = self._latest_properties

                        # Only send the message if we have data (checked outside the lock to minimize lock time)
                        if data_to_send is not None:
                            self.send_message_to_iot_hub(data_to_send, properties_to_send)
                            self._last_sync_time = current_time

                # Perform any additional maintenance tasks
                self._perform_maintenance()

            except Exception as e:
                logger.error(f"Error in maintenance loop for {self._sensor_id}: {e}")

            # Wait for the next check or until stop is signaled
            self._stop_event.wait(check_interval)

    def _perform_maintenance(self) -> None:
        """
        Perform periodic maintenance tasks.
        Override in subclasses to add sensor-specific maintenance.
        """
        # Base implementation does nothing
        pass

    def _handle_sensor_metadata_event(self, event: SensorMetadataEvent) -> None:
        """
        Handle sensor metadata events and report properties to IoT Hub.

        Args:
            event: The sensor metadata event
        """
        # Only process events for our specific sensor
        if event.sensor_id != self._sensor_id:
            return

        logger.info(f"Processing metadata event for {self._sensor_id}")

        try:
            # Store metadata for future reference
            self._sensor_metadata = event

            # Create standard device property structure
            device_properties = {
                "deviceInfo": {
                    "manufacturer": event.manufacturer,
                    "model": event.model,
                    "swVersion": event.firmware_version,
                    "hwVersion": event.hardware_version
                },
                "sensorInfo": {
                    "type": event.sensor_type,
                    "measurementUnits": event.measurement_units,
                    "description": event.description,
                    "location": event.location
                },
                "patientId": event.patient_id
            }

            # Add the client relationship if available
            if self._client_info:
                device_properties["clientRelationship"] = {
                    "clientId": self._client_info.get("client_id", "unknown"),
                    "clientType": self._client_info.get("client_type", "unknown"),
                    "connectionStatus": self._client_info.get("connection_status", "unknown")
                }

            # Allow derived classes to extend the properties
            self._extend_metadata_properties(device_properties, event)

            # Report to IoT Hub
            if self._iot_client and self._iot_client.is_connected():
                self._iot_client.send_device_properties(device_properties)
                logger.info(f"Reported metadata properties for {self._sensor_id}")
            else:
                logger.warning(f"IoT client not connected, can't report metadata for {self._sensor_id}")

        except Exception as e:
            logger.error(f"Error processing metadata event for {self._sensor_id}: {e}", exc_info=True)

    def _extend_metadata_properties(self, properties: Dict[str, Any], event: SensorMetadataEvent) -> None:
        """
        Extend metadata properties with sensor-specific fields.

        Override this method in derived classes to add sensor-specific properties.

        Args:
            properties: The properties dictionary to extend
            event: The original metadata event
        """
        # Base implementation does nothing
        pass

    def _handle_sensor_status_event(self, event: SensorStateEvent) -> None:
        """
        Handle sensor status events and report properties to IoT Hub.

        Args:
            event: The sensor status event
        """
        # Only process events for our specific sensor
        if event.sensor_id != self._sensor_id:
            return

        logger.info(f"Processing status event for {self._sensor_id}: active={event.is_active}")

        try:
            # Update stored sensor status
            self._sensor_status = {
                "isActive": event.is_active,
                "inactiveMinutes": event.inactive_minutes if not event.is_active else 0,
                "lastStatusChange": datetime.now(timezone.utc).isoformat()
            }

            # Report to IoT Hub
            self._report_sensor_status()

        except Exception as e:
            logger.error(f"Error processing status event for {self._sensor_id}: {e}", exc_info=True)

    def _report_sensor_status(self) -> None:
        """Report the current sensor status to IoT Hub as device properties."""
        try:
            status_properties = {
                "sensorStatus": self._sensor_status
            }

            # Allow derived classes to extend the status properties
            self._extend_status_properties(status_properties)

            if self._iot_client and self._iot_client.is_connected():
                self._iot_client.send_device_properties(status_properties)
                logger.info(f"Reported status properties for {self._sensor_id}")
            else:
                logger.warning(f"IoT client not connected, can't report status for {self._sensor_id}")

        except Exception as e:
            logger.error(f"Error reporting sensor status: {e}", exc_info=True)

    def _extend_status_properties(self, properties: Dict[str, Any]) -> None:
        """
        Extend status properties with sensor-specific fields.

        Override this method in derived classes to add sensor-specific status properties.

        Args:
            properties: The property dictionary to extend
        """
        # Base implementation does nothing
        pass

    def _report_client_relationship(self) -> None:
        """Report client relationship to IoT Hub as device properties."""
        if not self._client_info:
            return

        try:
            client_properties = {
                "clientRelationship": {
                    "clientId": self._client_info.get("client_id", "unknown"),
                    "clientType": self._client_info.get("client_type", "unknown"),
                    "connectionStatus": self._client_info.get("connection_status", "unknown"),
                    "lastStatusChange": self._client_info.get("last_status_change",
                                                              datetime.now(timezone.utc).isoformat())
                }
            }

            if self._iot_client and self._iot_client.is_connected():
                self._iot_client.send_device_properties(client_properties)
                logger.info(f"Reported client relationship for {self._sensor_id}")
            else:
                logger.warning(f"IoT client not connected, can't report client relationship for {self._sensor_id}")

        except Exception as e:
            logger.error(f"Error reporting client relationship: {e}", exc_info=True)

    def _handle_sensor_data_event(self, event: SensorDataEvent) -> None:
        """
        Handle sensor data events and potentially send telemetry to IoT Hub.

        This method delegates to abstract methods for processing but implements
        the common batching logic.

        Args:
            event: The sensor data event
        """
        # Only process events for our specific sensor
        if event.sensor_id != self._sensor_id:
            return

        try:
            # Process the data (responsibility of the actual sensor service)
            processed_data = self._process_sensor_data(event)
            if processed_data is None:
                return

            # Create message properties (uses another abstract method)
            message_properties = self._get_message_properties(event)

            # Add common properties
            self._add_common_properties(message_properties)

            # Decision tree for sending mechanisms
            # Batch is the highest precedence
            if self._batch_enabled:
                # Batch Mode: Add to batch and check threshold
                self._add_to_batch(processed_data)

                # Check if the batch size threshold is reached
                if len(self._batch_buffer) >= self._batch_size:
                    self._send_batch_to_iot_hub()

            elif self._sync_interval == 0:
                # Immediate Mode: Send right away
                self.send_message_to_iot_hub(processed_data, message_properties)
            else:
                # Timer Mode: Store latest for later sending (thread-safe)
                with self._latest_data_lock:
                    self._latest_data = processed_data
                    self._latest_properties = message_properties

        except Exception as e:
            logger.error(f"Error handling sensor data event: {e}", exc_info=True)

    @abstractmethod
    def _process_sensor_data(self, event: SensorDataEvent) -> Optional[Dict[str, Any]]:
        """
        Process sensor data from the event.

        This method must be implemented by derived classes to provide
        sensor-specific data processing.

        Args:
            event: The sensor data event

        Returns:
            Optional[Dict[str, Any]]: The processed data, or None to skip this event
        """
        pass

    @abstractmethod
    def _get_message_properties(self, event: SensorDataEvent) -> Dict[str, str]:
        """
        Get message properties for routing.

        This method must be implemented by derived classes to provide
        sensor-specific message properties.

        Args:
            event: The sensor data event

        Returns:
            Dict[str, str]: Message properties for routing
        """
        pass

    def _add_common_properties(self, properties: Dict[str, str]) -> None:
        """
        Add common properties to message properties.

        Args:
            properties: The property dictionary to extend
        """
        common_props = {
            "sensorId": self._sensor_id,
            "messageTimestamp": datetime.now(timezone.utc).isoformat()
        }

        # Add client info if available
        if self._client_info:
            common_props["clientId"] = self._client_info.get("client_id", "unknown")
            common_props["clientType"] = self._client_info.get("client_type", "unknown")

        # Merge with provided properties (without overwriting)
        for key, value in common_props.items():
            if key not in properties:
                properties[key] = value

    def _add_to_batch(self, data: Dict[str, Any]) -> None:
        """
        Add data to the batch buffer.

        Args:
            data: The data to add to the batch
        """
        self._batch_buffer.append(data)
        logger.debug(f"Added data to batch buffer, size now: {len(self._batch_buffer)}")

    def _get_batch_type(self) -> str:
        """
        Get the batch type string for message properties.

        This method can be overridden by derived classes to provide
        sensor-specific batch types.

        Returns:
            str: The batch type string
        """
        return "sensorDataBatch"

    def _send_batch_to_iot_hub(self) -> bool:
        """
        Send the current batch to IoT Hub.

        Returns:
            bool: True if sent successfully, False otherwise
        """
        if not self._batch_buffer:
            return True  # Nothing to send

        try:
            # Get the first data item to extract type information
            first_item = self._batch_buffer[0] if self._batch_buffer else {}

            # Create the batch envelope
            batch_data = {
                "sensorId": self._sensor_id,
                "count": len(self._batch_buffer),
                "startTime": first_item.get("timestamp", 0),
                "endTime": self._batch_buffer[-1].get("timestamp", 0) if self._batch_buffer else 0,
                "readings": self._batch_buffer,
                "batchTimestamp": int(time.time() * 1000)
            }

            # Add the sensor type if available in the first item
            if "sensorType" in first_item:
                batch_data["sensorType"] = first_item["sensorType"]

            # Create message properties
            batch_properties = {
                "type": self._get_batch_type(),
                "sensorId": self._sensor_id,
                "count": str(len(self._batch_buffer))
            }

            # Add common properties
            self._add_common_properties(batch_properties)

            # Send the batch
            result = self.send_message_to_iot_hub(batch_data, batch_properties)

            if result:
                logger.info(f"Sent batch with {len(self._batch_buffer)} readings to IoT Hub")
                self._batch_buffer = []  # Clear the buffer on success
                self._last_sync_time = time.time()  # Reset the timer
            else:
                logger.warning(f"Failed to send batch to IoT Hub, will retry later")

            return result

        except Exception as e:
            logger.error(f"Error sending batch to IoT Hub: {e}", exc_info=True)
            return False

    def _get_certificate_file_path(self) -> str:
        """
        Get the path to the certificate file for this sensor.

        Returns:
            str: Path to the certificate file
        """
        cert_file = Path(self._azure_iot_hub_config.certificate_folder) / f"{self._sensor_id}.pem"
        return str(cert_file)

    def _get_key_file_path(self) -> str:
        """
        Get the path to the key file for this sensor.

        Returns:
            str: Path to the key file
        """
        key_file = Path(self._azure_iot_hub_config.certificate_folder) / f"{self._sensor_id}.key"
        return str(key_file)