#!/usr/bin/env python3
# -----------------------------------------------------------------------------
# Filename: network_inventory.py
# Author: Rajaram Lakshmanan
# Description:  Retrieves the Network registry.
# License: MIT (see LICENSE)
# -----------------------------------------------------------------------------

import os
import re
import logging
from abc import ABC
from typing import List

from edge_gateway.base_collector_publisher import BaseCollectorPublisher
from edge_gateway.helper.shell_command import ShellCommand
from event_bus.models.edge_gateway.inventory.network_inventory_event import NetworkInventoryEvent, NetworkInterfaceInfo
from event_bus.redis_stream_bus.redis_stream_bus import RedisStreamBus
from event_bus.stream_name import StreamName

logger = logging.getLogger("NetworkInventory")

class NetworkInventory(BaseCollectorPublisher, ABC):
    """
    A utility class for gathering and publishing network hardware registry.

    This class collects detailed registry about the network configuration from any Linux system,
    including hostname, FQDN, DNS servers, and network interfaces (with MAC addresses, IP addresses,
    and states). After collection, it publishes this registry to a Redis stream for downstream
    consumption by other services.

    Network configuration visibility is essential for security monitoring, connectivity
    verification, and establishing trust boundaries for health time_series transmission.
    """

    def __init__(self, event_bus: RedisStreamBus):
        """Initialize the Network Inventory.

        Args:
            event_bus (RedisStreamBus): The event bus for publishing events.

        Initializes local variables to store network registry.
        """
        super().__init__(event_bus)

        self._event_bus.register_stream(StreamName.EDGE_GW_NETWORK_INVENTORY.value, NetworkInventoryEvent)

        # Local variables to store collected time_series with default values
        self._hostname = "Unknown"
        self._fqdn = "Unknown"
        self._dns_servers = []
        self._interfaces: List[dict] = []

        logger.debug("Successfully initialized Network Inventory")

    def collect(self):
        """Collect network registry and store it in local variables.

        This method collects registry about network interfaces, host name,
        fully qualified domain name (FQDN), and DNS servers.
        """
        try:
            logger.debug("Collecting Network inventory registry")
            self._information_available = False
            self._collection_in_progress = True

            try:
                # Clear any existing interfaces, this must be done as registry may be accumulated
                self._interfaces.clear()

                interface_list = os.listdir('/sys/class/net')
                if not interface_list:
                    logger.warning("No network interfaces found.")
                else:
                    for interface in interface_list:
                        network_interface = {
                            "name": interface,
                            "mac_address": self._get_mac_address(interface),
                            "ip_address": self._get_ip_address(interface),
                            "state": self._get_interface_state(interface)
                        }
                        self._interfaces.append(network_interface)
            except Exception as e:
                logger.exception(f"Failed to get the Network Interfaces registry: {e}", exc_info=True)

            # Failure to extract the following registry will return UNKNOWN
            self._hostname = self._get_host_name()
            self._fqdn = self._get_domain_name()
            self._dns_servers = self._get_dns_servers()

            self._information_available = True
            logger.debug("Successfully collected network registry")
        finally:
            self._collection_in_progress = False

    def publish(self):
        """
        Publish the collected network registry to event bus.

        Creates a NetworkInventoryEvent with the collected time_series and publishes it to the Redis stream.
        """
        try:
            logger.info("Publishing Network inventory event")

            # Convert dicts to NetworkInterfaceEvent instances
            interface_events = [
                NetworkInterfaceInfo(**interface) for interface in self._interfaces
            ]

            event = NetworkInventoryEvent( hostname=self._hostname,
                                           fqdn=self._fqdn,
                                           dns_servers=self._dns_servers,
                                           interfaces=interface_events)

            self._publish_to_stream(StreamName.EDGE_GW_NETWORK_INVENTORY.value, event)
            logger.info(f"Published Network inventory event: {event.event_id}")
        except Exception as e:
            logger.error(f"Failed to publish Network inventory event: {e}", exc_info=True)

    @staticmethod
    def _get_mac_address(interface: str) -> str:
        """Get the MAC address of the specified interface.

        Args:
            interface (str): The name of the network interface.

        Returns:
            str: The MAC address of the interface. If an error occurs, it returns "Unknown".
        """
        try:
            with open(f'/sys/class/net/{interface}/address', 'r') as f:
                return f.read().strip()
        except Exception as e:
            logger.exception(f"Failed to get the MAC address of {interface} : {e}", exc_info=True)
            return "Unknown"

    @staticmethod
    def _get_ip_address(interface: str) -> str:
        """Get the IPv4 address of the specified interface.

        Args:
            interface (str): The name of the network interface.

        Returns:
            str: The IPv4 address of the interface. If an error occurs, it returns "Unknown".
                  If no IP address is configured, it returns "Not configured".
        """
        try:
            ip_output = ShellCommand.execute(["ip", "-o", "-4", "addr", "show", interface])
            if ip_output:
                ip_match = re.search(r'inet\s+(\d+\.\d+\.\d+\.\d+)', ip_output)
                return ip_match.group(1) if ip_match else "Not configured"
            else:
                return "Unknown"
        except Exception as e:
            logger.exception(f"Failed to get the IP address of {interface} : {e}", exc_info=True)
            return "Unknown"

    @staticmethod
    def _get_interface_state(interface: str) -> str:
        """Get the state of the specified interface.

        Args:
            interface (str): The name of the network interface.

        Returns:
            str: The state of the interface (e.g., "up", "down", etc.).
                 If an error occurs, it returns "Unknown".
        """
        try:
            with open(f'/sys/class/net/{interface}/operstate', 'r') as f:
                return f.read().strip()
        except Exception as e:
            logger.exception(f"Failed to get the state of the {interface} : {e}", exc_info=True)
            return "Unknown"

    @staticmethod
    def _get_host_name() -> str:
        """Get the host name of the system.

        Returns:
            str: The host name of the system. If there is an error, returns "Unknown".
        """
        try:
            host_name = ShellCommand.execute(["hostname"])
            return host_name if host_name else "Unknown"
        except Exception as e:
            logger.exception(f"Failed to get the host name: {e}", exc_info=True)
            return "Unknown"

    @staticmethod
    def _get_domain_name() -> str:
        """Get the fully qualified domain name (FQDN) of the system.

        Returns:
            str: The fully qualified domain name (FQDN). If an error occurs, it returns "Unknown".
        """
        try:
            domain_name = ShellCommand.execute(["hostname", "-f"])
            return domain_name
        except Exception as e:
            logger.exception(f"Failed to get the domain name: {e}", exc_info=True)
            return "Unknown"

    @staticmethod
    def _get_dns_servers() -> List[str]:
        """Get the list of configured DNS servers.

        Returns:
            List[str]: A list of DNS server IP addresses. If there is an error, it returns an empty list.
        """
        try:
            with open('/etc/resolv.conf', 'r') as f:
                resolv_conf = f.read()
                return re.findall(r'nameserver\s+([0-9.]+)', resolv_conf)
        except Exception as e:
            logger.exception(f"Failed to get the DNS servers: {e}", exc_info=True)
            return []