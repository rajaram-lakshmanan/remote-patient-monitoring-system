#!/usr/bin/env python3
# -----------------------------------------------------------------------------
# Filename: base_client_manager.py
# Author: Rajaram Lakshmanan
# Description:  Base class for client managers.
# License: MIT (see LICENSE)
# -----------------------------------------------------------------------------

import abc
import logging
import threading
from typing import Dict, Optional, TypeVar, Generic

from event_bus.redis_stream_bus.redis_stream_bus import RedisStreamBus

# Type variables for the client and config
C = TypeVar('C')  # Client type
T = TypeVar('T')  # Config type

logger = logging.getLogger("BaseClientManager")

class BaseClientManager(abc.ABC, Generic[C, T]):
    """
    Base class for client managers.

    This defines the common interface that all client managers must implement,
    regardless of the protocol (BLE, I2C, etc.) they use to communicate with devices.

    Type Parameters:
        C: The type of client this manager manages.
        T: The type of configuration for this manager.
    """

    def __init__(self, event_bus: RedisStreamBus, config: T):
        """
        Initialize the Client Manager.

        Args:
            event_bus (RedisStreamBus): The event bus for publishing events.
            config (T): Manager configuration.
        """
        self._event_bus = event_bus
        self._config = config

        # Client storage
        self._clients: Dict[str, C] = {}

        # Thread safety
        self._lock = threading.RLock()

    # === Required Public API Methods ===

    @abc.abstractmethod
    def start(self) -> None:
        """
        Start client operations and connect all clients.
        """
        pass

    @abc.abstractmethod
    def stop(self) -> None:
        """
        Clean up resources and disconnect all clients.
        """
        pass

    @abc.abstractmethod
    def get_client(self, client_id: str) -> Optional[C]:
        """
        Get a client by ID.

        Args:
            client_id (str): ID of the client to retrieve.

        Returns:
            C or None: The client instance or None if not found.
        """
        pass

    @abc.abstractmethod
    def get_all_clients(self) -> Dict[str, C]:
        """
        Get all clients.

        Returns:
            Dict[str, C]: Dictionary of all clients, keyed by client_id.
        """
        pass

    def subscribe_to_events(self) -> None:
        """Subscribe to the events required by the manager and its configured clients."""
        logger.debug("Subscribing to events")

        try:
            clients = (self.get_all_clients() or {}).values()
            for client in clients:
                if client is not None:
                    client.subscribe_to_events()
        except Exception as e:
            logger.error(f"Error subscribing to events: {e}", exc_info=True)