#!/usr/bin/env python3
# -----------------------------------------------------------------------------
# Filename: service_inventory.py
# Author: Rajaram Lakshmanan
# Description: Collects running system services including security services.
# License: MIT (see LICENSE)
# -----------------------------------------------------------------------------

import logging
from abc import ABC
from typing import List

from edge_gateway.base_collector_publisher import BaseCollectorPublisher
from edge_gateway.helper.shell_command import ShellCommand
from event_bus.models.edge_gateway.inventory.service_inventory_event import ServiceInventoryEvent
from event_bus.redis_stream_bus.redis_stream_bus import RedisStreamBus
from event_bus.stream_name import StreamName

logger = logging.getLogger("ServiceInventory")


class ServiceInventory(BaseCollectorPublisher, ABC):
    """
    A utility class for gathering and publishing service registry from Linux systems.

    This class collects registry about running system services, including a count of running
    services and active security-related services. After collection, it publishes this registry
    to a Redis stream for downstream consumption by other services.

    Service inventory time_series provides critical visibility into system functionality and
    security coverage, revealing both operational and security states for the digital twin.
    """

    def __init__(self, event_bus: RedisStreamBus):
        """Initialize the Network Inventory.

        Args:
            event_bus (RedisStreamBus): The event bus for publishing events.

        Initializes local variables to store running and security services registry.
        """
        super().__init__(event_bus)

        self._event_bus.register_stream(StreamName.EDGE_GW_SERVICE_INVENTORY.value, ServiceInventoryEvent)

        self._running_services: List[str] = []
        self._running_count: int = 0
        self._security_services: List[str] = []
        logger.debug("Successfully initialized Service Inventory")

    def collect(self):
        """Collect running service registry."""
        try:
            logger.debug("Collecting services registry")
            self._information_available = False
            self._collection_in_progress = True

            self._collect_services()

            self._information_available = True
            logger.debug("Successfully collected services registry")
        except Exception as e:
            logger.exception(f"Failed during service inventory collection. {e}", exc_info=True)
            self._collection_in_progress = False
        finally:
            self._collection_in_progress = False

    def publish(self):
        """
        Publish the collected services to event bus.

        Creates a CpuInventoryEvent with the collected time_series and publishes it to the appropriate stream.
        """
        try:
            logger.info("Publishing Services inventory event")
            event = ServiceInventoryEvent(running_services=self._running_services,
                                          running_count=self._running_count,
                                          security_services=self._security_services)
            self._publish_to_stream(StreamName.EDGE_GW_SERVICE_INVENTORY.value, event)
            logger.info(f"Published service inventory event: {event.event_id}")
        except Exception as e:
            logger.error(f"Failed to publish service inventory event: {e}", exc_info=True)

    def _collect_services(self):
        """Internal method to gather service registry from systemd."""
        try:
            systemd_output = ShellCommand.execute([
                "systemctl", "list-units", "--type=service", "--state=running", "--no-pager"
            ])

            services = []
            if systemd_output:
                for line in systemd_output.strip().split('\n'):
                    if ".service" in line:
                        parts = line.split()
                        if parts:
                            services.append(parts[0])

            self._running_services = services
            self._running_count = len(services)

            self._security_services = ServiceInventory._get_active_security_services()
        except Exception as e:
            logger.exception(f"Error collecting systemd service registry: {e}", exc_info=True)

    @staticmethod
    def _get_active_security_services() -> List[str]:
        """Check for active security-related services.

        Returns:
            List[str]: The active security-related services.
            """
        active = []
        for service in ["ssh", "fail2ban", "ufw", "firewalld", "clamav", "apparmor"]:
            try:
                status = ShellCommand.execute(["systemctl", "is-active", f"{service}.service"])
                if status and status.strip() == "active":
                    active.append(service)
            except Exception as e:
                logger.debug(f"Service check failed for {service}: {e}")
        return active