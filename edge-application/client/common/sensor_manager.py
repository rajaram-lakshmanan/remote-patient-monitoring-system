#!/usr/bin/env python3
# -----------------------------------------------------------------------------
# Filename: sensor_manager.py
# Author: Rajaram Lakshmanan
# Description:  Manager class to monitor the activity status of all the sensors
# configured in a client.
# License: MIT (see LICENSE)
# -----------------------------------------------------------------------------

import logging
import threading
import time
from typing import List
from client.common.base_sensor_handler import BaseSensorHandler
from event_bus.redis_stream_bus.redis_stream_bus import RedisStreamBus

logger = logging.getLogger("SensorManager")

class SensorManager:
    """
    Manager class to monitor the activity status of all the sensors configured in a client.
    Handles periodic checking of sensor activity and manages sensor inactivity events.
    """

    def __init__(self, event_bus: RedisStreamBus):
        """
        Initialize the sensor manager to monitor the status of all the sensors.

        Args:
            event_bus (RedisStreamBus): The event bus for publishing events
        """
        self._event_bus = event_bus
        self._sensors: List[BaseSensorHandler] = []
        self._monitor_thread = None
        self._is_running = False
        self._lock = threading.Lock()  # For thread-safe sensor list modifications
        logger.debug("Sensor Manager initialized")

    def add_sensor(self, sensor: BaseSensorHandler) -> None:
        """
        Add a sensor to be monitored.

        Args:
            sensor (BaseSensorHandler): The sensor handler to monitor
        """
        with self._lock:
            if sensor not in self._sensors:
                self._sensors.append(sensor)
                logger.debug(f"Added sensor {sensor.sensor_metadata.sensor_id} to monitoring")

    def remove_sensor(self, sensor: BaseSensorHandler) -> None:
        """
        Remove a sensor from monitoring.

        Args:
            sensor (BaseSensorHandler): The sensor handler to remove
        """
        with self._lock:
            if sensor in self._sensors:
                self._sensors.remove(sensor)
                logger.debug(f"Removed sensor {sensor.sensor_metadata.sensor_id} from monitoring")

    def start_monitoring(self) -> None:
        """Start the sensor monitoring thread."""
        if not self._is_running:
            self._is_running = True
            self._monitor_thread = threading.Thread(
                target=self._monitor_sensors,
                name="SensorMonitorThread",
                daemon=True
            )
            self._monitor_thread.start()
            logger.debug("Started sensor activity monitoring")

    def stop_monitoring(self) -> None:
        """Stop the sensor monitoring thread."""
        if self._is_running:
            self._is_running = False
            if self._monitor_thread:
                self._monitor_thread.join(timeout=1.0)  # Wait up to 1 second for the thread to finish
                self._monitor_thread = None
            logger.debug("Stopped sensor activity monitoring")

    def _monitor_sensors(self) -> None:
        """Thread function to monitor sensor activity."""
        logger.debug(f"Starting monitoring of {len(self._sensors)} sensors")

        while self._is_running:
            try:
                with self._lock:
                    sensors_to_check = self._sensors.copy()  # Create a copy to avoid holding the lock

                for sensor in sensors_to_check:
                    try:
                        # Sensor maybe configured but not enabled to start acquisition of time_series
                        if sensor.is_enabled:
                            sensor.check_activity_status()
                    except Exception as e:
                        logger.error(f"Error checking sensor {sensor.sensor_metadata.sensor_id} status: {e}")

                time.sleep(10)  # Check every 10 seconds

            except Exception as e:
                logger.error(f"Error in sensor monitoring loop: {e}")
                time.sleep(5)  # Wait a bit before retrying