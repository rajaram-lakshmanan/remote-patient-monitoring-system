#!/usr/bin/env python3
# -----------------------------------------------------------------------------
# Filename: i2c_client_manager.py
# Author: Rajaram Lakshmanan
# Description:  Manager for I2C clients.
# License: MIT (see LICENSE)
# -----------------------------------------------------------------------------

import logging
from typing import Dict, Optional

from client.common.base_client_manager import BaseClientManager
from client.i2c.i2c_client import I2CClient
from config.models.i2c.i2c_client_config import I2CClientConfig
from config.models.i2c.i2c_client_manager_config import I2CClientManagerConfig
from event_bus.models.client.i2c_client_event import I2CClientEvent
from event_bus.redis_stream_bus.redis_stream_bus import RedisStreamBus
from event_bus.stream_name import StreamName

logger = logging.getLogger("I2CClientManager")


class I2CClientManager(BaseClientManager[I2CClient, I2CClientManagerConfig]):
    """
    Manager for I2C clients.

    This manager is responsible for creating and managing I2C clients,
    ensuring each bus has only one client instance, and handling the
    initial configuration of clients based on the provided configuration.

    Note: I2C client(s) is different to the BLE client. I2C connections are physical
    connections to sensors through the I2C bus on the edge gateway (e.g., Raspberry Pi).
    Multiple sensors can be connected to the same I2C bus, each with a unique address.
    """

    def __init__(self, event_bus: RedisStreamBus, config: I2CClientManagerConfig):
        """
        Initialize the I2C Client Manager.

        Args:
            event_bus (RedisStreamBus): The event bus for publishing events.
            config (I2CClientManagerConfig): I2C Client Manager configuration.
        """
        super().__init__(event_bus, config)

        # Initialize clients from configuration
        self._init_configured_clients()

        # Finally, register to the event bus to publish BLE client connection registry; this is at the global
        # level, hence registering at the manager
        self._event_bus.register_stream(StreamName.I2C_CLIENT_CONNECTION_INFO_UPDATED.value, I2CClientEvent)

        logger.info("I2CClientManager initialized")

    # === Public API Functions ===

    def start(self) -> None:
        """Start I2C operations for all clients."""
        logger.info("Starting I2C client manager")

        # Start all configured clients
        for client_id in self._clients:
            try:
                i2c_client = self.get_client(client_id)
                if i2c_client and i2c_client.is_enabled:
                     self._start_client(client_id)
            except Exception as e:
                logger.error(f"Error starting I2C client '{client_id}': {e}")

    def stop(self) -> None:
        """Clean up resources and stop all clients."""
        logger.info("Stopping I2CClientManager")

        # Start all configured clients
        for client_id in self._clients:
            try:
                self._stop_client(client_id)
            except Exception as e:
                logger.error(f"Error stopping I2C client '{client_id}': {e}")

        # Clear client registry
        with self._lock:
            self._clients.clear()

        logger.info("I2CClientManager stopped")

    def get_client(self, client_id: str) -> Optional[I2CClient]:
        """
        Get a client by client ID.

        Args:
            client_id: The client ID.

        Returns:
            I2CClient: The client instance or None if not found.
        """
        with self._lock:
            for client in self._clients.values():
                if client.client_id == client_id:
                    return client
            return None

    def get_all_clients(self) -> Dict[str, I2CClient]:
        """
        Get all clients.

        Returns:
            dict: Dictionary mapping client_id to the client.
        """
        with self._lock:
            return dict(self._clients)

    # === Local Functions ===

    def _init_configured_clients(self) -> None:
        """Initialize clients from configuration."""
        for i2c_client_config in self._config.clients:
            try:
                # Create the I2C client for this bus
                client = self._create_i2c_client(i2c_client_config)
                logger.info(f"Successfully initialized I2C client '{client.client_id}' for bus {client.bus_id}")
            except Exception as e:
                logger.error(f"Error initializing I2C client for bus {i2c_client_config.bus_id}: {e}")

    def _create_i2c_client(self, i2c_client_config: I2CClientConfig) -> I2CClient:
        """
        Create a new I2C client for a specific bus.

        Args:
            i2c_client_config (I2CClientConfig): I2C client configuration.

        Returns:
            I2CClient: The created client.
        """
        with self._lock:
            # Check if the client for this bus already exists
            if i2c_client_config.client_id in self._clients:
                logger.warning(f"Client '{i2c_client_config.client_id}' already exists, returning existing client")
                return self._clients[i2c_client_config.client_id]

            logger.info(f"Creating new I2C client '{i2c_client_config.client_id}' for bus: {i2c_client_config.bus_id}")
            client = I2CClient(self._event_bus, i2c_client_config)
            self._clients[i2c_client_config.client_id] = client
            return client

    def _start_client(self, client_id: str) -> bool:
        """
        Start a specific I2C client.

        Args:
            client_id (str): The ID of the client to start.

        Returns:
            bool: True if the client was started successfully, False otherwise.
        """
        client = self.get_client(client_id)
        if not client:
            logger.warning(f"Client '{client_id}' not found")
            return False

        logger.info(f"Starting client '{client_id}'")
        success = client.start()
        if success:
            logger.info(f"Successfully started I2C client {client.client_id} for bus {client.bus_id}")
        else:
            logger.error(f"Failed to start I2C client {client.client_id} for bus {client.bus_id}")

        return success

    def _stop_client(self, client_id: str) -> bool:
        """
        Stop a specific I2C client.

        Args:
            client_id (str): The ID of the client to stop.

        Returns:
            bool: True if the client was stopped successfully, False otherwise.
        """
        client = self.get_client(client_id)
        if not client:
            logger.warning(f"Client '{client_id}' not found")
            return False

        # Stop the client
        success = client.stop()
        return success