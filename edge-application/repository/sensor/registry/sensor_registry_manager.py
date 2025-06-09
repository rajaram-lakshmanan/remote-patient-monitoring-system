#!/usr/bin/env python3
# -----------------------------------------------------------------------------
# Filename: sensor_registry_manager.py
# Author: Rajaram Lakshmanan
# Description: Manages the SQLite database for sensor registry information.
# Creates database files, tables, and provides connection handling.
# License: MIT (see LICENSE)
# -----------------------------------------------------------------------------

import logging
import sqlite3
from pathlib import Path

logger = logging.getLogger("SensorRegistryManager")

class SensorRegistryManager:
    """
    Manages the SQLite database for sensor registry information.
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

        # Define database path
        self.sensor_registry_db = self.db_dir / "sensor_registry.db"

        # Record limits configuration
        self._record_limits = None

        # Initialize database
        self._init_sensor_registry_db()

        logger.info(f"Sensor Registry Manager initialized with database directory: {db_dir}")

    def get_connection(self):
        """
        Get a connection to the sensor registry database.

        Returns:
            SQLite connection object
        """
        try:
            conn = sqlite3.connect(self.sensor_registry_db, check_same_thread=False)
            conn.row_factory = sqlite3.Row  # Return rows as dictionaries
            return conn
        except Exception as e:
            logger.error(f"Error getting database connection: {e}")
            raise

    def check_record_limit(self, table_name, event_id=None):
        """
        Check if a table exceeds its record limit and remove the oldest records if necessary.

        Args:
            table_name: Table name to check
            event_id: Optional ID of the event that was just inserted (to not delete it)

        Returns:
            int: Number of records removed, or 0 if no cleanup was needed
        """
        # Skip if record limits aren't defined
        if not self._record_limits:
            self._record_limits = SensorRegistryManager.get_default_record_limits()

        # Check if table has a defined limit
        if table_name not in self._record_limits:
            return 0

        # Get record limit for this table
        record_limit = self._record_limits[table_name]

        try:
            # Get database connection
            conn = self.get_connection()
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

            # Determine primary key column and timestamp column
            if table_name == "sensor_metadata":
                primary_key = "sensor_id"
                timestamp_col = "last_updated"
            elif table_name == "sensor_state":
                primary_key = "state_id"
                timestamp_col = "timestamp"
            elif table_name == "ble_connection_details":
                primary_key = "connection_id"
                timestamp_col = "timestamp"
            elif table_name == "i2c_connection_details":
                primary_key = "connection_id"
                timestamp_col = "timestamp"
            else:
                logger.warning(f"Unknown table: {table_name}, skipping record limit check")
                conn.close()
                return 0

            # Create the event condition if needed
            event_condition = f"AND {primary_key} != '{event_id}'" if event_id else ""

            # Delete the oldest records based on timestamp
            cursor.execute(f"""
            DELETE FROM {table_name} 
            WHERE {primary_key} IN (
                SELECT {primary_key} FROM {table_name}
                ORDER BY {timestamp_col} ASC
                LIMIT {records_to_remove}
            ) {event_condition}
            """)

            # Record the actual number of rows deleted
            rows_deleted = cursor.rowcount

            # For sensor_state, we don't need to clean up child tables as it's a child itself

            # Commit changes
            conn.commit()
            conn.close()

            if rows_deleted > 0:
                logger.info(f"Removed {rows_deleted} old records from {table_name}")

            return rows_deleted

        except Exception as e:
            logger.error(f"Error checking record limit for {table_name}: {e}")
            return 0

    def _init_sensor_registry_db(self):
        """Initialize the sensor registry database with required tables."""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()

            # Create the sensor metadata table
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS sensor_metadata (
                sensor_id TEXT PRIMARY KEY,
                sensor_name TEXT NOT NULL,
                sensor_type TEXT NOT NULL,
                patient_id TEXT,
                manufacturer TEXT,
                model TEXT,
                firmware_version TEXT,
                hardware_version TEXT,
                description TEXT,
                measurement_units TEXT,
                location TEXT,
                is_enabled INTEGER,
                last_updated INTEGER
            )
            ''')

            # Create sensor state table
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS sensor_state (
                state_id TEXT PRIMARY KEY,
                sensor_id TEXT NOT NULL,
                timestamp INTEGER NOT NULL,
                is_active INTEGER NOT NULL,
                inactive_minutes REAL,
                last_updated INTEGER,
                FOREIGN KEY (sensor_id) REFERENCES sensor_metadata(sensor_id)
            )
            ''')

            # Create BLE connection details table
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS ble_connection_details (
                connection_id TEXT PRIMARY KEY,
                client_id TEXT NOT NULL,
                timestamp INTEGER NOT NULL,
                target_device_name TEXT,
                target_device_type TEXT,
                target_device_mac_address TEXT,
                is_connected INTEGER NOT NULL,
                sensors TEXT,
                message TEXT,
                version TEXT,
                last_updated INTEGER
            )
            ''')

            # Create I2C connection details table
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS i2c_connection_details (
                connection_id TEXT PRIMARY KEY,
                client_id TEXT NOT NULL,
                timestamp INTEGER NOT NULL,
                i2c_bus_id INTEGER,
                is_connected INTEGER NOT NULL,
                sensors TEXT,
                message TEXT,
                version TEXT,
                last_updated INTEGER
            )
            ''')

            conn.commit()
            conn.close()
            logger.info("Sensor registry database initialized")
        except Exception as e:
            logger.error(f"Error initializing sensor registry database: {e}")
            raise

    @staticmethod
    def get_default_record_limits():
        """
        Get default record limits for all tables.

        Returns:
            Dictionary with default record limits
        """
        return {
            "sensor_metadata": 500,  # Keep ~500 sensors (longer retention)
            "sensor_state": 1000,    # Keep ~1000 state entries per sensor (higher frequency)
            "ble_connection_details": 500,  # Keep ~500 BLE connection records
            "i2c_connection_details": 500   # Keep ~500 I2C connection records
        }

    @staticmethod
    def _cleanup_orphaned_states(cursor):
        """
        Clean up orphaned sensor state records.

        Args:
            cursor: Database cursor
        """
        try:
            # Delete sensor states without a valid sensor_id in metadata
            cursor.execute("""
            DELETE FROM sensor_state
            WHERE sensor_id NOT IN (
                SELECT sensor_id FROM sensor_metadata
            )
            """)

            if cursor.rowcount > 0:
                logger.info(f"Removed {cursor.rowcount} orphaned records from sensor_state")

        except Exception as e:
            logger.error(f"Error cleaning up orphaned sensor states: {e}")