#!/usr/bin/env python3
# -----------------------------------------------------------------------------
# Filename: ble_client.py
# Author: Rajaram Lakshmanan
# Description: BLE client for connecting to and interacting with a
# BLE GATT device.
# License: MIT (see LICENSE)
# -----------------------------------------------------------------------------

import time
import logging
import threading
from typing import Optional, Callable, Dict, cast

from bluepy import btle

from client.ble.ble_client.ble_notification_delegate import BleNotificationDelegate
from client.ble.ble_client.ble_scan_delegate import BleScanDelegate
from client.ble.ble_sensor_handler.base_ble_sensor_handler import BaseBleSensorHandler
from client.common.base_client import BaseClient
from client.common.base_sensor_handler_provider import BaseSensorHandlerProvider
from client.common.sensor_handler_provider_factory import SensorHandlerProviderFactory
from client.common.sensor_manager import SensorManager
from config.models.ble.ble_client_config import BleClientConfig
from event_bus.models.client.ble_client_event import BleClientEvent
from event_bus.redis_stream_bus.redis_stream_bus import RedisStreamBus
from event_bus.stream_name import StreamName

logger = logging.getLogger("BleClient")

class BleClient(BaseClient):
    """BLE client for connecting to and interacting with a BLE GATT device."""

    def __init__(self, event_bus: RedisStreamBus, config: BleClientConfig):
        """
        Initialize the BleClient.

        Args:
            event_bus (RedisStreamBus): The event bus for publishing events.
            config (BleClientConfig): BLE Client configuration object.
        """
        try:
            super().__init__(event_bus)
            self._config = config
            self._is_successfully_initialized = False
            self._peripheral = None

            # At least one of this registry must be provided in the config
            self._device_address = self._config.device_address
            self._device_name = self._config.device_name

            self._notification_delegate = None
            self._connected_event = threading.Event()
            self._services_discovered_event = threading.Event()

            # Thread-safety
            self._lock = threading.RLock()

            # Sensor handlers and manager to monitor their state
            self._sensor_handlers: Dict[str, BaseBleSensorHandler]= {}
            self._sensor_manager = SensorManager(self._event_bus)

            sensor_handler_provider = SensorHandlerProviderFactory.create_provider(self._config.device_type,
                                                                                   self._event_bus)
            if sensor_handler_provider:
                self._initialize_sensor_handlers(sensor_handler_provider)

            # Disconnection callback
            self._on_disconnect_callback = None

            self._is_successfully_initialized = True
            logger.info(f"BLE client {self._config.client_id} is initialized")
        except Exception as e:
            logger.error(f"Failed to initialize the BLE Client {self.client_id}: {e}")

    @property
    def is_enabled(self) -> bool:
        """Return the flag to indicate whether the client is enabled to initiate the connection with the
        server (target sensors)."""
        return self._config.is_enabled

    @property
    def is_connected(self) -> bool:
        """Return the flag to indicate whether the client is connected."""
        return self._connected_event.is_set() if self._connected_event else False

    @property
    def client_id(self) -> str:
        """Return the identifier of the BLE client."""
        return self._config.client_id if self._config else "Unknown"

    @property
    def device_type(self) -> str:
        """Return the type of the BLE device the client is connected to."""
        # Static registry set in the config and will not change during the runtime
        return self._config.device_type

    @property
    def device_name(self) -> str:
        """Return the name of the BLE device the client is connected to."""
        return self._device_name

    @property
    def device_address(self) -> str:
        """Return the address of the BLE device the client is connected to."""
        return self._device_address

    @property
    def sensors(self) -> list[str]:
        """Return a list of sensor IDs from the connected sensors."""
        if self._sensor_handlers:
            return list(self._sensor_handlers.keys())
        return []

    @property
    def is_ble_services_discovered(self) -> bool:
        """Return the flag to indicate whether the client has discovered BLE services in the target device."""
        return self._services_discovered_event.is_set() if self._services_discovered_event else False

    # === Public API Functions ===

    def start(self, notification_time: float = 60.0) -> bool:
        """
        Start the BLE client. This is the primary entry point for starting the
        client's connection.

        Args:
            notification_time (float): Time to listen for notifications in seconds.
                                      If 0, wait indefinitely until disconnected.

        Returns:
            bool: True if run successfully, False otherwise.
        """
        if not self._is_successfully_initialized:
            raise RuntimeError(f"Unable to start the BLE Client {self.client_id}. Not Initialized.")

        try:
            # Find the device
            device_addr = self._config.device_address or self._find_device()
            if not device_addr:
                return False

            # Connect to the device
            if not self._connect(device_addr):
                return False

            # Discover services
            if not self._discover_services():
                self.stop()
                return False

            # Add a small delay to allow the BLE stack to stabilize
            time.sleep(0.5)

            # Read initial data from the sensors
            self._read_initial_data()

            # Enable notifications
            if not self._enable_notifications():
                self.stop()
                return False

            self._publish_client_info("Client has connected successfully")

            # Start monitoring the sensor for reporting its status
            self._sensor_manager.start_monitoring()

            # Wait for notifications
            self._wait_for_notifications(notification_time)

            # Once no notifications are received for a while, disconnect
            self.stop()
            return True
        except KeyboardInterrupt:
            logger.info("Operation interrupted by user")
            if self._connected_event.is_set():
                self.stop()
            return False
        except Exception as e:
            logger.error(f"Error in run method: {e}")
            if self._connected_event.is_set():
                self.stop()
            return False

    def stop(self) -> bool:
        """
        Disconnect from the device.

        Returns:
            bool: True if disconnected successfully, False otherwise.
        """
        with self._lock:
            if not self._connected_event.is_set() or not self._peripheral:
                logger.warning("Not connected to a device")
                return True

            try:
                logger.info("Disconnecting...")

                # Stop monitoring the sensor before disconnecting the peripheral
                self._sensor_manager.stop_monitoring()

                peripheral = self._peripheral
                self._connected_event.clear()
                self._services_discovered_event.clear()
                self._peripheral = None
            except Exception as e:
                logger.error(f"Error disconnecting: {e}")
                self._connected_event.clear()
                self._peripheral = None
                return False

        # Perform disconnection outside the lock
        if peripheral:
            try:
                peripheral.disconnect()
            except Exception as e:
                logger.error(f"Error disconnecting peripheral: {e}")

        self._publish_client_info("Stopped the client")
        logger.info("Disconnected successfully")
        return True

    def handle_disconnect(self):
        """
        Handle device disconnection.

        This method is called when the device unexpectedly disconnects.
        It cleans up the connection state and notifies listeners.
        """
        with self._lock:
            if not self._connected_event.is_set():
                logger.debug("Not connected, ignoring disconnect call")
                return

            self._connected_event.clear()
            self._services_discovered_event.clear()

            # Defer cleanup and callbacks to a background thread
            def deferred_cleanup():
                try:
                    logger.debug("Starting deferred disconnect cleanup...")
                    # Stop monitoring the sensor as part of handling the disconnect
                    self._sensor_manager.stop_monitoring()

                    self._publish_client_info("Unexpected disconnection of the client")

                    # Call the disconnect callback if set
                    if self._on_disconnect_callback:
                        try:
                            self._on_disconnect_callback(self._config.client_id)
                        except Exception as e:
                            logger.error(f"Error in disconnect callback: {e}")
                    logger.debug("Deferred disconnect cleanup complete.")
                except Exception as e:
                    logger.error(f"Error during deferred disconnect handling: {e}")

            threading.Thread(target=deferred_cleanup, daemon=True).start()

    def set_on_disconnect_callback(self, callback: Callable):
        """
        Set a callback to be called when the device disconnects.

        Args:
            callback (Callable): Function to call on disconnect.
        """
        self._on_disconnect_callback = callback

    def subscribe_to_events(self) -> None:
        """Subscribe to the events required by the client and its configured sensors."""
        logger.debug("Subscribing to events")

        if not self._is_successfully_initialized:
            return

        try:
            sensor_handlers = (self._sensor_handlers or {}).values()
            for sensor_handler in sensor_handlers:
                if sensor_handler is not None:
                    sensor_handler.subscribe_to_events()
        except Exception as e:
            logger.error(f"Error subscribing to events: {e}", exc_info=True)

    def write_characteristic(self, characteristic, data, with_response=True):
        """
        Thread-safe method to write to a characteristic.

        Args:
            characteristic: The characteristic to write to.
            data: The sensor data to write.
            with_response: Whether to expect a response.

        Returns:
            bool: True if successful, False otherwise.
        """
        with self._lock:
            if not self._connected_event.is_set() or not self._peripheral:
                logger.error("Not connected to a device")
                return False

            try:
                characteristic.write(data, withResponse=with_response)
                return True
            except Exception as e:
                logger.error(f"Error writing to characteristic: {e}")
                return False

    # === Local Functions ===

    def _initialize_sensor_handlers(self, sensor_handler_provider: BaseSensorHandlerProvider):
        """
        Initialize sensor handlers based on the configured sensors.

         Args:
             sensor_handler_provider (BaseSensorHandlerProvider): Provider class to create the sensor handlers.

        This method calls the sensor initialization service to create
        sensor handlers for each configured sensor.
        """
        try:
            with self._lock:
                for sensor in self._config.sensors:
                    # Even if the sensor is disabled, we still need to create a handler instance and
                    # store it in the configuration dictionary. The enabled flag is used to determine
                    # whether the sensor should start acquiring sensor data or not

                    # Get the sensor handler from the provider
                    handler = sensor_handler_provider.get_handler(self,
                                                                  sensor.is_enabled,
                                                                  sensor.sensor_id,
                                                                  sensor.sensor_name,
                                                                  sensor.sensor_type,
                                                                  sensor.patient_id,
                                                                  sensor.location)
                    ble_sensor_handler = cast(BaseBleSensorHandler, handler)
                    if handler:
                        self._sensor_handlers[sensor.sensor_id] = ble_sensor_handler
                        self._sensor_manager.add_sensor(ble_sensor_handler)
                        logger.info(f"Registered sensor handler for {sensor.sensor_id}")
                    else:
                        logger.warning(f"No handler instance for {sensor.sensor_id}")
        except Exception as e:
            logger.error(f"Error initializing sensor handlers: {e}", exc_info=True)
            raise

    def _find_device(self, timeout: float = 30.0) -> Optional[str]:
        """
        Scan for and find the target device.

        Args:
            timeout (float): Maximum time to scan in seconds.

        Returns:
            str: Device MAC address if found, None otherwise.
        """
        if self._device_address:
            logger.info(f"Using provided device address: {self._device_address}")
            return self._device_address

        if not self._device_name:
            logger.error("Neither device address nor device name provided")
            return None

        # Create the scanner with the delegate
        scanner = btle.Scanner().withDelegate(BleScanDelegate(self._device_name))

        start_time = time.time()
        remaining_time = timeout

        while remaining_time > 0:
            try:
                # Perform scanning for a short interval (e.g., 3 seconds) at a time
                # This allows us to check for results periodically
                scan_time = min(3.0, remaining_time)

                try:
                    # This will perform the actual scan and update our delegate's found_devices
                    scanner.scan(scan_time)
                except StopIteration:
                    # The delegate will raise this exception when the target device is found
                    # We can now access the target_device_addr directly from the delegate
                    if scanner.delegate.device_addr:
                        return scanner.delegate.device_addr

                delegate = scanner.delegate

                # Check if we found our target device
                for addr, name in delegate.found_devices.items():
                    if self._device_name.lower() in name.lower():
                        logger.info(f"Found target device: {name} ({addr})")
                        return addr

                # Update remaining time
                remaining_time = timeout - (time.time() - start_time)

            except btle.BTLEException as e:
                logger.error(f"Error during scanning: {e}")
                time.sleep(1)
                # Update remaining time after the sleep
                remaining_time = timeout - (time.time() - start_time)

        logger.error(f"Failed to find the target device with name: {self._device_name}")
        return None

    def _connect(self, device_addr: Optional[str] = None) -> bool:
        """
        Connect to the specified BLE device (internal method).

        Args:
            device_addr (str, optional): Device MAC address to connect to.
                                        If None, use the stored address.

        Returns:
            bool: True if connected successfully, False otherwise.
        """
        with self._lock:
            if self._connected_event.is_set():
                logger.warning("Already connected to a device")
                return True

            addr = device_addr or self._device_address
            if not addr:
                logger.error("No device address provided")
                return False

            try:
                logger.info(f"Connecting to {addr}...")

                # Local import to avoid circular dependency
                from client.ble.ble_client.ble_peripheral_with_reconnect import BlePeripheralWithReconnect

                # Create the BLE peripheral with an auto reconnect wrapper
                self._peripheral = BlePeripheralWithReconnect(addr, self)

                # Create a new notification delegate
                self._notification_delegate = BleNotificationDelegate()
                self._peripheral.withDelegate(self._notification_delegate)

                self._connected_event.set()
                self._device_address = addr  # Store the address

                # Try to increase MTU for better data handling
                try:
                    self._peripheral.setMTU(512)
                    logger.info("MTU increased to 512")
                except Exception as e:
                    logger.warning(f"Could not increase MTU, using default: {e}")

                logger.info("Connected successfully")
                return True

            except btle.BTLEDisconnectError as e:
                logger.error(f"Failed to connect to {addr}: {e}")
                return False
            except Exception as e:
                logger.error(f"Error connecting to {addr}: {e}", exc_info=True)
                return False

    def _discover_services(self) -> bool:
        """
        Discover services and characteristics.

        Returns:
            bool: True if services were discovered successfully, False otherwise.
        """
        with self._lock:
            if not self._connected_event.is_set() or not self._peripheral:
                logger.error("Not connected to a device")
                return False

            if self._services_discovered_event.is_set():
                logger.info("Services already discovered")
                return True

            try:
                logger.debug("Discovering services...")
                all_services = self._peripheral.getServices()

                # Log all services and characteristics for debugging
                for service in all_services:
                    logger.debug(f"Service: {service.uuid}")
                    for char in service.getCharacteristics():
                        logger.debug(f"  Characteristic: {char.uuid}, Properties: {char.propertiesToString()}")
                        for desc in char.getDescriptors():
                            logger.debug(f"    Descriptor: {desc.uuid}")

                # Let each sensor handler discover its service and characteristics
                for sensor_id, handler in self._sensor_handlers.items():
                    if handler.is_enabled and handler.discover_service(all_services):
                        logger.info(f"Discovering service for {sensor_id} and registering notification handlers...")
                        # Register notification handlers
                        for uuid, func in handler.notification_handlers.items():
                            self._notification_delegate.register_handler(uuid, func)

                self._services_discovered_event.set()
                return True

            except Exception as e:
                logger.error(f"Error discovering services: {e}")
                return False

    def _enable_notifications(self) -> bool:
        """
        Enable notifications for all discovered characteristics.

        Returns:
            bool: True if notifications were enabled successfully, False otherwise.
        """
        with self._lock:
            if not self._connected_event.is_set() or not self._peripheral:
                logger.error("Not connected to a device")
                return False

            if not self._services_discovered_event.is_set():
                logger.error("Services not discovered yet")
                return False

            try:
                enabled_count = 0

                for sensor_id, handler in self._sensor_handlers.items():
                    if handler.is_enabled:
                        logger.info(f"Enabling notifications for {sensor_id} handler")
                        try:
                            count = handler.enable_notifications(self._peripheral, self._notification_delegate)
                            enabled_count += count
                        except Exception as e:
                            logger.error(f"Error enabling notifications for {sensor_id}: {e}")
                            # Continue with other handlers

                # If we enabled some but not all notifications, that's still a success
                if enabled_count > 0:
                    logger.info(f"Enabled notifications for {enabled_count} characteristics")
                    return True
                else:
                    logger.error("Failed to enable any notifications")
                    return False
            except Exception as e:
                logger.error(f"Error enabling notifications: {e}")
                return False

    def _read_initial_data(self) -> None:
        """Read initial values from all characteristics."""
        with self._lock:
            if not self._connected_event.is_set() or not self._peripheral:
                logger.error("Not connected to a device")
                return

            if not self._services_discovered_event.is_set():
                logger.error("Services not discovered yet")
                return

            try:
                for sensor_id, handler in self._sensor_handlers.items():
                    if handler.is_enabled:
                        logger.info(f"Reading initial data for {sensor_id}")
                        try:
                            handler.read_initial_data()
                        except Exception as e:
                            # Log but continue with the next sensor
                            logger.warning(f"Error reading initial data for {sensor_id}: {e}")
            except Exception as e:
                logger.error(f"Error reading initial data: {e}")

    def _wait_for_notifications(self, timeout: float) -> bool:
        """
        Wait for notifications for the specified time.
        """
        if not self._connected_event.is_set() or not self._peripheral:
            logger.error("Not connected to a device")
            return False

        if timeout > 0:
            logger.debug(f"Waiting for notifications for {timeout} seconds...")
        else:
            logger.debug("Waiting for notifications indefinitely...")

        start_time = time.time()
        try:
            while timeout == 0 or time.time() - start_time < timeout:
                # Check connection without the lock first
                if not self._connected_event.is_set():
                    return False

                peripheral = None
                with self._lock:
                    if not self._peripheral:
                        return False
                    peripheral = self._peripheral

                # Do notification waiting outside the lock
                try:
                    if peripheral and peripheral.waitForNotifications(0.5):
                        # Delegate has been called
                        continue
                except btle.BTLEDisconnectError:
                    logger.warning("Device disconnected during notification wait")
                    self.handle_disconnect()
                    return False
                except Exception as e:
                    if "Unexpected response" in str(e):
                        # Log the error but continue processing instead of crashing
                        logger.warning(f"Received unexpected response during notification wait: {e}")
                        # Short delay to allow the system to stabilize
                        time.sleep(0.1)
                        continue
                    else:
                        # For other errors, log but continue
                        logger.error(f"Error waiting for notifications: {e}")

                # No notifications received in the last attempt
                idle_time = time.time() - self._notification_delegate.last_update_time
                if idle_time > 5.0:  # Log if no notifications for 5 seconds
                    logger.debug(f"No notifications received for {idle_time:.1f} seconds")

            return True

        except KeyboardInterrupt:
            logger.info("Notification wait interrupted by user")
            return False
        except Exception as e:
            logger.error(f"Error in notification wait loop: {e}")
            return False

    def _publish_client_info(self, message: str) -> None:
        """Publish BLE client registry to the event bus.

        Args:
            message (str): Custom message to be published.
        """
        if not self._event_bus:
            return

        try:
            # Create a client registry event for Redis
            client_info_event = BleClientEvent(
                client_id = self.client_id,
                is_connected = self.is_connected,
                target_device_name = self.device_name,
                target_device_type = self.device_type,
                target_device_mac_address = self.device_address,
                sensors = self.sensors,
                message = message
            )

            # Publish to Redis Stream
            if not self._event_bus.shutdown_active:
                self._event_bus.publish(StreamName.BLE_CLIENT_CONNECTION_INFO_UPDATED.value, client_info_event)
        except Exception as e:
            logger.error(f"Error publishing registry for the client '{self.client_id}' to Redis Stream: {e}")