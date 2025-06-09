#!/usr/bin/env python3
# -----------------------------------------------------------------------------
# Filename: i2c_client.py
# Author: Rajaram Lakshmanan
# Description:  I2C client for connecting to I2C sensors.
# License: MIT (see LICENSE)
# -----------------------------------------------------------------------------

import logging
import threading
from typing import Dict, TypedDict, Optional, cast

import smbus2

from client.common.base_client import BaseClient
from client.common.sensor_handler_provider_factory import SensorHandlerProviderFactory
from client.common.sensor_manager import SensorManager
from client.i2c.i2c_multiplexer import I2CMultiplexer
from client.i2c.i2c_sensor_handler.base_i2c_sensor_handler import BaseI2CSensorHandler
from config.models.i2c.i2c_client_config import I2CClientConfig
from event_bus.models.client.i2c_client_event import I2CClientEvent
from event_bus.redis_stream_bus.redis_stream_bus import RedisStreamBus
from event_bus.stream_name import StreamName

logger = logging.getLogger("I2CClient")

class ValidatedI2CSensorConfig(TypedDict, total=False):
    sensor_id: str
    address: int
    poll_interval: float
    is_enabled: bool
    handler: Optional[BaseI2CSensorHandler]
    sensor_name: str
    sensor_type: str
    patient_id: str
    device_type: str
    location: str

class I2CClient(BaseClient):
    """
    I2C client for connecting to I2C sensors.

    This client manages the connection to an I2C bus and handles
    sensor registration and time_series collection.
    """

    def __init__(self,
                 event_bus: RedisStreamBus,
                 config: I2CClientConfig):
        """
        Initialize the I2CClient.

        Args:
            event_bus (RedisStreamBus): The event bus for publishing events
            config (I2CClientConfig): I2C client configuration
        """
        try:
            super().__init__(event_bus)
            self._is_successfully_initialized = False
            self._config = config

            # Thread-safety
            self._lock = threading.RLock()

            self._bus = None
            self._bus_active_event = threading.Event()

            # Track active sensor acquisitions
            self._active_acquisitions = set()

            # Sensor configuration including the initialized handler
            self._sensor_configs: Dict[str, ValidatedI2CSensorConfig] = {}

            # Initialize the sensor manager to monitor their state and the sensor handlers. Manager must
            # be initialized before the handlers
            self._sensor_manager = SensorManager(self._event_bus)
            self._initialize_sensor_handlers()

            # Initialize I2C Multiplexer if enabled in the configuration
            if self._config.i2c_mux and self._config.i2c_mux.is_enabled:
                self._initialize_i2x_mux()
            self._is_successfully_initialized = True
            logger.info(f"I2C client {self.client_id} initialized for bus {self.bus_id}")
        except Exception as e:
            logger.error(f"Failed to initialize the I2C Client {self.client_id}: {e}")

    @property
    def is_successfully_initialized(self) -> bool:
        """Return the flag to indicate whether the client has been successfully initialized.
        This must be checked before starting the client."""
        return self._is_successfully_initialized

    @property
    def is_enabled(self) -> bool:
        """Return the flag to indicate whether the client is enabled to initiate the connection with the
        server (target sensors)."""
        return self._config.is_enabled

    @property
    def is_active(self) -> bool:
        """Return the flag to indicate whether the bus is active."""
        return self._bus_active_event.is_set() if self._bus_active_event else False

    @property
    def client_id(self) -> str:
        """Return the identifier of the I2C client."""
        return self._config.client_id if self._config else "Unknown"

    @property
    def bus_id(self) -> int:
        """Return the identifier of the I2C bus."""
        return self._config.bus_id if self._config else 0

    @property
    def is_acquiring_data(self) -> bool:
        """Return True if any sensors are currently acquiring time_series."""
        with self._lock:
            return len(self._active_acquisitions) > 0

    @property
    def sensors(self) -> list[str]:
        """Return a list of sensor IDs from the connected sensors."""
        if self._sensor_configs:
            return list(self._sensor_configs.keys())
        return []

    # === Public API Functions ===

    def start(self) -> bool:
        """
        Open the I2C bus, initialize configured sensors, and start time_series acquisition.

        Returns:
            bool: True if successfully opened the bus and started acquisition, False otherwise
        """
        if not self.is_successfully_initialized:
            raise RuntimeError(f"Unable to start the I2C Client {self.client_id}. Not Initialized.")

        with self._lock:
            if self._bus_active_event.is_set():
                logger.warning(f"I2C bus {self.bus_id} is already active")
                return True

            try:
                self._bus = smbus2.SMBus(self.bus_id)
                self._bus_active_event.set()
                self._start_data_acquisition()
                self._sensor_manager.start_monitoring()

                self._publish_client_info("Client has connected successfully.")
                logger.info(f"Successfully opened I2C bus {self.bus_id} and started time_series acquisition.")
                return True
            except Exception as e:
                logger.error(f"Error opening I2C bus {self.bus_id}: {e}")
                # Clean up if partially initialized
                if self._bus:
                    try:
                        self._bus.close()
                    except Exception as e:
                        logger.error(f"Error closing the partially opened I2C bus {self.bus_id}: {e}")
                    self._bus = None
                self._bus_active_event.clear()
                self._publish_client_info("Failed to connect the client.")
                return False

    def stop(self) -> bool:
        """
        Close the I2C bus and stop all sensor handlers.

        Returns:
            bool: True if successfully closed the bus, False otherwise
        """
        with self._lock:
            if not self._bus_active_event.is_set():
                logger.warning(f"I2C bus {self.bus_id} is not active")
                return True

            try:
                logger.info(f"Closing I2C bus {self.bus_id}...")
                self._sensor_manager.stop_monitoring()
                self._stop_data_acquisition()
                if self._bus:
                    self._bus.close()
                    self._bus = None
                self._bus_active_event.clear()

                # If I2C multiplexer is used, disable all channels
                if self._i2c_multiplexer and self._mux_channels and len(self._mux_channels) > 0:
                    self._i2c_multiplexer.disable_mux_channels(self._mux_channels)

                self._publish_client_info("Stopped the I2C client.")
                logger.info(f"Successfully closed I2C bus {self.bus_id}")
                return True
            except Exception as e:
                logger.error(f"Error closing I2C bus {self.bus_id}: {e}")
                self._bus_active_event.clear()
                self._bus = None
                return False

    def subscribe_to_events(self) -> None:
        """Subscribe to the events required by the client and its configured sensors."""
        logger.debug("Subscribing to events")

        try:
            sensor_configs = (self._sensor_configs or {}).values()
            for sensor_config in sensor_configs:
                if sensor_config['is_enabled'] and sensor_config['handler']:
                    sensor_handler = sensor_config['handler']
                    if sensor_handler is not None:
                        sensor_handler.subscribe_to_events()
        except Exception as e:
            logger.error(f"Error subscribing to events: {e}", exc_info=True)

    # === Local Functions ===

    def _initialize_sensor_handlers(self):
        """
        Initialize sensor handlers based on the configured sensors.

        This method calls the sensor initialization service to create
        sensor handlers for each configured sensor.
        """
        try:
            with self._lock:
                for sensor in self._config.sensors:

                    # Create a sensor configuration dictionary with all the necessary registry
                    sensor_config = ValidatedI2CSensorConfig(
                        sensor_id = sensor.sensor_id,
                        address = int(sensor.address, 16),
                        poll_interval=sensor.poll_interval,
                        is_enabled=sensor.is_enabled,
                        handler=None,  # Will be populated for sensor that is enabled
                        sensor_name=sensor.sensor_name,
                        sensor_type=sensor.sensor_type,
                        patient_id=sensor.patient_id,
                        device_type=sensor.device_type,
                        location=sensor.location,
                    )

                    # Even if the sensor is disabled, we still need to create a handler instance and
                    # store it in the configuration dictionary. The enabled flag is used to determine
                    # whether the sensor should start acquiring time_series or not

                    # Get the sensor handler
                    sensor_handler_provider = SensorHandlerProviderFactory.create_provider(sensor.device_type,
                                                                                           self._event_bus)
                    if sensor_handler_provider:
                        sensor_handler = sensor_handler_provider.get_handler(self,
                                                                             sensor.is_enabled,
                                                                             sensor.sensor_id,
                                                                             sensor.sensor_name,
                                                                             sensor.sensor_type,
                                                                             sensor.patient_id,
                                                                             sensor.location)

                        handler = cast(BaseI2CSensorHandler, sensor_handler)
                        if handler:
                            sensor_config['handler'] = handler
                            self._sensor_manager.add_sensor(handler)
                            logger.info(f"Registered sensor handler for {sensor.sensor_id}")
                        else:
                            logger.warning(f"No handler instance for {sensor.sensor_id}")

                    # Store the configuration dictionary using sensor_id as the key
                    self._sensor_configs[sensor.sensor_id] = sensor_config

        except Exception as e:
            logger.error(f"Error initializing sensor handlers: {e}", exc_info=True)
            raise

    def _initialize_i2x_mux(self):
        """
        Initialize the I2C mux, which is one of the options to multi-drop I2C sensors on the same bus.

        Note: I2C multiplexer is essential if the I2C sensors connected to the bus have the same address. In which case
        the Mux channel needs to be enabled/disabled to send commands to the sensor. I2C multiplexer can also be
        used as an alternative to Breadboard, I2C hub to multi-drop I2C sensors with unique addresses, in which case
        all channels can be enabled.

        This initialization must happen after the sensor handlers are initialized.
        """
        try:
            self._i2c_multiplexer = I2CMultiplexer(self._event_bus, self._config)
            self._mux_channels = []
            for sensor in self._config.sensors:
                if sensor and sensor.mux_channel_no >= 0:
                    self._mux_channels.append(sensor.mux_channel_no)
            # This logic will work if the sensors have unique addresses and the Mux is used only for
            # multi-drop i2c sensors. If the sensors have the same address, mux channel needs to be
            # enabled and disabled when polling the sensor
            if len(self._mux_channels) > 0:
                self._i2c_multiplexer.enable_mux_channels(self._mux_channels)

            # Validate the configured sensors on this bus using its addresses
            if self._sensor_configs:
                self._i2c_mux_sensor_addresses = self._i2c_multiplexer.get_i2c_sensor_address()
                for sensor_id, config in self._sensor_configs.items():
                    if config:
                        address = config['address']
                        if address in self._i2c_mux_sensor_addresses:
                             logger.info(f"Sensor {sensor_id} is enabled using I2C multiplexer")
                        else:
                            logger.warning(f"Sensor {sensor_id} is not enabled using I2C multiplexer")
        except Exception as e:
            logger.error(f"Error initializing i2c multiplexer: {e}", exc_info=True)
            raise

    def _start_data_acquisition(self) -> bool:
        """
        Start time_series acquisition for all enabled sensors.
        Uses each sensor handler's built-in acquisition mechanism.

        Returns:
            bool: True if at least one sensor started successfully, False otherwise
        """
        if not self._bus_active_event.is_set():
            logger.warning("Cannot start time_series acquisition: I2C bus is not active")
            return False

        successful_starts = 0
        with self._lock:
            for sensor_id, config in self._sensor_configs.items():
                if config['is_enabled'] and config['handler']:
                    handler = config['handler']
                    address = config['address']
                    poll_interval = config['poll_interval']
                    try:
                        # Use the handler's built-in acquisition method
                        handler.start_data_acquisition(self._bus, address, poll_interval)
                        logger.info(f"Started time_series acquisition for sensor {sensor_id}")
                        successful_starts += 1
                        self._active_acquisitions.add(sensor_id)
                    except Exception as e:
                        logger.error(f"Failed to start acquisition for sensor {sensor_id}: {e}")

            return successful_starts > 0

    def _stop_data_acquisition(self) -> bool:
        """
        Stop time_series acquisition for all sensors.

        Returns:
            bool: True if all sensors were successfully stopped or no sensors to stop
        """
        all_stopped = True
        with self._lock:
            if not self._sensor_configs:
                logger.info("No sensor handlers to stop")
                return True

            for sensor_id, config in self._sensor_configs.items():
                if config['is_enabled'] and config['handler']:
                    handler = config['handler']
                    try:
                        # Use the handler's built-in stop method
                        handler.stop_data_acquisition()
                        logger.info(f"Stopped time_series acquisition for sensor {sensor_id}")
                        self._active_acquisitions.discard(sensor_id)
                    except Exception as e:
                        logger.error(f"Failed to stop acquisition for sensor {sensor_id}: {e}")
                        all_stopped = False

            return all_stopped

    def _publish_client_info(self, message: str) -> None:
        """
        Publish I2C client registry to the event bus.

        Args:
            message (str): Custom message to be published.
        """
        if not self._event_bus:
            return

        try:
            # Create a client registry event for Redis
            client_info_event = I2CClientEvent(
                client_id = self.client_id,
                is_connected = self.is_active,
                i2c_bus_id = self.bus_id,
                sensors = self.sensors,
                message = message
            )

            # Publish to Redis Stream
            if not self._event_bus.shutdown_active:
                self._event_bus.publish(StreamName.I2C_CLIENT_CONNECTION_INFO_UPDATED.value, client_info_event)
        except Exception as e:
            logger.error(f"Error publishing registry for the client '{self.client_id}' to Redis Stream: {e}")