#!/usr/bin/env python3
# -----------------------------------------------------------------------------
# Filename: cpu_inventory.py
# Author: Rajaram Lakshmanan
# Description:  Retrieves the CPU registry.
# License: MIT (see LICENSE)
# -----------------------------------------------------------------------------

import re
import logging
from abc import ABC

from edge_gateway.base_collector_publisher import BaseCollectorPublisher
from edge_gateway.helper.shell_command import ShellCommand
from event_bus.models.edge_gateway.inventory.cpu_inventory_event import CpuInventoryEvent
from event_bus.redis_stream_bus.redis_stream_bus import RedisStreamBus
from event_bus.stream_name import StreamName

logger = logging.getLogger("CpuInventory")

class CpuInventory(BaseCollectorPublisher, ABC):
    """
    A utility class for gathering and publishing CPU hardware registry.

    This class collects detailed registry about the CPU hardware from any Linux system,
    including the model, revision, serial number, core count, and architecture. After collection,
    it publishes this registry to a Redis stream for downstream consumption by other services.

    This registry forms a critical part of the system inventory for the digital twin,
    providing hardware context for security analysis and health monitoring operations.
    """

    def __init__(self, event_bus: RedisStreamBus):
        """Initialize the Cpu Inventory.

        Args:
            event_bus (RedisStreamBus): The event bus for publishing events.

        Initializes local variables to store cpu registry.
        """
        super().__init__(event_bus)

        self._event_bus.register_stream(StreamName.EDGE_GW_CPU_INVENTORY.value, CpuInventoryEvent)

        # Local variables to store collected time_series with default values
        self._pi_model = None
        self._revision = None
        self._serial = None
        self._cpu_cores = None
        self._cpu_model = None
        self._cpu_architecture = None
        logger.debug("Successfully initialized CPU Inventory")

    def collect(self):
        """Collect CPU registry and store it in local variables."""
        try:
            logger.debug("Collecting CPU inventory registry")
            self._information_available = False
            self._collection_in_progress = True

            # Read the contents of /proc/cpuinfo
            cpu_info_file_contents = ShellCommand.execute(["cat", "/proc/cpuinfo"])
            if not cpu_info_file_contents:
                raise ValueError("No output from /proc/cpuinfo")

            # Extract key CPU registry using regex
            cpu_info_dict = {key: re.findall(rf'{key}\s+:\s+(.*)', cpu_info_file_contents)
                             for key in ['Model', 'Revision', 'Serial', 'Hardware']}
            self._pi_model = cpu_info_dict.get('Model', ["Unknown"])[0]
            self._revision = cpu_info_dict.get('Revision', ["Unknown"])[0]
            self._serial = cpu_info_dict.get('Serial', ["Unknown"])[0]
            self._cpu_model = cpu_info_dict.get('Hardware', ["Unknown"])[0]

            # Count CPU cores
            self._cpu_cores = cpu_info_file_contents.count("processor") or 1
            if self._cpu_cores == 1:
                logger.warning("CPU core count was not found; defaulting to 1 core.")

            # Get the CPU architecture
            self._cpu_architecture = ShellCommand.execute(["uname", "-m"]) or "Unknown"
            if not self._cpu_architecture:
                logger.warning("Failed to retrieve CPU architecture; defaulting to 'Unknown'.")

            self._information_available = True
            logger.debug("Successfully collected CPU inventory registry")
        except Exception as e:
            logger.exception(f"Failed to retrieve CPU inventory: {e}", exc_info=True)
        finally:
            self._collection_in_progress = False

    def publish(self):
        """
        Publish the collected CPU registry to event bus.

        Creates a CpuInventoryEvent with the collected time_series and publishes it to the appropriate stream.
        """
        try:
            logger.info("Publishing CPU inventory event")
            event = CpuInventoryEvent(pi_model=self._pi_model,
                                      revision=self._revision,
                                      serial=self._serial,
                                      cpu_cores=self._cpu_cores,
                                      cpu_model=self._cpu_model,
                                      cpu_architecture=self._cpu_architecture)
            self._publish_to_stream(StreamName.EDGE_GW_CPU_INVENTORY.value, event)
            logger.info(f"Published CPU inventory event: {event.event_id}")
        except Exception as e:
            logger.error(f"Failed to publish CPU inventory event: {e}", exc_info=True)