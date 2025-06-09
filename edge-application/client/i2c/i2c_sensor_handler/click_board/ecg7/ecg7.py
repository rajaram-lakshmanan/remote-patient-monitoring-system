#!/usr/bin/env python3
# -----------------------------------------------------------------------------
# Filename: ecg7.py
# Author: Rajaram Lakshmanan
# Description:  Ecg7 Class for interfacing with the Ecg 7 Click board over I2C.
# License: MIT (see LICENSE)
# -----------------------------------------------------------------------------

import logging

from smbus2 import SMBus

logger = logging.getLogger("Ecg7")

class Ecg7:
    """
    Ecg7 Class for interfacing with the Ecg 7 Click board (based on MCP6N16) over I2C.

    This class allows you to interact with the ECG sensor by reading raw ADC values and
    converting them into voltages. It is used to measure electrical activity of the heart,
    typically used in medical monitoring devices.

    The Ecg7 Click uses the MCP3221 chip and provides a 12-bit ADC resolution (4095 values).
    """
    ADC_RESOLUTION = 0x0FFF  # 12-bit resolution (4095)

    def __init__(self, bus: SMBus, address, vref=3.3):
        """
        Initializes the Ecg7 class for I2C communication with the Ecg 7 Click board.

        Args:
            bus (int): The I2C bus object for communication.
            address (int): The I2C address of the Ecg7 Click device.
            vref (float): Reference voltage for ADC conversion. Defaults to 3.3 V.
        """
        self.vref = vref
        self.address = address
        self.bus = bus

    def read_raw_adc(self):
        """
        Reads the raw ADC value from the Ecg7 Click device.

        The function reads 2 bytes from the I2C device and combines them to form a 12-bit value.
        The raw value is then masked using the 12-bit resolution to ensure it doesn't exceed the
        ADC's maximum value.

        Returns:
            int: A 12-bit raw ADC value (0 to 4095) if successful, None if there was an error.

        Raises:
            Exception: If there is an issue with the I2C communication.
        """
        try:
            # Direct 2-byte read (no register address specified)
            data = self.bus.read_i2c_block_data(self.address, 0x00, 2)
            logger.debug(f"Raw ADC Data: {data}")
            raw_value = ((data[0] << 8) | (data[1] & 0xFF)) & self.ADC_RESOLUTION
            return raw_value
        except Exception as e:
            logger.error(f"I2C Read Error for Ecg7 Click: {e}")
            return None

    def read_ecg_mv(self):
        """
        Read ECG signal in millivolts, calibrated for the ECG7 Click board.

        Returns:
            float: ECG signal in millivolts, or None if reading failed.

        Note: This method is not used, as the Offset seems arbitrary to set.
        """
        voltage = self.read_voltage()
        if voltage is not None:
            # Constants for the ECG7 Click board
            vref = 3.3  # Reference voltage (3.3V for Raspberry Pi)
            mid_point = vref / 2  # Signal is centered at half of Vref

            # Set to 301 based on the switch position in the Clickboard
            instr_amp_gain = 301

            # Additional gain from the op-amp stage
            op_amp_gain = 1.0

            # Total gain in the signal path
            total_gain = instr_amp_gain * op_amp_gain

            # Convert to mV and compensate for hardware gain
            ecg_mv = (voltage - mid_point) * 1000.0 / total_gain

            ecg_mv += 4.45  # Offset correction
            return ecg_mv


        return None

    def read_voltage(self):
        """
        Converts the raw ADC value into a voltage based on the reference voltage.

        This function calls `read_raw_adc` to get the raw ADC value and then converts it to
        the corresponding voltage using the formula:
            Voltage = (Raw Value * Vref) / ADC_RESOLUTION

        Returns:
            float: The voltage corresponding to the raw ADC value, or None if there was an error.

        Raises:
            Exception: If there is an issue in reading the raw ADC value.
        """
        raw = self.read_raw_adc()
        return (raw * self.vref) / self.ADC_RESOLUTION if raw is not None else None