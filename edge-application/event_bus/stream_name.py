#!/usr/bin/env python3
# -----------------------------------------------------------------------------
# Filename: stream_name.py
# Author: Rajaram Lakshmanan
# Description:  Stream names supported by the Redis Event-bus and includes
# generating stream names based on the sensor ID.
# License: MIT (see LICENSE)
# -----------------------------------------------------------------------------

from enum import Enum

class StreamName(Enum):
    """Stream names supported by the Redis Event-bus."""

    # The strategy for generating stream name is to optimize the number of streams created for each event type.
    # Clients will typically have a lower frequency of updates, so one stream per type of the client will work.
    # For sensors, the frequency of updates will vary, so we will create one stream per sensor. And retention
    # will be set for sensor time_series to not consume more memory. As the time_series in the event bus is meant to be
    # transient (i.e., it will be discarded after a certain time) before sent to the Cloud and local storage.
    # So streams are categorized into two types:
    # 1. Lower frequency streams - Client connections, Sensor metadata
    # 2. Higher frequency streams - Sensor time_series and status
    BLE_CLIENT_CONNECTION_INFO_UPDATED = "ble_client_connection_info_updated"

    I2C_CLIENT_CONNECTION_INFO_UPDATED = "i2c_client_connection_info_updated"

    SENSOR_METADATA_CREATED = "sensor_metadata_created"

    # Base name for sensor-specific streams for update in the sensor status (will be appended with sensor_id)
    SENSOR_STATUS_PREFIX = "sensor_status_updated_"

    # Base name for sensor-specific streams for update in the sensor time_series (will be appended with sensor_id)
    SENSOR_DATA_PREFIX = "sensor_data_updated_"

    # Base name for sensor-specific streams to trigger the sensor (will be appended with sensor_id)
    SENSOR_TRIGGER_PREFIX = "sensor_trigger_"

    # Edge Gateway CPU Telemetry Stream
    EDGE_GW_CPU_TELEMETRY = "edge_gateway_cpu_telemetry"

    # Edge Gateway Memory Telemetry Stream
    EDGE_GW_MEMORY_TELEMETRY = "edge_gateway_memory_telemetry"

    # Edge Gateway Storage Telemetry Stream
    EDGE_GW_STORAGE_TELEMETRY = "edge_gateway_storage_telemetry"

    # Edge Gateway Package Inventory Stream
    EDGE_GW_PACKAGE_INVENTORY = "edge_gateway_package_inventory"

    # Edge Gateway CPU Inventory Stream
    EDGE_GW_CPU_INVENTORY = "edge_gateway_cpu_inventory"

    # Edge Gateway Network Inventory Stream
    EDGE_GW_NETWORK_INVENTORY = "edge_gateway_network_inventory"

    # Edge Gateway OS and Kernel Inventory Stream
    EDGE_GW_OS_KERNEL_INVENTORY = "edge_gateway_os_kernel_inventory"

    # Edge Gateway Service Inventory Stream
    EDGE_GW_SERVICE_INVENTORY = "edge_gateway_service_inventory"

    # Edge Gateway Account security monitor Stream
    EDGE_GW_ACCOUNT_SECURITY_MONITOR = "edge_gateway_account_security_monitor"

    # Edge Gateway Hardening registry Stream
    EDGE_GW_HARDENING_INFORMATION = "edge_gateway_hardening_information"

    # Edge Gateway System audit log Stream
    EDGE_GW_SYSTEM_AUDIT_COLLECTOR  = "edge_gateway_system_audit_collector"

    # Edge Gateway Bluetooth device monitor Stream
    EDGE_GW_BLUETOOTH_DEVICE_MONITOR = "edge_gateway_bluetooth_device_monitor"

    # Edge Gateway Wi-Fi connection monitor Stream
    EDGE_GW_WIFI_CONNECTION_MONITOR = "edge_gateway_wifi_connection_monitor"

    # Edge Gateway Vulnerability scan Stream
    EDGE_GW_VULNERABILITY_SCAN = "edge_gateway_vulnerability_scan"

    # Edge Gateway Vulnerability scan Stream
    EDGE_GW_VULNERABILITY_SCAN_TRIGGER = "edge_gateway_vulnerability_scan_trigger"

    @staticmethod
    def get_sensor_stream_name(stream_prefix: str, sensor_id: str) -> str:
        """
        Generate a unique stream name for a specific sensor.

        Args:
            stream_prefix: The prefix for the sensor-specific streams, e.g., sensor time_series or sensor status.
            sensor_id: The unique ID of the sensor.

        Returns:
            A stream name for this specific sensor
        """
        return f"{stream_prefix}{sensor_id}"

