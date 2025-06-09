#!/usr/bin/env python3
# -----------------------------------------------------------------------------
# Filename: storage_telemetry.py
# Author: Rajaram Lakshmanan
# Description:  Retrieves the telemetry registry of the Storage.
# License: MIT (see LICENSE)
# -----------------------------------------------------------------------------

import json
from abc import ABC
from typing import List
import logging

from edge_gateway.base_collector_publisher import BaseCollectorPublisher
from edge_gateway.helper.shell_command import ShellCommand
from event_bus.models.edge_gateway.telemetry.storage_telemetry_event import StorageTelemetryEvent
from event_bus.redis_stream_bus.redis_stream_bus import RedisStreamBus
from event_bus.stream_name import StreamName

logger = logging.getLogger("StorageTelemetry")

class StorageTelemetry(BaseCollectorPublisher, ABC):
    """
    A utility class for gathering and publishing storage telemetry time_series from Linux systems.

    This class collects real-time registry about the storage subsystems from any Linux system,
    including mounted file systems and block devices with their usage statistics and properties.
    After collection, it publishes this registry to a Redis stream for downstream consumption
    by other services.

    The time_series is collected using system commands like 'df' for file system registry and 'lsblk'
    for block device details. The class creates a unified hierarchical structure that represents
    the relationship between devices and their partitions, providing a comprehensive view of
    the system's storage configuration and utilization.

    Storage telemetry provides critical insights into disk space availability, I/O subsystem
    health, and potential capacity issues for both system operations and health time_series storage.
    """

    def __init__(self, event_bus: RedisStreamBus):
        """Initialize the Storage telemetry.

         Args:
             event_bus (RedisStreamBus): The event bus for publishing events.
        """
        super().__init__(event_bus)

        self._event_bus.register_stream(StreamName.EDGE_GW_STORAGE_TELEMETRY.value, StorageTelemetryEvent)

        self._mounted_file_systems = []  # Raw storage time_series for mounted file systems
        self._block_devices = []  # Raw storage time_series for block devices
        logger.debug("Successfully initialized Storage Telemetry")

    def collect(self):
        """Collect storage and block device registry."""
        try:
            logger.debug("Collecting storage registry from system")
            self._information_available = False
            self._collection_in_progress = True

            self._mounted_file_systems = self._get_mounted_file_systems()
            self._block_devices = self._get_block_devices()

            self._information_available = True
            logger.debug("Successfully collected storage registry")
        except Exception as e:
            logger.exception(f"Failed to retrieve storage registry: {e}", exc_info=True)
        finally:
            self._collection_in_progress = False

    def publish(self):
        """
        Publish the collected storage telemetry to event bus.

        Creates a StorageTelemetryEvent with the collected time_series and publishes it to the appropriate stream.
        """
        try:
            logger.info("Publishing Storage telemetry event")
            unified_data = self._unify_storage_info()
            event = StorageTelemetryEvent(storage_data=unified_data)
            self._publish_to_stream(StreamName.EDGE_GW_STORAGE_TELEMETRY.value, event)
            logger.info(f"Published storage telemetry event: {event.event_id}")
        except Exception as e:
            logger.error(f"Failed to publish event: {e}", exc_info=True)

    def _unify_storage_info(self):
        """Combines mounted file systems and block devices into a unified structure."""
        unified_info = []

        # Add mounted file systems registry
        for fs in self._mounted_file_systems:
            unified_info.append({
                "device_name": fs["filesystem"],
                "size": fs["size"],
                "used": fs["used"],
                "available": fs["available"],
                "use_percent": fs["use_percent"],
                "mount_point": fs["mount_point"],
                "rm": False,  # Mounted file systems are not removable
                "ro": False,  # Assuming not read-only unless specified
                "type": "filesystem",
                "children": []  # Filesystems do not have partitions
            })

        # Add block devices registry (including children partitions)
        for device in self._block_devices:
            block_device_info = {
                "device_name": device["name"],
                "size": device["size"],
                "used": None,  # Block device registry doesn't have used space by default
                "available": None,
                "use_percent": None,
                "mount_point": device.get("mountpoint", ""),
                "rm": device["rm"],
                "ro": device["ro"],
                "type": device["type"],
                "children": []  # Initialize an empty list for children (partitions)
            }

            # If the device has children (partitions), include them in the "children" field
            if device.get("children"):
                for child in device["children"]:
                    block_device_info["children"].append({
                        "device_name": child["name"],
                        "size": child["size"],
                        "used": None,  # Partitions may not have used space by default
                        "available": None,
                        "use_percent": None,
                        "mount_point": child.get("mountpoint", ""),
                        "rm": child["rm"],
                        "ro": child["ro"],
                        "type": child["type"],
                        "children": []  # Partitions typically have no children
                    })

            unified_info.append(block_device_info)

        return unified_info

    @staticmethod
    def _get_mounted_file_systems() -> List[dict]:
        """Collect registry about mounted file systems."""
        mounted_file_systems_info = []
        try:
            # Get disk registry using df command
            df_output = ShellCommand.execute(["df", "-h"])
            if df_output:
                lines = df_output.strip().split('\n')
                for line in lines[1:]:  # Skip header
                    parts = line.split()
                    if len(parts) >= 6:
                        mounted_file_system_info = {
                            "filesystem": parts[0],
                            "size": parts[1],
                            "used": parts[2],
                            "available": parts[3],
                            "use_percent": parts[4],
                            "mount_point": parts[5]
                        }
                        mounted_file_systems_info.append(mounted_file_system_info)
        except Exception as e:
            logger.exception(f"Failed to retrieve mounted file systems registry: {e}", exc_info=True)

        return mounted_file_systems_info

    @staticmethod
    def _get_block_devices() -> List[dict]:
        """Collect registry about block devices (eMMC, SD, USB, etc.)."""
        block_devices_info = []
        try:
            output = ShellCommand.execute(["lsblk", "-J"])
            if output:
                raw_devices = json.loads(output).get("blockdevices", [])
                for device in raw_devices:
                    block_device_info = {
                        "name": device["name"],
                        "maj_min": device.get("maj:min", ""),  # Make maj_min optional with a default value
                        "rm": device["rm"],
                        "size": device["size"],
                        "ro": device["ro"],
                        "type": device["type"],
                        "mountpoint": device.get("mountpoint"),
                        "children": device.get("children", [])
                    }
                    block_devices_info.append(block_device_info)
        except Exception as e:
            logger.error(f"Error parsing block devices: {e}", exc_info=True)

        return block_devices_info