#!/usr/bin/env python3
# -----------------------------------------------------------------------------
# Filename: account_security_monitor.py
# Author: Rajaram Lakshmanan
# Description: Collects registry about user accounts in the Edge
# gateway and indicates security status.
# License: MIT (see LICENSE)
# -----------------------------------------------------------------------------

import glob
import gzip
import logging
import pwd
import grp
import os
import subprocess
from abc import ABC
from datetime import datetime
from pathlib import Path

from edge_gateway.base_collector_publisher import BaseCollectorPublisher
from event_bus.models.edge_gateway.security.account_security_monitor_event import AccountSecurityMonitorEvent, AccountInfo
from event_bus.redis_stream_bus.redis_stream_bus import RedisStreamBus
from event_bus.stream_name import StreamName

logger = logging.getLogger("AccountSecurityMonitor")

class AccountSecurityMonitor(BaseCollectorPublisher, ABC):
    """
    A utility class for collecting and analyzing user account security registry.

    This class gathers comprehensive account registry including creation dates,
    password policies, login attempts, sudo privileges, SSH keys, and account status.
    After collection, it publishes this registry to a Redis stream for digital twin
    consumption and security analysis.

    Account security monitoring is essential for regulatory compliance in healthcare
    environments, providing visibility into who has access to sensitive patient time_series
    and detecting potential unauthorized access attempts.
    """

    def __init__(self, event_bus: RedisStreamBus):
        """
        Initialize the collection of the Account Information.

        Args:
            event_bus (RedisStreamBus): Event bus to publish time_series to.
        """
        super().__init__(event_bus)

        self._event_bus.register_stream(StreamName.EDGE_GW_ACCOUNT_SECURITY_MONITOR.value,
                                       AccountSecurityMonitorEvent)

        self.user_accounts = []
        logger.debug("Successfully initialized Account Security Monitor")

    def collect(self):
        """Collect registry about local user accounts."""
        try:
            logger.debug("Collecting user account registry")
            self._information_available = False
            self._collection_in_progress = True

            for user in pwd.getpwall():
                username = user.pw_name
                uid = user.pw_uid
                home_dir = user.pw_dir
                user_info = user.pw_gecos

                # The service accounts listed are essential for the proper operation of various system services,
                # and are not intended for direct user login. By monitoring these accounts, we can analyze potential
                # anomalies in their activity and ensure the services they support are functioning as expected
                service_accounts = ['sshd', 'www-time_series', 'messagebus', 'systemd-timesync', 'systemd-network',
                                    'systemd-resolve', 'avahi']
                if uid < 1000 and username not in service_accounts:
                    continue

                logger.debug(f"Processing account: {username}")

                primary_gid = user.pw_gid
                primary_group = grp.getgrgid(primary_gid).gr_name
                secondary_groups = [g.gr_name for g in grp.getgrall() if username in g.gr_mem]
                groups = list(set([primary_group] + secondary_groups))

                account_type = AccountSecurityMonitor._get_account_type(username, user_info)
                sudo_privileges = AccountSecurityMonitor._has_sudo_privileges(username)
                creation_date = AccountSecurityMonitor._get_creation_date(home_dir) \
                    if os.path.isdir(home_dir) else self._get_creation_date("/etc/passwd")
                last_password_change = AccountSecurityMonitor._get_last_password_change(username)
                last_login = AccountSecurityMonitor._get_last_login(username)
                login_attempts = AccountSecurityMonitor._get_login_attempts(username)
                account_status = AccountSecurityMonitor._get_account_status(username)
                ssh_key_fingerprints = AccountSecurityMonitor._get_ssh_key_fingerprints(home_dir)
                ssh_activity = AccountSecurityMonitor._has_ssh_activity(username)

                user_info_dict = {
                    "username": username,
                    "account_type": account_type,
                    "user_groups": groups,
                    "creation_date": creation_date,
                    "last_password_change": last_password_change,
                    "login_attempts": login_attempts,
                    "sudo_privileges": sudo_privileges,
                    "last_login": last_login,
                    "account_status": account_status,
                    "ssh_activity": ssh_activity,
                    "ssh_key_fingerprints": ssh_key_fingerprints
                }

                self.user_accounts.append(user_info_dict)

            self._information_available = True
            logger.debug("Successfully collected user account registry")
        except Exception as e:
            logger.exception(f"Failed to collect account security registry: {e}", exc_info=True)
        finally:
            self._collection_in_progress = False

    def publish(self):
        """
        Publish the collected account registry to event bus.

        Creates a AccountInfoEvent with the collected time_series and publishes it to the appropriate stream.
        """
        try:
            logger.info("Publishing account security registry")
            account_info_events = [AccountInfo(username=user['username'],
                                               account_type=user['account_type'],
                                               creation_date=user['creation_date'],
                                               last_password_change=user['last_password_change'],
                                               login_attempts=user['login_attempts'],
                                               sudo_privileges=user['sudo_privileges'],
                                               last_login=user['last_login'],
                                               account_status=user['account_status'],
                                               user_groups=user['user_groups'],
                                               ssh_activity=user['ssh_activity'],
                                               ssh_key_fingerprints=user['ssh_key_fingerprints'])
                                   for user in self.user_accounts]

            account_security_event = AccountSecurityMonitorEvent(accounts_info=account_info_events)
            self._publish_to_stream(StreamName.EDGE_GW_ACCOUNT_SECURITY_MONITOR.value, account_security_event)
            logger.debug("Successfully published account security event.")
        except Exception as e:
            logger.error(f"Failed to publish account security event: {e}", exc_info=True)

    @staticmethod
    def _get_account_type(username: str, user_info: str) -> str:
        """Determine if the account is root, service, or standard."""
        if username == "root":
            return "root"
        elif "svc" in username.lower() or "service" in user_info.lower():
            return "service"
        return "standard"

    @staticmethod
    def _has_sudo_privileges(username: str) -> int:
        """Check if the user has any sudo privileges."""
        try:
            output = subprocess.check_output(['sudo', '-lU', username], text=True, stderr=subprocess.DEVNULL)
            if "may run the following commands" in output:
                return 1
        except subprocess.CalledProcessError:
            # User likely has no sudo privileges or command failed
            return 0
        except Exception as e:
            logger.warning(f"Error checking sudo privileges for {username}: {e}")
            return 0
        return 0

    @staticmethod
    def _get_creation_date(path: str) -> str:
        """Get the file creation date (ctime) as a proxy for account creation."""
        try:
            st = os.stat(path)
            return datetime.fromtimestamp(st.st_ctime).strftime('%Y-%m-%d %H:%M:%S')
        except Exception as e:
            logger.warning(f"Failed to get creation date for {path}: {e}")
            return ""

    @staticmethod
    def _get_last_password_change(username: str) -> str:
        """Get the last password change date from /etc/shadow."""
        try:
            shadow = subprocess.check_output(['sudo', 'grep', f'^{username}:', '/etc/shadow'], text=True).strip()
            fields = shadow.split(':')
            if len(fields) >= 3:
                days_since_epoch = int(fields[2])
                if days_since_epoch > 0:
                    ts = days_since_epoch * 86400
                    return datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M:%S')
        except Exception as e:
            logger.warning(f"Error getting password change date for {username}: {e}")
        return ""

    @staticmethod
    def _get_last_login(username: str) -> str:
        """Retrieve the last login timestamp using the `last` command."""
        try:
            output = subprocess.check_output(['last', '-n', '1', username], text=True).splitlines()
            for line in output:
                if username in line and "in" not in line:
                    parts = line.split()
                    if len(parts) >= 7:
                        try:
                            dt_str = " ".join(parts[4:8])
                            dt = datetime.strptime(dt_str, "%b %d %H:%M:%S %Y")
                            return dt.strftime('%Y-%m-%d %H:%M:%S')
                        except Exception as e:
                            logger.error(f"Error when processing datetime in Last login: {e}")
                            continue
        except Exception as e:
            logger.warning(f"Error retrieving last login for {username}: {e}")
        return ""

    @staticmethod
    def _get_login_attempts(username: str) -> int:
        """Count the number of login attempts from /var/log/auth.log."""
        try:
            log_lines = []
            auth_log_paths = ["/var/log/auth.log"]  # Main auth log path

            # Check for rotated logs (auth.log.1, auth.log.{YYYY-MM-DD}, etc.)
            rotated_logs = glob.glob("/var/log/auth.log*")
            auth_log_paths.extend(rotated_logs)

            for log_path in auth_log_paths:
                log_lines.extend(AccountSecurityMonitor._read_log_file(log_path))

            return sum(1 for line in log_lines if ("sshd" in line or "login:" in line) and username in line)
        except Exception as e:
            logger.warning(f"Could not read login attempts for {username}: {e}")
            return 0

    @staticmethod
    def _read_log_file(log_path: str):
        try:
            # Check if the file is a gzipped file
            if log_path.endswith('.gz'):
                with gzip.open(log_path, 'rt', encoding='utf-8') as f:
                    return f.readlines()
            else:
                with open(log_path, 'r', encoding='utf-8') as f:
                    return f.readlines()
        except Exception as e:
            logger.warning(f"Error reading log file {log_path}: {e}")
            return []

    @staticmethod
    def _get_account_status(username: str) -> str:
        """Check if an account is active, locked, or expired based on /etc/shadow."""
        try:
            shadow = subprocess.check_output(['sudo', 'grep', f'^{username}:', '/etc/shadow'], text=True).strip()
            if ":!:" in shadow:
                return "locked"
            fields = shadow.split(':')
            if len(fields) >= 8 and fields[7] not in ("", "0"):
                expiry_days = int(fields[7])
                expiry_date = datetime.fromtimestamp(expiry_days * 86400).date()
                if expiry_date < datetime.today().date():
                    return "expired"
        except Exception as e:
            logger.warning(f"Could not determine account status for {username}: {e}")
        return "active"

    @staticmethod
    def _get_ssh_key_fingerprints(home_dir: str) -> list:
        """Extract SSH key fingerprints from the authorized_keys file."""
        fingerprints = []

        # Skip /root if not running as root
        if home_dir == "/root" and os.geteuid() != 0:
            logger.warning(f"Skipping {home_dir} – insufficient permissions.")
            return fingerprints

        try:
            ssh_path = Path(home_dir) / ".ssh" / "authorized_keys"
            if ssh_path.exists():
                with ssh_path.open() as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#"):
                            try:
                                result = subprocess.run(
                                    ['ssh-keygen', '-lf', '/dev/stdin'],
                                    input=line,
                                    text=True,
                                    stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE
                                )
                                if result.returncode == 0:
                                    fp = result.stdout.strip().split()[1]
                                    fingerprints.append(fp)
                            except Exception as e:
                                logger.error(f"Error executing ssh-keygen: {e}")
        except Exception as e:
            logger.warning(f"Failed to read SSH keys for {home_dir}: {e}")
        return fingerprints

    @staticmethod
    def _has_ssh_activity(username: str) -> bool:
        """Check if the user has connected via SSH based on auth logs."""
        auth_log_paths = ["/var/log/auth.log"]  # Main auth log path

        # Check for rotated logs (auth.log.1, auth.log.{YYYY-MM-DD}, etc.)
        rotated_logs = glob.glob("/var/log/auth.log*")
        auth_log_paths.extend(rotated_logs)

        # Ensure that there are any logs to check
        if not auth_log_paths:
            logger.warning("No auth log files found. SSH activity cannot be checked.")
            return False

        try:
            log_lines = []
            for log_path in auth_log_paths:
                log_lines.extend(AccountSecurityMonitor._read_log_file(log_path))

            for line in log_lines:
                # Search for SSH login attempts for the specific user
                if "sshd" in line and username in line:
                    return True
        except Exception as e:
            logger.warning(f"Error reading log files: {e}")

        return False