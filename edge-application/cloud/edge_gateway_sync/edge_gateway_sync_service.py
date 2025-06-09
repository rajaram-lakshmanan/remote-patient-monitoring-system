#!/usr/bin/env python3
# -----------------------------------------------------------------------------
# Filename: edge_gateway_sync_service.py
# Author: Rajaram Lakshmanan
# Description: Sync service for Edge Gateway data to cloud
# License: MIT (see LICENSE)
# -----------------------------------------------------------------------------

import logging
import threading
from typing import Dict, Any

from cloud.azure_iot_hub.cloud_to_device_command import CloudToDeviceCommand
from event_bus.models.trigger_event import TriggerEvent
from event_bus.redis_stream_bus.redis_stream_bus import RedisStreamBus
from event_bus.stream_name import StreamName
from cloud.azure_iot_hub.azure_iot_hub_client import AzureIoTHubClient
from config.models.cloud.azure_iot_hub_config import AzureIoTHubConfig
from config.models.cloud.cloud_edge_gateway_sync_config import CloudEdgeGatewaySyncConfig
from event_bus.models.edge_gateway.telemetry.cpu_telemetry_event import CpuTelemetryEvent
from event_bus.models.edge_gateway.telemetry.memory_telemetry_event import MemoryTelemetryEvent
from event_bus.models.edge_gateway.telemetry.storage_telemetry_event import StorageTelemetryEvent
from event_bus.models.edge_gateway.inventory.cpu_inventory_event import CpuInventoryEvent
from event_bus.models.edge_gateway.inventory.network_inventory_event import NetworkInventoryEvent
from event_bus.models.edge_gateway.inventory.os_kernel_inventory_event import OsKernelInventoryEvent
from event_bus.models.edge_gateway.inventory.package_inventory_event import PackageInventoryEvent
from event_bus.models.edge_gateway.inventory.service_inventory_event import ServiceInventoryEvent
from event_bus.models.edge_gateway.security.account_security_monitor_event import AccountSecurityMonitorEvent
from event_bus.models.edge_gateway.security.bluetooth_device_monitor_event import BluetoothDeviceMonitorEvent
from event_bus.models.edge_gateway.security.hardening_information_event import HardeningInformationEvent
from event_bus.models.edge_gateway.security.system_audit_collector_event import SystemAuditCollectorEvent
from event_bus.models.edge_gateway.security.vulnerability_scan_event import VulnerabilityScanEvent
from event_bus.models.edge_gateway.security.wifi_connection_monitor_event import WifiConnectionMonitorEvent

logger = logging.getLogger("EdgeGatewaySyncService")

class EdgeGatewaySyncService:
    """
    Sync service for Edge Gateway data to the cloud.

    This service subscribes to all Edge Gateway events (telemetry, inventory, security)
    and forwards them to the cloud IoT Hub.
    """

    def __init__(self,
                 event_bus: RedisStreamBus,
                 config: CloudEdgeGatewaySyncConfig,
                 azure_iot_hub_config: AzureIoTHubConfig):
        """
        Initialize the Edge Gateway sync service.

        Args:
            event_bus: Redis event bus for subscribing to events
            config: Configuration for the edge gateway sync
            azure_iot_hub_config: Azure IoT Hub configuration
        """
        self._event_bus = event_bus
        self._config = config
        self._azure_iot_hub_config = azure_iot_hub_config

        self._device_id = "edge_gateway"  # Device ID for the gateway in IoT Hub
        self._iot_client = None
        self._running = False
        self._lock = threading.RLock()

        # Map of stream names to event handlers
        self._stream_handlers = {
            # Telemetry events
            StreamName.EDGE_GW_CPU_TELEMETRY.value: self._handle_cpu_telemetry_event,
            StreamName.EDGE_GW_MEMORY_TELEMETRY.value: self._handle_memory_telemetry_event,
            StreamName.EDGE_GW_STORAGE_TELEMETRY.value: self._handle_storage_telemetry_event,

            # Inventory events
            StreamName.EDGE_GW_CPU_INVENTORY.value: self._handle_cpu_inventory_event,
            StreamName.EDGE_GW_NETWORK_INVENTORY.value: self._handle_network_inventory_event,
            StreamName.EDGE_GW_OS_KERNEL_INVENTORY.value: self._handle_os_kernel_inventory_event,
            StreamName.EDGE_GW_PACKAGE_INVENTORY.value: self._handle_package_inventory_event,
            StreamName.EDGE_GW_SERVICE_INVENTORY.value: self._handle_service_inventory_event,

            # Security events
            StreamName.EDGE_GW_ACCOUNT_SECURITY_MONITOR.value: self._handle_account_security_event,
            StreamName.EDGE_GW_BLUETOOTH_DEVICE_MONITOR.value: self._handle_bluetooth_device_event,
            StreamName.EDGE_GW_HARDENING_INFORMATION.value: self._handle_hardening_information_event,
            StreamName.EDGE_GW_SYSTEM_AUDIT_COLLECTOR.value: self._handle_system_audit_event,
            StreamName.EDGE_GW_VULNERABILITY_SCAN.value: self._handle_vulnerability_scan_event,
            StreamName.EDGE_GW_WIFI_CONNECTION_MONITOR.value: self._handle_wifi_connection_event
        }

        logger.debug(f"EdgeGatewaySyncService initialized for gateway device")

    def start(self) -> bool:
        """
        Start the edge gateway sync service.

        Returns:
            bool: True if started successfully, False otherwise
        """
        with self._lock:
            if self._running:
                logger.warning("Edge Gateway sync service is already running")
                return True

            try:
                logger.debug("Starting Edge Gateway sync service")

                # Initialize the IoT Hub client
                if not self._initialize_iot_client():
                    logger.error("Failed to initialize IoT Hub client")
                    return False

                self._running = True
                logger.info("Edge Gateway sync service started")
                return True

            except Exception as e:
                logger.error(f"Error starting Edge Gateway sync service: {e}")
                self._cleanup()
                return False

    def stop(self) -> bool:
        """
        Stop the edge gateway sync service.

        Returns:
            bool: True if stopped successfully, False otherwise
        """
        with self._lock:
            if not self._running:
                logger.warning("Edge Gateway sync service is not running")
                return True

            try:
                logger.debug("Stopping Edge Gateway sync service")

                self._cleanup()

                self._running = False
                logger.info("Edge Gateway sync service stopped")
                return True

            except Exception as e:
                logger.error(f"Error stopping Edge Gateway sync service: {e}")
                self._running = False
                return False

    def _initialize_iot_client(self) -> bool:
        """
        Initialize the Azure IoT Hub client.

        Returns:
            bool: True if initialized successfully, False otherwise
        """
        try:
            # Set up device info and certificate paths
            cert_file = f"{self._azure_iot_hub_config.certificate_folder}/edge_gateway.pem"
            key_file = f"{self._azure_iot_hub_config.certificate_folder}/edge_gateway.key"

            # Create the IoT Hub client
            self._iot_client = AzureIoTHubClient(
                host_name=self._azure_iot_hub_config.host_name,
                device_id=self._device_id,
                x509_cert_file=cert_file,
                x509_key_file=key_file,
                connection_timeout=self._azure_iot_hub_config.connection_timeout,
                retry_count=self._azure_iot_hub_config.retry_count
            )

            self._iot_client.register_method_handler( CloudToDeviceCommand.TRIGGER_VULN_SCAN.value,
                                                      self._generic_handler)

            # Connect to IoT Hub
            if not self._iot_client.start():
                logger.error("Failed to connect to IoT Hub")
                return False

            logger.debug("Connected to IoT Hub")
            return True

        except Exception as e:
            logger.error(f"Error initializing IoT Hub client: {e}")
            return False

    def _generic_handler(self, method_name, payload):
        """
        Generic handler for the commands from the Cloud to the Device (Edge Gateway).

        Args:
            method_name: Name of the method sent from the Cloud.
            payload: Payload sent from the Cloud.
        """
        normalized_method = method_name.replace(" ", "").lower()
        normalized_trigger_vuln = CloudToDeviceCommand.TRIGGER_VULN_SCAN.value.replace(" ", "").lower()
        if normalized_method == normalized_trigger_vuln:
            event = TriggerEvent(command_name=method_name,
                                 trigger_source="cloud",
                                 reason="manual_trigger")
            self._event_bus.publish(StreamName.EDGE_GW_VULNERABILITY_SCAN_TRIGGER.value, event)

    def _cleanup(self) -> None:
        """Clean up resources."""
        if self._iot_client:
            try:
                self._iot_client.stop()
                logger.debug("IoT Hub client stopped")
            except Exception as e:
                logger.error(f"Error stopping IoT Hub client: {e}")

            self._iot_client = None

    def subscribe_to_events(self, consumer_group_name: str) -> None:
        """Subscribe to all Edge Gateway events."""
        logger.debug("Subscribing to Edge Gateway events")

        # Subscribe to each event stream
        for stream_name, handler in self._stream_handlers.items():
            self._event_bus.subscribe(stream_name,
                                      consumer_group_name,
                                      handler)

        logger.debug(f"Subscribed to {len(self._stream_handlers)} Edge Gateway event streams")

    def send_message_to_iot_hub(self, data: Dict[str, Any], properties: Dict[str, str]) -> bool:
        """
        Send a message to IoT Hub with the provided data and properties.

        Args:
            data: The data to send
            properties: Message properties for routing

        Returns:
            bool: True if sent successfully, False otherwise
        """
        with self._lock:
            if not self._iot_client or not self._iot_client.is_connected():
                logger.warning("IoT Hub client not connected, can't send message")
                return False

            try:
                # Send the message
                result = self._iot_client.send_message(data, properties)
                if result:
                    logger.debug("Message sent to IoT Hub")
                else:
                    logger.warning("Failed to send message to IoT Hub")
                return result
            except Exception as e:
                logger.error(f"Error sending message to IoT Hub: {e}")
                return False

    # === Telemetry Event Handlers ===

    def _handle_cpu_telemetry_event(self, event: CpuTelemetryEvent) -> None:
        """Handle CPU telemetry event."""
        logger.debug(f"Processing CPU telemetry event: {event.event_id}")

        processed_data = {
            "timestamp": event.timestamp.isoformat(),
            "temperature": event.temperature_celsius,
            "frequency": event.frequency_mhz,
            "eventId": event.event_id
        }

        properties = {
            "type": "edgeGatewayTelemetry",
            "category": "cpu",
            "deviceType": "EdgeGateway"
        }

        self.send_message_to_iot_hub(processed_data, properties)
        logger.debug("CPU telemetry sent to IoT Hub")

    def _handle_memory_telemetry_event(self, event: MemoryTelemetryEvent) -> None:
        """Handle memory telemetry event."""
        logger.debug(f"Processing memory telemetry event: {event.event_id}")

        processed_data = {
            "timestamp": event.timestamp.isoformat(),
            "totalMemory": event.total_memory,
            "freeMemory": event.free_memory,
            "availableMemory": event.available_memory,
            "swapTotalMemory": event.swap_total_memory,
            "swapFreeMemory": event.swap_free_memory,
            "eventId": event.event_id
        }

        properties = {
            "type": "edgeGatewayTelemetry",
            "category": "memory",
            "deviceType": "EdgeGateway"
        }

        self.send_message_to_iot_hub(processed_data, properties)
        logger.debug("Memory telemetry sent to IoT Hub")

    def _handle_storage_telemetry_event(self, event: StorageTelemetryEvent) -> None:
        """Handle storage telemetry event."""
        logger.debug(f"Processing storage telemetry event: {event.event_id}")

        # Convert to dict for easier serialization
        storage_data = [device.model_dump() for device in event.storage_data]

        processed_data = {
            "timestamp": event.timestamp.isoformat(),
            "storageData": storage_data,
            "eventId": event.event_id
        }

        properties = {
            "type": "edgeGatewayTelemetry",
            "category": "storage",
            "deviceType": "EdgeGateway"
        }

        self.send_message_to_iot_hub(processed_data, properties)
        logger.debug("Storage telemetry sent to IoT Hub")

    # === Inventory Event Handlers ===

    def _handle_cpu_inventory_event(self, event: CpuInventoryEvent) -> None:
        """Handle CPU inventory event."""
        logger.debug(f"Processing CPU inventory event: {event.event_id}")

        processed_data = {
            "timestamp": event.timestamp.isoformat(),
            "piModel": event.pi_model,
            "revision": event.revision,
            "serial": event.serial,
            "cpuCores": event.cpu_cores,
            "cpuModel": event.cpu_model,
            "cpuArchitecture": event.cpu_architecture,
            "eventId": event.event_id
        }

        properties = {
            "type": "edgeGatewayInventory",
            "category": "cpu",
            "deviceType": "EdgeGateway"
        }

        self.send_message_to_iot_hub(processed_data, properties)
        logger.debug("CPU inventory sent to IoT Hub")

    def _handle_network_inventory_event(self, event: NetworkInventoryEvent) -> None:
        """Handle network inventory event."""
        logger.debug(f"Processing network inventory event: {event.event_id}")

        # Convert interfaces to dict for easier serialization
        interfaces = [interface.model_dump() for interface in event.interfaces]

        processed_data = {
            "timestamp": event.timestamp.isoformat(),
            "hostname": event.hostname,
            "fqdn": event.fqdn,
            "dnsServers": event.dns_servers,
            "interfaces": interfaces,
            "eventId": event.event_id
        }

        properties = {
            "type": "edgeGatewayInventory",
            "category": "network",
            "deviceType": "EdgeGateway"
        }

        self.send_message_to_iot_hub(processed_data, properties)
        logger.debug("Network inventory sent to IoT Hub")

    def _handle_os_kernel_inventory_event(self, event: OsKernelInventoryEvent) -> None:
        """Handle OS/kernel inventory event."""
        logger.debug(f"Processing OS/kernel inventory event: {event.event_id}")

        # Convert logged-in users to dict for easier serialization
        users = [user.model_dump() for user in event.logged_in_users]

        processed_data = {
            "timestamp": event.timestamp.isoformat(),
            "osName": event.os_name,
            "osVersion": event.os_version,
            "osId": event.os_id,
            "uptime": event.uptime,
            "loggedInUsers": users,
            "kernelName": event.kernel_name,
            "kernelVersion": event.kernel_version,
            "kernelBuildDate": event.kernel_build_date,
            "eventId": event.event_id
        }

        properties = {
            "type": "edgeGatewayInventory",
            "category": "osKernel",
            "deviceType": "EdgeGateway"
        }

        self.send_message_to_iot_hub(processed_data, properties)
        logger.debug("OS/kernel inventory sent to IoT Hub")

    def _handle_package_inventory_event(self, event: PackageInventoryEvent) -> None:
        """Handle package inventory event."""
        logger.debug(f"Processing package inventory event: {event.event_id}")

        # Convert packages to a simple list format for efficiency
        all_packages = [{"name": pkg.name, "version": pkg.version} for pkg in event.all_packages]
        security_packages = [{"name": pkg.name, "version": pkg.version} for pkg in event.security_packages]
        python_packages = [{"name": pkg.name, "version": pkg.version} for pkg in event.python_packages]

        # Optional: For very large package lists, consider sending counts only with the option to query details
        processed_data = {
            "timestamp": event.timestamp.isoformat(),
            "packageCounts": {
                "all": len(all_packages),
                "security": len(security_packages),
                "python": len(python_packages)
            },
            "securityPackages": security_packages,  # Always send security packages
            "allPackages": all_packages if len(all_packages) < 500 else [],  # Only send the package info if not too large
            "pythonPackages": python_packages if len(python_packages) < 500 else [],  # Only the python package info if not too large
            "eventId": event.event_id
        }

        properties = {
            "type": "edgeGatewayInventory",
            "category": "packages",
            "deviceType": "EdgeGateway"
        }

        self.send_message_to_iot_hub(processed_data, properties)
        logger.debug("Package inventory sent to IoT Hub")

    def _handle_service_inventory_event(self, event: ServiceInventoryEvent) -> None:
        """Handle service inventory event."""
        logger.debug(f"Processing service inventory event: {event.event_id}")

        processed_data = {
            "timestamp": event.timestamp.isoformat(),
            "runningServices": event.running_services,
            "runningCount": event.running_count,
            "securityServices": event.security_services,
            "eventId": event.event_id
        }

        properties = {
            "type": "edgeGatewayInventory",
            "category": "services",
            "deviceType": "EdgeGateway"
        }

        self.send_message_to_iot_hub(processed_data, properties)
        logger.debug("Service inventory sent to IoT Hub")

    # === Security Event Handlers ===

    def _handle_account_security_event(self, event: AccountSecurityMonitorEvent) -> None:
        """Handle account security event."""
        logger.debug(f"Processing account security event: {event.event_id}")

        # Convert account info to dict for easier serialization
        accounts = [account.model_dump() for account in event.accounts_info]

        processed_data = {
            "timestamp": event.timestamp.isoformat(),
            "accountsInfo": accounts,
            "eventId": event.event_id
        }

        properties = {
            "type": "edgeGatewaySecurity",
            "category": "accounts",
            "deviceType": "EdgeGateway"
        }

        self.send_message_to_iot_hub(processed_data, properties)
        logger.debug("Account security data sent to IoT Hub")

    def _handle_bluetooth_device_event(self, event: BluetoothDeviceMonitorEvent) -> None:
        """Handle Bluetooth device security event."""
        logger.debug(f"Processing Bluetooth device event: {event.event_id}")

        # Convert devices to dict for easier serialization
        devices = [device.model_dump() for device in event.devices]

        processed_data = {
            "timestamp": event.timestamp.isoformat(),
            "devices": devices,
            "eventId": event.event_id
        }

        properties = {
            "type": "edgeGatewaySecurity",
            "category": "bluetooth",
            "deviceType": "EdgeGateway"
        }

        self.send_message_to_iot_hub(processed_data, properties)
        logger.debug("Bluetooth device data sent to IoT Hub")

    def _handle_hardening_information_event(self, event: HardeningInformationEvent) -> None:
        """Handle the security-hardening event."""
        logger.debug(f"Processing security hardening event: {event.event_id}")

        # Convert hardening measures to dict for easier serialization
        hardening_info = [measure.model_dump() for measure in event.hardening_info]

        processed_data = {
            "timestamp": event.timestamp.isoformat(),
            "hardeningInfo": hardening_info,
            "eventId": event.event_id
        }

        properties = {
            "type": "edgeGatewaySecurity",
            "category": "hardening",
            "deviceType": "EdgeGateway"
        }

        self.send_message_to_iot_hub(processed_data, properties)
        logger.debug("Security hardening data sent to IoT Hub")

    def _handle_system_audit_event(self, event: SystemAuditCollectorEvent) -> None:
        """Handle system audit event."""
        logger.debug(f"Processing system audit event: {event.event_id}")

        # Convert audit logs to dict for easier serialization
        logs = [log.model_dump() for log in event.logs]

        processed_data = {
            "timestamp": event.timestamp.isoformat(),
            "logs": logs,
            "lastCollectionTime": event.last_collection_time,
            "eventId": event.event_id
        }

        properties = {
            "type": "edgeGatewaySecurity",
            "category": "audit",
            "deviceType": "EdgeGateway"
        }

        self.send_message_to_iot_hub(processed_data, properties)
        logger.debug("System audit data sent to IoT Hub")

    def _handle_vulnerability_scan_event(self, event: VulnerabilityScanEvent) -> None:
        """Handle vulnerability scan event."""
        logger.debug(f"Processing vulnerability scan event: {event.event_id}")

        # Convert vulnerabilities to dict for easier serialization
        vulnerabilities = [vuln.model_dump() for vuln in event.vulnerabilities]

        processed_data = {
            "timestamp": event.timestamp.isoformat(),
            "scanDate": event.scan_date,
            "vulnerabilities": vulnerabilities,
            "eventId": event.event_id
        }

        properties = {
            "type": "edgeGatewaySecurity",
            "category": "vulnerabilities",
            "deviceType": "EdgeGateway"
        }

        self.send_message_to_iot_hub(processed_data, properties)
        logger.debug("Vulnerability scan data sent to IoT Hub")

    def _handle_wifi_connection_event(self, event: WifiConnectionMonitorEvent) -> None:
        """Handle Wi-Fi connection security event."""
        logger.debug(f"Processing Wi-Fi connection event: {event.event_id}")

        # Convert network info to dict for easier serialization
        network_info = event.network_info.model_dump()

        processed_data = {
            "timestamp": event.timestamp.isoformat(),
            "networkInfo": network_info,
            "eventId": event.event_id
        }

        properties = {
            "type": "edgeGatewaySecurity",
            "category": "wifi",
            "deviceType": "EdgeGateway"
        }

        self.send_message_to_iot_hub(processed_data, properties)
        logger.debug("Wi-Fi connection data sent to IoT Hub")