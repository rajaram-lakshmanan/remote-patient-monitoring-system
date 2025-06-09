#!/usr/bin/env python3
# -----------------------------------------------------------------------------
# Filename: bluetooth_device_monitor.py
# Author: Rajaram Lakshmanan
# Description: Collects and publishes Bluetooth device registry from the
# Edge gateway.
# License: MIT (see LICENSE)
# -----------------------------------------------------------------------------

import re
import time
import logging
from abc import ABC
from datetime import datetime, timezone
from typing import List, Dict, Optional

from edge_gateway.base_collector_publisher import BaseCollectorPublisher
from edge_gateway.helper.shell_command import ShellCommand
from event_bus.models.edge_gateway.security.bluetooth_device_monitor_event import (BluetoothDeviceInfo,
                                                                                   BluetoothDeviceMonitorEvent)
from event_bus.redis_stream_bus.redis_stream_bus import RedisStreamBus
from event_bus.stream_name import StreamName

logger = logging.getLogger("BluetoothSecurity")

class BluetoothDeviceMonitor(BaseCollectorPublisher, ABC):
    """
    A utility class for collecting and analyzing Bluetooth device security registry.

    This class gathers registry about paired and nearby Bluetooth devices, including
    connection status, encryption types, signal strength, and service registry.
    After collection, it publishes this registry to a Redis stream for digital twin
    consumption and security analysis.

    Bluetooth monitoring is particularly critical for healthcare applications where
    medical wearables and devices communicate over Bluetooth, ensuring secure and
    authorized connections for health time_series transmission.
    """

    def __init__(self, event_bus: RedisStreamBus):
        """
        Initialize the BluetoothSecurity collector.

        Args:
            event_bus (RedisStreamBus): Event bus to publish time_series to.
        """
        super().__init__(event_bus)

        # Register the event type with the event bus
        self._event_bus.register_stream(StreamName.EDGE_GW_BLUETOOTH_DEVICE_MONITOR.value,
                                       BluetoothDeviceMonitorEvent)

        self._devices: List[Dict] = []
        logger.debug("Successfully initialized Bluetooth Device Monitor")

    def get_data(self):
        """Return the collected Bluetooth device time_series."""
        return self._devices

    def collect(self):
        """Collect Bluetooth device registry."""
        try:
            logger.info("Collecting Bluetooth device registry")
            self._information_available = False
            self._collection_in_progress = True

            paired_output = ShellCommand.execute(["bluetoothctl", "paired-devices"])
            if not paired_output:
                logger.warning("No paired Bluetooth devices found.")
                return

            for line in paired_output.splitlines():
                match = re.match(r"Device ([0-9A-F:]+) (.+)", line)
                if match:
                    mac, name = match.groups()
                    device_info = self._extract_device_info(mac, name)
                    if device_info:
                        self._devices.append(device_info)

            # Scan for nearby devices
            logger.info("Scanning for nearby Bluetooth devices...")
            ShellCommand.execute(["bluetoothctl", "scan", "on"])
            # Sleep for 10 seconds to allow scanning to happen (additional timeout of 30 seconds is
            # configured in the ShellCommand execute function (total = 40 seconds)
            time.sleep(10)
            ShellCommand.execute(["bluetoothctl", "scan", "off"])  # Stop scanning

            nearby_output = ShellCommand.execute(["bluetoothctl", "devices"])
            if nearby_output:
                for line in nearby_output.splitlines():
                    match = re.match(r"Device ([0-9A-F:]+) (.+)", line)
                    if match:
                        mac, name = match.groups()
                        if not any(d["mac_address"] == mac for d in self._devices):
                            device_info = BluetoothDeviceMonitor._infer_device_type(mac, name)
                            self._devices.append(device_info)

            self._information_available = True
            logger.debug(f"Successfully collected registry for {len(self._devices)} Bluetooth devices")
        except Exception as e:
            logger.exception(f"Failed to collect Bluetooth device registry: {e}", exc_info=True)
        finally:
            self._collection_in_progress = False

    def publish(self):
        """Publish the Bluetooth device registry to the event bus."""
        try:
            logger.info("Publishing Bluetooth device monitor registry")

            if not self._devices:
                logger.warning("No Bluetooth devices to publish")
                return

            # Create BluetoothDeviceInfo objects
            bluetooth_device_infos = [BluetoothDeviceInfo(device_id=device["device_id"],
                                                          device_name=device["device_name"],
                                                          device_type=device["device_type"],
                                                          mac_address=device["mac_address"],
                                                          pairing_status=device["pairing_status"],
                                                          encryption_type=device["encryption_type"],
                                                          last_connected=device["last_connected"],
                                                          connection_strength=device["connection_strength"],
                                                          trusted_status=device["trusted_status"],
                                                          authorized_services=device["authorized_services"])
                                      for device in self._devices
            ]

            bluetooth_security_event = BluetoothDeviceMonitorEvent(devices=bluetooth_device_infos)
            self._publish_to_stream(StreamName.EDGE_GW_BLUETOOTH_DEVICE_MONITOR.value,
                                    bluetooth_security_event)
            logger.info(f"Published Bluetooth device monitor event: {bluetooth_security_event.event_id}")
        except Exception as e:
            logger.error(f"Failed to publish Bluetooth device monitor event: {e}", exc_info=True)

    def _extract_device_info(self, mac: str, name: str) -> Optional[Dict]:
        """Extract detailed registry about a Bluetooth device."""
        try:
            info = ShellCommand.execute(["bluetoothctl", "registry", mac])
            if not info:
                return None

            connected = "yes" in re.search(r"Connected: (\w+)", info).group(1) if "Connected" in info else False
            rssi_match = re.search(r"RSSI: (-?\d+)", info)
            rssi = int(rssi_match.group(1)) if rssi_match else None
            strength = self._rssi_to_strength(rssi) if rssi else 0
            last_connected = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S") if connected else ""

            device_type = self._detect_device_type(info)
            encryption = self._detect_encryption(info)
            trusted = 1 if "Trusted: yes" in info else 0

            services = "[]"
            if "Watch" in name or device_type == "wearable":
                gatt_output = ShellCommand.execute(["gatttool", "-b", mac, "--primary"])
                if gatt_output:
                    services = BluetoothDeviceMonitor._parse_gatt_services(gatt_output)

            return {"device_id": mac,
                    "device_name": name,
                    "device_type": device_type,
                    "mac_address": mac,
                    "pairing_status": "connected" if connected else "not_connected",
                    "encryption_type": encryption,
                    "last_connected": last_connected,
                    "connection_strength": strength,
                    "trusted_status": trusted,
                    "authorized_services": services}
        except Exception as e:
            logger.warning(f"Error extracting registry for device {mac}: {e}")
            return None

    @staticmethod
    def _infer_device_type(mac: str, name: str) -> Dict:
        """Infer the type of Bluetooth device based on its name."""
        try:
            name_lower = name.lower()
            device_type = "unknown"
            if "watch" in name_lower or "galaxy" in name_lower:
                device_type = "wearable"
            elif "phone" in name_lower or "smartphone" in name_lower:
                device_type = "phone"
            elif "tv" in name_lower:
                device_type = "entertainment"
            elif any(x in name_lower for x in ["speaker", "headphone", "audio"]):
                device_type = "audio"

            return {"device_id": mac,
                    "device_name": name,
                    "device_type": device_type,
                    "mac_address": mac,
                    "pairing_status": "not_connected",
                    "encryption_type": "none",
                    "last_connected": "",
                    "connection_strength": 0,
                    "trusted_status": 0,
                    "authorized_services": "[]"}
        except Exception as e:
            logger.warning(f"Error inferring device type for {mac}: {e}")
            return {"device_id": mac,
                    "device_name": name if name else "Unknown",
                    "device_type": "unknown",
                    "mac_address": mac,
                    "pairing_status": "not_connected",
                    "encryption_type": "none",
                    "last_connected": "",
                    "connection_strength": 0,
                    "trusted_status": 0,
                    "authorized_services": "[]"}

    @staticmethod
    def _parse_gatt_services(output: Optional[str]) -> str:
        """Parse GATT services from GATT tool output."""
        if not output:
            return "[]"
        services = []
        for line in output.splitlines():
            match = re.search(r"attr handle: ([0-9a-fx]+), end grp handle: ([0-9a-fx]+) uuid: ([0-9a-f-]+)", line)
            if match:
                handle, end_handle, uuid = match.groups()
                services.append({
                    "uuid": uuid,
                    "handle": handle,
                    "end_handle": end_handle
                })
        return str(services).replace("'", '"')

    @staticmethod
    def _rssi_to_strength(rssi: int) -> int:
        """Convert RSSI value to a signal strength percentage."""
        strength = 100 - ((-rssi - 30) * 100 // 70)
        return max(0, min(100, strength))

    @staticmethod
    def _detect_device_type(info: str) -> str:
        """Determine the device type based on its Bluetooth class."""
        class_match = re.search(r"Class: 0x([0-9a-f]+)", info)
        if class_match:
            class_hex = class_match.group(1)
            if "0504" in class_hex:
                return "wearable"
            elif "0408" in class_hex or "0200" in class_hex:
                return "phone"
            elif "0104" in class_hex:
                return "laptop"
            elif "0108" in class_hex:
                return "desktop"
            elif "0418" in class_hex:
                return "smartphone"
            elif "0204" in class_hex:
                return "audio"
        return "unknown"

    @staticmethod
    def _detect_encryption(info: str) -> str:
        """Determine the encryption type used by the device."""
        pairing_match = re.search(r"Pairing method: ([A-Za-z0-9-]+)", info)
        return ({"SSP-Passkey": "Secure Simple Pairing",
                "Legacy-Passkey": "Legacy",
                "SSP-Just-Works": "Secure Simple Pairing"}
                .get(pairing_match.group(1), "unknown")) if pairing_match else "unknown"