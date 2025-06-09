#!/usr/bin/env python3
# -----------------------------------------------------------------------------
# Filename: memory_telemetry.py
# Author: Rajaram Lakshmanan
# Description:  Retrieves the telemetry registry of the Memory.
# License: MIT (see LICENSE)
# -----------------------------------------------------------------------------

import re
import logging
from abc import ABC

from edge_gateway.base_collector_publisher import BaseCollectorPublisher
from edge_gateway.helper.shell_command import ShellCommand
from event_bus.models.edge_gateway.telemetry.memory_telemetry_event import MemoryTelemetryEvent
from event_bus.redis_stream_bus.redis_stream_bus import RedisStreamBus
from event_bus.stream_name import StreamName

logger = logging.getLogger("MemoryTelemetry")

class MemoryTelemetry(BaseCollectorPublisher, ABC):
    """
    A utility class for gathering and publishing memory telemetry time_series from Linux systems.

    This class collects real-time registry about the system memory from any Linux system,
    including total memory, free memory, available memory, and swap usage. After collection,
    it publishes this registry to a Redis stream for downstream consumption by other services.

    The time_series is collected from the /proc/meminfo file, which provides detailed memory statistics
    maintained by the Linux kernel. The collected values are formatted with appropriate units
    for better readability and understanding.

    Memory telemetry enables resource constraint monitoring, performance analysis,
    and detection of memory leaks or unusual consumption patterns in the digital twin.
    """

    def __init__(self, event_bus: RedisStreamBus):
        """
        Initialize the Memory telemetry.

        Args:
            event_bus (RedisStreamBus): The event bus for publishing events.

         Initializes local variables to store memory telemetry.
        """
        super().__init__(event_bus)

        self._event_bus.register_stream(StreamName.EDGE_GW_MEMORY_TELEMETRY.value, MemoryTelemetryEvent)

        self._total_memory = None
        self._free_memory = None
        self._available_memory = None
        self._swap_total_memory = None
        self._swap_free_memory = None

        logger.debug("Successfully initialized Memory Telemetry")

    def collect(self):
        """
        Collects live memory telemetry registry from the system.

        This method reads from `/proc/meminfo` and extracts key memory metrics
        such as total, free, and available RAM, as well as swap memory stats.
        """
        try:
            logger.debug("Collecting memory registry")
            self._information_available = False
            self._collection_in_progress = True

            meminfo = ShellCommand.execute(["cat", "/proc/meminfo"])
            if meminfo:
                # Total RAM in MB
                self._total_memory = f"{MemoryTelemetry._extract_kb('MemTotal', meminfo) // 1024} MB"
                # Free RAM in MB
                self._free_memory = f"{MemoryTelemetry._extract_kb('MemFree', meminfo) // 1024} MB"
                # Memory available for new apps in MB
                self._available_memory = f"{MemoryTelemetry._extract_kb('MemAvailable', meminfo) // 1024} MB"
                # Total swap space in MB
                self._swap_total_memory = f"{MemoryTelemetry._extract_kb('SwapTotal', meminfo) // 1024} MB"
                # Free swap space in MB
                self._swap_free_memory = f"{MemoryTelemetry._extract_kb('SwapFree', meminfo) // 1024} MB"

            self._information_available = True
            logger.debug("Successfully collected memory telemetry")
        except Exception as e:
            logger.exception(f"Failed to retrieve memory registry: {e}", exc_info=True)
        finally:
            self._collection_in_progress = False

    def publish(self) -> None:
        """
        Publish the collected Memory telemetry to event bus.

        Creates a MemoryTelemetryEvent with the collected time_series and publishes it to the appropriate stream.
        """
        try:
            logger.info("Publishing Memory telemetry event")
            event = MemoryTelemetryEvent(total_memory=self._total_memory,
                                         free_memory=self._free_memory,
                                         available_memory=self._available_memory,
                                         swap_total_memory=self._swap_total_memory,
                                         swap_free_memory=self._swap_free_memory)

            self._publish_to_stream(StreamName.EDGE_GW_MEMORY_TELEMETRY.value, event)
            logger.info(f"Published memory telemetry event: {event.event_id}")
        except Exception as e:
            logger.error(f"Error publishing Edge Gateway Memory Telemetry to Redis Stream: {e}")

    @staticmethod
    def _extract_kb(key: str, meminfo: str) -> int:
        """
        Helper function to extract memory time_series from /proc/meminfo.

        Args:
            key (str): The memory metric to extract (e.g., 'MemTotal').
            meminfo (str): The content of /proc/meminfo.

        Returns:
            int: The memory value in kilobytes (KB).
        """
        match = re.search(rf'{key}:\s+(\d+)\s+kB', meminfo)
        return int(match.group(1)) if match else 0