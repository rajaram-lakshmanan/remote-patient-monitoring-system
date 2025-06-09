#!/usr/bin/env python3
# -----------------------------------------------------------------------------
# Filename: ble_client_manager.py
# Author: Rajaram Lakshmanan
# Description:  Manager for BLE clients.
# License: MIT (see LICENSE)
# -----------------------------------------------------------------------------

import logging
import time
import threading
from typing import Dict, Optional

from client.common.base_client_manager import BaseClientManager
from client.ble.ble_client.ble_client import BleClient
from config.models.ble.ble_client_config import BleClientConfig
from config.models.ble.ble_client_manager_config import BleClientManagerConfig
from event_bus.models.client.ble_client_event import BleClientEvent
from event_bus.redis_stream_bus.redis_stream_bus import RedisStreamBus
from event_bus.stream_name import StreamName

logger = logging.getLogger("BleClientManager")


class BleClientManager(BaseClientManager[BleClient, BleClientManagerConfig]):
    """
    Manager for BLE clients.

    This manager is responsible for creating and managing BLE clients,
    handling connection state, and providing a central point of access
    to BLE devices.
    """

    def __init__(self, event_bus: RedisStreamBus, config: BleClientManagerConfig):
        """
        Initialize the BLE Client Manager.

        Args:
            event_bus (RedisStreamBus): The event bus for publishing events.
            config (BleClientManagerConfig): BLE Client Manager configuration.
        """
        super().__init__(event_bus, config)

        # Thread management
        self._monitoring_thread = None
        self._monitoring_active = False
        self._client_threads = {}

        self._terminate_event = threading.Event()

        # Initialize clients from configuration
        self._init_configured_clients()

        # Finally, register to the event bus to publish BLE client connection registry; this is at the global
        # level, hence registering at the manager
        self._event_bus.register_stream(StreamName.BLE_CLIENT_CONNECTION_INFO_UPDATED.value, BleClientEvent)

        logger.info("BleClientManager initialized")

    # === Public API Functions ===

    def start(self) -> None:
        """Start BLE operations and connect all clients."""
        logger.info("Starting BLE client manager")

        # Start connecting all configured clients
        for client_id in self._clients:
            try:
                logger.info(f"Starting client {client_id}")
                self._start_client(client_id)
            except Exception as e:
                logger.error(f"Error starting client {client_id}: {e}")

        # Start connection monitoring if auto reconnect is enabled
        if self._config.auto_reconnect:
            self._start_connection_monitoring()

    def stop(self) -> None:
        """Clean up resources and disconnect all clients."""
        logger.info("Stopping BleClientManager")

        # Stop monitoring
        self._terminate_event.set()  # Signal termination
        self._monitoring_active = False

        # Wait for the monitoring thread to finish
        if self._monitoring_thread and self._monitoring_thread.is_alive():
            logger.debug("Waiting for monitoring thread to finish...")
            self._monitoring_thread.join(5.0)  # Wait up to 5 seconds

            # Check after a join attempt
            if self._monitoring_thread.is_alive():
                logger.warning("Monitoring thread did not terminate within the timeout period")

        with self._lock:
            client_ids = list(self._clients.keys())

        for client_id in client_ids:
            self._stop_client(client_id)

        # Check for any remaining threads
        remaining_threads = []
        with self._lock:
            for client_id, thread in list(self._client_threads.items()):
                if thread.is_alive():
                    remaining_threads.append(client_id)

        if remaining_threads:
            logger.warning(
                f"BleClientManager stop() completed with threads still running for clients: {remaining_threads}")

        # Clear all clients
        with self._lock:
            self._clients.clear()
            self._client_threads.clear()

        logger.info("BleClientManager stopped")

    def get_client(self, client_id: str) -> Optional[BleClient]:
        """
        Get a client by ID.

        Args:
            client_id (str): ID of the client to retrieve.

        Returns:
            BleClient: The client instance or None if not found.
        """
        with self._lock:
            return self._clients.get(client_id)

    def get_all_clients(self) -> Dict[str, BleClient]:
        """
        Get all clients.

        Returns:
            dict: Dictionary of all clients, keyed by client_id.
        """
        with self._lock:
            # Return a copy to avoid threading issues
            return dict(self._clients)

    # === Local Functions ===

    def _init_configured_clients(self) -> None:
        """Initialize clients from configuration."""
        ble_clients = self._config.clients

        for ble_client in ble_clients:
            try:
                # Create the client
                client = self._create_ble_client(ble_client)
                if not client:
                    logger.error(f"Failed to create client {ble_client.client_id}")
                    continue
            except Exception as e:
                logger.error(f"Error initializing client {ble_client.client_id}: {e}", exc_info=True)

    def _create_ble_client(self, ble_client_config: BleClientConfig) -> Optional[BleClient]:
        """
        Create a new BLE client.

        Args:
            ble_client_config (BleClientConfig): Configuration model of the BLE Client.

        Returns:
            BleClient: The created client or None if creation failed.
        """
        with self._lock:
            if ble_client_config.client_id in self._clients:
                logger.warning(f"Client {ble_client_config.client_id} already exists, returning existing client")
                return self._clients[ble_client_config.client_id]

            logger.info(f"Creating new BLE client: {ble_client_config.client_id}")
            try:
                client = BleClient(self._event_bus, ble_client_config)
                client.set_on_disconnect_callback(self._handle_client_disconnect)
                self._clients[ble_client_config.client_id] = client
                return client
            except Exception as e:
                logger.error(f"Error creating client {ble_client_config.client_id}: {e}", exc_info=True)
                return None

    def _start_client(self, client_id: str) -> None:
        """
        Start a client connection in a separate thread.

        Args:
            client_id (str): The client ID to connect.
        """
        client = self.get_client(client_id)
        if client and client.is_enabled:
            # Stop any existing thread for this client
            self._stop_client_thread(client.client_id)

            # Create and start a new thread that calls the client's run method
            thread = threading.Thread(
                target=self._start_client_thread,
                name=f"connect-{client.client_id}",
                args=(client,),
                daemon=True
            )

            with self._lock:
                self._client_threads[client.client_id] = thread

            thread.start()
            logger.info("Started connection thread", extra={
                "client_id": client.client_id,
                "thread_name": thread.name,
                "BLE device name": client.device_name
            })
        else:
            logger.error(f"Unable to start the Client with ID '{client_id}'. Client not found.")

    def _stop_client(self, client_id: str) -> bool:
        """
        Disconnect a specific client.

        Args:
            client_id (str): ID of the client to disconnect.

        Returns:
            bool: True if the client was disconnected, False otherwise.
        """
        client = self.get_client(client_id)
        if not client:
            logger.warning(f"Client {client_id} not found")
            return False

        # Stop any running thread
        self._stop_client_thread(client_id)

        if client.is_connected:
            disconnected = client.stop()
            return disconnected
        else:
            # Client was already disconnected
            logger.info(f"Client '{client_id}' was already disconnected.")
            return True

    def _start_client_thread(self, client: BleClient) -> None:
        """
        Thread function to run a client's connection lifecycle.

        Args:
            client (BleClient): The BLE client to run.
        """
        attempt = 0
        max_attempts = self._config.reconnect_attempts

        while attempt < max_attempts:
            attempt += 1
            try:
                logger.info(f"Starting client {client.client_id} connection (attempt {attempt}/{max_attempts})")

                # Configure notification time based on manager settings
                notification_time = self._config.notification_timeout

                # Call the client's run method with our configured timeout
                # The run method handles the entire connection lifecycle
                result = client.start(notification_time)

                if result:
                    break
                else:
                    logger.warning(f"Client {client.client_id} run method returned failure")

                    if attempt < max_attempts:
                        # Wait before trying again
                        delay = min(2 ** attempt, 30)  # Exponential backoff, max 30 seconds
                        logger.info(f"Waiting {delay} seconds before reconnect attempt {attempt + 1}")
                        time.sleep(delay)

            except Exception as e:
                logger.error(f"Unhandled error in client thread for {client.client_id}: {e}", exc_info=True)
                # Ensure the client is disconnected
                if client and client.is_connected:
                    client.stop()

                if attempt < max_attempts:
                    # Wait before trying again
                    delay = min(2 ** attempt, 30)
                    logger.info(f"Waiting {delay} seconds before reconnect attempt {attempt + 1}")
                    time.sleep(delay)

        # Clean up thread tracking
        with self._lock:
            self._client_threads.pop(client.client_id, None)

        if attempt >= max_attempts:
            logger.error(f"Failed to connect client {client.client_id} after {max_attempts} attempts")

    def _stop_client_thread(self, client_id: str) -> None:
        """
        Stop a client thread if it exists.

        Args:
            client_id (str): ID of the client whose thread should be stopped.
        """
        thread = None
        with self._lock:
            if client_id in self._client_threads:
                thread = self._client_threads.pop(client_id)

        if thread and thread.is_alive():
            logger.info(f"Waiting for client thread {client_id} to finish...")
            # We can't forcibly terminate threads in Python, but we can
            # disconnect the client which should cause the thread to exit
            client = self._clients.get(client_id)
            if client and client.is_connected:
                client.stop()

            # Wait for the thread to terminate
            thread.join(5.0)

            #  Check after a join attempt
            if thread.is_alive():
                logger.warning(f"Client thread for {client_id} did not terminate within timeout")

    def _handle_client_disconnect(self, client_id: str):
        """
        Handle client disconnection notification.

        This callback is called by the BleClient when it detects
        that the device has disconnected.

        Args:
            client_id: ID of the disconnected client.
        """
        logger.info(f"Received disconnect notification for client {client_id}")

        client = self.get_client(client_id)
        if client:
            if self._config.auto_reconnect and client_id:
                # Start reconnection in a new thread after a short delay
                threading.Timer(2.0, self._start_client, args=(client_id,)).start()

    def _start_connection_monitoring(self) -> None:
        """Start a thread to monitor and maintain BLE connections."""
        if self._monitoring_thread and self._monitoring_thread.is_alive():
            logger.warning("Connection monitoring already active")
            return

        def monitor_connections():
            self._monitoring_active = True

            while self._monitoring_active and not self._terminate_event.is_set():
                try:
                    # Get a copy of client IDs to avoid modifying during iteration
                    with self._lock:
                        client_ids = list(self._clients.keys())

                    for client_id in client_ids:
                        try:
                            client = self._clients.get(client_id)
                            if not client or not client.is_enabled:
                                continue

                            # Check if the client thread exists and is active
                            thread = self._client_threads.get(client_id)
                            thread_active = thread and thread.is_alive()

                            # Check if we need to reconnect
                            if not client.is_connected and not thread_active:
                                logger.info(f"Connection monitor detected disconnected client {client_id}")
                                logger.info(f"Attempting to reconnect client {client_id}")
                                self._start_client(client_id)
                        except Exception as e:
                            logger.error(f"Error monitoring client {client_id}: {e}")
                            # Continue with the next client

                    # Sleep before the next check
                    self._terminate_event.wait(min(1.0, self._config.reconnect_interval))
                except Exception as e:
                    logger.error(f"Error in connection monitoring: {e}", exc_info=True)
                    self._terminate_event.wait(1.0)

        # Start the monitoring thread
        self._monitoring_thread = threading.Thread(
            target=monitor_connections,
            name="ble-connection-monitor",
            daemon=True
        )
        self._monitoring_thread.start()
        logger.info("BLE connection monitoring started")