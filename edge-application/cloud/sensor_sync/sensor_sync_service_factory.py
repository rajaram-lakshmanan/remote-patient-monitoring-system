#!/usr/bin/env python3
# -----------------------------------------------------------------------------
# Filename: sensor_sync_service_factory.py
# Author: Rajaram Lakshmanan
# Description: Factory for creating sensor-specific sync services
# License: MIT (see LICENSE)
# -----------------------------------------------------------------------------

import logging
from typing import Optional

from client.common.device_sensor_classification_types import GalaxyWatchBleSensorType, DeviceTypes, \
    ClickBoardI2CSensorType
from cloud.sensor_sync.base_sensor_sync_service import BaseSensorSyncService
from cloud.sensor_sync.generic_sensor_sync_service import GenericSensorSyncService
from cloud.sensor_sync.galaxy_watch.galaxy_watch_accelerometer_sync_service import GalaxyWatchAccelerometerSyncService
from cloud.sensor_sync.galaxy_watch.galaxy_watch_ecg_sync_service import GalaxyWatchEcgSyncService
from cloud.sensor_sync.galaxy_watch.galaxy_watch_heart_rate_sync_service import GalaxyWatchHeartRateSyncService
from cloud.sensor_sync.galaxy_watch.galaxy_watch_ppg_sync_service import GalaxyWatchPpgSyncService
from cloud.sensor_sync.galaxy_watch.galaxy_watch_spo2_sync_service import GalaxyWatchSpo2SyncService
from cloud.sensor_sync.galaxy_watch.galaxy_watch_temperature_sync_service import GalaxyWatchTemperatureSyncService
from cloud.sensor_sync.clickboard.clickboard_environment_sync_service import ClickBoardEnvironmentSyncService
from cloud.sensor_sync.clickboard.clickboard_oximeter_sync_service import ClickBoardOximeterSyncService
from cloud.sensor_sync.clickboard.clickboard_ecg_sync_service import ClickBoardEcgSyncService
from config.models.cloud.cloud_sensor_sync_config import SensorSyncServiceConfig

logger = logging.getLogger("SyncServiceFactory")

class SensorSyncServiceFactory:
    """Factory for creating sensor-specific sync services"""

    @classmethod
    def create_sync_service(cls,
                            event_bus,
                            sensor_sync_service_config: SensorSyncServiceConfig,
                            azure_iot_hub_config) -> BaseSensorSyncService:
        """
        Create the appropriate sync service based on device and sensor type.

        Args:
            event_bus: Event bus for communication
            sensor_sync_service_config: Sensor sync service configuration
            azure_iot_hub_config: Azure IoT Hub configuration

        Returns:
            An instance of the appropriate sync service or a generic service if the type is not recognized
        """
        try:
            try:
                # Convert string values to enum members
                device_type_enum = DeviceTypes.from_string(sensor_sync_service_config.device_type)
            except ValueError:
                # Ignore and continue
                device_type_enum = None

            # Create the appropriate service based on device and sensor type
            if device_type_enum == DeviceTypes.GALAXY_WATCH:
                service = cls._create_galaxy_watch_service(event_bus,
                                                           sensor_sync_service_config,
                                                           azure_iot_hub_config)
            elif device_type_enum == DeviceTypes.CLICK_BOARD:
                service = cls._create_click_board_service(event_bus,
                                                          sensor_sync_service_config,
                                                          azure_iot_hub_config)
            else:
                logger.warning(f"Unknown device type: {sensor_sync_service_config.device_type}, using generic service")
                service = None

            # If no specific service was created, use the generic service
            if service is None:
                logger.info(f"No specific sync service for {sensor_sync_service_config.device_type}/"
                            f"{sensor_sync_service_config.sensor_type}, using generic service")
                service = GenericSensorSyncService(event_bus,
                                                   sensor_sync_service_config,
                                                   azure_iot_hub_config)

            return service

        except Exception as e:
            logger.error(f"Error creating sync service: {e}", exc_info=True)
            # Fall back to generic service if there's any error
            return GenericSensorSyncService(event_bus,
                                            sensor_sync_service_config,
                                            azure_iot_hub_config)

    @classmethod
    def _create_galaxy_watch_service(cls,
                                     event_bus,
                                     sensor_sync_service_config: SensorSyncServiceConfig,
                                     azure_iot_hub_config) -> Optional[BaseSensorSyncService]:
        """
        Create a sync service for Galaxy Watch sensors

        Args:
            event_bus: Event bus for communication
            sensor_sync_service_config: Sensor sync service configuration
            azure_iot_hub_config: Azure IoT Hub configuration

        Returns:
            Specific sync service for the sensor type or None if not recognized
        """
        try:
            # Convert string to enum
            sensor_type_enum = GalaxyWatchBleSensorType.from_string(sensor_sync_service_config.sensor_type)

            # Map sensor types to service classes
            service_map = {
                GalaxyWatchBleSensorType.HEART_RATE: GalaxyWatchHeartRateSyncService,
                GalaxyWatchBleSensorType.ECG: GalaxyWatchEcgSyncService,
                GalaxyWatchBleSensorType.ACCELEROMETER: GalaxyWatchAccelerometerSyncService,
                GalaxyWatchBleSensorType.PPG: GalaxyWatchPpgSyncService,
                GalaxyWatchBleSensorType.SPO2: GalaxyWatchSpo2SyncService,
                GalaxyWatchBleSensorType.TEMPERATURE: GalaxyWatchTemperatureSyncService,
            }

            # Get the service class
            service_class = service_map.get(sensor_type_enum)
            if service_class:
                return service_class(event_bus, sensor_sync_service_config, azure_iot_hub_config)
            else:
                logger.warning(f"No specific sync service for Galaxy Watch sensor type: "
                               f"{sensor_sync_service_config.sensor_type}")
                return None

        except ValueError:
            logger.warning(f"Unrecognized Galaxy Watch sensor type: {sensor_sync_service_config.sensor_type}")
            return None

    @classmethod
    def _create_click_board_service(cls,
                                    event_bus,
                                    sensor_sync_service_config: SensorSyncServiceConfig,
                                    azure_iot_hub_config) -> Optional[BaseSensorSyncService]:
        """
        Create a sync service for Click Board sensors

        Args:
            event_bus: Event bus for communication
            sensor_sync_service_config: Sensor sync service configuration
            azure_iot_hub_config: Azure IoT Hub configuration

        Returns:
            Specific sync service for the sensor type or None if not recognized
        """
        sensor_type = sensor_sync_service_config.sensor_type
        try:
            # Convert string to enum
            sensor_type_enum = ClickBoardI2CSensorType.from_string(sensor_type)

            # Map sensor types to service classes
            service_map = {
                ClickBoardI2CSensorType.ENVIRONMENT: ClickBoardEnvironmentSyncService,
                ClickBoardI2CSensorType.OXIMETER_5: ClickBoardOximeterSyncService,
                ClickBoardI2CSensorType.ECG_7: ClickBoardEcgSyncService,
            }

            # Get the service class
            service_class = service_map.get(sensor_type_enum)
            if service_class:
                return service_class(event_bus, sensor_sync_service_config, azure_iot_hub_config)
            else:
                logger.warning(f"No specific sync service for Click Board sensor type: {sensor_type}")
                return None

        except ValueError:
            logger.warning(f"Unrecognized Click Board sensor type: {sensor_type}")
            return None