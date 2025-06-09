#!/usr/bin/env python3
# -----------------------------------------------------------------------------
# Filename: health_monitor.py
# Author: Rajaram Lakshmanan
# Description:  Main Application.
# License: MIT (see LICENSE)
# -----------------------------------------------------------------------------

import os
import signal
import sys
import logging
import threading
import time
from logging.handlers import RotatingFileHandler
import argparse
from typing import Optional

from config.config_manager import ConfigManager
from config.models.health_monitoring_config import HealthMonitorConfig
from edge_gateway.edge_gateway import EdgeGateway
from event_bus.models.sensor.sensor_metadata_event import SensorMetadataEvent
from event_bus.redis_manager import RedisManager
from event_bus.redis_stream_bus.redis_stream_bus import RedisStreamBus
from client.ble.ble_client_manager import BleClientManager
from client.i2c.i2c_client_manager import I2CClientManager
from cloud.cloud_sync_manager import CloudSyncManager
from event_bus.stream_name import StreamName
from repository.repository_manager import RepositoryManager
from gui.web_server import WebServer

logger = logging.getLogger("HealthMonitor")

class HealthMonitor:
    """Main health monitoring application class."""

    def __init__(self, config_path: str = 'config/config.yaml'):
        """
        Initialize the health monitoring application.

        Args:
            config_path: Path to the configuration file.
        """
        self._config_path = config_path
        self._config: Optional[HealthMonitorConfig] = None

        self._redis_manager: Optional[RedisManager] = None
        self._event_bus: Optional[RedisStreamBus] = None

        self._edge_gateway: Optional[EdgeGateway] = None

        self._ble_client_manager: Optional[BleClientManager] = None
        self._i2c_client_manager: Optional[I2CClientManager] = None

        self._cloud_sync_manager: Optional[CloudSyncManager] = None
        self._cloud_sync_manager = None

        self._repository_manager: Optional[RepositoryManager] = None

        self._web_server: Optional[WebServer] = None
        self._web_server_thread = None

        # Flag to control the main loop
        self._heartbeat = 0
        self._running = False

        # Register signal handlers for graceful shutdown
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    # === Public API Functions ===

    def start(self):
        """Start the health monitoring application."""
        try:
            # Load configuration
            self._load_configuration()

            # Set up logging
            self._setup_logging()

            # Log application registry
            logger.info(f"Starting health monitoring application: {self._config.app.name}")
            logger.info(f"Version: {self._config.app.version}")

            # Initialize components
            self._initialize_components()

            # Run the application
            self._run()

        except Exception as e:
            logger.error(f"Error running application: {e}", exc_info=True)
            sys.exit(1)

        logger.info("Application shutdown complete")

    # === Local Functions ===

    def _setup_logging(self):
        """Set up logging based on configuration."""
        try:
            root_logger = logging.getLogger()
            root_logger.setLevel(getattr(logging, self._config.logging.level.upper(), logging.INFO))

            # Clear any old handlers (important!)
            if root_logger.hasHandlers():
                root_logger.handlers.clear()

            # Console handler
            console_handler = logging.StreamHandler(sys.stdout)
            console_handler.setLevel(root_logger.level)
            console_formatter = logging.Formatter(self._config.logging.format)
            console_handler.setFormatter(console_formatter)
            root_logger.addHandler(console_handler)

            # File handler
            if self._config.logging.handlers.get("file", {}).get("is_enabled", False):
                file_config = self._config.logging.handlers.get("file", {})

                file_path = file_config.get("path", "health_monitor.log")
                max_size_mb = file_config.get("max_size_mb", 10)
                backup_count = file_config.get("backup_count", 5)

                os.makedirs(os.path.dirname(file_path), exist_ok=True)

                file_handler = RotatingFileHandler(
                    file_path,
                    maxBytes=max_size_mb * 1024 * 1024,
                    backupCount=backup_count
                )
                file_handler.setLevel(root_logger.level)
                file_formatter = logging.Formatter(self._config.logging.format)
                file_handler.setFormatter(file_formatter)
                root_logger.addHandler(file_handler)

            logger.info("Logging configured successfully")
        except Exception as e:
            # Using print as logging might not be available
            print(f"Error setting up logging: {e}")
            raise

    def _load_configuration(self):
        """Load the application configuration."""
        config_manager = ConfigManager()
        try:
            self._config = config_manager.load(self._config_path)
        except FileNotFoundError as e:
            logger.error(f"Error: {e}")
            raise
        except ValueError as e:
            logger.error(f"Configuration validation error: {e}")
            raise

    def _initialize_components(self):
        """Initialize all the components required by the health monitoring application.

        Note: All components must be initialized successfully, if any of the components fail to initialize,
        the application will exit.
        """
        logger.info("Initializing components...")

        self._initialize_event_bus()
        self._initialize_edge_gateway()

        self._initialize_ble_client_manager()
        self._initialize_i2c_client_manager()

        # Initialize the Client manager(s) first, as this will be passed to the cloud sync manager
        # This is to handle Client connection events in the cloud sync manager
        self._initialize_cloud_sync_manager()

        self._initialize_repository_manager()

        self._initialize_web_server()

    def _initialize_event_bus(self):
        """Initialize the event bus based on configuration."""
        try:
            logger.info("Initializing event bus...")

            # First, ensure Redis is running
            max_retries = 3
            retry_delay = 2

            for attempt in range(max_retries):
                try:
                    # This initialization includes starting the Redis server, Event (Stream) bus
                    # will be started separately
                    self._redis_manager = RedisManager(self._config.event_bus.redis)
                    if self._redis_manager.start():
                        break
                except Exception as ex:
                    if attempt == max_retries - 1:
                        logger.error(f"Failed to initialize Redis after maximum retries: {ex}")
                        os.kill(os.getpid(), signal.SIGTERM)
                    else:
                        logger.warning(f"Redis initialization attempt {attempt + 1} failed, retrying...")
                        time.sleep(retry_delay)

            self._event_bus = RedisStreamBus(
                host=self._config.event_bus.redis.host,
                port=self._config.event_bus.redis.port,
                db=self._config.event_bus.redis.db
            )

            # Redis stream must register all allowed streams on the event bus
            # Sensor metadata stream is common to all sensors, so it must be at the application level. Other
            # required streams will be registered by the respective objects
            self._event_bus.register_stream(StreamName.SENSOR_METADATA_CREATED.value, SensorMetadataEvent)

            logger.info("Event bus initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize and start the event bus: {e}", exc_info=True)
            # This is critical - exit if event bus can't start
            os.kill(os.getpid(), signal.SIGTERM)

    def _initialize_edge_gateway(self):
        """Initialize Edge Gateway, which is the central component to the health monitoring
        architecture."""
        logger.info("Initializing Edge Gateway...")
        try:
            if self._config.edge_gateway:
                self._edge_gateway = EdgeGateway(self._event_bus, self._config.edge_gateway)
                logger.info("Edge Gateway initialized successfully.")
            else:
                logger.error("Failed to initialize Edge Gateway: No Cloud Sync configuration found.")
        except Exception as e:
            logger.error(f"Failed to initialize Edge Gateway: {e}", exc_info=True)
            raise

    def _initialize_ble_client_manager(self):
        """Initialize BLE client manager based on configuration."""
        logger.info("Initializing BLE client manager...")
        try:
            if self._config.ble_client_manager.is_enabled:
                logger.info(
                    f"BLE communication is enabled. "
                    f"Initializing {len(self._config.ble_client_manager.clients)} BLE clients...")
                self._ble_client_manager = BleClientManager(self._event_bus, self._config.ble_client_manager)
            else:
                logger.info("BLE communication is disabled")
        except Exception as e:
            logger.error(f"Failed to initialize BLE client manager: {e}", exc_info=True)
            raise

    def _initialize_i2c_client_manager(self):
        """Initialize I2C client manager based on configuration."""
        logger.info("Initializing I2C client manager...")
        try:
            if self._config.i2c_client_manager.is_enabled:
                logger.info(
                    f"I2C communication is enabled. Initializing {len(self._config.i2c_client_manager.clients)} I2C clients...")
                self._i2c_client_manager = I2CClientManager(self._event_bus, self._config.i2c_client_manager)
            else:
                logger.info("I2C communication is disabled")
        except Exception as e:
            logger.error(f"Failed to initialize I2C client manager: {e}", exc_info=True)
            raise

    def _initialize_cloud_sync_manager(self):
        """Initialize the cloud synchronization manager based on configuration."""
        logger.info("Initializing cloud synchronization manager...")
        try:
            if self._config.cloud_sync_manager.is_enabled:
                logger.info("Cloud Synchronization is enabled.")
                self._cloud_sync_manager = CloudSyncManager(self._event_bus,
                                                            self._config.cloud_sync_manager,
                                                            self._config)
            else:
                logger.info("Cloud synchronization is disabled")
        except Exception as e:
            logger.error(f"Failed to initialize cloud sync manager: {e}", exc_info=True)
            raise

    def _initialize_repository_manager(self):
        """Initialize time_series repository based on configuration."""
        logger.info("Initializing repository services for back-end local storage...")
        try:
            if self._config.repository_manager.is_enabled:
                logger.info("Repository service is enabled")
                self._repository_manager = RepositoryManager(self._event_bus, self._config.repository_manager)
            else:
                logger.info("Repository service is disabled")
        except Exception as e:
            logger.error(f"Failed to initialize repository: {e}", exc_info=True)
            raise

    def _initialize_web_server(self):
        """Initialize the web server based on configuration."""
        logger.info("Initializing web server...")
        try:
            if self._config.web_server.is_enabled:
                self._web_server = WebServer(
                    self._event_bus,
                    self._ble_client_manager,
                    self._i2c_client_manager
                )
                logger.info("Web server initialized successfully")
            else:
                logger.info("Web server is disabled")
        except Exception as e:
            logger.error(f"Failed to initialize web server: {e}", exc_info=True)

    def _subscribe_events(self):
        """Once all the components are initialized, the 'consumers' have to subscribe to all the required events.
        """
        logger.info("Events Subscriptions...")

        # Configuration contains the information on the services enabled to register for events, this is
        # essential for all consumers
        if self._web_server:
            self._web_server.subscribe_to_events(self._config)
            logger.info("Web Server events subscriptions completed successfully.")

        if self._cloud_sync_manager:
            self._cloud_sync_manager.subscribe_to_events()
            logger.info("Cloud Sync Manager events subscriptions completed successfully.")

        if self._repository_manager:
            self._repository_manager.subscribe_to_events()

        if self._edge_gateway:
            self._edge_gateway.subscribe_to_events()
            logger.info("Edge Gateway events subscriptions completed successfully.")

        if self._ble_client_manager:
            self._ble_client_manager.subscribe_to_events()
            logger.info("BLE Client Manager events subscriptions completed successfully.")

        if self._i2c_client_manager:
            self._i2c_client_manager.subscribe_to_events()
            logger.info("I2C Client Manager events subscriptions completed successfully.")

    def _start_components(self):
        """Start all initialized components.

        Note: All components must be started successfully, if any of the components fail to start,
        the application will exit. If any components are initialized, this needs to be shutdown before exiting
        the application.
        """
        logger.info("Starting components...")

        # Start the event bus first
        if self._event_bus:
            self._event_bus.start()
            logger.info("Event bus started")

        # Start all the consumers before "producers". Consumers are Cloud Sync, Web Server (Web GUI), Repositories
        if self._cloud_sync_manager:
            try:
                self._cloud_sync_manager.start()
                logger.info("Cloud sync manager started")
            except Exception as e:
                logger.error(f"Failed to start cloud sync manager: {e}", exc_info=True)
                os.kill(os.getpid(), signal.SIGTERM)

        # Start web server
        if self._web_server:
            try:
                # Start in a daemon thread
                self._web_server_thread = threading.Thread(
                    target=self._web_server.start,
                    kwargs={
                        'host': self._config.web_server.host,
                        'port': self._config.web_server.port,
                        'debug': self._config.web_server.debug
                    },
                    daemon=True
                )
                self._web_server_thread.start()
                logger.info(f"Web server started on {self._config.web_server.host}:{self._config.web_server.port}")
            except Exception as e:
                logger.error(f"Failed to start web server: {e}", exc_info=True)

        # Start the Edge Gateway. Edge gateway has a scheduled publication of events, which will
        # start immediately as a one-off when the application has started
        if self._edge_gateway:
            self._edge_gateway.start()
            logger.info("Edge Gateway started")

        # Initialize the Client manager(s) once all "consumer" components are started; this is to make sure
        # no publishing events from the clients or sensors are missed by other interested consumers.
        # Consumers are Cloud Sync, Web Server (Web GUI), Repositories

        # Start BLE client manager
        if self._ble_client_manager:
            try:
                self._ble_client_manager.start()
                logger.info("BLE client manager started")
            except Exception as e:
                logger.error(f"Failed to start BLE client manager: {e}", exc_info=True)
                os.kill(os.getpid(), signal.SIGTERM)

        # Start I2C client manager
        if self._i2c_client_manager:
            try:
                self._i2c_client_manager.start()
                logger.info("I2C client manager started")
            except Exception as e:
                logger.error(f"Failed to start I2C client manager: {e}", exc_info=True)
                os.kill(os.getpid(), signal.SIGTERM)

        logger.info("All components started")

        # Add Redis diagnostics
        from event_bus.redis_diagnostics import diagnose_redis_streams

        # Use the same Redis settings as your event bus
        redis_host = self._config.event_bus.redis.host
        redis_port = self._config.event_bus.redis.port
        redis_db = self._config.event_bus.redis.db

        # Run diagnostics
        diagnose_redis_streams(host=redis_host, port=redis_port, db=redis_db)

        logger.info("All components started")

    def _stop_components(self):
        """Gracefully shut down all components."""
        logger.info("Shutting down components...")

        if self._event_bus:
            # Set a flag to indicate shutdown in progress - to be added to all components
            self._event_bus.initiate_shutdown()

        if self._edge_gateway:
            self._edge_gateway.stop()
            logger.info("Edge Gateway stopped")

        # First, stop all time_series producers
        if self._web_server:
            logger.info("Shutting down web server...")
            self._web_server.stop()
            # Wait for the web server to fully stop
            if self._web_server_thread and self._web_server_thread.is_alive():
                self._web_server_thread.join(timeout=5)
                logger.info("Web server stopped")

        if self._i2c_client_manager:
            logger.info("Shutting down I2C client manager...")
            self._i2c_client_manager.stop()
            # Add a small delay to allow final messages to process
            time.sleep(0.5)

        if self._ble_client_manager:
            logger.info("Shutting down BLE client manager...")
            self._ble_client_manager.stop()
            # Add a small delay to allow final messages to process
            time.sleep(0.5)

        if self._repository_manager:
            logger.info("Shutting down repository...")
            self._repository_manager.stop()
            # Add a small delay to allow final messages to process
            time.sleep(0.5)

        if self._cloud_sync_manager:
            logger.info("Shutting down cloud sync manager...")
            self._cloud_sync_manager.stop()
            # Add a small delay to allow final messages to process
            time.sleep(0.5)

        # This must be the last one to be shutdown - event bus (and Redis)
        # Wait a moment to ensure all pending messages are processed
        time.sleep(1)

        if self._event_bus:
            logger.info("Shutting down event bus...")
            self._event_bus.stop()
            # Wait for all event processing to complete
            time.sleep(1)

        if self._redis_manager:
            logger.info("Stopping the Redis manager...")
            self._redis_manager.stop()

        logger.info("All components shut down successfully")

    def _signal_handler(self, sig, _frame):
        """Handle termination signals for a graceful shutdown."""
        logger.info(f"Received signal {sig}, initiating shutdown...")
        self._running = False

    def _run(self):
        """Run the application."""
        # Consumers must subscribe to the events after the event bus and other components are initialized
        self._subscribe_events()

        # Start all components
        self._start_components()

        self._running = True
        try:
            while self._running:
                # Small sleep to avoid spinning the CPU at 100%
                self._heartbeat += 1
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("Application shutdown requested via keyboard interrupt")
        except Exception as e:
            logger.error(f"Unexpected error in main loop: {e}", exc_info=True)
        finally:
            self._stop_components()

def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description='Health Monitoring System')
    parser.add_argument('-c', '--config', type=str, default='config/config.yaml',
                        help='Path to configuration file (default: config/config.yaml)')
    return parser.parse_args()


def main():
    """Main application entry point."""
    # Parse command line arguments
    args = parse_arguments()

    # Create and start the health monitor
    health_monitor = HealthMonitor(config_path=args.config)
    health_monitor.start()

if __name__ == "__main__":

    main()