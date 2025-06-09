#!/usr/bin/env python3
# -----------------------------------------------------------------------------
# Filename: cloud_sync_manager.py
# Author: Rajaram Lakshmanan
# Description: Manage the synchronization services used to sync data with
# the cloud.
# License: MIT (see LICENSE)
# -----------------------------------------------------------------------------

import logging
import threading
from typing import Dict

from cloud.edge_gateway_sync.edge_gateway_sync_service import EdgeGatewaySyncService
from cloud.sensor_sync.base_sensor_sync_service import BaseSensorSyncService
from cloud.sensor_sync.sensor_sync_service_factory import SensorSyncServiceFactory
from config.models.cloud.cloud_sync_manager_config import CloudSyncManagerConfig
from config.models.health_monitoring_config import HealthMonitorConfig
from event_bus.models.client.ble_client_event import BleClientEvent
from event_bus.models.client.i2c_client_event import I2CClientEvent
from event_bus.redis_stream_bus.redis_stream_bus import RedisStreamBus
from event_bus.stream_name import StreamName

logger = logging.getLogger("CloudSyncManager")

class CloudSyncManager:
    """
    Manager for cloud synchronization services.

    Handles the creation and management of sync services; sensor and edge gateway.
    And, for each sensor, coordinates client events to update sensor services.
    """

    def __init__(self,
                 event_bus: RedisStreamBus,
                 config: CloudSyncManagerConfig,
                 health_monitor_config: HealthMonitorConfig):
        """
        Initialize the Cloud Sync Manager.

        Args:
            event_bus: Event bus for communication
            config: Cloud sync manager configuration
            health_monitor_config: Health Monitoring application configuration
        """
        self._event_bus = event_bus
        self._config: CloudSyncManagerConfig = config

        # Cloud sync manager requires application wide information such as clients and sensors configured
        self._health_monitor_config: HealthMonitorConfig = health_monitor_config

        # Track sync services with Sensor ID as the key
        self._sensor_sync_services: Dict[str, BaseSensorSyncService] = {}

        # Edge gateway will have its sync service to sync Telemetry, Inventory, and Security information
        self._edge_gateway_sync_service = None

        # Thread safety
        self._lock = threading.RLock()

        # Initialize services if cloud sync is enabled
        if self._config.is_enabled:
            self._initialize_services()

        logger.info("CloudSyncManager initialized")

    @property
    def redis_consumer_group_name(self) -> str:
        """Returns the name of the Consumer group in Redis Stream."""
        return "cloud_sync_manager_consumer"

    def start(self) -> bool:
        """
        Start all cloud synchronization services.

        Returns:
            bool: True if started successfully
        """
        if not self._config.is_enabled:
            logger.info("Cloud sync is disabled in configuration")
            return False

        try:
            success_count = 0
            error_count = 0

            # Start sensor sync services
            if self._config.cloud_sensor_sync.is_enabled:
                logger.info("Starting sensor sync services...")

                with self._lock:
                    services = list(self._sensor_sync_services.items())

                for sensor_id, service in services:
                    try:
                        if service.start():
                            success_count += 1
                            logger.info(f"Started sync service for {sensor_id}")
                        else:
                            error_count += 1
                            logger.error(f"Failed to start sync service for {sensor_id}")
                    except Exception as e:
                        error_count += 1
                        logger.error(f"Error starting sync service for {sensor_id}: {e}", exc_info=True)

            # Start the edge gateway sync
            if self._config.cloud_edge_gateway_sync.is_enabled and self._edge_gateway_sync_service:
                try:
                    logger.info("Starting edge gateway sync service...")
                    if self._edge_gateway_sync_service.start():
                        success_count += 1
                        logger.info("Started edge gateway sync service")
                    else:
                        error_count += 1
                        logger.error("Failed to start edge gateway sync service")
                except Exception as e:
                    error_count += 1
                    logger.error(f"Error starting edge gateway sync service: {e}", exc_info=True)

            logger.info(f"Cloud sync started: {success_count} services started, {error_count} failures")
            return success_count > 0 or error_count == 0

        except Exception as e:
            logger.error(f"Error starting cloud sync services: {e}", exc_info=True)
            return False

    def stop(self) -> bool:
        """
        Stop all cloud synchronization services.

        Returns:
            bool: True if stopped successfully
        """
        try:
            # Stop all sensor sync services
            with self._lock:
                services = list(self._sensor_sync_services.values())

            for service in services:
                try:
                    service.stop()
                    logger.info(f"Stopped sync service for {service.get_sensor_id}")
                except Exception as e:
                    logger.error(f"Error stopping sync service for {service.get_sensor_id}: {e}")

            # Stop edge gateway sync if present
            if self._edge_gateway_sync_service:
                self._edge_gateway_sync_service.stop()
                logger.info("Stopped edge gateway sync service")

            logger.info("All cloud sync services stopped")
            return True

        except Exception as e:
            logger.error(f"Error stopping cloud sync services: {e}", exc_info=True)
            return False

    def subscribe_to_events(self) -> None:
        """Subscribe to client events to update sensor sync services."""
        logger.debug("Subscribing to events")

        if (self._health_monitor_config.ble_client_manager and
                self._health_monitor_config.ble_client_manager.is_enabled):
            self._event_bus.subscribe(StreamName.BLE_CLIENT_CONNECTION_INFO_UPDATED.value,
                                      self.redis_consumer_group_name,
                                      lambda event: self._handle_ble_client_event(event))

        if (self._health_monitor_config.i2c_client_manager and
                self._health_monitor_config.i2c_client_manager.is_enabled):
            self._event_bus.subscribe(StreamName.I2C_CLIENT_CONNECTION_INFO_UPDATED.value,
                                      self.redis_consumer_group_name,
                                      lambda event: self._handle_i2c_client_event(event))

        # Subscribe to sensor events
        for sensor in self._sensor_sync_services.values():
            sensor.subscribe_to_events(self.redis_consumer_group_name)

        if self._edge_gateway_sync_service:
            self._edge_gateway_sync_service.subscribe_to_events(self.redis_consumer_group_name)

        logger.info("Subscribed to events")

    def _initialize_services(self) -> None:
        """
        Initialize all cloud synchronization services.
        """
        success_count = 0
        error_count = 0

        # Initialize sensor sync services
        if self._config.cloud_sensor_sync.is_enabled:
            logger.info("Initializing sensor sync services...")

            for sensor_config in self._config.cloud_sensor_sync.sensors:
                # Only process the sensor if cloud sync is configured (is sync enabled)
                if not sensor_config.is_enabled:
                    logger.debug(f"Skipping sensor: {sensor_config.sensor_id} for which the cloud sync is disabled.")
                    continue

                try:
                    # Create the appropriate sync service using factory
                    service = SensorSyncServiceFactory.create_sync_service(self._event_bus,
                                                                           sensor_config,
                                                                           self._config.azure_iot_hub)
                    # Store the service
                    with self._lock:
                        self._sensor_sync_services[sensor_config.sensor_id] = service
                    success_count += 1
                    logger.info(f"Initialized sync service for {sensor_config.sensor_id}")
                except Exception as e:
                    error_count += 1
                    logger.error(f"Error creating sync service for {sensor_config.sensor_id}: {e}", exc_info=True)

        # Initialize the edge gateway sync
        if self._config.cloud_edge_gateway_sync.is_enabled:
            try:
                logger.info("Initializing edge gateway sync service...")
                self._edge_gateway_sync_service = EdgeGatewaySyncService(self._event_bus,
                                                                        self._config.cloud_edge_gateway_sync,
                                                                        self._config.azure_iot_hub)
                success_count += 1
                logger.info("Initialized edge gateway sync service")
            except Exception as e:
                error_count += 1
                logger.error(f"Error creating sync service for edge gateway: {e}", exc_info=True)

        logger.info(f"Cloud sync initialization complete: {success_count} services initialized, {error_count} failures")

    def _handle_ble_client_event(self, event: BleClientEvent) -> None:
        """Handle BLE client connection/disconnection events."""
        logger.debug(f"Received BLE client event for {event.client_id}, connected: {event.is_connected}")

        # For each sensor in the sensor list, update its service directly
        for sensor_id in event.sensors:
            # Try to find the service for this sensor
            service = self._sensor_sync_services.get(sensor_id)

            # If the service exists, update its client status
            if service is not None:
                try:
                    service.update_client_status(
                        "connected" if event.is_connected else "disconnected",
                        {
                            "client_id": event.client_id,
                            "client_type": event.client_type,
                            "last_status_change": event.timestamp.isoformat(),
                            "target_device_name": event.target_device_name,
                            "target_device_mac_address": event.target_device_mac_address,
                            "message": event.message
                        }
                    )
                    logger.info(f"Updated client status for sensor {sensor_id}")
                except Exception as e:
                    logger.error(f"Error updating client status for sensor {sensor_id}: {e}")

    def _handle_i2c_client_event(self, event: I2CClientEvent) -> None:
        """Handle I2C client connection/disconnection events."""
        logger.debug(f"Received I2C client event for {event.client_id}, connected: {event.is_connected}")

        # For each sensor in the sensor list, update its service directly
        for sensor_id in event.sensors:
            # Try to find the service for this sensor
            service = self._sensor_sync_services.get(sensor_id)

            # If the service exists, update its client status
            if service is not None:
                try:
                    service.update_client_status(
                        "connected" if event.is_connected else "disconnected",
                        {
                            "client_id": event.client_id,
                            "client_type": event.client_type,
                            "last_status_change": event.timestamp.isoformat(),
                            "i2c_bus_id": event.i2c_bus_id,
                            "message": event.message
                        }
                    )
                    logger.info(f"Updated client status for sensor {sensor_id}")
                except Exception as e:
                    logger.error(f"Error updating client status for sensor {sensor_id}: {e}")