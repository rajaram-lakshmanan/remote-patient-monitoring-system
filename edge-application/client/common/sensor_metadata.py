#!/usr/bin/env python3
# -----------------------------------------------------------------------------
# Filename: sensor_metadata.py
# Author: Rajaram Lakshmanan
# Description:  Immutable class to represent sensor metadata.
# License: MIT (see LICENSE)
# -----------------------------------------------------------------------------

class SensorMetadata:
    """
    A class to represent sensor metadata, which includes details such as sensor ID,
    name, type, manufacturer, model, and more. This class ensures the immutability
    of the sensor's attributes once initialized.
    """

    # Declare attributes with type hints to satisfy linters
    _sensor_id: str
    _sensor_name: str
    _sensor_type: str
    _manufacturer: str
    _model: str
    _firmware_version: str
    _hardware_version: str
    _description: str
    _measurement_units: str
    _location: str

    def __init__(self,
                 sensor_id: str,
                 sensor_name: str,
                 sensor_type: str,
                 manufacturer: str,
                 model: str,
                 firmware_version: str,
                 hardware_version: str,
                 description: str,
                 measurement_units: str,
                 location: str):
        """
        Initializes the SensorMetadata object with the provided sensor details.
        The attributes are assigned immutably, and no further modifications are allowed
        after initialization.

        Args:
            sensor_id (str): Unique identifier for the sensor.
            sensor_name (str): Name of the sensor.
            sensor_type (str): Type of the sensor (e.g., heart rate, temperature).
            manufacturer (str): Manufacturer of the sensor.
            model (str): Model of the sensor.
            firmware_version (str): Firmware version of the sensor.
            hardware_version (str): Hardware version of the sensor.
            description (str): Description of the sensor's functionality.
            measurement_units (str): Units of measurement (e.g., BPM, °C).
            location (str): Location where the sensor is placed (e.g., wrist, room).
        """
        # Initialize attributes using __setattr__ to enforce immutability
        object.__setattr__(self, '_sensor_id', sensor_id)
        object.__setattr__(self, '_sensor_name', sensor_name)
        object.__setattr__(self, '_sensor_type', sensor_type)
        object.__setattr__(self, '_manufacturer', manufacturer)
        object.__setattr__(self, '_model', model)
        object.__setattr__(self, '_firmware_version', firmware_version)
        object.__setattr__(self, '_hardware_version', hardware_version)
        object.__setattr__(self, '_description', description)
        object.__setattr__(self, '_measurement_units', measurement_units)
        object.__setattr__(self, '_location', location)

    @property
    def sensor_id(self) -> str:
        """Returns the unique identifier of the sensor."""
        return self._sensor_id

    @property
    def sensor_name(self) -> str:
        """Returns the name of the sensor."""
        return self._sensor_name

    @property
    def sensor_type(self) -> str:
        """Returns the type of the sensor."""
        return self._sensor_type

    @property
    def manufacturer(self) -> str:
        """Returns the manufacturer of the sensor."""
        return self._manufacturer

    @property
    def model(self) -> str:
        """Returns the model of the sensor."""
        return self._model

    @property
    def firmware_version(self) -> str:
        """Returns the firmware version of the sensor."""
        return self._firmware_version

    @property
    def hardware_version(self) -> str:
        """Returns the hardware version of the sensor."""
        return self._hardware_version

    @property
    def description(self) -> str:
        """Returns the description of the sensor's functionality."""
        return self._description

    @property
    def measurement_units(self) -> str:
        """Returns the measurement units used by the sensor."""
        return self._measurement_units

    @property
    def location(self) -> str:
        """Returns the location where the sensor is placed."""
        return self._location

    def __setattr__(self, name, value):
        """
        Prevents modification of any attribute after initialization.

        Args:
            name (str): The name of the attribute to modify.
            value (Any): The value to assign to the attribute.

        Raises:
            AttributeError: If an attempt is made to modify an existing attribute.
        """
        if hasattr(self, name):
            raise AttributeError(f"Can't modify immutable attribute '{name}'")
        super().__setattr__(name, value)

    def to_dict(self) -> dict:
        """
        Returns the sensor metadata as a dictionary.

        Returns:
            dict: A dictionary containing all the sensor metadata attributes.
        """
        return {
            'sensor_id': self.sensor_id,
            'sensor_name': self.sensor_name,
            'sensor_type': self.sensor_type,
            'manufacturer': self.manufacturer,
            'model': self.model,
            'firmware_version': self.firmware_version,
            'hardware_version': self.hardware_version,
            'description': self.description,
            'measurement_units': self.measurement_units,
            'location': self.location
        }