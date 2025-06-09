#!/usr/bin/env python3
# -----------------------------------------------------------------------------
# Filename: wifi_connection_monitor.py
# Author: Rajaram Lakshmanan
# Description: Collects and publishes Wi-Fi connection registry from
# the Edge gateway.
# License: MIT (see LICENSE)
# -----------------------------------------------------------------------------

from abc import ABC
from datetime import datetime, timezone
import logging
import re

from edge_gateway.base_collector_publisher import BaseCollectorPublisher
from edge_gateway.helper.shell_command import ShellCommand
from event_bus.models.edge_gateway.security.wifi_connection_monitor_event import (WifiConnectionMonitorEvent,
                                                                                  WifiConnectionInfo)
from event_bus.redis_stream_bus.redis_stream_bus import RedisStreamBus
from event_bus.stream_name import StreamName

logger = logging.getLogger("WifiConnectionMonitor")

class WifiConnectionMonitor(BaseCollectorPublisher, ABC):
    """
    A utility class for monitoring and analyzing Wi-Fi connection security.

    This class collects registry about the current Wi-Fi connection, including
    encryption type, signal strength, network details, and security assessment.
    After collection, it publishes this registry to a Redis stream for digital twin
    consumption and security analysis.

    Wi-Fi security monitoring ensures secure transmission of health time_series over wireless
    networks, preventing connection to insecure networks that could compromise patient
    registry and monitoring wireless link quality for reliable health monitoring services.
    """

    def __init__(self, event_bus: RedisStreamBus):
        """
        Initialize the Wi-Fi connection monitor.

        Args:
            event_bus (RedisStreamBus): Event bus to publish time_series to.
        """
        super().__init__(event_bus)

        self._event_bus.register_stream(StreamName.EDGE_GW_WIFI_CONNECTION_MONITOR.value,
                                       WifiConnectionMonitorEvent)

        self._network_data = {}
        logger.debug("Successfully initialized Wifi Connection Monitor")

    def collect(self):
        """Collect Wi-Fi security details."""
        try:
            logger.debug("Collecting WiFi security registry")
            self._information_available = False
            self._collection_in_progress = True

            # Get current connected SSID
            current_ssid = self._get_connected_ssid()
            if not current_ssid:
                logger.warning("No active WiFi connection detected")
                return

            # Get the wireless interface (wlan0)
            interface_output = ShellCommand.execute(["/usr/sbin/iw", "dev"]) or ""
            interfaces = [line.split()[1] for line in interface_output.splitlines() if "Interface" in line]
            iface = interfaces[0] if interfaces else None

            if not iface:
                logger.warning("No wireless interface detected")
                return

            current_mac = ShellCommand.execute(["cat", f"/sys/class/net/{iface}/address"]) if iface else ""

            # Run the command to get the output of `hostname -I`
            output = ShellCommand.execute(["hostname", "-I"])
            current_ip = output.split()[0] if output else None

            logger.debug(f"Current SSID: {current_ssid}, MAC: {current_mac}, IP: {current_ip}")

            # Get encryption details for the current network
            encryption = WifiConnectionMonitor._get_encryption_details(current_ssid)

            # Check if the network is secure (based on the encryption type)
            security_status = self._check_security(encryption)

            # Get signal strength
            signal_strength = WifiConnectionMonitor._get_signal_strength(iface)

            # Prepare time_series for the connected network
            self._network_data = {"ssid": current_ssid,
                                  "encryption": encryption,
                                  "signal_strength": signal_strength,
                                  "mac_address": current_mac.strip() if current_mac else "",
                                  "ip_address": current_ip.strip() if current_ip else "",
                                  "last_connected": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                                  "security_status": security_status}

            self._information_available = True
            logger.debug("Successfully collected WiFi security registry")
        except Exception as e:
            logger.exception(f"Failed to collect WiFi security registry: {e}", exc_info=True)
        finally:
            self._collection_in_progress = False

    def publish(self):
        """Publish the Wi-Fi security registry to the event bus."""
        try:
            logger.info("Publishing WiFi connection registry")

            if not self._network_data:
                logger.warning("No WiFi network time_series to publish")
                return

            wifi_security_info = WifiConnectionInfo(ssid=self._network_data["ssid"],
                                                    encryption=self._network_data["encryption"],
                                                    signal_strength=self._network_data["signal_strength"],
                                                    mac_address=self._network_data["mac_address"],
                                                    ip_address=self._network_data["ip_address"],
                                                    last_connected=self._network_data["last_connected"],
                                                    security_status=self._network_data["security_status"])

            wifi_security_event = WifiConnectionMonitorEvent(network_info=wifi_security_info)
            self._publish_to_stream(StreamName.EDGE_GW_WIFI_CONNECTION_MONITOR.value, wifi_security_event)
            logger.info(f"Published WiFi connection monitor event: {wifi_security_event.event_id}")
        except Exception as e:
            logger.error(f"Failed to publish WiFi security event: {e}", exc_info=True)

    @staticmethod
    def _get_connected_ssid():
        """Fetch the SSID of the currently connected network."""
        output = ShellCommand.execute(["sudo", "iw", "dev", "wlan0", "link"])
        if output:
            for line in output.splitlines():
                if "SSID" in line:
                    ssid = line.split(":")[1].strip()
                    return ssid
        return ""

    @staticmethod
    def _get_encryption_details(ssid):
        """Fetch encryption type for the connected SSID."""
        encryption = "Unknown"
        output = ShellCommand.execute(["sudo", "iwlist", "wlan0", "scan"])
        if output:
            for line in output.splitlines():
                if f"ESSID:\"{ssid}\"" in line:
                    # Look ahead in the scan results to find encryption details
                    next_lines = output.splitlines()[output.splitlines().index(line):]
                    for next_line in next_lines:
                        if "Encryption key" in next_line:
                            encryption = "WPA2" if "on" in next_line else "Open"
                        elif "IE:" in next_line:
                            if "WPA2" in next_line:
                                encryption = "WPA2"
                            elif "WPA" in next_line:
                                encryption = "WPA"
                            elif "WEP" in next_line:
                                encryption = "WEP"
                    break
        return encryption

    @staticmethod
    def _get_signal_strength(iface):
        """Get the signal strength of the current Wi-Fi connection."""
        try:
            output = ShellCommand.execute(["iwconfig", iface])
            if output:
                for line in output.splitlines():
                    if "Link Quality" in line:
                        quality_match = re.search(r"Link Quality=(\d+)/(\d+)", line)
                        if quality_match:
                            current, max_val = map(int, quality_match.groups())
                            return int(current * 100 / max_val)
                    elif "Signal level" in line:
                        level_match = re.search(r"Signal level=(-?\d+) dBm", line)
                        if level_match:
                            level = int(level_match.group(1))
                            # Convert dBm to percentage (approx)
                            if level <= -100:
                                return 0
                            elif level >= -50:
                                return 100
                            return 2 * (level + 100)
        except Exception as e:
            logger.warning(f"Error getting signal strength: {e}")
        return 100  # Default to 100 if we can't determine

    @staticmethod
    def _check_security(encryption):
        """Determine if the network is secure based on its encryption."""
        if encryption == "WPA2":
            return "Secure"
        elif encryption == "WPA":
            return "Moderate"
        elif encryption == "WEP":
            return "Insecure"
        else:
            return "Unsecured"

    def get_data(self):
        """Return the collected Wi-Fi network time_series."""
        return self._network_data