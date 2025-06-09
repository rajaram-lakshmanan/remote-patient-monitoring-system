#!/usr/bin/env python3
# -----------------------------------------------------------------------------
# Filename: edge_gateway_registry_event_consumer.py
# Author: Rajaram Lakshmanan
# Description:  Consumes events from Redis streams and stores them in
# SQLite databases.
# License: MIT (see LICENSE)
# -----------------------------------------------------------------------------

import json
import logging
from datetime import datetime
from typing import Any, Optional

from repository.edge_gateway.edge_gateway_registry_manager import EdgeGatewayRegistryManager
from event_bus.redis_stream_bus.redis_stream_bus import RedisStreamBus
from event_bus.stream_name import StreamName

# Import event types
from event_bus.models.edge_gateway.inventory.cpu_inventory_event import CpuInventoryEvent
from event_bus.models.edge_gateway.inventory.network_inventory_event import NetworkInventoryEvent
from event_bus.models.edge_gateway.inventory.os_kernel_inventory_event import OsKernelInventoryEvent
from event_bus.models.edge_gateway.inventory.package_inventory_event import PackageInventoryEvent
from event_bus.models.edge_gateway.inventory.service_inventory_event import ServiceInventoryEvent

from event_bus.models.edge_gateway.telemetry.cpu_telemetry_event import CpuTelemetryEvent
from event_bus.models.edge_gateway.telemetry.memory_telemetry_event import MemoryTelemetryEvent
from event_bus.models.edge_gateway.telemetry.storage_telemetry_event import StorageTelemetryEvent, DeviceInfo

from event_bus.models.edge_gateway.security.account_security_monitor_event import AccountSecurityMonitorEvent
from event_bus.models.edge_gateway.security.bluetooth_device_monitor_event import BluetoothDeviceMonitorEvent
from event_bus.models.edge_gateway.security.hardening_information_event import HardeningInformationEvent
from event_bus.models.edge_gateway.security.system_audit_collector_event import SystemAuditCollectorEvent
from event_bus.models.edge_gateway.security.vulnerability_scan_event import VulnerabilityScanEvent
from event_bus.models.edge_gateway.security.wifi_connection_monitor_event import WifiConnectionMonitorEvent

logger = logging.getLogger("EdgeGatewayRegistryEventConsumer")

class EdgeGatewayRegistryEventConsumer:
    """
    Consumes events from Redis streams and stores them in SQLite databases.
    """

    def __init__(self, event_bus: RedisStreamBus, db_manager: EdgeGatewayRegistryManager):
        """
        Initialize the event consumer.

        Args:
            event_bus: Redis event bus instance
            db_manager: Database manager instance
        """
        self.event_bus = event_bus
        self.db_manager = db_manager
        self.consumer_group = "sqlite_consumer"
        logger.info("Event consumer initialized")

    def subscribe_to_events(self):
        """Register handlers for all event types."""
        # Inventory events
        self._register_inventory_handlers()

        # Telemetry events
        self._register_telemetry_handlers()

        # Security events
        self._register_security_handlers()

    def _register_inventory_handlers(self):
        """Register handlers for inventory events."""
        # CPU Inventory
        self.event_bus.subscribe(
            StreamName.EDGE_GW_CPU_INVENTORY.value,
            self.consumer_group,
            lambda event: self._handle_cpu_inventory(event)
        )

        # Network Inventory
        self.event_bus.subscribe(
            StreamName.EDGE_GW_NETWORK_INVENTORY.value,
            self.consumer_group,
            lambda event: self._handle_network_inventory(event)
        )

        # OS Kernel Inventory
        self.event_bus.subscribe(
            StreamName.EDGE_GW_OS_KERNEL_INVENTORY.value,
            self.consumer_group,
            lambda event: self._handle_os_kernel_inventory(event)
        )

        # Package Inventory
        self.event_bus.subscribe(
            StreamName.EDGE_GW_PACKAGE_INVENTORY.value,
            self.consumer_group,
            lambda event: self._handle_package_inventory(event)
        )

        # Service Inventory
        self.event_bus.subscribe(
            StreamName.EDGE_GW_SERVICE_INVENTORY.value,
            self.consumer_group,
            lambda event: self._handle_service_inventory(event)
        )

    def _register_telemetry_handlers(self):
        """Register handlers for telemetry events."""
        # CPU Telemetry
        self.event_bus.subscribe(
            StreamName.EDGE_GW_CPU_TELEMETRY.value,
            self.consumer_group,
            lambda event: self._handle_cpu_telemetry(event)
        )

        # Memory Telemetry
        self.event_bus.subscribe(
            StreamName.EDGE_GW_MEMORY_TELEMETRY.value,
            self.consumer_group,
            lambda event: self._handle_memory_telemetry(event)
        )

        # Storage Telemetry
        self.event_bus.subscribe(
            StreamName.EDGE_GW_STORAGE_TELEMETRY.value,
            self.consumer_group,
            lambda event: self._handle_storage_telemetry(event)
        )

    def _register_security_handlers(self):
        """Register handlers for security events."""
        # Account Security
        self.event_bus.subscribe(
            StreamName.EDGE_GW_ACCOUNT_SECURITY_MONITOR.value,
            self.consumer_group,
            lambda event: self._handle_account_security(event)
        )

        # Bluetooth Device Monitor
        self.event_bus.subscribe(
            StreamName.EDGE_GW_BLUETOOTH_DEVICE_MONITOR.value,
            self.consumer_group,
            lambda event: self._handle_bluetooth_devices(event)
        )

        # Hardening Information
        self.event_bus.subscribe(
            StreamName.EDGE_GW_HARDENING_INFORMATION.value,
            self.consumer_group,
            lambda event: self._handle_hardening_info(event)
        )

        # System Audit Collector
        self.event_bus.subscribe(
            StreamName.EDGE_GW_SYSTEM_AUDIT_COLLECTOR.value,
            self.consumer_group,
            lambda event: self._handle_system_audit(event)
        )

        # Vulnerability Scan
        self.event_bus.subscribe(
            StreamName.EDGE_GW_VULNERABILITY_SCAN.value,
            self.consumer_group,
            lambda event: self._handle_vulnerability_scan(event)
        )

        # Wi-Fi Connection Monitor
        self.event_bus.subscribe(
            StreamName.EDGE_GW_WIFI_CONNECTION_MONITOR.value,
            self.consumer_group,
            lambda event: self._handle_wifi_connection(event)
        )

    def _check_table_limit(self, db_type: str, table_name: str, event_id: str):
        """
        Check if the table has exceeded its record limit and trim if necessary.

        Args:
            db_type: Database type ("inventory", "telemetry", or "security")
            table_name: Name of the table to check
            event_id: ID of the event that was just inserted (to not delete it)
        """
        if hasattr(self.db_manager, 'check_record_limit'):
            self.db_manager.check_record_limit(db_type, table_name, event_id)

    @staticmethod
    def _format_timestamp(timestamp: Any) -> str:
        """Format a timestamp value to the ISO format string."""
        if isinstance(timestamp, datetime):
            return timestamp.isoformat()
        return str(timestamp)

    # ===== Inventory Event Handlers =====

    def _handle_cpu_inventory(self, event: CpuInventoryEvent):
        """Handle CPU inventory events."""
        try:
            conn = self.db_manager.get_connection("inventory")
            cursor = conn.cursor()

            # Insert into the cpu_inventory table using event attributes directly
            cursor.execute('''
            INSERT OR REPLACE INTO cpu_inventory
            (event_id, timestamp, pi_model, revision, serial, cpu_cores, 
             cpu_model, cpu_architecture, version)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                event.event_id,
                EdgeGatewayRegistryEventConsumer._format_timestamp(event.timestamp),
                event.pi_model,
                event.revision,
                event.serial,
                event.cpu_cores,
                event.cpu_model,
                event.cpu_architecture,
                event.version
            ))

            conn.commit()
            conn.close()
            logger.info(f"Stored CPU inventory event: {event.event_id}")

            self._check_table_limit("inventory", "cpu_inventory", event.event_id)
        except Exception as e:
            logger.error(f"Error handling CPU inventory event: {e}")

    def _handle_network_inventory(self, event: NetworkInventoryEvent):
        """Handle network inventory events."""
        try:
            conn = self.db_manager.get_connection("inventory")
            cursor = conn.cursor()

            # Insert into the network_inventory table
            cursor.execute('''
            INSERT OR REPLACE INTO network_inventory
            (event_id, timestamp, hostname, fqdn, dns_servers, version)
            VALUES (?, ?, ?, ?, ?, ?)
            ''', (
                event.event_id,
                EdgeGatewayRegistryEventConsumer._format_timestamp(event.timestamp),
                event.hostname,
                event.fqdn,
                json.dumps(event.dns_servers),
                event.version
            ))

            # First, delete any existing interfaces for this event
            cursor.execute("DELETE FROM network_interfaces WHERE network_event_id = ?",
                           (event.event_id,))

            # Insert network interfaces
            for interface in event.interfaces:
                cursor.execute('''
                               INSERT INTO network_interfaces
                                   (network_event_id, name, ip_address, mac_address, state)
                               VALUES (?, ?, ?, ?, ?)
                               ''', (
                                   event.event_id,
                                   interface.name,
                                   interface.ip_address,
                                   interface.mac_address,
                                   interface.state
                               ))

            conn.commit()
            conn.close()
            logger.info(f"Stored network inventory event: {event.event_id}")

            self._check_table_limit("inventory", "network_inventory", event.event_id)
        except Exception as e:
            logger.error(f"Error handling network inventory event: {e}")

    def _handle_os_kernel_inventory(self, event: OsKernelInventoryEvent):
        """Handle OS kernel inventory events."""
        try:
            conn = self.db_manager.get_connection("inventory")
            cursor = conn.cursor()

            # Insert into os_kernel_inventory table
            cursor.execute('''
            INSERT OR REPLACE INTO os_kernel_inventory
            (event_id, timestamp, os_name, os_version, os_id, uptime, 
             kernel_name, kernel_version, kernel_build_date, version)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                event.event_id,
                EdgeGatewayRegistryEventConsumer._format_timestamp(event.timestamp),
                event.os_name,
                event.os_version,
                event.os_id,
                event.uptime,
                event.kernel_name,
                event.kernel_version,
                event.kernel_build_date,
                event.version
            ))

            # First, delete any existing logged-in users for this event
            cursor.execute("DELETE FROM logged_in_users WHERE os_kernel_event_id = ?",
                           (event.event_id,))

            # Insert logged-in users
            for user in event.logged_in_users:
                cursor.execute('''
                               INSERT INTO logged_in_users
                                   (os_kernel_event_id, username, terminal, login_time, host)
                               VALUES (?, ?, ?, ?, ?)
                               ''', (
                                   event.event_id,
                                   user.user,
                                   user.terminal,
                                   user.login_time,
                                   user.host
                               ))

            conn.commit()
            conn.close()
            logger.info(f"Stored OS kernel inventory event: {event.event_id}")

            self._check_table_limit("inventory", "os_kernel_inventory", event.event_id)
        except Exception as e:
            logger.error(f"Error handling OS kernel inventory event: {e}")

    def _handle_package_inventory(self, event: PackageInventoryEvent):
        """Handle package inventory events."""
        try:
            conn = self.db_manager.get_connection("inventory")
            cursor = conn.cursor()

            # Insert into the package_inventory table
            cursor.execute('''
            INSERT OR REPLACE INTO package_inventory
            (event_id, timestamp, version)
            VALUES (?, ?, ?)
            ''', (
                event.event_id,
                EdgeGatewayRegistryEventConsumer._format_timestamp(event.timestamp),
                event.version
            ))

            # Process each package type
            package_types = {
                "all_packages": event.all_packages,
                "security_packages": event.security_packages,
                "python_packages": event.python_packages
            }

            for pkg_type, packages in package_types.items():
                # First, delete any existing packages for this event
                cursor.execute(f"DELETE FROM {pkg_type} WHERE package_event_id = ?",
                               (event.event_id,))

                # Insert packages
                for package in packages:
                    cursor.execute(f'''
                    INSERT INTO {pkg_type}
                    (package_event_id, name, version)
                    VALUES (?, ?, ?)
                    ''', (
                        event.event_id,
                        package.name,
                        package.version
                    ))

            conn.commit()
            conn.close()
            logger.info(f"Stored package inventory event: {event.event_id}")

            self._check_table_limit("inventory", "package_inventory", event.event_id)
        except Exception as e:
            logger.error(f"Error handling package inventory event: {e}")

    def _handle_service_inventory(self, event: ServiceInventoryEvent):
        """Handle service inventory events."""
        try:
            conn = self.db_manager.get_connection("inventory")
            cursor = conn.cursor()

            # Insert into the service_inventory table
            cursor.execute('''
            INSERT OR REPLACE INTO service_inventory
            (event_id, timestamp, running_services, running_count, security_services, version)
            VALUES (?, ?, ?, ?, ?, ?)
            ''', (
                event.event_id,
                EdgeGatewayRegistryEventConsumer._format_timestamp(event.timestamp),
                json.dumps(event.running_services),
                event.running_count,
                json.dumps(event.security_services),
                event.version
            ))

            conn.commit()
            conn.close()
            logger.info(f"Stored service inventory event: {event.event_id}")

            self._check_table_limit("inventory", "service_inventory", event.event_id)
        except Exception as e:
            logger.error(f"Error handling service inventory event: {e}")

    # ===== Telemetry Event Handlers =====

    def _handle_cpu_telemetry(self, event: CpuTelemetryEvent):
        """Handle CPU telemetry events."""
        try:
            conn = self.db_manager.get_connection("telemetry")
            cursor = conn.cursor()

            # Insert into the cpu_telemetry table
            cursor.execute('''
            INSERT OR REPLACE INTO cpu_telemetry
            (event_id, timestamp, temperature_celsius, frequency_mhz, version)
            VALUES (?, ?, ?, ?, ?)
            ''', (
                event.event_id,
                EdgeGatewayRegistryEventConsumer._format_timestamp(event.timestamp),
                event.temperature_celsius,
                event.frequency_mhz,
                event.version
            ))

            conn.commit()
            conn.close()
            logger.info(f"Stored CPU telemetry event: {event.event_id}")

            self._check_table_limit("telemetry", "cpu_telemetry", event.event_id)
        except Exception as e:
            logger.error(f"Error handling CPU telemetry event: {e}")

    def _handle_memory_telemetry(self, event: MemoryTelemetryEvent):
        """Handle memory telemetry events."""
        try:
            conn = self.db_manager.get_connection("telemetry")
            cursor = conn.cursor()

            # Insert into the memory_telemetry table
            cursor.execute('''
            INSERT OR REPLACE INTO memory_telemetry
            (event_id, timestamp, total_memory, free_memory, available_memory,
             swap_total_memory, swap_free_memory, version)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                event.event_id,
                EdgeGatewayRegistryEventConsumer._format_timestamp(event.timestamp),
                event.total_memory,
                event.free_memory,
                event.available_memory,
                event.swap_total_memory,
                event.swap_free_memory,
                event.version
            ))

            conn.commit()
            conn.close()
            logger.info(f"Stored memory telemetry event: {event.event_id}")

            self._check_table_limit("telemetry", "memory_telemetry", event.event_id)
        except Exception as e:
            logger.error(f"Error handling memory telemetry event: {e}")

    def _handle_storage_telemetry(self, event: StorageTelemetryEvent):
        """Handle storage telemetry events."""
        try:
            conn = self.db_manager.get_connection("telemetry")
            cursor = conn.cursor()

            # Insert into the storage_telemetry table
            cursor.execute('''
            INSERT OR REPLACE INTO storage_telemetry
            (event_id, timestamp, version)
            VALUES (?, ?, ?)
            ''', (
                event.event_id,
                EdgeGatewayRegistryEventConsumer._format_timestamp(event.timestamp),
                event.version
            ))

            # First, delete any existing storage devices for this event
            cursor.execute("DELETE FROM storage_devices WHERE storage_event_id = ?",
                           (event.event_id,))

            # Helper function to recursively insert storage devices and their children
            def insert_storage_device(device_info: DeviceInfo, parent_id: Optional[int] = None):
                cursor.execute('''
                               INSERT INTO storage_devices
                               (storage_event_id, device_name, size, used, available, use_percent,
                                mount_point, removable, read_only, device_type, parent_id)
                               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                               ''', (
                                   event.event_id,
                                   device_info.device_name,
                                   device_info.size,
                                   device_info.used,
                                   device_info.available,
                                   device_info.use_percent,
                                   device_info.mount_point,
                                   device_info.rm,
                                   device_info.ro,
                                   device_info.type,
                                   parent_id
                               ))

                device_id = cursor.lastrowid

                # Insert children if any
                for child in device_info.children:
                    insert_storage_device(child, device_id)

            # Insert all storage devices
            for device in event.storage_data:
                insert_storage_device(device)

            conn.commit()
            conn.close()
            logger.info(f"Stored storage telemetry event: {event.event_id}")

            self._check_table_limit("telemetry", "storage_telemetry", event.event_id)
        except Exception as e:
            logger.error(f"Error handling storage telemetry event: {e}")

    # ===== Security Event Handlers =====

    def _handle_account_security(self, event: AccountSecurityMonitorEvent):
        """Handle account security events."""
        try:
            conn = self.db_manager.get_connection("security")
            cursor = conn.cursor()

            # Insert into the account_security table
            cursor.execute('''
            INSERT OR REPLACE INTO account_security
            (event_id, timestamp, version)
            VALUES (?, ?, ?)
            ''', (
                event.event_id,
                EdgeGatewayRegistryEventConsumer._format_timestamp(event.timestamp),
                event.version
            ))

            # First, delete any existing account registry for this event
            cursor.execute("DELETE FROM account_info WHERE account_event_id = ?",
                           (event.event_id,))

            # Insert account registry
            for account in event.accounts_info:
                cursor.execute('''
                               INSERT INTO account_info
                               (account_event_id, username, account_type, creation_date,
                                last_password_change, login_attempts, sudo_privileges,
                                last_login, account_status, user_groups, ssh_activity,
                                ssh_key_fingerprints)
                               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                               ''', (
                                   event.event_id,
                                   account.username,
                                   account.account_type,
                                   account.creation_date,
                                   account.last_password_change,
                                   account.login_attempts,
                                   account.sudo_privileges,
                                   account.last_login,
                                   account.account_status,
                                   json.dumps(account.user_groups),
                                   account.ssh_activity,
                                   json.dumps(account.ssh_key_fingerprints)
                               ))

            conn.commit()
            conn.close()
            logger.info(f"Stored account security event: {event.event_id}")

            self._check_table_limit("security", "account_security", event.event_id)
        except Exception as e:
            logger.error(f"Error handling account security event: {e}")

    def _handle_bluetooth_devices(self, event: BluetoothDeviceMonitorEvent):
        """Handle Bluetooth device monitor events."""
        try:
            conn = self.db_manager.get_connection("security")
            cursor = conn.cursor()

            # Insert into the bluetooth_devices table
            cursor.execute('''
            INSERT OR REPLACE INTO bluetooth_devices
            (event_id, timestamp, version)
            VALUES (?, ?, ?)
            ''', (
                event.event_id,
                EdgeGatewayRegistryEventConsumer._format_timestamp(event.timestamp),
                event.version
            ))

            # First, delete any existing bluetooth device registry for this event
            cursor.execute("DELETE FROM bluetooth_device_info WHERE bluetooth_event_id = ?",
                           (event.event_id,))

            # Insert bluetooth device registry
            for device in event.devices:
                cursor.execute('''
                               INSERT INTO bluetooth_device_info
                               (bluetooth_event_id, device_id, device_name, device_type,
                                mac_address, pairing_status, encryption_type, last_connected,
                                connection_strength, trusted_status, authorized_services)
                               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                               ''', (
                                   event.event_id,
                                   device.device_id,
                                   device.device_name,
                                   device.device_type,
                                   device.mac_address,
                                   device.pairing_status,
                                   device.encryption_type,
                                   device.last_connected,
                                   device.connection_strength,
                                   device.trusted_status,
                                   device.authorized_services
                               ))

            conn.commit()
            conn.close()
            logger.info(f"Stored Bluetooth device monitor event: {event.event_id}")

            self._check_table_limit("security", "bluetooth_devices", event.event_id)
        except Exception as e:
            logger.error(f"Error handling Bluetooth device monitor event: {e}")

    def _handle_hardening_info(self, event: HardeningInformationEvent):
        """Handle hardening information events."""
        try:
            conn = self.db_manager.get_connection("security")
            cursor = conn.cursor()

            # Insert into hardening_info table
            cursor.execute('''
            INSERT OR REPLACE INTO hardening_info
            (event_id, timestamp, version)
            VALUES (?, ?, ?)
            ''', (
                event.event_id,
                EdgeGatewayRegistryEventConsumer._format_timestamp(event.timestamp),
                event.version
            ))

            # First, delete any existing hardening measures for this event
            cursor.execute("DELETE FROM hardening_measures WHERE hardening_event_id = ?",
                           (event.event_id,))

            # Insert hardening measures
            for measure in event.hardening_info:
                cursor.execute('''
                               INSERT INTO hardening_measures
                               (hardening_event_id, category, description, implementation_date,
                                status, verification_method, last_verified, compliance_standard)
                               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                               ''', (
                                   event.event_id,
                                   measure.category,
                                   measure.description,
                                   measure.implementation_date,
                                   measure.status,
                                   measure.verification_method,
                                   measure.last_verified,
                                   measure.compliance_standard
                               ))

            conn.commit()
            conn.close()
            logger.info(f"Stored hardening information event: {event.event_id}")

            self._check_table_limit("security", "hardening_info", event.event_id)
        except Exception as e:
            logger.error(f"Error handling hardening information event: {e}")

    def _handle_system_audit(self, event: SystemAuditCollectorEvent):
        """Handle system audit collector events."""
        try:
            conn = self.db_manager.get_connection("security")
            cursor = conn.cursor()

            # Insert into the system_audit table
            cursor.execute('''
            INSERT OR REPLACE INTO system_audit
            (event_id, timestamp, last_collection_time, version)
            VALUES (?, ?, ?, ?)
            ''', (
                event.event_id,
                EdgeGatewayRegistryEventConsumer._format_timestamp(event.timestamp),
                event.last_collection_time,
                event.version
            ))

            # First, delete any existing audit log entries for this event
            cursor.execute("DELETE FROM audit_log_entries WHERE audit_event_id = ?",
                           (event.event_id,))

            # Insert audit log entries
            for log_entry in event.logs:
                cursor.execute('''
                               INSERT INTO audit_log_entries
                               (audit_event_id, log_timestamp, event_type, severity,
                                source, action, username, result, ip_address, details)
                               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                               ''', (
                                   event.event_id,
                                   log_entry.timestamp,
                                   log_entry.event_type,
                                   log_entry.severity,
                                   log_entry.source,
                                   log_entry.action,
                                   log_entry.username,
                                   log_entry.result,
                                   log_entry.ip_address,
                                   log_entry.details
                               ))

            conn.commit()
            conn.close()
            logger.info(f"Stored system audit collector event: {event.event_id}")

            self._check_table_limit("security", "system_audit", event.event_id)
        except Exception as e:
            logger.error(f"Error handling system audit collector event: {e}")

    def _handle_vulnerability_scan(self, event: VulnerabilityScanEvent):
        """Handle vulnerability scan events."""
        try:
            conn = self.db_manager.get_connection("security")
            cursor = conn.cursor()

            # Insert into the vulnerability_scan table
            cursor.execute('''
            INSERT OR REPLACE INTO vulnerability_scan
            (event_id, timestamp, scan_date, version)
            VALUES (?, ?, ?, ?)
            ''', (
                event.event_id,
                EdgeGatewayRegistryEventConsumer._format_timestamp(event.timestamp),
                event.scan_date,
                event.version
            ))

            # First, delete any existing vulnerability registry for this event
            cursor.execute("DELETE FROM vulnerability_info WHERE scan_event_id = ?",
                           (event.event_id,))

            # Insert vulnerability registry
            for vuln in event.vulnerabilities:
                cursor.execute('''
                               INSERT INTO vulnerability_info
                                   (scan_event_id, cve_id, component, severity, description, status)
                               VALUES (?, ?, ?, ?, ?, ?)
                               ''', (
                                   event.event_id,
                                   vuln.cve_id,
                                   vuln.component,
                                   vuln.severity,
                                   vuln.description,
                                   vuln.status
                               ))

            conn.commit()
            conn.close()
            logger.info(f"Stored vulnerability scan event: {event.event_id}")

            self._check_table_limit("security", "vulnerability_scan", event.event_id)
        except Exception as e:
            logger.error(f"Error handling vulnerability scan event: {e}")

    def _handle_wifi_connection(self, event: WifiConnectionMonitorEvent):
        """Handle Wi-Fi connection monitor events."""
        try:
            conn = self.db_manager.get_connection("security")
            cursor = conn.cursor()

            # Insert directly into the wifi_connection table using event attributes
            cursor.execute('''
            INSERT OR REPLACE INTO wifi_connection
            (event_id, timestamp, ssid, encryption, signal_strength, 
             mac_address, ip_address, last_connected, security_status, version)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                event.event_id,
                EdgeGatewayRegistryEventConsumer._format_timestamp(event.timestamp),
                event.network_info.ssid,
                event.network_info.encryption,
                event.network_info.signal_strength,
                event.network_info.mac_address,
                event.network_info.ip_address,
                event.network_info.last_connected,
                event.network_info.security_status,
                event.version
            ))

            conn.commit()
            conn.close()
            logger.info(f"Stored WiFi connection monitor event: {event.event_id}")

            self._check_table_limit("security", "wifi_connection", event.event_id)
        except Exception as e:
            logger.error(f"Error handling WiFi connection monitor event: {e}")