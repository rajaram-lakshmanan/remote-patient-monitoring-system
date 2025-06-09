#!/usr/bin/env python3
# -----------------------------------------------------------------------------
# Filename: package_inventory.py
# Author: Rajaram Lakshmanan
# Description:  Retrieves the Package(s) registry.
# License: MIT (see LICENSE)
# -----------------------------------------------------------------------------

import logging
import os
import re
import subprocess
from abc import ABC
from typing import Optional

from edge_gateway.base_collector_publisher import BaseCollectorPublisher
from edge_gateway.helper.shell_command import ShellCommand
from event_bus.models.edge_gateway.inventory.package_inventory_event import PackageInventoryEvent, PackageInfo
from event_bus.redis_stream_bus.redis_stream_bus import RedisStreamBus
from event_bus.stream_name import StreamName

logger = logging.getLogger("PackageInventory")

class PackageInventory(BaseCollectorPublisher, ABC):
    """
    A utility class for gathering and publishing package registry from Linux systems.

    This class collects detailed registry about installed packages, including system packages,
    security-related packages, and Python packages. After collection, it publishes this registry
    to a Redis stream for downstream consumption by other services.

    Package inventory time_series enables vulnerability management, security compliance verification,
    and software dependency analysis in the digital twin.
    """

    def __init__(self, event_bus: RedisStreamBus):
        """Initialize the Package Inventory.

         Args:
             event_bus (RedisStreamBus): The event bus for publishing events.

        Initializes local variables to store all, security and python packages registry.
        """
        super().__init__(event_bus)

        self._event_bus.register_stream(StreamName.EDGE_GW_PACKAGE_INVENTORY.value, PackageInventoryEvent)

        # Raw package time_series: [(name, version)]
        self._all_packages = None

        # Raw security package time_series: [(name, version)]
        self._security_packages = None

        # Raw Python package time_series: [(name, version)]
        self._python_packages = None

        # Determine system package manager
        self._system_type = PackageInventory._detect_system_type()
        logger.info(f"Detected system type: {self._system_type}")

        logger.debug("Successfully initialized Package Inventory")

    def collect(self):
        """Collect package registry using platform-appropriate methods."""
        try:
            logger.debug("Collecting Package inventory registry")
            self._information_available = False
            self._collection_in_progress = True

            # Collect all installed packages (raw time_series)
            self._collect_all_packages()

            # Collect security-related packages (raw time_series)
            self._collect_security_packages()

            # Collect Python packages (using pip and pip3)
            self._collect_python_packages()

            self._information_available = True
            logger.info(f"Successfully collected package registry. "
                        f"Found {len(self._all_packages)} system packages, "
                        f"{len(self._security_packages)} security packages, "
                        f"{len(self._python_packages)} Python packages")
        except Exception as e:
            logger.exception(f"Failed to collect package registry: {e}", exc_info=True)
        finally:
            self._collection_in_progress = False

    def publish(self):
        """
        Publish the collected package registry to event bus.

        Creates a PackageInventoryEvent with the collected time_series and publishes it to the appropriate stream.
        """
        try:
            logger.info("Publishing Package inventory event")

            # Convert raw time_series to PackageInfo during publishing
            all_packages_info = [PackageInfo(name=name, version=version)
                                 for name, version in self._all_packages]
            security_packages_info = [PackageInfo(name=name, version=version)
                                      for name, version in self._security_packages]
            python_packages_info = [PackageInfo(name=name, version=version)
                                    for name, version in self._python_packages]

            event = PackageInventoryEvent(all_packages=all_packages_info,
                                          security_packages=security_packages_info,
                                          python_packages=python_packages_info)

            self._publish_to_stream(StreamName.EDGE_GW_PACKAGE_INVENTORY.value, event)
            logger.info(f"Published package inventory event: {event.event_id}")
        except Exception as e:
            logger.error(f"Failed to publish package inventory event: {e}", exc_info=True)

    @staticmethod
    def _detect_system_type() -> str:
        """Detect the type of Linux system to determine the package manager.

        Returns:
            str: The detected system type ('debian', 'redhat', 'unknown')
        """
        try:
            # First try to use package manager commands directly
            if ShellCommand.execute(["which", "dpkg-query"]):
                return "debian"
            elif ShellCommand.execute(["which", "rpm"]):
                return "redhat"

            # If package manager commands aren't available, check for distribution files
            if os.path.exists("/etc/debian_version"):
                return "debian"
            elif os.path.exists("/etc/redhat-release"):
                return "redhat"
            elif os.path.exists("/etc/os-release"):
                # Parse os-release file
                os_release = ShellCommand.execute(["cat", "/etc/os-release"])
                id_match = re.search(r'ID=(.*)', os_release) if os_release else None
                if id_match:
                    os_id = id_match.group(1).strip('"').lower()
                    if os_id in ["debian", "ubuntu", "linuxmint", "raspbian"]:
                        return "debian"
                    elif os_id in ["rhel", "centos", "fedora", "rocky", "alma"]:
                        return "redhat"

            # If we still can't determine, log a warning and return unknown
            logger.warning("Could not determine system distribution, package collection may be limited")
            return "unknown"
        except Exception as e:
            logger.exception(f"Error detecting system type: {e}", exc_info=True)
            return "unknown"

    def _collect_all_packages(self):
        """Collect all installed packages using the appropriate package manager."""
        logger.debug("Collecting all installed packages")
        self._all_packages = []

        try:
            if self._system_type == "debian":
                output = ShellCommand.execute(["dpkg-query", "-W", "-f", "${Package} ${Version}\n"])
                if output:
                    for line in output.splitlines():
                        parts = line.strip().split(' ', 1)  # Split on first space only
                        if len(parts) == 2:
                            self._all_packages.append((parts[0], parts[1]))

            elif self._system_type == "redhat":
                output = ShellCommand.execute(["rpm", "-qa", "--queryformat", "%{NAME} %{VERSION}-%{RELEASE}\n"])
                if output:
                    for line in output.splitlines():
                        parts = line.strip().split(' ', 1)  # Split on first space only
                        if len(parts) == 2:
                            self._all_packages.append((parts[0], parts[1]))

            else:
                logger.warning("Unsupported system type for package collection")

            logger.debug(f"Collected {len(self._all_packages)} system packages")

        except Exception as e:
            logger.exception(f"Error collecting system packages: {e}", exc_info=True)

    def _collect_security_packages(self):
        """Collect security-related packages."""
        logger.debug("Collecting security-related packages")
        self._security_packages = []

        # Common security packages across distributions
        security_list = [
            "ufw", "fail2ban", "iptables", "apparmor", "selinux",
            "clamav", "rkhunter", "chkrootkit", "firehol", "aide",
            "lynis", "cis-hardening", "openscap", "tripwire", "snort",
            "auditd", "ossec"
        ]

        try:
            for security_pkg in security_list:
                version = self._get_package_version(security_pkg)
                if version:
                    self._security_packages.append((security_pkg, version))

            logger.debug(f"Collected {len(self._security_packages)} security packages")

        except Exception as e:
            logger.exception(f"Error collecting security packages: {e}", exc_info=True)

    def _collect_python_packages(self):
        """Collect Python packages using both pip and pip3."""
        logger.debug("Collecting Python packages")
        self._python_packages = []
        all_python_packages = set()

        try:
            # Check for pip command availability
            pip_cmds = []
            if ShellCommand.execute(["which", "pip3"]):
                pip_cmds.append("pip3")
            if ShellCommand.execute(["which", "pip"]) and "pip3" not in pip_cmds:
                pip_cmds.append("pip")

            for pip_cmd in pip_cmds:
                output = ShellCommand.execute([pip_cmd, "freeze"])
                if output:
                    for line in output.splitlines():
                        # Handle different pip output formats
                        if "==" in line:
                            parts = line.split("==", 1)
                            if len(parts) == 2:
                                all_python_packages.add((parts[0], parts[1]))
                        elif "@" in line:  # Handle editable packages
                            parts = line.split("@", 1)
                            if len(parts) == 2:
                                all_python_packages.add((parts[0], "editable"))

            # Convert to list
            self._python_packages = list(all_python_packages)
            logger.debug(f"Collected {len(self._python_packages)} Python packages")

        except Exception as e:
            logger.exception(f"Error collecting Python packages: {e}", exc_info=True)

    def _get_package_version(self, package_name: str) -> Optional[str]:
        """Get the version of a specific package using the appropriate package manager.

        Args:
            package_name (str): The name of the package to check

        Returns:
            Optional[str]: The package version if installed, None otherwise
        """
        try:
            if self._system_type == "debian":
                # Use a different approach to avoid error logs for non-installed packages
                # The -s flag is for "status" which doesn't produce an error for missing packages
                status_cmd = ["dpkg", "-s", package_name]
                try:
                    status_output = subprocess.check_output(status_cmd, stderr=subprocess.PIPE, universal_newlines=True)
                    if "Status: install ok installed" in status_output:
                        version_match = re.search(r'Version:\s+(.*)', status_output)
                        if version_match:
                            return version_match.group(1)
                except subprocess.CalledProcessError:
                    # Package not installed, no need to log as error
                    return None

            elif self._system_type == "redhat":
                try:
                    # The -q flag in rpm is quieter
                    output = subprocess.check_output(
                        ["rpm", "-q", "--queryformat", "%{VERSION}-%{RELEASE}", package_name],
                        stderr=subprocess.PIPE,
                        universal_newlines=True
                    )
                    if output and "not installed" not in output:
                        return output
                except subprocess.CalledProcessError:
                    # Package not installed, no need to log as error
                    return None

            return None

        except Exception as e:
            logger.debug(f"Error checking package {package_name}: {e}")
            return None