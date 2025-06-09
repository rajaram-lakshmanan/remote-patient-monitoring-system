#!/usr/bin/env python3
# -----------------------------------------------------------------------------
# Filename: system_audit_collector.py
# Author: Rajaram Lakshmanan
# Description: Collects and publishes audit logs from the Edge gateway.
# License: MIT (see LICENSE)
# -----------------------------------------------------------------------------

import os
import re
import logging
from abc import ABC
from datetime import datetime, timezone

from edge_gateway.base_collector_publisher import BaseCollectorPublisher
from event_bus.models.edge_gateway.security.system_audit_collector_event import AuditLogEntry, SystemAuditCollectorEvent
from event_bus.redis_stream_bus.redis_stream_bus import RedisStreamBus
from event_bus.stream_name import StreamName

logger = logging.getLogger("SystemAuditCollector")

MAX_ENTRIES = 1000

class SystemAuditCollector(BaseCollectorPublisher, ABC):
    """
    A utility class for collecting and processing system audit logs.

    This class gathers audit registry from multiple sources including SSH login
    attempts, sudo usage, system boots, package installations, and Bluetooth connections.
    It processes raw log time_series into structured events with consistent metadata. After
    collection, it publishes this registry to a Redis stream for digital twin
    consumption and security analysis.

    Audit logs provide the forensic timeline needed for security incident investigation
    and regulatory compliance in healthcare environments, creating an audit trail
    of system activities that might affect patient time_series or health monitoring services.
    """

    def __init__(self, event_bus: RedisStreamBus):
        """
        Initialize the collection of the Audit Logs.

        Args:
            event_bus (RedisStreamBus): Event bus to publish time_series to.
        """
        super().__init__(event_bus)

        self._event_bus.register_stream(StreamName.EDGE_GW_SYSTEM_AUDIT_COLLECTOR.value, SystemAuditCollectorEvent)

        self.entries_collected = 0
        self.logs = []

        # Last collection time is essential to ensure collection of logs does not contain duplicate logs
        self.last_collection_time = self._get_last_collection_time()
        logger.debug("Successfully initialized System Audit Collector")

    def collect(self):
        """Collect audit logs from various sources."""
        try:
            logger.debug("Collecting audit logs")
            self._information_available = False
            self._collection_in_progress = True

            self._collect_ssh_logs()
            self._collect_sudo_logs()
            self._collect_boot_logs()
            self._collect_package_logs()
            self._collect_bluetooth_logs()

            self._information_available = True
            logger.debug(f"Successfully collected {self.entries_collected} audit log entries")
        except Exception as e:
            logger.exception(f"Failed to collect audit logs: {e}", exc_info=True)
        finally:
            self._collection_in_progress = False

    def publish(self):
        """
        Publish the collected audit logs to the event bus.

        Creates a SystemAuditCollectorEvent with the collected time_series and publishes it to the appropriate stream.
        """
        try:
            logger.info("Publishing audit logs registry")
            audit_log_entries = [AuditLogEntry(timestamp=log['timestamp'],
                                               event_type=log['event_type'],
                                               severity=log['severity'],
                                               source=log['source'],
                                               action=log['action'],
                                               username=log['username'],
                                               result=log['result'],
                                               ip_address=log['ip_address'],
                                               details=log['details']) for log in self.logs]

            # Create the AuditLogEvent with the current collection time
            current_time = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            audit_log_event = SystemAuditCollectorEvent(logs=audit_log_entries,
                                                        last_collection_time=current_time)

            self._publish_to_stream(StreamName.EDGE_GW_SYSTEM_AUDIT_COLLECTOR.value, audit_log_event)
            logger.info(f"Published audit logs event: {audit_log_event.event_id}")

            # Store the current time as the last collection time for next run
            self._store_last_collection_time(current_time)
        except Exception as e:
            logger.error(f"Failed to publish audit logs event: {e}", exc_info=True)

    @staticmethod
    def _command_exists(command):
        """Check if a command exists on the system."""
        return any(
            os.access(os.path.join(path, command), os.X_OK)
            for path in os.environ["PATH"].split(os.pathsep)
        )

    @staticmethod
    def _format_timestamp(month, day, time_str):
        """Format a timestamp from log file components."""
        year = datetime.now(timezone.utc).year
        return f"{year}-{datetime.strptime(f'{month} {day}', '%b %d').strftime('%m-%d')} {time_str}"

    @staticmethod
    def _get_last_collection_time():
        """Get the timestamp of the last successful log collection."""
        try:
            if os.path.exists("/var/log/edge_gateway/last_audit_collection.txt"):
                with open("/var/log/edge_gateway/last_audit_collection.txt", "r") as f:
                    return f.read().strip()
        except Exception as e:
            logger.warning(f"Could not read last collection time: {e}")

        # Default to yesterday if no record exists
        yesterday = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        return yesterday.strftime("%Y-%m-%d %H:%M:%S")

    @staticmethod
    def _store_last_collection_time(collection_time):
        """Store the timestamp of the current successful log collection."""
        try:
            log_dir = os.path.expanduser("~/.local/share/edge_gateway")
            os.makedirs(log_dir, exist_ok=True)
            with open(os.path.join(log_dir, "last_audit_collection.txt"), "w") as f:
                f.write(collection_time)
        except Exception as e:
            logger.warning(f"Could not store last collection time: {e}")

    def _collect_ssh_logs(self):
        """Collect SSH login attempts from auth.log."""
        logger.debug("Collecting SSH login attempts...")
        if not os.path.exists("/var/log/auth.log"):
            return

        with open("/var/log/auth.log") as f:
            for line in f:
                match = re.match(r"(\w{3})\s+(\d+)\s([\d:]+)\s\S+\ssshd\[.*]:\s(.+)", line)
                if not match:
                    continue
                month, day, time_str, message = match.groups()
                timestamp = SystemAuditCollector._format_timestamp(month, day, time_str)

                if "Accepted" in message:
                    m = re.search(r"Accepted (\w+) for (\w+) from ([\d.]+)", message)
                    if m:
                        method, username, ip = m.groups()
                        self._process_log_entry(timestamp,
                                                "login",
                                                "registry",
                                                "sshd",
                                                "login",
                                                username,
                                                "success",
                                                ip,
                                               f"Successful login via {method}")
                elif "Failed" in message:
                    m = re.search(r"Failed (\w+) for (\w+) from ([\d.]+)", message)
                    if not m:
                        m = re.search(r"Failed (\w+) for invalid user (\w+) from ([\d.]+)", message)
                    if m:
                        method, username, ip = m.groups()
                        self._process_log_entry(timestamp,
                                                "login",
                                                "warning",
                                                "sshd",
                                                "login",
                                                username,
                                                "failure",
                                                ip,
                                                f"Failed login attempt via {method}")

    def _collect_sudo_logs(self):
        """Collect sudo usage logs from auth.log."""
        logger.debug("Collecting sudo usage logs...")
        if not os.path.exists("/var/log/auth.log"):
            return

        with open("/var/log/auth.log") as f:
            for line in f:
                match = re.match(r"(\w{3})\s+(\d+)\s([\d:]+)\s\S+\ssudo:\s(.+)", line)
                if not match:
                    continue
                month, day, time_str, message = match.groups()
                timestamp = SystemAuditCollector._format_timestamp(month, day, time_str)

                parts = message.split(':', 1)
                if len(parts) < 2:
                    continue
                username, action_msg = parts
                username = username.strip()
                action_msg = action_msg.strip()

                if "COMMAND=" in action_msg:
                    m = re.search(r"COMMAND=(.+)", action_msg)
                    if m:
                        command = m.group(1)
                        self._process_log_entry(timestamp,
                                                "privilege_escalation",
                                                "registry",
                                                "sudo",
                                                "command_execution",
                                                username,
                                                "success",
                                                "",
                                                f"Executed command with sudo: {command}")
                elif "incorrect password" in action_msg:
                    self._process_log_entry(timestamp,
                                            "privilege_escalation",
                                            "warning",
                                            "sudo",
                                            "authentication",
                                           username,
                                            "failure",
                                            "",
                                            "Failed sudo authentication: incorrect password")

    def _collect_boot_logs(self):
        """Collect system boot logs from journalctl or syslog."""
        logger.debug("Collecting system boot logs...")
        if self._command_exists("journalctl"):
            from subprocess import Popen, PIPE
            proc = Popen(["journalctl", "-b", "-o", "short-iso"], stdout=PIPE)
            for line in proc.stdout:
                line = line.decode()
                if "kernel: Linux version" in line:
                    parts = line.split(" ", 1)
                    timestamp = parts[0]
                    details = parts[1].strip()
                    self._process_log_entry(timestamp,
                                            "system",
                                            "registry",
                                            "kernel",
                                            "boot",
                                            "system",
                                            "success",
                                            "",
                                            f"System boot: {details}")
        elif os.path.exists("/var/log/syslog"):
            with open("/var/log/syslog") as f:
                for line in f:
                    if "kernel: Linux version" in line:
                        match = re.match(r"(\w{3})\s+(\d+)\s([\d:]+)\s\S+\skernel:\s(.+)", line)
                        if match:
                            month, day, time_str, message = match.groups()
                            timestamp = SystemAuditCollector._format_timestamp(month, day, time_str)
                            self._process_log_entry(timestamp,
                                                    "system",
                                                    "registry",
                                                    "kernel",
                                                    "boot",
                                                    "system",
                                                    "success",
                                                    "",
                                                    f"System boot: {message}")

    def _collect_package_logs(self):
        """Collect package installation logs from dpkg.log."""
        logger.debug("Collecting package installation logs...")
        if not os.path.exists("/var/log/dpkg.log"):
            return

        with open("/var/log/dpkg.log") as f:
            for line in list(f)[-50:]:
                parts = line.split()
                if len(parts) < 5:
                    continue
                timestamp = parts[0] + " " + parts[1]
                status, package = parts[2], parts[3]
                version = parts[4] if len(parts) > 4 else ""
                action = {
                    "install": "installation",
                    "upgrade": "upgrade",
                    "remove": "removal"
                }.get(status, "modification")
                details = f"{action.title()}d package: {package} version {version}"
                self._process_log_entry(timestamp,
                                        "software",
                                        "registry",
                                        "dpkg",
                                        action,
                                        "system",
                                        "success",
                                        "",
                                        details)

    def _collect_bluetooth_logs(self):
        """Collect Bluetooth connection logs from syslog."""
        logger.debug("Collecting Bluetooth connection logs...")
        if not os.path.exists("/var/log/syslog"):
            return

        lines = []
        with open("/var/log/syslog") as f:
            for line in f:
                if "bluetooth" in line.lower() and "connect" in line.lower():
                    lines.append(line)
        for line in lines[-50:]:
            match = re.match(r"(\w{3})\s+(\d+)\s([\d:]+)\s\S+\s\S+:\s(.+)", line)
            if not match:
                continue
            month, day, time_str, message = match.groups()
            timestamp = SystemAuditCollector._format_timestamp(month, day, time_str)
            action = "connection" if "connect" in message.lower() else "disconnection"
            severity = "warning" if any(w in message.lower() for w in ["failed", "error"]) else "registry"
            result = "failure" if severity == "warning" else "success"
            m = re.search(r"([0-9A-F:]{17})", message)
            device = m.group(1) if m else None
            details = f"Bluetooth {'device ' + action if device else 'connection'}: {device or message.strip()}"
            self._process_log_entry(timestamp,
                                    "bluetooth",
                                    severity,
                                    "bluetooth",
                                    action,
                                    "system",
                                    result,
                                    "",
                                    details)

    def _process_log_entry(self,
                           timestamp,
                           event_type,
                           severity,
                           source,
                           action,
                           username,
                           result,
                           ip_address,
                           details):
        """Process and store a log entry if it meets the criteria."""
        if self.entries_collected >= MAX_ENTRIES:
            return

        # Skip entries that are older than the last collection time
        try:
            entry_time = datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S")
            last_time = datetime.strptime(self.last_collection_time, "%Y-%m-%d %H:%M:%S")
            if entry_time <= last_time:
                return
        except ValueError:
            # If we can't parse the timestamp, include the entry to be safe
            pass

        details = details.replace("'", "''")
        log_entry = {
            "timestamp": timestamp,
            "event_type": event_type,
            "severity": severity,
            "source": source,
            "action": action,
            "username": username,
            "result": result,
            "ip_address": ip_address,
            "details": details
        }
        self.logs.append(log_entry)
        self.entries_collected += 1