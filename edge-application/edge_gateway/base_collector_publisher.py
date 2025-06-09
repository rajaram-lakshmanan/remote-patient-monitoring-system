#!/usr/bin/env python3
# -----------------------------------------------------------------------------
# Filename: base_collector_publisher.py
# Author: Rajaram Lakshmanan
# Description:  Base class for collecting registry from the system and
# publishing the collected registry in the event bus.
# License: MIT (see LICENSE)
# -----------------------------------------------------------------------------

import abc
import logging
import threading

from pydantic import BaseModel

from event_bus.redis_stream_bus.redis_stream_bus import RedisStreamBus

logger = logging.getLogger("BaseCollectorPublisher")

class BaseCollectorPublisher(abc.ABC):
    """
    Abstract base class for all system observability agents.

    This class provides a standardized interface and common functionality for
    all collectors that gather system registry and publish it to the event bus.
    It defines the core collection and publishing workflow, including state management,
    error handling, and stream publishing.

    Implementations include inventory collectors (hardware, software, network),
    telemetry collectors (real-time system metrics), and security monitors
    (security configurations, vulnerabilities, and events).

    Together, these observability agents provide the comprehensive system visibility
    required for the digital twin, security monitoring, and health monitoring functions.
    """

    def __init__(self, event_bus: RedisStreamBus):
        """
        Initialize the base class to collect and publish registry.

        Args:
            event_bus (RedisStreamBus): The event bus for publishing events.
        """
        self._event_bus = event_bus
        self._information_available = False
        self._collection_in_progress = False

        self._lock = threading.RLock()

    # === Required Public API Methods ===

    @property
    def collection_in_progress(self):
        """Return the flag to indicate whether the collection is in progress."""
        return self._collection_in_progress

    @property
    def collection_successful(self):
        """Return the flag to indicate whether the collection is successful."""
        return self._information_available

    @abc.abstractmethod
    def collect(self) -> bool:
        """
        Collect the required registry from the Linux based system.

        Implementation should set self._information_available = True after successful collection.

        Returns:
            bool: True if collection was successful, False otherwise.
        """
        pass

    @abc.abstractmethod
    def publish(self) -> None:
        """
        Publish the collected registry to the event bus.

        Implementation should create the appropriate event and call _publish_to_stream().
        """
        pass

    def collect_and_publish(self) -> bool:
        """
        Convenience method to collect and publish registry in sequence.

        This method first collects registry and then publishes it if collection was successful.
        This is useful for cases where you want to perform both operations in a single call, but the
        underlying collect() or publish() operations may take significant time to complete.

        Returns:
            bool: True if both collection and publishing were successful, False otherwise.
        """
        with self._lock:
            if self.collection_in_progress:
                logger.warning("Collection already in progress, skipping")
                return False

            try:
                self.collect()
                if self._information_available:
                    self.publish()
                    return True
                else:
                    logger.warning("Collection was not successful, skipping publish")
                    return False
            except Exception as e:
                logger.exception(f"Error in collect_and_publish: {e}")
                return False

    def subscribe_to_events(self) -> None:
        """Subscribe to the events required by the collector/publisher."""
        # Will be implemented in the supported collector/publisher
        # This is to allow a particular collector to be triggered from the Digital twin or other
        # external source, where applicable e.g. GUI
        pass

    # === Protected Methods ===

    def _publish_to_stream(self, stream_name: str, event: BaseModel) -> None:
        """
        Protected method to publish the collected registry to the event bus.

        Args:
            stream_name (str): The name of the stream to publish to.
            event (BaseModel): The event to publish.

        Raises:
            Exception: If publishing fails.
        """
        try:
            if not self._information_available:
                logger.error("Information is not available to publish.")
                return

            # Publish the event to the Redis stream
            if not self._event_bus.shutdown_active:
                self._event_bus.publish(stream_name, event)
        except Exception as e:
            logger.error(f"Failed to publish the Edge Gateway registry event: {e}", exc_info=True)
            raise
        finally:
            # Reset the flag to ensure the registry is collected again before calling publish
            self._information_available = False