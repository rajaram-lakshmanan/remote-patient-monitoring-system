#!/usr/bin/env python3
# -----------------------------------------------------------------------------
# Filename: edge_gateway.py
# Author: Rajaram Lakshmanan
# Description: Orchestrator script for Edge Gateway monitoring modules.
# Runs modules on specified schedules:
# - Inventory: monthly
# - Telemetry: daily
# - Security: weekly
# License: MIT (see LICENSE)
# -----------------------------------------------------------------------------

import threading
from datetime import datetime, timezone
import time
import logging
from typing import Dict, Any, Optional
from enum import Enum

from config.models.edge_gateway.edge_gateway_config import EdgeGatewayConfig
from edge_gateway.base_collector_publisher import BaseCollectorPublisher
from event_bus.redis_stream_bus.redis_stream_bus import RedisStreamBus
from edge_gateway.security.account_security_monitor import AccountSecurityMonitor
from edge_gateway.security.system_audit_collector import SystemAuditCollector
from edge_gateway.security.bluetooth_device_monitor import BluetoothDeviceMonitor
from edge_gateway.security.hardening_information import HardeningInformation
from edge_gateway.security.vulnerability_scan import VulnerabilityScan
from edge_gateway.security.wifi_connection_monitor import WifiConnectionMonitor
from edge_gateway.telemetry.cpu_telemetry import CpuTelemetry
from edge_gateway.telemetry.memory_telemetry import MemoryTelemetry
from edge_gateway.telemetry.storage_telemetry import StorageTelemetry
from edge_gateway.inventory.cpu_inventory import CpuInventory
from edge_gateway.inventory.network_inventory import NetworkInventory
from edge_gateway.inventory.os_kernel_inventory import OsKernelInventory
from edge_gateway.inventory.package_inventory import PackageInventory
from edge_gateway.inventory.service_inventory import ServiceInventory

logger = logging.getLogger("EdgeGateway")

class AgentType(Enum):
    """Types of observability agents for group operations."""
    INVENTORY = "inventory"
    TELEMETRY = "telemetry"
    SECURITY = "security"
    ALL = "all"

class EdgeGateway:
    """
    Main Edge Gateway class that manages all system observability agents.

    This class initializes and coordinates the collection and publishing of
    system registry, telemetry, and security time_series to provide comprehensive
    visibility for the digital twin.
    """

    def __init__(self,
                 event_bus: RedisStreamBus,
                 config: EdgeGatewayConfig):
        """
        Initialize the Edge Gateway with all observability agents.

        Args:
            event_bus: The event bus instance passed from the main app.
            config: Synchronization configuration of the Edge gateway to the cloud.
        """
        self._event_bus = event_bus
        self._config = config

        # Threading synchronization
        self._lock = threading.RLock()
        self._scheduler_thread = None
        self._running = False
        self._collection_threads = {}

        # Track when tasks were last run to avoid running them multiple times
        self._last_run: Dict[AgentType, Optional[datetime]] = {}

        # Dictionary to store all observability agents grouped by type
        self._observability_agents: Dict[str, BaseCollectorPublisher] = {}
        self._agent_types: Dict[str, AgentType] = {}

        # Initialize all agents
        self._initialize_observability_agents()

        logger.info(f"Edge Gateway initialized with {len(self._observability_agents)} observability agents")

    # === Public API Methods ===

    def start(self) -> None:
        """
        Start the Edge Gateway scheduler for periodic collection.

        This method starts a background thread that runs the collection
        operations on the configured schedule (config file):
        - Security modules
        - Telemetry modules
        - Inventory modules
        """
        with self._lock:
            if self._running:
                logger.warning("Edge Gateway already running")
                return

            self._running = True

        # Start the background scheduler thread
        self._scheduler_thread = threading.Thread(
            target=self._scheduler_loop,
            name="edge-gateway-scheduler",
            daemon=True
        )
        self._scheduler_thread.start()

        logger.info("Edge Gateway scheduler started")

    def stop(self) -> None:
        """
        Stop the Edge Gateway scheduler and cleanup resources.
        """
        logger.info("Stopping Edge Gateway")

        with self._lock:
            self._running = False

        # Wait for the scheduler thread to finish
        if self._scheduler_thread and self._scheduler_thread.is_alive():
            logger.debug("Waiting for scheduler thread to finish...")
            self._scheduler_thread.join(5.0)

            # Check after a join attempt
            if self._scheduler_thread.is_alive():
                logger.warning("Scheduler thread did not terminate within timeout")

        # Wait for any collection threads to finish
        with self._lock:
            collection_threads = list(self._collection_threads.values())

        for thread in collection_threads:
            if thread.is_alive():
                logger.debug(f"Waiting for collection thread {thread.name} to finish...")
                thread.join(5.0)

                if thread.is_alive():
                    logger.warning(f"Collection thread {thread.name} did not terminate within timeout")

        logger.info("Edge Gateway stopped")

    def subscribe_to_events(self) -> None:
        """Subscribe to the events required by the manager and its agents."""
        logger.debug("Subscribing to events")

        try:
            for agent in self._observability_agents.values():
                agent.subscribe_to_events()
            logger.info("Subscribed to events")
        except Exception as e:
            logger.error(f"Error subscribing to events: {e}", exc_info=True)

    def run_collection_cycle(self, agent_type: AgentType = AgentType.ALL) -> Dict[str, Any]:
        """
        Run a complete collection and publication cycle synchronously.

        This is a blocking call that will collect and publish time_series from
        all specified agents and return the results.

        Args:
            agent_type: The type of agents to collect from (default: ALL)

        Returns:
            A dictionary with collection results/status
        """
        logger.info(f"Starting synchronous collection cycle for {agent_type.value}")

        results = {}
        start_time = datetime.now(timezone.utc)

        try:
            # Get the list of agents to collect from
            agents_to_collect = self._get_agents_by_type(agent_type)

            # Collect and publish from each agent
            for name, agent in agents_to_collect.items():
                try:
                    logger.debug(f"Collecting from {name}")
                    agent.collect()

                    # If the agent collected a registry, publish it
                    if agent.collection_successful:
                        logger.debug(f"Publishing from {name}")
                        agent.publish()
                        results[name] = {
                            "status": "success"
                        }
                    else:
                        logger.warning(f"Collection from {name} did not produce registry to publish")
                        results[name] = {
                            "status": "no_data"
                        }
                except Exception as e:
                    logger.error(f"Error processing agent {name}: {e}", exc_info=True)
                    results[name] = {
                        "status": "error",
                        "error": str(e)
                    }

            # Add a summary registry
            results["summary"] = {
                "total_agents": len(agents_to_collect),
                "successful": sum(1 for r in results.values() if isinstance(r, dict) and r.get("status") == "success"),
                "no_data": sum(1 for r in results.values() if isinstance(r, dict) and r.get("status") == "no_data"),
                "failed": sum(1 for r in results.values() if isinstance(r, dict) and r.get("status") == "error"),
                "duration_seconds": (datetime.now(timezone.utc) - start_time).total_seconds()
            }

            logger.info(f"Completed collection cycle: {results['summary']}")
            return results

        except Exception as e:
            logger.error(f"Error in collection cycle: {e}", exc_info=True)
            return {
                "status": "error",
                "error": str(e),
                "duration_seconds": (datetime.now(timezone.utc) - start_time).total_seconds()
            }

    # === Internal Implementation ===

    def _initialize_observability_agents(self):
        """Initialize all system observability agents."""
        # Inventory agents
        self._add_agent("cpu_inventory", CpuInventory(self._event_bus), AgentType.INVENTORY)
        self._add_agent("network_inventory", NetworkInventory(self._event_bus), AgentType.INVENTORY)
        self._add_agent("os_kernel_inventory", OsKernelInventory(self._event_bus), AgentType.INVENTORY)
        self._add_agent("package_inventory", PackageInventory(self._event_bus), AgentType.INVENTORY)
        self._add_agent("service_inventory", ServiceInventory(self._event_bus), AgentType.INVENTORY)

        # Telemetry agents
        self._add_agent("cpu_telemetry", CpuTelemetry(self._event_bus), AgentType.TELEMETRY)
        self._add_agent("memory_telemetry", MemoryTelemetry(self._event_bus), AgentType.TELEMETRY)
        self._add_agent("storage_telemetry", StorageTelemetry(self._event_bus), AgentType.TELEMETRY)

        # Security monitoring agents
        self._add_agent("account_security", AccountSecurityMonitor(self._event_bus), AgentType.SECURITY)
        self._add_agent("bluetooth_security", BluetoothDeviceMonitor(self._event_bus), AgentType.SECURITY)
        self._add_agent("hardening_information", HardeningInformation(self._event_bus), AgentType.SECURITY)
        self._add_agent("system_audit", SystemAuditCollector(self._event_bus), AgentType.SECURITY)
        self._add_agent("vulnerability_scan", VulnerabilityScan(self._event_bus), AgentType.SECURITY)
        self._add_agent("wifi_security", WifiConnectionMonitor(self._event_bus), AgentType.SECURITY)

    def _add_agent(self, name: str, agent: BaseCollectorPublisher, agent_type: AgentType):
        """
        Add an observability agent to the collection.

        Args:
            name: The name to register the agent under
            agent: The agent instance
            agent_type: The type of agent (INVENTORY, TELEMETRY, SECURITY)
        """
        with self._lock:
            self._observability_agents[name] = agent
            self._agent_types[name] = agent_type

        logger.debug(f"Added {agent_type.value} agent: {name}")

    def _get_agents_by_type(self, agent_type: AgentType) -> Dict[str, BaseCollectorPublisher]:
        """
        Get all agents of a specific type.

        Args:
            agent_type: The type of agents to retrieve

        Returns:
            A dictionary of agent instances keyed by name
        """
        with self._lock:
            if agent_type == AgentType.ALL:
                return dict(self._observability_agents)

            return {
                name: agent for name, agent in self._observability_agents.items()
                if self._agent_types.get(name) == agent_type
            }

    def _collect_publish_thread(self, request_id: str, agent_type: AgentType, trigger_type: str):
        """
        Background thread function for running a collection and publishing cycle.

        Args:
            request_id: The unique ID for this collection request
            agent_type: The type of agents to collect from
            trigger_type: Whether this is "scheduled" or "on-demand"
        """
        try:
            logger.info(f"Starting {trigger_type} collection {request_id} for {agent_type.value}")
            results = self.run_collection_cycle(agent_type)
            logger.info(f"Completed {trigger_type} collection {request_id} with summary: {results.get('summary', {})}")
        except Exception as e:
            logger.error(f"Error in {trigger_type} collection thread {request_id}: {e}", exc_info=True)
        finally:
            with self._lock:
                self._collection_threads.pop(request_id, None)

    def _scheduler_loop(self):
        """
        Background thread function for running the scheduler, checking intervals
        for various agents (telemetry, security, inventory) and performing the necessary
        actions based on the configured intervals.
        """
        try:
            logger.info("Scheduler thread started")

            while self._running:
                now = datetime.now(timezone.utc)

                # Check and run scheduled tasks for each agent type
                self._check_and_run(AgentType.TELEMETRY, self._config.telemetry_schedule_seconds, now)
                self._check_and_run(AgentType.SECURITY, self._config.security_schedule_seconds, now)
                self._check_and_run(AgentType.INVENTORY, self._config.inventory_schedule_seconds, now)

                if not self._running:
                    break
                time.sleep(30)  # Sleep for 30 seconds before re-checking, can adjust this interval

        except Exception as e:
            logger.error(f"Error in scheduler loop: {e}", exc_info=True)
        finally:
            logger.info("Scheduler thread stopped")

    def _check_and_run(self, agent_type: AgentType, interval_seconds: int, now: datetime):
        """
        Determines whether the data collection for a given agent type should be executed based
        on the specified time interval and the last time it was run. If the collection is due,
        it runs the scheduled collection and updates the last run timestamp.

        Args:
            agent_type (AgentType): The type of agent for which the collection is to be checked and possibly run.
            interval_seconds (int): The minimum number of seconds that must elapse between consecutive runs.
            now (datetime): The current time used to compare against the last run time.
        """
        last_run = self._last_run.get(agent_type)

        # If last_run is None or if the time difference exceeds the interval
        if last_run is None or (now - last_run).total_seconds() >= interval_seconds:
            logger.info(f"Running scheduled collection for {agent_type.name}...")
            self._run_scheduled_collection(agent_type)
            self._last_run[agent_type] = now

    def _run_scheduled_collection(self, agent_type: AgentType):
        """
        Run a scheduled collection for the specified agent type.

        Args:
            agent_type: The type of agents to collect from
        """
        logger.info(f"Running scheduled collection for {agent_type.value}")

        request_id = f"scheduled-{agent_type.value}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"

        # Start the collection in a separate thread to avoid blocking the scheduler
        thread = threading.Thread(
            target=self._collect_publish_thread,
            name=f"scheduled-collection-{agent_type.value}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}",
            args=(request_id, agent_type, "scheduled"),
            daemon=True
        )

        with self._lock:
            self._collection_threads[request_id] = thread

        thread.start()
        logger.info(f"Started scheduled collection thread for {agent_type.value}")

    @staticmethod
    def _is_time_to_run(hour, day_of_week=None, day_of_month=None):
        """
        Check if it's time to run a scheduled task.

        Args:
            hour: Hour to run (0-23)
            day_of_week: Day of week to run (0=Monday, 6=Sunday), or None for any day
            day_of_month: Day of month to run (1-31), or None for any day

        Returns:
            True if it's time to run, False otherwise
        """
        now = datetime.now(timezone.utc)

        # Check if the current hour matches
        if now.hour != hour:
            return False

        # Check day of week if specified
        if day_of_week is not None:
            # datetime uses 0=Monday for weekday()
            if now.weekday() != day_of_week:
                return False

        # Check day of month if specified
        if day_of_month is not None:
            if now.day != day_of_month:
                return False

        return True