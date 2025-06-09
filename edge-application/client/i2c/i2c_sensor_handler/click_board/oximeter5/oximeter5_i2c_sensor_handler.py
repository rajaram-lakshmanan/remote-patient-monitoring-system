#!/usr/bin/env python3
# -----------------------------------------------------------------------------
# Filename: oximeter5_i2c_sensor_handler.py
# Author: Rajaram Lakshmanan
# Description:  Handler for communicating with Oximeter 5 Click from MikroE
# I2C sensor handler.
# License: MIT (see LICENSE)
# -----------------------------------------------------------------------------

from datetime import datetime, timezone
import logging
import time
from typing import Dict, Any

from client.common.base_client import BaseClient
from client.common.sensor_metadata import SensorMetadata
from client.i2c.i2c_sensor_handler.base_i2c_sensor_handler import BaseI2CSensorHandler
import numpy as np
from smbus2 import SMBus

from client.i2c.i2c_sensor_handler.click_board.oximeter5.heart_rate_and_spo2_calculation import HeartRateSp02Calculation
from client.i2c.i2c_sensor_handler.click_board.oximeter5.oximeter5 import Oximeter5
from event_bus.redis_stream_bus.redis_stream_bus import RedisStreamBus

logger = logging.getLogger("Oximeter5I2CSensorHandler")

class Oximeter5I2CSensorHandler(BaseI2CSensorHandler):
    """Handler for communicating with Oximeter 5 Click from MikroE I2C sensor handler.

    Note: This I2C sensor is a compact add-on board suitable for measuring blood oxygen saturation.
    This board features the MAX30102, integrated pulse oximetry, and heart-rate monitor module from Analog Devices.
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
        Initialize the Oximeter 5 I2C handler.

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
        self.heart_rate = 0.0
        self.spo2 = 0.0
        self.timestamp = 0

        # Initialize the Oximeter sensor metadata, generate a unique ID with the prefix
        self._sensor_metadata = SensorMetadata(self._sensor_id,
                                               self._sensor_name,
                                               self._sensor_type,
                                               "Mikroe",
                                               "MIKROE-6366",
                                               "N/A",
                                               "MAX30102 ",
                                               "Oximeter 5 click suitable for measuring blood oxygen saturation",
                                               "Heart Rate: BPM, SpO2: %",
                                               self._location)

        logger.info("Oximeter5 I2C sensor handler initialized")

    @property
    def sensor_metadata(self) -> SensorMetadata:
        """Return metadata for Oximeter5 I2C sensor."""
        return self._sensor_metadata

    def get_data(self) -> Dict[str, Any]:
        """
        Return the current Oximeter5 I2C sensor time_series as a dictionary.

        Returns:
            dict: Dictionary containing Oximeter5 I2C sensor time_series.
        """
        return {
            'timestamp': self.timestamp,
            'values': {
                'Heart Rate': self.heart_rate,
                'SpO2': self.spo2
            }
        }

    def _poll_sensor_data(self, bus: SMBus, address: int,  poll_interval: float) -> None:
        """Periodically poll the sensor for time_series and publish it to the event bus.

        Args:
            bus (SMBus): The I2C bus to use for communication with the sensor.
            address (int): Address of the sensor.
            poll_interval (float): Polling interval for the sensor in seconds.
        """
        try:
            # Initialize the I2C sensor which reads the raw time_series Red and IR time_series when available
            sensor = Oximeter5(bus, address)

            ir_data = []
            red_data = []
            heart_rates = []
            spo2_values = []

            while not self.stop_event.is_set():
                # check if any time_series is available in the sensor
                num_bytes = sensor.get_data_present()
                if num_bytes <= 0:
                    time.sleep(poll_interval)
                    continue
                with self._data_lock:
                    # grab all the time_series and stash it into arrays
                    # grab all the time_series and add it to arrays
                    for _ in range(num_bytes):
                        red, ir = sensor.read_fifo()
                        ir_data.append(ir)
                        red_data.append(red)

                    # Keep buffer at fixed size (sliding window)
                    if len(ir_data) > 250:
                        ir_data = ir_data[-250:]
                        red_data = red_data[-250:]

                    # Check if the finger is on the sensor with more detailed conditions
                    ir_mean = np.mean(ir_data)
                    red_mean = np.mean(red_data)

                    if ir_mean < 50000 or red_mean < 50000:
                        self.heart_rate = 0
                        self.spo2 = 0
                        logger.debug("Finger not detected or poor signal quality")
                    else:
                        if len(ir_data) >= 100:
                            # Use only the most recent 100 points for the calculation
                            recent_ir = ir_data[-100:]
                            recent_red = red_data[-100:]
                            heart_rate, spo2 = HeartRateSp02Calculation.get_heartrate_sp02(recent_ir, recent_red)

                            # Validate heart rate and SPO2 values before storing
                            if not np.isnan(heart_rate) and 40 <= heart_rate <= 240:
                                heart_rates.append(heart_rate)
                                # Keep a longer history for better averaging
                                if len(heart_rates) > 8:
                                    heart_rates.pop(0)

                                # Use median for a more stable heart rate
                                if len(heart_rates) >= 3:
                                    self.heart_rate = np.median(heart_rates)
                                else:
                                    self.heart_rate = heart_rate

                            if not np.isnan(spo2) and 70 <= spo2 <= 100:
                                spo2_values.append(spo2)
                                if len(spo2_values) > 8:
                                    spo2_values.pop(0)

                                # Use median for more stable SPO2
                                if len(spo2_values) >= 3:
                                    self.spo2 = np.median(spo2_values)
                                else:
                                    self.spo2 = spo2

                                self.timestamp = int(time.time() * 1000)
                                logger.debug(f"Timestamp: {self.timestamp}, Heart Rate: {self.heart_rate:.1f}, "
                                            f"SpO2: {self.spo2:.1f}")

                                self._last_data_timestamp = datetime.now(timezone.utc)

                                # Only publish when we have valid time_series
                                self._publish_sensor_data(self.get_data())

                # Wait before retrieving the next set of time_series
                time.sleep(poll_interval)
            if sensor:
                sensor.shutdown()
        except Exception as e:
            logger.error(f"Failed to get the time_series from the Oximeter5 I2C sensor. {e}")
            self.stop_event.set()