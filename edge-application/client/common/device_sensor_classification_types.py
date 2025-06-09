#!/usr/bin/env python3
# -----------------------------------------------------------------------------
# Filename: device_sensor_classification_types.py
# Author: Rajaram Lakshmanan
# Description:  Type of devices and sensors supported by each device supported.
# License: MIT (see LICENSE)
# -----------------------------------------------------------------------------

from enum import Enum

class EnumWithValues(str, Enum):
    """
    Base class for enums that provides methods for listing values and converting a string to an enum member.
    """
    @classmethod
    def list_values(cls) -> list[str]:
        """
        Returns the enum members as a list of strings.

        Returns:
            List[str]: List of enum values.
        """
        return [member.value for member in cls]

    @classmethod
    def from_string(cls, value: str):
        """
        Converts a string to an enum member or raises a ValueError if not found.
        """
        try:
            return cls(value)
        except ValueError:
            raise ValueError(f"{value} is not a valid {cls.__name__} value.")

class DeviceTypes(EnumWithValues):
    """
    Enum representing supported device types.
    """
    # Represents a Samsung Galaxy Watch BLE device
    GALAXY_WATCH = "galaxy_watch"
    # Represents a MikroE Click Board connected via I2C
    CLICK_BOARD = "click_board"

class GalaxyWatchBleSensorType(EnumWithValues):
    """
    Enum representing types of sensors available on a Galaxy Watch over BLE.
    """
    # List of continuous and on-demand sensors available on Galaxy Watch 7
    ACCELEROMETER = "accelerometer"
    ECG = "ecg"
    HEART_RATE = "heart_rate"
    PPG = "ppg"
    SPO2 = "spo2"
    TEMPERATURE = "temperature"

class ClickBoardI2CSensorType(EnumWithValues):
    """
    Enum representing types of sensors available on Click Boards over I2C.
    """
    # List of click board sensors from MikroE configured in the setup
    ENVIRONMENT = "environment"
    OXIMETER_5 = "oximeter"
    ECG_7 = "ecg"