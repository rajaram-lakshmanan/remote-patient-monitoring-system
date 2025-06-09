#!/usr/bin/env python3
# -----------------------------------------------------------------------------
# Filename: health_monitoring_config.py
# Author: Rajaram Lakshmanan
# Description: Main application (Health monitoring) configuration.
# License: MIT (see LICENSE)
# ------------------------------------------------------------------------------
import logging
import os

from pydantic import BaseModel, model_validator

from config.models.app_config import AppConfig
from config.models.ble.ble_client_manager_config import BleClientManagerConfig
from config.models.cloud.cloud_sync_manager_config import CloudSyncManagerConfig
from config.models.edge_gateway.edge_gateway_config import EdgeGatewayConfig
from config.models.i2c.i2c_client_manager_config import I2CClientManagerConfig
from config.models.logging.logging_config import LoggingConfig
from config.models.event_bus.redis_config import EventBusConfig
from config.models.repository.repository_manager_config import RepositoryManagerConfig
from config.models.gui.web_server_config import WebServerConfig

logger = logging.getLogger("HealthMonitorConfig")

class HealthMonitorConfig(BaseModel):
    """Main application configuration."""
    app: AppConfig
    logging: LoggingConfig
    event_bus: EventBusConfig
    ble_client_manager: BleClientManagerConfig
    i2c_client_manager: I2CClientManagerConfig
    edge_gateway: EdgeGatewayConfig
    cloud_sync_manager: CloudSyncManagerConfig
    repository_manager: RepositoryManagerConfig
    web_server: WebServerConfig = WebServerConfig()  # Default config if not specified

    @model_validator(mode='after')
    def run_all_validations(self):

        # Sensor ID across the application shall be unique
        self._validate_unique_sensor_ids()

        # Cloud-specific configuration validation, sensors must be validated before the
        # certificate files for the sensor
        self._validate_cloud_sensors()
        self._validate_certificate_files()
        return self

    def _validate_unique_sensor_ids(self):
        """Ensure that all sensor IDs are unique across the application."""
        sensor_ids = set()
        duplicate_sensors = set()

        # Get all sensors from BLE clients
        if self.ble_client_manager:
            for client in self.ble_client_manager.clients:
                for sensor in client.sensors:
                    if sensor.sensor_id in sensor_ids:
                        duplicate_sensors.add(sensor.sensor_id)
                    sensor_ids.add(sensor.sensor_id)

        # Get all sensors from I2C clients
        if self.i2c_client_manager:
            for client in self.i2c_client_manager.clients:
                for sensor in client.sensors:
                    if sensor.sensor_id in sensor_ids:
                        duplicate_sensors.add(sensor.sensor_id)
                    sensor_ids.add(sensor.sensor_id)

        if duplicate_sensors:
            raise ValueError(f"Duplicate sensor IDs found: {', '.join(duplicate_sensors)}")

        return self

    def _validate_cloud_sensors(self):
        """Ensure that all sensors in cloud_sensor_sync are configured in the application."""
        # Get sensor states
        all_sensor_ids, active_sensor_ids = self._get_sensor_states()
        disabled_sensor_ids = all_sensor_ids - active_sensor_ids

        # Validate cloud sync configuration
        if self.cloud_sync_manager and self.cloud_sync_manager.cloud_sensor_sync:
            cloud_sync_enabled = self._is_cloud_sync_enabled()
            all_cloud_sensor_ids, active_cloud_sensor_ids = self._get_cloud_sensor_states(cloud_sync_enabled)

            # Perform validations
            self._validate_unknown_sensors(all_sensor_ids, all_cloud_sensor_ids)
            self._validate_disabled_sensors_enabled_in_cloud(disabled_sensor_ids, active_cloud_sensor_ids)
            self._warn_about_missing_cloud_configs(active_sensor_ids, all_cloud_sensor_ids)

        return self

    def _get_sensor_states(self):
        """Get the sets of all sensors and active sensors."""
        all_sensor_ids = set()
        active_sensor_ids = set()

        # Process BLE clients and sensors
        if self.ble_client_manager:
            ble_manager_enabled = self.ble_client_manager.is_enabled
            self._process_clients(
                self.ble_client_manager.clients,
                ble_manager_enabled,
                all_sensor_ids,
                active_sensor_ids
            )

        # Process I2C clients and sensors
        if self.i2c_client_manager:
            i2c_manager_enabled = self.i2c_client_manager.is_enabled
            self._process_clients(
                self.i2c_client_manager.clients,
                i2c_manager_enabled,
                all_sensor_ids,
                active_sensor_ids
            )

        return all_sensor_ids, active_sensor_ids

    @staticmethod
    def _process_clients(clients, manager_enabled, all_sensor_ids, active_sensor_ids):
        """Process clients and their sensors, updating the provided sets."""
        for client in clients:
            client_effectively_enabled = manager_enabled and client.is_enabled

            for sensor in client.sensors:
                # Add to all sensors regardless of the enabled state
                all_sensor_ids.add(sensor.sensor_id)

                # Sensor is active only if manager, client, and sensor are all enabled
                if client_effectively_enabled and sensor.is_enabled:
                    active_sensor_ids.add(sensor.sensor_id)

    def _is_cloud_sync_enabled(self):
        """Check if cloud sync is enabled at all levels."""
        return self.cloud_sync_manager.is_enabled and self.cloud_sync_manager.cloud_sensor_sync.is_enabled

    def _get_cloud_sensor_states(self, cloud_sync_enabled):
        """Get cloud sensor IDs, both all and active ones."""
        all_cloud_sensor_ids = set(
            sensor.sensor_id for sensor in self.cloud_sync_manager.cloud_sensor_sync.sensors
        )

        active_cloud_sensor_ids = set(
            sensor.sensor_id for sensor in self.cloud_sync_manager.cloud_sensor_sync.sensors
            if cloud_sync_enabled and sensor.is_enabled
        )

        return all_cloud_sensor_ids, active_cloud_sensor_ids

    @staticmethod
    def _validate_unknown_sensors(all_sensor_ids, all_cloud_sensor_ids):
        """Validate that all cloud-configured sensors exist in the application."""
        unknown_sensors = all_cloud_sensor_ids - all_sensor_ids
        if unknown_sensors:
            raise ValueError(
                f"The following sensors in cloud_sensor_sync are not configured in the application: "
                f"{', '.join(unknown_sensors)}"
            )

    @staticmethod
    def _validate_disabled_sensors_enabled_in_cloud(disabled_sensor_ids, active_cloud_sensor_ids):
        """Validate that no disabled sensors are enabled for cloud sync."""
        invalid_state = active_cloud_sensor_ids & disabled_sensor_ids
        if invalid_state:
            raise ValueError(
                f"The following sensors are disabled (at manager, client, or sensor level) "
                f"but enabled in cloud_sensor_sync: {', '.join(invalid_state)}"
            )

    @staticmethod
    def _warn_about_missing_cloud_configs(active_sensor_ids, all_cloud_sensor_ids):
        """Warn about active sensors not configured for cloud sync."""
        missing_from_cloud = active_sensor_ids - all_cloud_sensor_ids
        if missing_from_cloud:
            logger.warning(
                f"The following active sensors are not configured in cloud_sensor_sync: "
                f"{', '.join(missing_from_cloud)}"
            )

    def _validate_certificate_files(self):
        """Validate that certificate files exist for each sensor."""
        # This is a placeholder for certificate validation
        # In a real implementation, this would check for certificate files

        if not self.cloud_sync_manager or not self.cloud_sync_manager.azure_iot_hub:
            return self

        cert_folder = self.cloud_sync_manager.azure_iot_hub.certificate_folder
        if not os.path.isdir(cert_folder):
            raise ValueError(f"Warning: Certificate folder {cert_folder} does not exist")

        cloud_sync_enabled = self._is_cloud_sync_enabled()
        _, active_cloud_sensor_ids = self._get_cloud_sensor_states(cloud_sync_enabled)

        missing_files = []

        # Add hardcoded ID for the edge gateway device
        required_ids = active_cloud_sensor_ids | {"edge_gateway"}

        # Service ID = Sensor or Edge Gateway sync services ID
        for service_id in required_ids:
            cert_file_crt = os.path.join(cert_folder, f"{service_id}.crt")
            cert_file_pem = os.path.join(cert_folder, f"{service_id}.pem")
            key_file = os.path.join(cert_folder, f"{service_id}.key")

            cert_exists = os.path.isfile(cert_file_crt) or os.path.isfile(cert_file_pem)
            key_exists = os.path.isfile(key_file)

            if not (cert_exists and key_exists):
                missing_files.append(service_id)

        if missing_files:
            raise ValueError(
                f"Missing certificate (.crt/.pem) or key (.key) files for cloud-synced services in {cert_folder}: "
                f"{', '.join(missing_files)}"
            )

        return self

    model_config = {
        "extra": "ignore"
    }