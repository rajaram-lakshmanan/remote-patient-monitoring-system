#!/usr/bin/env python3
# -----------------------------------------------------------------------------
# Filename: os_kernel_inventory.py
# Author: Rajaram Lakshmanan
# Description:  Retrieves the Operating System registry.
# License: MIT (see LICENSE)
# -----------------------------------------------------------------------------

import os
import re
import logging
from abc import ABC

from edge_gateway.base_collector_publisher import BaseCollectorPublisher
from edge_gateway.helper.shell_command import ShellCommand
from event_bus.models.edge_gateway.inventory.os_kernel_inventory_event import OsKernelInventoryEvent, LoggedInUserInfo
from event_bus.redis_stream_bus.redis_stream_bus import RedisStreamBus
from event_bus.stream_name import StreamName

logger = logging.getLogger("OsKernelInventory")

class OsKernelInventory(BaseCollectorPublisher, ABC):
    """
    A utility class for gathering and publishing OS and kernel registry.

    This class collects detailed registry about the operating system and kernel from any Linux system,
    including OS name, version, ID, uptime, logged-in users, kernel name, version, and build date.
    After collection, it publishes this registry to a Redis stream for downstream consumption by
    other services.

    OS and kernel registry provides the foundation for understanding system capabilities,
    vulnerabilities, and security update status for the digital twin.
    """

    def __init__(self, event_bus: RedisStreamBus):
        """Initialize the OS and Kernel Inventory.

        Args:
            event_bus (RedisStreamBus): The event bus for publishing events.

        Initializes local variables to store OS and Kernel registry.
        """
        super().__init__(event_bus)

        self._event_bus.register_stream(StreamName.EDGE_GW_OS_KERNEL_INVENTORY.value, OsKernelInventoryEvent)

        self._os_name = None
        self._os_version = None
        self._os_id = None
        self._uptime = None
        self._logged_in_users = []
        self._kernel_name = None
        self._kernel_version = None
        self._kernel_build_date = None
        logger.debug("Successfully initialized OS and Kernel Inventory")

    def collect(self):
        """Collect OS and Kernel registry."""
        try:
            logger.debug("Collecting OS and Kernel inventory registry")
            self._information_available = False
            self._collection_in_progress = True

            self._collect_os_info()
            self._collect_kernel_info()

            self._information_available = True
            logger.debug("Successfully collected OS and Kernel inventory registry")
        except Exception as e:
            logger.exception(f"Failed during OS and Kernel collection. {e}", exc_info=True)
        finally:
            self._collection_in_progress = False

    def publish(self):
        """
        Publish OS and Kernel registry to the event bus.

        Creates a OsKernelInventoryEvent with the collected time_series and publishes it to the appropriate stream.
        """
        try:
            logger.info("Publishing OS and Kernel inventory event")
            event = OsKernelInventoryEvent(os_name=self._os_name,
                                           os_version=self._os_version,
                                           os_id=self._os_id,
                                           uptime=self._uptime,
                                           logged_in_users=[
                                               LoggedInUserInfo(**user_dict) for user_dict in self._logged_in_users],
                                           kernel_name=self._kernel_name,
                                           kernel_version=self._kernel_version,
                                           kernel_build_date=self._kernel_build_date)

            self._publish_to_stream(StreamName.EDGE_GW_OS_KERNEL_INVENTORY.value, event)
            logger.info(f"Published OS and Kernel inventory event: {event.event_id}")
        except Exception as e:
            logger.error(f"Failed to publish OS and Kernel inventory event: {e}", exc_info=True)

    def _collect_os_info(self):
        """Populate OS-related local variables."""
        if os.path.exists('/etc/os-release'):
            os_release = ShellCommand.execute(["cat", "/etc/os-release"])
            if os_release:
                self._os_name = self._get_os_name(os_release)
                self._os_version = self._get_os_version(os_release)
                self._os_id = self._get_os_id(os_release)
        if not self._os_name:
            os_name = ShellCommand.execute(["uname", "-o"])
            self._os_name = os_name.strip() if os_name else "Unknown"


        self._uptime = self._get_uptime()
        self._logged_in_users = self._get_logged_in_users()

    def _collect_kernel_info(self):
        """Populate Kernel-related local variables."""
        self._kernel_name = ShellCommand.execute(["uname", "-s"])
        self._kernel_version = ShellCommand.execute(["uname", "-r"])
        self._kernel_build_date = ShellCommand.execute(["uname", "-v"])

        if not all([self._kernel_name, self._kernel_version, self._kernel_build_date]):
            logger.warning("Some kernel registry values may be missing.")

    @staticmethod
    def _get_os_name(os_release: str) -> str:
        """
        Get the name of the Operating System.

        Args:
            os_release: String containing the contents of /etc/os-release
        """
        try:
            name_match = re.search(r'PRETTY_NAME="(.*)"', os_release)
            return name_match.group(1) if name_match else "Unknown"
        except Exception as e:
            logger.exception(f"Failed to get the name of the Operating system: {e}", exc_info=True)
            # Fallback to uname if no os-release registry found
            uname = ShellCommand.execute(["uname", "-o"])
            return uname.strip() if uname else "Unknown"

    @staticmethod
    def _get_os_version(os_release: str) -> str:
        """
        Get the version of the Operating System.

        Args:
            os_release: String containing the contents of /etc/os-release
        """
        try:
            version_match = re.search(r'VERSION="(.*)"', os_release)
            return version_match.group(1) if version_match else "Unknown"
        except Exception as e:
            logger.exception(f"Failed to get the version of the Operating system : {e}", exc_info=True)
            return "Unknown"

    @staticmethod
    def _get_os_id(os_release: str) -> str:
        """
        Get the ID of the Operating System.

        Args:
            os_release: String containing the contents of /etc/os-release
        """
        try:
            id_match = re.search(r'ID=(.*)', os_release)
            return id_match.group(1).strip('"') if id_match else "Unknown"
        except Exception as e:
            logger.exception(f"Failed to get the ID of the Operating system : {e}", exc_info=True)
            return "Unknown"

    @staticmethod
    def _get_uptime() -> str:
        """
        Get the uptime of the Operating System.

        Returns:
            Uptime (str) of the Operating System.
        """
        try:
            uptime_output = ShellCommand.execute(["cat", "/proc/uptime"]).strip()
            if uptime_output:
                uptime_seconds = float(uptime_output.split()[0])
                days, remainder = divmod(uptime_seconds, 86400)
                hours, remainder = divmod(remainder, 3600)
                minutes, seconds = divmod(remainder, 60)
                return f"{int(days)}d {int(hours)}h {int(minutes)}m {int(seconds)}s"
            return "Unknown"
        except Exception as e:
            logger.exception(f"Failed to get the Uptime of the Operating system : {e}", exc_info=True)
            return "Unknown"

    @staticmethod
    def _get_logged_in_users():
        """Get the users logged into (both local and remote) the Operating System."""
        logged_in_users = []
        try:
            who_output = ShellCommand.execute(["who"]).strip()
            if who_output:
                for line in who_output.split("\n"):
                    match = re.match(r"(\S+)\s+(\S+)\s+(\d{4}-\d{2}-\d{2} \d{2}:\d{2})(?: \((.*?)\))?", line)
                    if match:
                        user, terminal, time_str, host = match.groups()
                        logged_in_users.append({
                            "user": user,
                            "terminal": terminal,
                            "login_time": time_str,
                            "host": host or "local"
                        })
        except Exception as e:
            logger.exception(f"Failed to get the users logged into the Operating system : {e}", exc_info=True)

        return logged_in_users