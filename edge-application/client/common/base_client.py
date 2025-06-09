#!/usr/bin/env python3
# -----------------------------------------------------------------------------
# Filename: base_client_manager.py
# Author: Rajaram Lakshmanan
# Description:  Base class for client managers.
# License: MIT (see LICENSE)
# -----------------------------------------------------------------------------

import abc
import logging

from event_bus.redis_stream_bus.redis_stream_bus import RedisStreamBus

logger = logging.getLogger("BaseClient")

class BaseClient(abc.ABC):
    """
    Base class for the client.

    This defines the common interface that all clients must implement.

    Type Parameters:
        C: The type of client this manager manages.
    """

    def __init__(self, event_bus: RedisStreamBus):
        """
        Initialize the Client.

        Args:
            event_bus (RedisStreamBus): The event bus for publishing events.
        """
        self._event_bus = event_bus

    # === Required Public API Methods ===

    @property
    @abc.abstractmethod
    def is_enabled(self) -> bool:
        """Return the flag to indicate whether the client is enabled."""
        # Will be implemented in the concrete client class
        pass

    @property
    @abc.abstractmethod
    def client_id(self) -> str:
        """Return the identifier of the client."""
        pass

    @property
    @abc.abstractmethod
    def sensors(self) -> list[str]:
        """Return a list of sensor IDs from the connected sensors."""
        pass

    @abc.abstractmethod
    def start(self) -> None:
        """
        Start the client and start communicating with all the sensors that are enabled.
        """
        pass

    @abc.abstractmethod
    def stop(self) -> None:
        """
        Clean up resources and disconnect the client and stop time_series acquisition from the sensors, if applicable.
        """
        pass