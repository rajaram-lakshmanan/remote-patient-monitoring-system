#!/usr/bin/env python3
# -----------------------------------------------------------------------------
# Filename: hardening_information.py
# Author: Rajaram Lakshmanan
# Description: Collects and publishes security hardening registry from the
# Edge gateway.
# License: MIT (see LICENSE)
# -----------------------------------------------------------------------------

import os
import shutil
import logging
from abc import ABC
from datetime import datetime, timezone
from enum import Enum

from edge_gateway.base_collector_publisher import BaseCollectorPublisher
from edge_gateway.helper.shell_command import ShellCommand
from event_bus.models.edge_gateway.security.hardening_information_event import (HardeningMeasure,
                                                                                HardeningInformationEvent)
from event_bus.redis_stream_bus.redis_stream_bus import RedisStreamBus
from event_bus.stream_name import StreamName

logger = logging.getLogger("HardeningInformation")

class Status(str, Enum):
    IMPLEMENTED = "implemented"
    PARTIAL = "partial"
    NEEDED = "needed"
    NOT_APPLICABLE = "not_applicable"

class Verification(str, Enum):
    COMMAND = "command check"
    CONFIG = "config check"
    FILE = "file check"
    PACKAGE = "package check"
    SYSCTL = "sysctl check"
    TIMESTAMP = "timestamp check"
    MANUAL = "manual check"

class Compliance(str, Enum):
    CIS = "CIS"

SSHD_CONFIG_PATH = "/etc/ssh/sshd_config"
AUTO_UPDATE_PATH = "/etc/apt/apt.conf.d/20auto-upgrades"
UPDATE_STAMP_PATH = "/var/lib/apt/periodic/update-success-stamp"
COMMON_PASSWORD_PATH = "/etc/pam.d/common-password"
COMMON_AUTH_PATH = "/etc/pam.d/common-auth"
SHADOW_PATH = "/etc/shadow"
SYSCTL_CONFIG_PATH = "/etc/sysctl.conf"

class HardeningInformation(BaseCollectorPublisher, ABC):
    """
    A utility class for collecting and analyzing system security hardening status.

    This class evaluates security configurations across multiple domains, including
    firewall settings, SSH hardening, system updates, account security, and network
    security. It classifies each measure by implementation status, verification method,
    and compliance standard. After collection, it publishes this registry to a Redis
    stream for digital twin consumption and security analysis.

    Security hardening registry provides a baseline security posture assessment
    for healthcare applications, ensuring fundamental protections are in place
    for sensitive patient time_series and critical health monitoring functions.
    """

    def __init__(self, event_bus: RedisStreamBus):
        """
        Initialize the HardeningInformation collector.

        Args:
            event_bus (RedisStreamBus): Event bus to publish time_series to.
        """
        super().__init__(event_bus)

        # Register the event type with the event bus
        self._event_bus.register_stream(StreamName.EDGE_GW_HARDENING_INFORMATION.value, HardeningInformationEvent)

        self._measures = []
        logger.debug("Successfully initialized Hardening Information")

    def collect(self):
        """Collect security hardening registry."""
        try:
            logger.debug("Collecting hardening registry")
            self._information_available = False
            self._collection_in_progress = True

            self._check_firewall()
            self._check_ssh_hardening()
            self._check_system_updates()
            self._check_account_security()
            self._check_network_security()

            self._information_available = True
            logger.debug(f"Successfully collected {len(self._measures)} hardening measures")
        except Exception as e:
            logger.exception(f"Failed to collect hardening registry: {e}", exc_info=True)
        finally:
            self._collection_in_progress = False

    def publish(self):
        """Publish security hardening registry to the event bus."""
        try:
            logger.info("Publishing hardening security registry")

            if not self._measures:
                logger.warning("No hardening measures to publish")
                return

            hardening_measures = [HardeningMeasure(**measure) for measure in self._measures]
            hardening_information_event = HardeningInformationEvent(hardening_info=hardening_measures)
            self._publish_to_stream(StreamName.EDGE_GW_HARDENING_INFORMATION.value, hardening_information_event)
            logger.info(f"Published hardening security event: {hardening_information_event.event_id}")
        except Exception as e:
            logger.error(f"Failed to publish hardening security event: {e}", exc_info=True)

    @staticmethod
    def _command_exists(command: str) -> bool:
        """Check if a command exists on the system."""
        return shutil.which(command) is not None

    def _get_hardening_info_events(self):
        """Return all collected hardening measures."""
        return self._measures

    def _add_hardening_measure(self, category, description, status: Status,
                               verification: Verification = Verification.MANUAL,
                               compliance: Compliance = Compliance.CIS):
        """Add a security hardening measure to the collection."""
        implementation_date = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S") if status == Status.IMPLEMENTED else ""
        last_verified = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

        self._measures.append({
            "category": category,
            "description": description,
            "implementation_date": implementation_date,
            "status": status.value,
            "verification_method": verification.value,
            "last_verified": last_verified,
            "compliance_standard": compliance.value
        })

    def _check_firewall(self):
        """Check firewall configuration and status."""
        logger.debug("Checking firewall configuration...")

        if self._command_exists("ufw"):
            status = ShellCommand.execute(["ufw", "status"]) or ""
            if status and "Status: active" in status:
                self._add_hardening_measure("firewall",
                                            "UFW firewall enabled",
                                            Status.IMPLEMENTED,
                                            Verification.COMMAND)
            else:
                self._add_hardening_measure("firewall",
                                            "UFW installed but not enabled",
                                            Status.PARTIAL,
                                            Verification.COMMAND)
        elif self._command_exists("iptables"):
            rules = ShellCommand.execute(["iptables", "-L"]) or ""
            if rules and any(line.strip() for line in rules.splitlines() if not line.startswith("Chain") and "target" not in line):
                self._add_hardening_measure("firewall",
                                            "iptables rules configured",
                                            Status.IMPLEMENTED,
                                            Verification.COMMAND)
            else:
                self._add_hardening_measure("firewall", "iptables available but no rules configured", Status.NEEDED,
                                            Verification.COMMAND)
        else:
            self._add_hardening_measure("firewall", "No firewall installed", Status.NEEDED, Verification.PACKAGE)

    def _check_ssh_hardening(self):
        """Check SSH server hardening configuration."""
        logger.debug("Checking SSH hardening status...")

        if os.path.isfile(SSHD_CONFIG_PATH):
            config = open(SSHD_CONFIG_PATH).read()
            self._add_hardening_measure("ssh",
                                        "Root login disabled" if "PermitRootLogin no" in config
                                        else "Root login not explicitly disabled",
                                        Status.IMPLEMENTED if "PermitRootLogin no" in config else Status.NEEDED,
                                        Verification.CONFIG)

            self._add_hardening_measure("ssh",
                                        "Password authentication disabled" if "PasswordAuthentication no" in config
                                        else "Password authentication enabled",
                                        Status.IMPLEMENTED if "PasswordAuthentication no" in config else Status.PARTIAL,
                                        Verification.CONFIG)

            self._add_hardening_measure("ssh",
                                        "SSH Protocol 2 enforced",
                                        Status.IMPLEMENTED if "Protocol 2" in config else Status.NEEDED,
                                        Verification.CONFIG)

            self._add_hardening_measure("ssh",
                                        "SSH key exchange algorithms restricted" if "KexAlgorithms" in config
                                        else "SSH key exchange algorithms not restricted",
                                        Status.IMPLEMENTED if "KexAlgorithms" in config else Status.PARTIAL,
                                        Verification.CONFIG)

            self._add_hardening_measure("ssh",
                                        "SSH idle timeout configured" if "ClientAliveInterval" in config
                                        else "SSH idle timeout not configured",
                                        Status.IMPLEMENTED if "ClientAliveInterval" in config else Status.NEEDED,
                                        Verification.CONFIG)
        else:
            self._add_hardening_measure("ssh",
                                        "SSH server not installed",
                                        Status.NOT_APPLICABLE,
                                        Verification.PACKAGE)

    def _check_system_updates(self):
        """Check system update configuration and status."""
        logger.debug("Checking system update configuration...")

        if os.path.isfile(AUTO_UPDATE_PATH):
            content = open(AUTO_UPDATE_PATH).read()
            if "1" in content:
                self._add_hardening_measure("updates",
                                            "Automatic updates enabled",
                                            Status.IMPLEMENTED,
                                            Verification.CONFIG)
            else:
                self._add_hardening_measure("updates",
                                            "Automatic updates configured but not enabled",
                                            Status.PARTIAL,
                                            Verification.CONFIG)
        else:
            self._add_hardening_measure("updates",
                                        "Automatic updates not configured",
                                        Status.NEEDED,
                                        Verification.CONFIG)

        if os.path.exists(UPDATE_STAMP_PATH):
            last_update = os.path.getmtime(UPDATE_STAMP_PATH)
            days = (datetime.now(timezone.utc).timestamp() - last_update) / 86400
            if days < 7:
                self._add_hardening_measure("updates",
                                            "System updated in past week",
                                            Status.IMPLEMENTED,
                                            Verification.TIMESTAMP)
            elif days < 30:
                self._add_hardening_measure("updates",
                                            "System updated in past month",
                                            Status.PARTIAL,
                                            Verification.TIMESTAMP)
            else:
                self._add_hardening_measure("updates",
                                            "System not updated in over a month",
                                            Status.NEEDED,
                                            Verification.TIMESTAMP)
        else:
            self._add_hardening_measure("updates",
                                        "Cannot determine last update time",
                                        Status.NEEDED,
                                        Verification.TIMESTAMP)

    def _check_account_security(self):
        """Check account security configuration."""
        logger.debug("Checking account security...")

        if os.path.isfile(COMMON_PASSWORD_PATH):
            content = open(COMMON_PASSWORD_PATH).read()
            if "pam_pwquality.so" in content or "pam_cracklib.so" in content:
                self._add_hardening_measure("accounts",
                                            "Password complexity requirements configured",
                                            Status.IMPLEMENTED,
                                            Verification.CONFIG)
            else:
                self._add_hardening_measure("accounts",
                                            "Password complexity requirements not configured",
                                            Status.NEEDED,
                                            Verification.CONFIG)

            self._add_hardening_measure("accounts",
                                        "Password history enforced" if "remember=" in content
                                        else "Password history not enforced",
                                        Status.IMPLEMENTED if "remember=" in content else Status.NEEDED,
                                        Verification.CONFIG)

        if os.path.exists(COMMON_AUTH_PATH):
            content = open(COMMON_AUTH_PATH).read()
            if "pam_tally2.so" in content or "pam_faillock.so" in content:
                self._add_hardening_measure("accounts",
                                            "Failed login attempt lockout configured",
                                            Status.IMPLEMENTED,
                                            Verification.CONFIG)
            else:
                self._add_hardening_measure("accounts",
                                            "Failed login attempt lockout not configured",
                                            Status.NEEDED,
                                            Verification.CONFIG)

        try:
            with open(SHADOW_PATH) as f:
                empty_pw_users = [line.split(":")[0] for line in f if line.split(":")[1] == ""]
                if not empty_pw_users:
                    self._add_hardening_measure("accounts",
                                                "No empty passwords",
                                                Status.IMPLEMENTED,
                                                Verification.FILE)
                else:
                    self._add_hardening_measure("accounts",
                                                "Found accounts with empty passwords",
                                                Status.NEEDED,
                                                Verification.FILE)
        except PermissionError:
            self._add_hardening_measure("accounts",
                                        "Permission denied to read /etc/shadow",
                                        Status.PARTIAL,
                                        Verification.FILE)

    def _check_network_security(self):
        """Check network security configuration."""
        logger.debug("Checking network security...")

        if not self._command_exists("sysctl"):
            self._add_hardening_measure("network",
                                        "sysctl command not available",
                                        Status.NOT_APPLICABLE,
                                        Verification.PACKAGE)
            return

        ipv4_forward = ShellCommand.execute(["sysctl", "net.ipv4.ip_forward"]) or ""
        if ipv4_forward and " = 0" in ipv4_forward:
            if os.path.exists(SYSCTL_CONFIG_PATH) and "net.ipv4.ip_forward = 0" in open(SYSCTL_CONFIG_PATH).read():
                self._add_hardening_measure("network",
                                            "IPv4 forwarding disabled",
                                            Status.IMPLEMENTED,
                                            Verification.CONFIG)
            else:
                self._add_hardening_measure("network",
                                            "IPv4 forwarding currently disabled but not in config",
                                            Status.PARTIAL,
                                            Verification.SYSCTL)
        else:
            self._add_hardening_measure("network",
                                        "IPv4 forwarding enabled",
                                        Status.NEEDED,
                                        Verification.SYSCTL)

        syncookies = ShellCommand.execute(["sysctl", "net.ipv4.tcp_syncookies"]) or ""
        self._add_hardening_measure("network",
                                    "SYN flood protection enabled" if " = 1" in syncookies else "SYN flood protection not enabled",
                                    Status.IMPLEMENTED if " = 1" in syncookies else Status.NEEDED,
                                    Verification.SYSCTL)

        icmp_redirects = ShellCommand.execute(["sysctl", "net.ipv4.conf.all.accept_redirects"]) or ""
        self._add_hardening_measure("network",
                                    "ICMP redirects disabled" if " = 0" in icmp_redirects else "ICMP redirects enabled",
                                    Status.IMPLEMENTED if " = 0" in icmp_redirects else Status.NEEDED,
                                    Verification.SYSCTL)