#!/usr/bin/env python3
# -----------------------------------------------------------------------------
# Filename: repository_manager.py
# Author: Rajaram Lakshmanan
# Description:  Manage different repositories (databases) to store edge gateway
# registry, sensor registry, and sensor process data.
# License: MIT (see LICENSE)
# -----------------------------------------------------------------------------

import logging
import os
from pathlib import Path
from typing import Optional

from config.models.repository.repository_manager_config import RepositoryManagerConfig
from repository.edge_gateway.edge_gateway_registry_manager import EdgeGatewayRegistryManager
from repository.edge_gateway.edge_gateway_registry_event_consumer import EdgeGatewayRegistryEventConsumer
from repository.sensor.registry.sensor_registry_manager import SensorRegistryManager
from repository.sensor.registry.sensor_registry_event_consumer import SensorRegistryEventConsumer
from repository.sensor.time_series.sensor_time_series_repository import SensorTimeSeriesRepository
from event_bus.redis_stream_bus.redis_stream_bus import RedisStreamBus

logger = logging.getLogger("RepositoryManager")

class RepositoryManager:
    """
    Manager class that coordinates access to all repository services.
    Acts as a facade for different database services in the system.
    """

    def __init__(self, event_bus: RedisStreamBus, config: RepositoryManagerConfig):
        """
        Initialize the repository manager with configuration.

        Args:
            event_bus: Redis event bus for communication
            config: Application configuration containing repository settings
        """
        self._event_bus = event_bus
        self.config = config

        # Ensure the base database directory exists
        self.base_db_dir = Path("./repository/database")
        self.base_db_dir.mkdir(parents=True, exist_ok=True)

        # Edge Gateway registry components
        self.edge_gateway_registry_manager: Optional[EdgeGatewayRegistryManager] = None
        self.edge_gateway_registry_event_consumer: Optional[EdgeGatewayRegistryEventConsumer] = None

        # Sensor Registry components
        self.sensor_registry_manager: Optional[SensorRegistryManager] = None
        self.sensor_registry_event_consumer: Optional[SensorRegistryEventConsumer] = None

        # Sensor Time Series component
        self.sensor_time_series_repository: Optional[SensorTimeSeriesRepository] = None

        # Initialize repositories based on configuration
        self._initialize_repositories()

        logger.info("Repository manager initialized successfully")

    def stop(self):
        """Gracefully stop all repository components."""
        logger.info("Shutting down repository components...")

        # Close Time Series repository connections
        if hasattr(self, 'sensor_time_series_repository') and self.sensor_time_series_repository:
            try:
                self.sensor_time_series_repository.close()
                logger.info("Sensor Time Series Repository closed")
            except Exception as e:
                logger.error(f"Error closing Sensor Time Series Repository: {e}")

        # TODO Add any other cleanup needed for SQLite databases
        # SQLite connections are typically closed after each operation, but we could add explicit
        # cleanup here if needed

        logger.info("Repository components shutdown complete")

    def subscribe_to_events(self) -> None:
        """Subscribe to relevant event streams."""
        # Define consumer group name for the web server
        logger.debug("Subscribing to events")

        try:
            if self.edge_gateway_registry_event_consumer:
                self.edge_gateway_registry_event_consumer.subscribe_to_events()

            if self.sensor_registry_event_consumer:
                self.sensor_registry_event_consumer.subscribe_to_events()

            if self.sensor_time_series_repository:
                self.sensor_time_series_repository.subscribe_to_events()
        except Exception as e:
            logger.error(f"Error subscribing to events: {e}", exc_info=True)

    def _initialize_repositories(self):
        """Initialize all repository services based on configuration."""
        logger.info("Initializing repository services...")

        # Initialize Edge Gateway SQLite storage
        if hasattr(self.config, 'edge_gateway_db') and self.config.edge_gateway_db.is_enabled:
            logger.info("Initializing Edge Gateway Registry SQLite storage...")
            self._initialize_edge_gateway_registry()

        # Initialize Sensor Registry SQLite storage
        if hasattr(self.config, 'sensor_registry_db') and self.config.sensor_registry_db.is_enabled:
            logger.info("Initializing Sensor Registry SQLite storage...")
            self._initialize_sensor_registry()

        # Initialize Sensor Time Series InfluxDB storage
        if hasattr(self.config, 'sensor_time_series') and self.config.sensor_time_series.is_enabled:
            logger.info("Initializing Sensor Time Series InfluxDB storage...")
            self._initialize_sensor_time_series()

    def _initialize_edge_gateway_registry(self):
        """Initialize Edge Gateway Registry SQLite storage components."""
        try:
            # Get the SQLite database directory from config or use default
            db_dir = getattr(self.config.edge_gateway_db, 'db_dir',
                             str(self.base_db_dir / "edge_gateway_registry"))

            # Ensure the directory exists
            os.makedirs(db_dir, exist_ok=True)

            # Initialize the database manager
            self.edge_gateway_registry_manager = EdgeGatewayRegistryManager(db_dir=db_dir)

            # Configure record limits if specified in config
            if hasattr(self.config.edge_gateway_db, 'record_limits'):
                self.edge_gateway_registry_manager._record_limits = self.config.edge_gateway_db.record_limits
            else:
                # Use default record limits
                self.edge_gateway_registry_manager._record_limits = EdgeGatewayRegistryManager.get_default_record_limits()

            # Initialize the event consumer
            self.edge_gateway_registry_event_consumer = EdgeGatewayRegistryEventConsumer(
                event_bus=self._event_bus,
                db_manager=self.edge_gateway_registry_manager
            )

            logger.info(f"Edge Gateway Registry SQLite storage initialized with database directory: {db_dir}")
        except Exception as e:
            logger.error(f"Failed to initialize Edge Gateway Registry SQLite storage: {e}")
            raise

    def _initialize_sensor_registry(self):
        """Initialize Sensor Registry SQLite storage components."""
        try:
            # Get the SQLite database directory from config or use default
            db_dir = getattr(self.config.sensor_registry_db, 'db_dir',
                             str(self.base_db_dir / "sensor_registry"))

            # Ensure the directory exists
            os.makedirs(db_dir, exist_ok=True)

            # Initialize the database manager
            self.sensor_registry_manager = SensorRegistryManager(db_dir=db_dir)

            # Configure record limits if specified in config
            if hasattr(self.config.sensor_registry_db, 'record_limits'):
                self.sensor_registry_manager._record_limits = self.config.sensor_registry_db.record_limits

            # Initialize the event consumer
            self.sensor_registry_event_consumer = SensorRegistryEventConsumer(
                event_bus=self._event_bus,
                db_manager=self.sensor_registry_manager
            )

            logger.info(f"Sensor Registry SQLite storage initialized with database directory: {db_dir}")
        except Exception as e:
            logger.error(f"Failed to initialize Sensor Registry SQLite storage: {e}")
            raise

    def _initialize_sensor_time_series(self):
        """Initialize Sensor Time Series InfluxDB storage components."""
        try:
            # Configure paths for token and key files
            token_dir = self.base_db_dir / "sensor_time_series"
            token_dir.mkdir(exist_ok=True)

            # Get configuration values with defaults
            token_file = getattr(self.config.sensor_time_series, 'token_file',
                                 str(token_dir / "influx_token.enc"))
            key_file = getattr(self.config.sensor_time_series, 'key_file',
                               str(token_dir / "influx_token.key"))

            # Get other settings from config
            url = getattr(self.config.sensor_time_series, 'url', 'http://localhost:8086')
            token = getattr(self.config.sensor_time_series, 'token', None)
            org = getattr(self.config.sensor_time_series, 'org', 'health_monitoring')
            bucket = getattr(self.config.sensor_time_series, 'bucket', 'sensor_data')

            # Optional batch settings
            write_buffer_size = getattr(self.config.sensor_time_series, 'write_buffer_size', 100000)
            batch_size = getattr(self.config.sensor_time_series, 'batch_size', 1000)
            batch_interval_ms = getattr(self.config.sensor_time_series, 'batch_interval_ms', 5000)
            max_retries = getattr(self.config.sensor_time_series, 'max_retries', 5)

            # Initialize the time series repository
            self.sensor_time_series_repository = SensorTimeSeriesRepository(
                event_bus=self._event_bus,
                url=url,
                token=token,
                org=org,
                bucket=bucket,
                token_file=token_file,
                key_file=key_file,
                write_buffer_size=write_buffer_size,
                batch_size=batch_size,
                batch_interval_ms=batch_interval_ms,
                max_retries=max_retries
            )

            logger.info(f"Sensor Time Series Repository initialized with bucket: {bucket}")
        except Exception as e:
            logger.error(f"Failed to initialize Sensor Time Series Repository: {e}")
            raise