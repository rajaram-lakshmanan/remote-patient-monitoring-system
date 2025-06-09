#!/usr/bin/env python3
# -----------------------------------------------------------------------------
# Filename: base_ble_sensor_handler.py
# Author: Rajaram Lakshmanan
# Description: Base class for all BLE sensor handlers.
# License: MIT (see LICENSE)
# -----------------------------------------------------------------------------

import logging
from abc import abstractmethod
from typing import Dict, Callable

from client.common.base_client import BaseClient
from client.common.base_sensor_handler import BaseSensorHandler
from event_bus.redis_stream_bus.redis_stream_bus import RedisStreamBus

logger = logging.getLogger("BaseBleSensorHandler")

# Common constant
CCCD_UUID = "00002902-0000-1000-8000-00805f9b34fb"

class BaseBleSensorHandler(BaseSensorHandler):
    """
    Base class for all BLE sensor handlers.
    
    This abstract class defines the interface for all BLE sensor handlers and
    provides common functionality for handling BLE services and characteristics.
    Concrete implementations must provide service-specific logic.
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
        Initialize the base BLE sensor handler.
        
        Args:
            event_bus (RedisStreamBus): The event bus for publishing events.
            client: Client to which the sensor handler belongs.
            is_enabled (bool): Flag indicating whether the sensor is enabled or not.
            sensor_id (str): ID of the sensor, this ID shall be unique in the application.
            Follows the format: <interfaceType_shortenedClientId_sensorType> e.g., ble_c1_heart_rate.
            sensor_name (str): Name of the sensor, this does not need to be unique.
            sensor_type (str): Type of the sensor, this is used to determine the sensor-specific logic.
            patient_id (str): ID of the patient associated (wearing or using) with the sensors.
            location (str): Location or placement of the sensors.
        """
        # Initialize containers
        self.service = None
        self.characteristics = {}
        self.notification_handlers = {}
        
        # Track CCCD UUID
        self.cccd_uuid = CCCD_UUID

        # Call parent constructor
        super().__init__(event_bus, client, is_enabled, sensor_id, sensor_name, sensor_type, patient_id, location)
    
    @property
    @abstractmethod
    def service_uuid(self) -> str:
        """Return the UUID of the service this handler manages."""
        pass
    
    @property
    @abstractmethod
    def characteristic_uuids(self) -> Dict[str, str]:
        """Return a dictionary of characteristic names to UUIDs."""
        pass

    # === Public API Functions ===

    def discover_service(self, services) -> bool:
        """
        Discover the service and characteristics for this sensor.
        
        Args:
            services: List of available services.
        
        Returns:
            bool: True if the service was found, False otherwise
        """
        # Find the service
        for service in services:
            logger.debug(f"Service: {service.uuid}")
            if str(service.uuid).lower() == self.service_uuid.lower():
                self.service = service
                logger.info(f"Found {self.__class__.__name__} Service")
                
                # Find characteristics
                for char in service.getCharacteristics():
                    char_uuid = str(char.uuid).lower()
                    
                    # Match against our known characteristics
                    for name, uuid in self.characteristic_uuids.items():
                        if char_uuid == uuid.lower():
                            self.characteristics[name] = char
                            logger.info(f"Found {name.replace('_', ' ').title()} Characteristic")
                
                return True
        
        logger.warning(f"{self.__class__.__name__} Service not found")
        return False
    
    def enable_notifications(self, peripheral, notification_delegate) -> int:
        """
        Enable notifications for this sensor's characteristics.
        
        Args:
            peripheral: The BLE peripheral device.
            notification_delegate: The notification delegate.
        
        Returns:
            int: Number of characteristics for which notifications were enabled.
        """
        enabled_count = 0

        for name, char in self.characteristics.items():
            # Skip characteristics that don't need notifications (like triggers)
            if 'trigger' in name:
                continue

            logger.debug(f"Enabling notifications for {name.replace('_', ' ').title()}")

            try:
                # Find the CCCD descriptor
                cccd_handle = None
                for desc in char.getDescriptors():
                    if str(desc.uuid).lower() == self.cccd_uuid.lower():
                        cccd_handle = desc.handle
                        break

                if cccd_handle:
                    try:
                        peripheral.writeCharacteristic(cccd_handle, b"\x01\x00")
                        logger.debug(f"{name.replace('_', ' ').title()} notifications enabled")

                        # Register with notification delegate
                        notification_delegate.register_characteristic(
                            self.characteristic_uuids.get(name),
                            char.getHandle()
                        )

                        enabled_count += 1
                    except Exception as e:
                        logger.warning(f"Error writing to CCCD for {name}: {e}")
                else:
                    logger.warning(f"CCCD for {name.replace('_', ' ').title()} not found")
            except Exception as e:
                logger.warning(f"Error processing characteristic {name}: {e}")

        return enabled_count
    
    @abstractmethod
    def read_initial_data(self) -> None:
        """Read initial values from characteristics."""
        # Prior to reading the initial sensor data from the BLE server, publish the sensor metadata
        self._publish_sensor_metadata()

    def _register_notification_handler(self, uuid: str, handler_func: Callable) -> None:
        """
        Register a handler function for a characteristic UUID.

        Args:
            uuid (str): The UUID of the characteristic.
            handler_func (callable): Function to call when notifications are received.
        """
        self.notification_handlers[uuid.lower()] = handler_func