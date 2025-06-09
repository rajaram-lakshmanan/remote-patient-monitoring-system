#!/usr/bin/env python3
# -----------------------------------------------------------------------------
# Filename: ecg7_i2c_sensor_handler.py
# Author: Rajaram Lakshmanan
# Description:  Handler for communicating with the ECG7 Click from MikroE
# I2C sensor handler.
# License: MIT (see LICENSE)
# -----------------------------------------------------------------------------

from datetime import datetime, timezone
import logging
import time
from typing import Dict, Any

from smbus2 import SMBus

from client.common.base_client import BaseClient
from client.common.sensor_metadata import SensorMetadata
from client.i2c.i2c_sensor_handler.click_board.ecg7.ecg7 import Ecg7
from client.i2c.i2c_sensor_handler.base_i2c_sensor_handler import BaseI2CSensorHandler
from event_bus.redis_stream_bus.redis_stream_bus import RedisStreamBus

logger = logging.getLogger("Ecg7I2CSensorHandler")

class Ecg7I2CSensorHandler(BaseI2CSensorHandler):
    """Handler for communicating with the ECG7 Click from MikroE I2C sensor handler.

    Note: This I2C sensor is used to record the heart's electrical activity. The jack connector available
     in the ECG7 click is used to connect the cable with ECG electrodes.
     This could be deployed at a Patient's home, care home, or hospital.
    """

    def __init__(self,
                 event_bus: RedisStreamBus,
                 client: BaseClient,
                 is_enabled: bool,
                 sensor_id: str,
                 sensor_name: str,
                 sensor_type: str,
                 patient_id: str,
                 location: str):
        """
        Initialize the ECG 7 I2C handler.

        Args:
            event_bus (RedisStreamBus): The event bus for publishing events.
            client: Client to which the sensor handler belongs.
            is_enabled (bool): Flag indicating whether the sensor is enabled or not.
            sensor_id (str): ID of the sensor, this ID shall be unique in the application.
            Follows the format: <interfaceType_shortenedClientId_sensorType> e.g., ble_c1_heart_rate.
            sensor_name (str): Name of the sensor, this does not need to be unique.
            sensor_type (str): Type of the sensor, this is used to determine the sensor-specific logic.
            patient_id (str): ID of the patient associated (wearing or using) with the sensors.
            location (str): Location or placement of the sensors.
        """
        # Call parent constructor
        super().__init__(event_bus, client, is_enabled, sensor_id, sensor_name, sensor_type, patient_id, location)

        # Initialize the time_series that can be retrieved from the sensor
        self.ecgVoltage = 0.0
        self.timestamp = 0

        # Initialize the ECG sensor metadata, generate a unique ID with the prefix
        self._sensor_metadata = SensorMetadata(self._sensor_id,
                                               self._sensor_name,
                                               self._sensor_type,
                                               "Mikroe",
                                               "MIKROE-5214",
                                               "N/A",
                                               "MCP6N16",
                                               "Environment click records the heart's electrical activity",
                                               "mV",
                                               self._location)

        logger.info("ECG7 I2C sensor handler initialized")

    @property
    def sensor_metadata(self) -> SensorMetadata:
        """Return metadata for ECG7 I2C sensor."""
        return self._sensor_metadata

    def get_data(self) -> Dict[str, Any]:
        """
        Return the current ECG7 I2C sensor time_series as a dictionary.

        Returns:
            dict: Dictionary containing Environment I2C sensor time_series.
        """
        return {
            'timestamp': self.timestamp,
            'values': {
                'ECG': self.ecgVoltage
            }
        }

    def _poll_sensor_data(self, bus: SMBus, address: int,  poll_interval: float) -> None:
        """
        Periodically poll the sensor for time_series and publish it to the event bus in batches.
        Batch updates are more appropriate for the high-frequency sensors like ECG.

        Args:
            bus (SMBus): The I2C bus to use for communication with the sensor.
            address (int): Address of the sensor.
            poll_interval (float): Polling interval for the sensor in seconds.
            Typically, clinical ECG systems sample at 250 Hz to 1000 Hz (samples per second). This ensures
            that the high-frequency components of the ECG signal (like the QRS complex) are captured.
        """
        try:
            # Initialize the I2C sensor which reads the raw ADV and converts to voltage
            sensor = Ecg7(bus, address)

            # Buffers for storing readings
            timestamps = []
            voltages = []
            batch_size = 25  # Keep 25 readings per batch (100 ms at 250 Hz)

            while not self.stop_event.is_set():
                current_time = int(time.time() * 1e9)  # Current time in nanoseconds

                with self._data_lock:
                    # Read at full 250 Hz resolution
                    ecg_voltage = sensor.read_voltage() # In Volts
                    if ecg_voltage is not None:
                        # Update latest value for direct access
                        self.ecgVoltage = ecg_voltage
                        self.timestamp = current_time

                        # Add to buffers for batch publishing
                        timestamps.append(current_time)
                        voltages.append(ecg_voltage)

                        # When we've collected enough time_series, publish as a batch
                        if len(timestamps) >= batch_size:
                            # Prepare batch time_series
                            batch_data = {
                                'batch': True,
                                'timestamps': timestamps,
                                'values_list': [{'ECG': v} for v in voltages]
                            }

                            self._last_data_timestamp = datetime.now(timezone.utc)

                            # Publish the batch
                            self._publish_sensor_data(batch_data)

                            # Clear the buffers
                            timestamps = []
                            voltages = []

                time.sleep(poll_interval)

        except Exception as e:
            logger.error(f"Failed to get time_series from the ECG sensor: {e}")
            self.stop_event.set()