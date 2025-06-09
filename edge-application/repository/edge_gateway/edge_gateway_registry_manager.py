#!/usr/bin/env python3
# -----------------------------------------------------------------------------
# Filename: edge_gateway_registry_manager.py
# Author: Rajaram Lakshmanan
# Description:  Manages the SQLite databases for the Edge Gateway monitoring
# system. Creates database files, tables, and provides connection handling.
# License: MIT (see LICENSE)
# -----------------------------------------------------------------------------

"""
Database Structure Overview:

We'll use 3 separate SQLite database files to organize the time_series:
1. inventory.db  - Hardware and software inventory time_series (slower-changing time_series)
2. telemetry.db  - Performance metrics and real-time system time_series (frequent updates)
3. security.db   - Security-related information and events (security-focused time_series)

This separation provides:
- Better organization and modular management
- Improved performance (smaller, focused databases)
- Easier backup and maintenance
- Logical separation of concerns
"""

import sqlite3
import logging
from pathlib import Path

logger = logging.getLogger("EdgeGatewayRegistryManager")

class EdgeGatewayRegistryManager:
    """
    Manages the SQLite databases for the Edge Gateway monitoring system.
    Creates database files, tables, and provides connection handling.
    """

    def __init__(self, db_dir="./time_series"):
        """
        Initialize database manager with directory for database files.

        Args:
            db_dir: Directory where database files will be stored
        """
        self.db_dir = Path(db_dir)
        self.db_dir.mkdir(parents=True, exist_ok=True)

        # Define database paths
        self.inventory_db = self.db_dir / "inventory.db"
        self.telemetry_db = self.db_dir / "telemetry.db"
        self.security_db = self.db_dir / "security.db"

        self._record_limits = None

        # Initialize databases
        self._init_inventory_db()
        self._init_telemetry_db()
        self._init_security_db()

        logger.info(f"Database Manager initialized with database directory: {db_dir}")

    def get_connection(self, db_type):
        """
        Get a connection to the specified database.

        Args:
            db_type: Type of database ("inventory", "telemetry", or "security")

        Returns:
            SQLite connection object
        """
        if db_type == "inventory":
            return sqlite3.connect(self.inventory_db)
        elif db_type == "telemetry":
            return sqlite3.connect(self.telemetry_db)
        elif db_type == "security":
            return sqlite3.connect(self.security_db)
        else:
            raise ValueError(f"Unknown database type: {db_type}")

    def check_record_limit(self, db_type, table_name, event_id=None):
        """
        Check if a table exceeds its record limit and remove the oldest records if necessary.

        Args:
            db_type: Database type ("inventory", "telemetry", or "security")
            table_name: Table name to check
            event_id: Optional ID of the event that was just inserted (to not delete it)

        Returns:
            int: Number of records removed, or 0 if no cleanup was needed
        """
        # Skip if record limits aren't defined
        if not self._record_limits:
            self._record_limits = EdgeGatewayRegistryManager.get_default_record_limits()

        # Check if table has a defined limit
        if db_type not in self._record_limits or table_name not in self._record_limits[db_type]:
            return 0

        # Get record limit for this table
        record_limit = self._record_limits[db_type][table_name]

        try:
            # Get database connection
            conn = self.get_connection(db_type)
            cursor = conn.cursor()

            # Count records in the table
            cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
            record_count = cursor.fetchone()[0]

            # Check if cleanup is needed
            if record_count <= record_limit:
                conn.close()
                return 0

            # Calculate how many records to remove
            records_to_remove = record_count - record_limit

            # Get the timestamp column for ordering (assuming all tables have timestamp)
            event_condition = f"AND event_id != '{event_id}'" if event_id else ""

            # Delete the oldest records based on timestamp
            cursor.execute(f"""
            DELETE FROM {table_name} 
            WHERE event_id IN (
                SELECT event_id FROM {table_name}
                ORDER BY timestamp ASC
                LIMIT {records_to_remove}
            ) {event_condition}
            """)

            # Record the actual number of rows deleted
            rows_deleted = cursor.rowcount

            # For certain tables, we need to clean up child tables too
            if rows_deleted > 0:
                EdgeGatewayRegistryManager._cleanup_child_tables(table_name, cursor)

            # Commit changes
            conn.commit()
            conn.close()

            if rows_deleted > 0:
                logger.info(f"Removed {rows_deleted} old records from {db_type}.{table_name}")

            return rows_deleted

        except Exception as e:
            logger.error(f"Error checking record limit for {db_type}.{table_name}: {e}")
            return 0

    def _init_inventory_db(self):
        """Initialize the inventory database with required tables."""
        conn = sqlite3.connect(self.inventory_db)
        cursor = conn.cursor()

        # CPU Inventory table
        cursor.execute('''
                       CREATE TABLE IF NOT EXISTS cpu_inventory (
                                                                    event_id TEXT PRIMARY KEY,
                                                                    timestamp TEXT NOT NULL,
                                                                    pi_model TEXT,
                                                                    revision TEXT,
                                                                    serial TEXT,
                                                                    cpu_cores INTEGER,
                                                                    cpu_model TEXT,
                                                                    cpu_architecture TEXT,
                                                                    version TEXT
                       )
                       ''')

        # Network Inventory table
        cursor.execute('''
                       CREATE TABLE IF NOT EXISTS network_inventory (
                                                                        event_id TEXT PRIMARY KEY,
                                                                        timestamp TEXT NOT NULL,
                                                                        hostname TEXT,
                                                                        fqdn TEXT,
                                                                        dns_servers TEXT,  -- JSON array of DNS servers
                                                                        version TEXT
                       )
                       ''')

        # Network Interfaces table (related to network_inventory)
        cursor.execute('''
                       CREATE TABLE IF NOT EXISTS network_interfaces (
                                                                         id INTEGER PRIMARY KEY AUTOINCREMENT,
                                                                         network_event_id TEXT,
                                                                         name TEXT,
                                                                         ip_address TEXT,
                                                                         mac_address TEXT,
                                                                         state TEXT,
                                                                         FOREIGN KEY
                           (network_event_id
                       ) REFERENCES network_inventory
                       (
                           event_id
                       )
                           )
                       ''')

        # OS/Kernel Inventory table
        cursor.execute('''
                       CREATE TABLE IF NOT EXISTS os_kernel_inventory
                       (
                           event_id
                           TEXT
                           PRIMARY
                           KEY,
                           timestamp
                           TEXT
                           NOT
                           NULL,
                           os_name
                           TEXT,
                           os_version
                           TEXT,
                           os_id
                           TEXT,
                           uptime
                           TEXT,
                           kernel_name
                           TEXT,
                           kernel_version
                           TEXT,
                           kernel_build_date
                           TEXT,
                           version
                           TEXT
                       )
                       ''')

        # Logged-in Users table (related to os_kernel_inventory)
        cursor.execute('''
                       CREATE TABLE IF NOT EXISTS logged_in_users
                       (
                           id
                           INTEGER
                           PRIMARY
                           KEY
                           AUTOINCREMENT,
                           os_kernel_event_id
                           TEXT,
                           username
                           TEXT,
                           terminal
                           TEXT,
                           login_time
                           TEXT,
                           host
                           TEXT,
                           FOREIGN
                           KEY
                       (
                           os_kernel_event_id
                       ) REFERENCES os_kernel_inventory
                       (
                           event_id
                       )
                           )
                       ''')

        # Package Inventory table
        cursor.execute('''
                       CREATE TABLE IF NOT EXISTS package_inventory
                       (
                           event_id
                           TEXT
                           PRIMARY
                           KEY,
                           timestamp
                           TEXT
                           NOT
                           NULL,
                           version
                           TEXT
                       )
                       ''')

        # Packages tables (related to package_inventory)
        for pkg_type in ["all_packages", "security_packages", "python_packages"]:
            cursor.execute(f'''
            CREATE TABLE IF NOT EXISTS {pkg_type} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                package_event_id TEXT,
                name TEXT,
                version TEXT,
                FOREIGN KEY (package_event_id) REFERENCES package_inventory(event_id)
            )
            ''')

        # Service Inventory table
        cursor.execute('''
                       CREATE TABLE IF NOT EXISTS service_inventory
                       (
                           event_id
                           TEXT
                           PRIMARY
                           KEY,
                           timestamp
                           TEXT
                           NOT
                           NULL,
                           running_services
                           TEXT, -- JSON array of services
                           running_count
                           INTEGER,
                           security_services
                           TEXT, -- JSON array of security services
                           version
                           TEXT
                       )
                       ''')

        conn.commit()
        conn.close()
        logger.info("Inventory database initialized")

    def _init_telemetry_db(self):
        """Initialize the telemetry database with required tables."""
        conn = sqlite3.connect(self.telemetry_db)
        cursor = conn.cursor()

        # CPU Telemetry table
        cursor.execute('''
                       CREATE TABLE IF NOT EXISTS cpu_telemetry
                       (
                           event_id
                           TEXT
                           PRIMARY
                           KEY,
                           timestamp
                           TEXT
                           NOT
                           NULL,
                           temperature_celsius
                           REAL,
                           frequency_mhz
                           REAL,
                           version
                           TEXT
                       )
                       ''')

        # Memory Telemetry table
        cursor.execute('''
                       CREATE TABLE IF NOT EXISTS memory_telemetry
                       (
                           event_id
                           TEXT
                           PRIMARY
                           KEY,
                           timestamp
                           TEXT
                           NOT
                           NULL,
                           total_memory
                           TEXT,
                           free_memory
                           TEXT,
                           available_memory
                           TEXT,
                           swap_total_memory
                           TEXT,
                           swap_free_memory
                           TEXT,
                           version
                           TEXT
                       )
                       ''')

        # Storage Telemetry table
        cursor.execute('''
                       CREATE TABLE IF NOT EXISTS storage_telemetry
                       (
                           event_id
                           TEXT
                           PRIMARY
                           KEY,
                           timestamp
                           TEXT
                           NOT
                           NULL,
                           version
                           TEXT
                       )
                       ''')

        # Storage Device Info table (related to storage_telemetry)
        cursor.execute('''
                       CREATE TABLE IF NOT EXISTS storage_devices
                       (
                           id
                           INTEGER
                           PRIMARY
                           KEY
                           AUTOINCREMENT,
                           storage_event_id
                           TEXT,
                           device_name
                           TEXT,
                           size
                           TEXT,
                           used
                           TEXT,
                           available
                           TEXT,
                           use_percent
                           TEXT,
                           mount_point
                           TEXT,
                           removable
                           BOOLEAN,
                           read_only
                           BOOLEAN,
                           device_type
                           TEXT,
                           parent_id
                           INTEGER, -- For nested storage hierarchy
                           FOREIGN
                           KEY
                       (
                           storage_event_id
                       ) REFERENCES storage_telemetry
                       (
                           event_id
                       ),
                           FOREIGN KEY
                       (
                           parent_id
                       ) REFERENCES storage_devices
                       (
                           id
                       )
                           )
                       ''')

        conn.commit()
        conn.close()
        logger.info("Telemetry database initialized")

    def _init_security_db(self):
        """Initialize the security database with required tables."""
        conn = sqlite3.connect(self.security_db)
        cursor = conn.cursor()

        # Account Security Monitor table
        cursor.execute('''
                       CREATE TABLE IF NOT EXISTS account_security
                       (
                           event_id
                           TEXT
                           PRIMARY
                           KEY,
                           timestamp
                           TEXT
                           NOT
                           NULL,
                           version
                           TEXT
                       )
                       ''')

        # Account Info table (related to account_security)
        cursor.execute('''
                       CREATE TABLE IF NOT EXISTS account_info
                       (
                           id
                           INTEGER
                           PRIMARY
                           KEY
                           AUTOINCREMENT,
                           account_event_id
                           TEXT,
                           username
                           TEXT,
                           account_type
                           TEXT,
                           creation_date
                           TEXT,
                           last_password_change
                           TEXT,
                           login_attempts
                           INTEGER,
                           sudo_privileges
                           INTEGER,
                           last_login
                           TEXT,
                           account_status
                           TEXT,
                           user_groups
                           TEXT, -- JSON array of groups
                           ssh_activity
                           BOOLEAN,
                           ssh_key_fingerprints
                           TEXT, -- JSON array of fingerprints
                           FOREIGN
                           KEY
                       (
                           account_event_id
                       ) REFERENCES account_security
                       (
                           event_id
                       )
                           )
                       ''')

        # Bluetooth Device Monitor table
        cursor.execute('''
                       CREATE TABLE IF NOT EXISTS bluetooth_devices
                       (
                           event_id
                           TEXT
                           PRIMARY
                           KEY,
                           timestamp
                           TEXT
                           NOT
                           NULL,
                           version
                           TEXT
                       )
                       ''')

        # Bluetooth Device Info table (related to bluetooth_devices)
        cursor.execute('''
                       CREATE TABLE IF NOT EXISTS bluetooth_device_info
                       (
                           id
                           INTEGER
                           PRIMARY
                           KEY
                           AUTOINCREMENT,
                           bluetooth_event_id
                           TEXT,
                           device_id
                           TEXT,
                           device_name
                           TEXT,
                           device_type
                           TEXT,
                           mac_address
                           TEXT,
                           pairing_status
                           TEXT,
                           encryption_type
                           TEXT,
                           last_connected
                           TEXT,
                           connection_strength
                           INTEGER,
                           trusted_status
                           INTEGER,
                           authorized_services
                           TEXT, -- JSON string of services
                           FOREIGN
                           KEY
                       (
                           bluetooth_event_id
                       ) REFERENCES bluetooth_devices
                       (
                           event_id
                       )
                           )
                       ''')

        # Hardening Information table
        cursor.execute('''
                       CREATE TABLE IF NOT EXISTS hardening_info
                       (
                           event_id
                           TEXT
                           PRIMARY
                           KEY,
                           timestamp
                           TEXT
                           NOT
                           NULL,
                           version
                           TEXT
                       )
                       ''')

        # Hardening Measures table (related to hardening_info)
        cursor.execute('''
                       CREATE TABLE IF NOT EXISTS hardening_measures
                       (
                           id
                           INTEGER
                           PRIMARY
                           KEY
                           AUTOINCREMENT,
                           hardening_event_id
                           TEXT,
                           category
                           TEXT,
                           description
                           TEXT,
                           implementation_date
                           TEXT,
                           status
                           TEXT,
                           verification_method
                           TEXT,
                           last_verified
                           TEXT,
                           compliance_standard
                           TEXT,
                           FOREIGN
                           KEY
                       (
                           hardening_event_id
                       ) REFERENCES hardening_info
                       (
                           event_id
                       )
                           )
                       ''')

        # System Audit Collector table
        cursor.execute('''
                       CREATE TABLE IF NOT EXISTS system_audit
                       (
                           event_id
                           TEXT
                           PRIMARY
                           KEY,
                           timestamp
                           TEXT
                           NOT
                           NULL,
                           last_collection_time
                           TEXT,
                           version
                           TEXT
                       )
                       ''')

        # Audit Log Entries table (related to system_audit)
        cursor.execute('''
                       CREATE TABLE IF NOT EXISTS audit_log_entries
                       (
                           id
                           INTEGER
                           PRIMARY
                           KEY
                           AUTOINCREMENT,
                           audit_event_id
                           TEXT,
                           log_timestamp
                           TEXT,
                           event_type
                           TEXT,
                           severity
                           TEXT,
                           source
                           TEXT,
                           action
                           TEXT,
                           username
                           TEXT,
                           result
                           TEXT,
                           ip_address
                           TEXT,
                           details
                           TEXT,
                           FOREIGN
                           KEY
                       (
                           audit_event_id
                       ) REFERENCES system_audit
                       (
                           event_id
                       )
                           )
                       ''')

        # Vulnerability Scan table
        cursor.execute('''
                       CREATE TABLE IF NOT EXISTS vulnerability_scan
                       (
                           event_id
                           TEXT
                           PRIMARY
                           KEY,
                           timestamp
                           TEXT
                           NOT
                           NULL,
                           scan_date
                           TEXT,
                           version
                           TEXT
                       )
                       ''')

        # Vulnerability Info table (related to vulnerability_scan)
        cursor.execute('''
                       CREATE TABLE IF NOT EXISTS vulnerability_info
                       (
                           id
                           INTEGER
                           PRIMARY
                           KEY
                           AUTOINCREMENT,
                           scan_event_id
                           TEXT,
                           cve_id
                           TEXT,
                           component
                           TEXT,
                           severity
                           TEXT,
                           description
                           TEXT,
                           status
                           TEXT,
                           FOREIGN
                           KEY
                       (
                           scan_event_id
                       ) REFERENCES vulnerability_scan
                       (
                           event_id
                       )
                           )
                       ''')

        # Wi-Fi Connection Monitor table
        cursor.execute('''
                       CREATE TABLE IF NOT EXISTS wifi_connection
                       (
                           event_id
                           TEXT
                           PRIMARY
                           KEY,
                           timestamp
                           TEXT
                           NOT
                           NULL,
                           ssid
                           TEXT,
                           encryption
                           TEXT,
                           signal_strength
                           INTEGER,
                           mac_address
                           TEXT,
                           ip_address
                           TEXT,
                           last_connected
                           TEXT,
                           security_status
                           TEXT,
                           version
                           TEXT
                       )
                       ''')

        conn.commit()
        conn.close()
        logger.info("Security database initialized")

    @staticmethod
    def get_default_record_limits():
        """
        Get default record limits for all tables.

        Returns:
            Dictionary with default record limits
        """
        return {
            # Inventory database (longer retention)
            "inventory": {
                "cpu_inventory": 100,  # Keep ~100 entries
                "network_inventory": 100,  # Keep ~100 entries
                "os_kernel_inventory": 100,  # Keep ~100 entries
                "package_inventory": 100,  # Keep ~100 entries
                "service_inventory": 100  # Keep ~100 entries
            },

            # Telemetry database (higher frequency, shorter retention)
            "telemetry": {
                "cpu_telemetry": 1000,  # Keep ~1000 entries (higher frequency)
                "memory_telemetry": 1000,  # Keep ~1000 entries (higher frequency)
                "storage_telemetry": 500  # Keep ~500 entries
            },

            # Security database (medium retention)
            "security": {
                "account_security": 100,  # Keep ~100 entries
                "bluetooth_devices": 100,  # Keep ~100 entries
                "hardening_info": 50,  # Keep ~50 entries
                "system_audit": 500,  # Keep ~500 entries (logs)
                "vulnerability_scan": 100,  # Keep ~100 entries
                "wifi_connection": 100  # Keep ~100 entries
            }
        }

    @staticmethod
    def _cleanup_child_tables(parent_table, cursor):
        """
        Clean up orphaned records in child tables.

        Args:
            parent_table: Parent table name
            cursor: Database cursor
        """
        # Map of parent tables to their child tables with foreign key column names
        child_tables_map = {
            "network_inventory": [("network_interfaces", "network_event_id")],
            "os_kernel_inventory": [("logged_in_users", "os_kernel_event_id")],
            "package_inventory": [
                ("all_packages", "package_event_id"),
                ("security_packages", "package_event_id"),
                ("python_packages", "package_event_id")
            ],
            "storage_telemetry": [("storage_devices", "storage_event_id")],
            "account_security": [("account_info", "account_event_id")],
            "bluetooth_devices": [("bluetooth_device_info", "bluetooth_event_id")],
            "hardening_info": [("hardening_measures", "hardening_event_id")],
            "system_audit": [("audit_log_entries", "audit_event_id")],
            "vulnerability_scan": [("vulnerability_info", "scan_event_id")]
        }

        # Check if this table has child tables to clean up
        if parent_table not in child_tables_map:
            return

        # Clean up each child table
        for child_table, foreign_key in child_tables_map[parent_table]:
            try:
                # Delete orphaned records in child table
                cursor.execute(f"""
                DELETE FROM {child_table}
                WHERE {foreign_key} NOT IN (
                    SELECT event_id FROM {parent_table}
                )
                """)

                if cursor.rowcount > 0:
                    logger.info(f"Removed {cursor.rowcount} orphaned records from {child_table}")

            except Exception as e:
                logger.error(f"Error cleaning up child table {child_table}: {e}")