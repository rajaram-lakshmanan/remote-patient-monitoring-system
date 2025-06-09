#!/usr/bin/env python3
# -----------------------------------------------------------------------------
# Filename: sensor_registry_event_consumer.py
# Author: Rajaram Lakshmanan
# Description:  Consumes events from Redis streams and stores them in
# SQLite databases related to sensors, their status, and their connections.
# License: MIT (see LICENSE)
# -----------------------------------------------------------------------------

import logging
import time
import uuid
from typing import Set

from event_bus.models.client.ble_client_event import BleClientEvent
from event_bus.models.client.i2c_client_event import I2CClientEvent
from event_bus.models.sensor.sensor_metadata_event import SensorMetadataEvent
from event_bus.models.sensor.sensor_state_event import SensorStateEvent
from event_bus.redis_stream_bus.redis_stream_bus import RedisStreamBus
from event_bus.stream_name import StreamName

logger = logging.getLogger("SensorRegistryEventConsumer")


class SensorRegistryEventConsumer:
    """
    Consumes events from Redis streams and stores them in SQLite databases
    related to sensors, their status, and their connections.
    """

    def __init__(self, event_bus: RedisStreamBus, db_manager):
        """
        Initialize the event consumer.

        Args:
            event_bus: Redis event bus instance
            db_manager: Sensor registry database manager instance
        """
        self.event_bus = event_bus
        self.db_manager = db_manager
        self.consumer_group = "sensor_registry_consumer"

        # Track registered sensors and their status streams
        self._registered_sensors: Set[str] = set()

        logger.info("Sensor registry event consumer initialized")

    def subscribe_to_events(self):
        """Subscribe to events from the event bus"""
        try:
            # Subscribe to sensor metadata events
            self.event_bus.subscribe(
                StreamName.SENSOR_METADATA_CREATED.value,
                self.consumer_group,
                lambda event: self._handle_sensor_metadata_event(event)
            )

            # Subscribe to BLE client connection events
            self.event_bus.subscribe(
                StreamName.BLE_CLIENT_CONNECTION_INFO_UPDATED.value,
                self.consumer_group,
                lambda event: self._handle_ble_client_event(event)
            )

            # Subscribe to I2C client connection events
            self.event_bus.subscribe(
                StreamName.I2C_CLIENT_CONNECTION_INFO_UPDATED.value,
                self.consumer_group,
                lambda event: self._handle_i2c_client_event(event)
            )

            logger.info("Subscribed to events from event bus")
        except Exception as e:
            logger.error(f"Error subscribing to events: {e}")
            raise

    def _handle_sensor_metadata_event(self, event: SensorMetadataEvent):
        """
        Handle sensor metadata events.

        Args:
            event (SensorMetadataEvent): The sensor metadata event
        """
        try:
            sensor_id = event.sensor_id

            # Store the metadata in SQLite
            self._store_sensor_metadata(event)

            # Skip if we've already registered for this sensor's status
            if sensor_id in self._registered_sensors:
                return

            # Create the status stream name for this sensor
            status_stream_name = StreamName.get_sensor_stream_name(
                StreamName.SENSOR_STATUS_PREFIX.value,
                sensor_id
            )

            # Register for the sensor status stream
            self.event_bus.register_stream(status_stream_name, SensorStateEvent)

            # Subscribe to the sensor status stream
            self.event_bus.subscribe(
                status_stream_name,
                self.consumer_group,
                lambda sensor_state_event: self._handle_sensor_state_event(sensor_state_event)
            )

            # Add to our set of registered sensors
            self._registered_sensors.add(sensor_id)

            logger.info(f"Registered for status stream from sensor {sensor_id}")

        except Exception as e:
            logger.error(f"Error handling sensor metadata event: {e}")

    def _handle_sensor_state_event(self, event: SensorStateEvent):
        """
        Handle sensor state events.

        Args:
            event (SensorStateEvent): The sensor state event
        """
        try:
            # Store the sensor state in SQLite
            self._store_sensor_state(event)

        except Exception as e:
            logger.error(f"Error handling sensor state event: {e}")

    def _handle_ble_client_event(self, event: BleClientEvent):
        """
        Handle BLE client events.

        Args:
            event (BleClientEvent): The BLE client event
        """
        try:
            # Store the BLE client event in SQLite
            self._store_ble_client_event(event)

        except Exception as e:
            logger.error(f"Error handling BLE client event: {e}")

    def _handle_i2c_client_event(self, event: I2CClientEvent):
        """
        Handle I2C client events.

        Args:
            event (I2CClientEvent): The I2C client event
        """
        try:
            # Store the I2C client event in SQLite
            self._store_i2c_client_event(event)

        except Exception as e:
            logger.error(f"Error handling I2C client event: {e}")

    def _store_sensor_metadata(self, event: SensorMetadataEvent):
        """
        Store sensor metadata in SQLite.

        Args:
            event (SensorMetadataEvent): The sensor metadata event
        """
        try:
            conn = self.db_manager.get_connection()
            cursor = conn.cursor()

            # Check if the sensor already exists
            cursor.execute("SELECT COUNT(*) FROM sensor_metadata WHERE sensor_id = ?", (event.sensor_id,))
            count = cursor.fetchone()[0]

            current_time = int(time.time())

            if count > 0:
                # Update existing sensor
                cursor.execute('''
                               UPDATE sensor_metadata
                               SET sensor_name       = ?,
                                   sensor_type       = ?,
                                   patient_id        = ?,
                                   manufacturer      = ?,
                                   model             = ?,
                                   firmware_version  = ?,
                                   hardware_version  = ?,
                                   description       = ?,
                                   measurement_units = ?,
                                   location          = ?,
                                   is_enabled        = ?,
                                   last_updated      = ?
                               WHERE sensor_id = ?
                               ''', (
                                   event.sensor_name, event.sensor_type, event.patient_id, event.manufacturer,
                                   event.model, event.firmware_version, event.hardware_version, event.description,
                                   event.measurement_units, event.location, 1 if event.is_enabled else 0,
                                   current_time, event.sensor_id
                               ))

                logger.info(f"Updated metadata for sensor {event.sensor_id}")
            else:
                # Insert new sensor
                cursor.execute('''
                               INSERT INTO sensor_metadata
                               (sensor_id, sensor_name, sensor_type, patient_id, manufacturer, model,
                                firmware_version, hardware_version, description, measurement_units,
                                location, is_enabled, last_updated)
                               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                               ''', (
                                   event.sensor_id, event.sensor_name, event.sensor_type, event.patient_id,
                                   event.manufacturer, event.model, event.firmware_version, event.hardware_version,
                                   event.description, event.measurement_units, event.location,
                                   1 if event.is_enabled else 0, current_time
                               ))

                logger.info(f"Added metadata for sensor {event.sensor_id}")

            conn.commit()
            conn.close()

            # Check if we need to clean up old records
            self.db_manager.check_record_limit("sensor_metadata", event.sensor_id)

        except Exception as e:
            logger.error(f"Error storing sensor metadata: {e}")
            raise

    def _store_sensor_state(self, event: SensorStateEvent):
        """
        Store sensor state in SQLite.

        Args:
            event (SensorStateEvent): The sensor state event
        """
        try:
            conn = self.db_manager.get_connection()
            cursor = conn.cursor()

            # Create a unique ID for this state record
            state_id = str(uuid.uuid4())
            current_time = int(time.time())

            # Insert the state record
            cursor.execute('''
                           INSERT INTO sensor_state
                           (state_id, sensor_id, timestamp, is_active, inactive_minutes, last_updated)
                           VALUES (?, ?, ?, ?, ?, ?)
                           ''', (
                               state_id, event.sensor_id, int(event.timestamp.timestamp()),
                               1 if event.is_active else 0, event.inactive_minutes, current_time
                           ))

            conn.commit()
            conn.close()
            logger.info(f"Added state record for sensor {event.sensor_id}, active: {event.is_active}")

            # Check if we need to clean up old records
            self.db_manager.check_record_limit("sensor_state", state_id)

        except Exception as e:
            logger.error(f"Error storing sensor state: {e}")
            raise

    def _store_ble_client_event(self, event: BleClientEvent):
        """
        Store BLE client event in SQLite.

        Args:
            event (BleClientEvent): The BLE client event
        """
        try:
            conn = self.db_manager.get_connection()
            cursor = conn.cursor()

            # Create a unique ID for this connection record
            connection_id = str(uuid.uuid4())
            current_time = int(time.time())

            # Convert sensors list to comma-separated string
            sensors_str = ','.join(event.sensors) if event.sensors else ''

            # Insert the connection record
            cursor.execute('''
                           INSERT INTO ble_connection_details
                           (connection_id, client_id, timestamp, target_device_name, target_device_type,
                            target_device_mac_address, is_connected, sensors, message, version, last_updated)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                           ''', (
                               connection_id, event.client_id, int(event.timestamp.timestamp()),
                               event.target_device_name, event.target_device_type, event.target_device_mac_address,
                               1 if event.is_connected else 0, sensors_str, event.message, event.version, current_time
                           ))

            conn.commit()
            conn.close()
            logger.info(f"Added BLE connection record for client {event.client_id}, connected: {event.is_connected}")

            # Check if we need to clean up old records
            self.db_manager.check_record_limit("ble_connection_details", connection_id)

        except Exception as e:
            logger.error(f"Error storing BLE client event: {e}")
            raise

    def _store_i2c_client_event(self, event: I2CClientEvent):
        """
        Store I2C client event in SQLite.

        Args:
            event (I2CClientEvent): The I2C client event
        """
        try:
            conn = self.db_manager.get_connection()
            cursor = conn.cursor()

            # Create a unique ID for this connection record
            connection_id = str(uuid.uuid4())
            current_time = int(time.time())

            # Convert sensors list to comma-separated string
            sensors_str = ','.join(event.sensors) if event.sensors else ''

            # Insert the connection record
            cursor.execute('''
                           INSERT INTO i2c_connection_details
                           (connection_id, client_id, timestamp, i2c_bus_id, is_connected,
                            sensors, message, version, last_updated)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                           ''', (
                               connection_id, event.client_id, int(event.timestamp.timestamp()),
                               event.i2c_bus_id, 1 if event.is_connected else 0, sensors_str,
                               event.message, event.version, current_time
                           ))

            conn.commit()
            conn.close()
            logger.info(f"Added I2C connection record for client {event.client_id}, connected: {event.is_connected}")

            # Check if we need to clean up old records
            self.db_manager.check_record_limit("i2c_connection_details", connection_id)

        except Exception as e:
            logger.error(f"Error storing I2C client event: {e}")
            raise