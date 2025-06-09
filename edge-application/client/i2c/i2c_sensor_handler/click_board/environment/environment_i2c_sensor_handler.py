#!/usr/bin/env python3
# -----------------------------------------------------------------------------
# Filename: environment_i2c_sensor_handler.py
# Author: Rajaram Lakshmanan
# Description:  Handler for communicating with the Environment Click from
# MikroE I2C sensor handler.
# License: MIT (see LICENSE)
# -----------------------------------------------------------------------------

from datetime import datetime, timezone
import logging
import time
from typing import Dict, Any

import bme680
from smbus2 import SMBus

from client.common.base_client import BaseClient
from client.common.sensor_metadata import SensorMetadata
from client.i2c.i2c_sensor_handler.base_i2c_sensor_handler import BaseI2CSensorHandler
from event_bus.redis_stream_bus.redis_stream_bus import RedisStreamBus

logger = logging.getLogger("EnvironmentI2CSensorHandler")

class EnvironmentI2CSensorHandler(BaseI2CSensorHandler):
    """Handler for communicating with the Environment Click from MikroE I2C sensor handler.

    Note: This I2C sensor is used to test indoor air quality, to control HVAC (heating, ventilation, and
    air conditioning) systems. This could be deployed at a Patient's home, care home, or hospital.
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
        Initialize the Environment I2C handler.

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
        self.temperature = 0.0
        self.humidity = 0.0
        self.pressure = 0.0
        self.gas_resistance = 0.0
        self.timestamp = 0

        # Initialize the Environment sensor metadata, generate a unique ID with the prefix
        self._sensor_metadata = SensorMetadata(self._sensor_id,
                                               self._sensor_name,
                                               self._sensor_type,
                                               "Mikroe",
                                               "MIKROE-5546",
                                               "N/A",
                                               "BME680",
                                               "Environment click measures temperature, relative humidity, "
                                               "pressure and VOC (Volatile Organic compounds gases)",
                                               "Various (Temperature: Deg Celsius, "
                                               "Humidity: Percentage, "
                                               "Pressure: Millibar, "
                                               "Gas Resistance: Ohms)",
                                               self._location)

        logger.info("Environment I2C sensor handler initialized")

    @property
    def sensor_metadata(self) -> SensorMetadata:
        """Return metadata for Environment I2C sensor."""
        return self._sensor_metadata

    def get_data(self) -> Dict[str, Any]:
        """
        Return current Environment I2C sensor time_series as a dictionary.

        Returns:
            dict: Dictionary containing Environment I2C sensor time_series.
        """
        return {
            'timestamp': self.timestamp,
            'values': {
                'Environment Temperature': self.temperature,
                'Environment Humidity': self.humidity,
                'Environment Pressure': self.pressure,
                'Environment Gas Resistance': self.gas_resistance
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
            # Initialize sensor
            sensor = EnvironmentI2CSensorHandler._get_bme_sensor(address, bus)

            while not self.stop_event.is_set():
                if sensor.get_sensor_data():
                    with self._data_lock:
                        self.temperature = sensor.data.temperature
                        self.humidity = sensor.data.humidity
                        self.pressure = sensor.data.pressure
                        self.gas_resistance = sensor.data.gas_resistance
                        self.timestamp = int(time.time() * 1000)

                        logger.debug(f"Timestamp: {self.timestamp}, Temperature: {self.temperature:.2f} °C, "
                                    f"Humidity: {self.humidity:.2f} %, Pressure: {self.pressure:.2f} hPa, "
                                    f"Gas Resistance: {self.gas_resistance:.2f} Ω")

                        self._last_data_timestamp = datetime.now(timezone.utc)

                        # Publish sensor time_series event
                        self._publish_sensor_data(self.get_data())

                # Wait before retrieving the next set of time_series
                time.sleep(poll_interval)
        except Exception as e:
            logger.error(f"Failed to get the time_series from the Environment I2C sensor. {e}")
            self.stop_event.set()

    @staticmethod
    def _get_bme_sensor(address: int, bus: SMBus) -> bme680.BME680:
        """Get the BME680 sensor used in the Environment click to optimize the internal measurements.
        Optimization of the sensor includes: Samples time_series (oversampling rates), Filters noise, and
        Heats the gas sensor for stable VOC readings.

        Args:
            address (int): Address of the BME sensor.
            bus (SMBus): The I2C bus to use for communication with the sensor.

        Returns:
            bme680.BME680: Initialized and configured BME680 sensor.
        """
        # Initialize the I2C sensor using the BME library
        # Environment click measures temperature, relative humidity, pressure and VOC (Volatile Organic compounds gases)
        # The click carries the BME680 environmental sensor from Bosch.
        sensor = bme680.BME680(address, bus)
        sensor.set_humidity_oversample(bme680.constants.OS_2X)
        sensor.set_pressure_oversample(bme680.constants.OS_4X)
        sensor.set_temperature_oversample(bme680.constants.OS_8X)
        sensor.set_filter(bme680.constants.FILTER_SIZE_3)
        sensor.set_gas_heater_temperature(320)
        sensor.set_gas_heater_duration(150)
        sensor.select_gas_heater_profile(0)
        logger.info("Environment I2C sensor is successfully initialized.")
        return sensor