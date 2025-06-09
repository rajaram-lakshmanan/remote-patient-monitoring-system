#!/usr/bin/env python3
# -----------------------------------------------------------------------------
# Filename: oximeter5.py
# Author: Rajaram Lakshmanan
# Description:  Oximeter5 Class for interfacing with the Oximeter 5 Click board
# over I2C.
# License: MIT (see LICENSE)
# -----------------------------------------------------------------------------

import logging
import time

from smbus2 import SMBus

logger = logging.getLogger("Oximeter5")

class Oximeter5:
    """
    Oximeter5 Class for interfacing with the Oximeter 5 Click board (based on MAX30102) over I2C.

    This class provides methods to interact with the MAX30102 sensor, including configuring the sensor,
     reading SpO2 and heart rate time_series, temperature time_series, and controlling the sensor's state.
    """

    # Register addresses
    REG_INTR_STATUS_1 = 0x00
    REG_INTR_STATUS_2 = 0x01

    REG_INTR_ENABLE_1 = 0x02
    REG_INTR_ENABLE_2 = 0x03

    REG_FIFO_WR_PTR = 0x04
    REG_OVF_COUNTER = 0x05
    REG_FIFO_RD_PTR = 0x06
    REG_FIFO_DATA = 0x07
    REG_FIFO_CONFIG = 0x08

    REG_MODE_CONFIG = 0x09
    REG_SPO2_CONFIG = 0x0A
    REG_LED1_PA = 0x0C
    REG_LED2_PA = 0x0D
    REG_PILOT_PA = 0x10

    REG_TEMP_INTR = 0x1F
    REG_TEMP_FRAC = 0x20
    REG_TEMP_CONFIG = 0x21

    REG_REV_ID = 0xFE
    REG_PART_ID = 0xFF

    def __init__(self, bus: SMBus, address):
        """
        Initializes the Oximeter5 class for I2C communication with the Oximeter 5 Click board.

        Args:
            bus (int): The I2C bus object for communication.
            address (int): The I2C address of the Ecg7 Click device.
        """
        self.address = address
        self.bus = bus

        self._configure()

        self.revision = self.read_register(Oximeter5.REG_REV_ID)
        self.part_id = self.read_register(Oximeter5.REG_PART_ID)
        logger.debug(f"Oximeter 5 Sensor - Rev ID: {self.revision}, Part ID: {self.part_id}")

        self.board_temperature = self.read_temperature()
        logger.debug(f"Oximeter 5 Sensor - Temperature: {self.board_temperature}")

    def _configure(self, led_mode=0x03) -> None:
        """Configure the Oximeter 5 sensor with default settings."""

        # Soft reset the sensor and wait for a second for initialization
        self.reset()
        time.sleep(1)

        # Read interrupt status
        status = self.read_register(Oximeter5.REG_INTR_STATUS_1)
        time.sleep(0.01)
        logger.debug(f"Oximeter 5 Sensor - Interrupt Status: {status}")

        # Configure interrupts
        # Set Interrupt Full Enable 1 = 0x80, Set Interrupt PPG Ready Enable 1 = 0x40
        # ORing 0x80 and 0x40 = 0xC0
        self.write_register(Oximeter5.REG_INTR_ENABLE_1, 0xC0)
        time.sleep(0.01)

        # Disable temp interrupt
        # Set Interrupt Enable 2 Temporary Interrupt = 0x00
        self.write_register(Oximeter5.REG_INTR_ENABLE_2, 0x00)
        time.sleep(0.01)

        # Reset the FIFO write pointer
        self.write_register(Oximeter5.REG_FIFO_WR_PTR, 0x00)
        time.sleep(0.01)

        # Reset the FIFO counter
        self.write_register(Oximeter5.REG_OVF_COUNTER, 0x00)
        time.sleep(0.01)

        # Reset the FIFO read pointer
        self.write_register(Oximeter5.REG_FIFO_RD_PTR, 0x00)
        time.sleep(0.01)

        # Configuration of the FIFO.
        # FIFO configuration simple average = 0x40, Set FIFO CFG Data sample 15 = 0x0F
        # ORing 0x40 and 0x0F = 0x4F
        self.write_register(Oximeter5.REG_FIFO_CONFIG, 0x4F)
        time.sleep(0.01)

        # Set config mode
        # 0x02 for read-only, 0x03 for SpO2 mode, 0x07 multimode LED
        self.write_register(Oximeter5.REG_MODE_CONFIG, led_mode)
        time.sleep(0.01)

        # SpO2 mode
        # Set Sp02 config ADC RGE 4096 = 0x20, Set Sp02 Config SR SEC 100 = 0x04, Set Sp02 Config LED PW 18 Bit = 0x03
        # ORing 0x20, 0x04 and 0x03 = 0x27
        self.write_register(Oximeter5.REG_SPO2_CONFIG, 0x27)
        time.sleep(0.01)

        # 7.2mA for LED1
        self.write_register(Oximeter5.REG_LED1_PA, 0x3C)
        time.sleep(0.01)

        # 7.2mA for LED2
        self.write_register(Oximeter5.REG_LED2_PA, 0x3C)
        time.sleep(0.01)

        # ~25mA for Pilot LED
        self.write_register(Oximeter5.REG_PILOT_PA, 0x7F)
        time.sleep(0.01)

        # Enable temperature measurement
        self.write_register(Oximeter5.REG_TEMP_CONFIG, 0x01)
        time.sleep(0.01)  # Delay 10ms

    def write_register(self, reg, value):
        """Write to an I2C register."""
        self.bus.write_byte_data(self.address, reg, value)

    def read_register(self, reg):
        """Read from an I2C register."""
        return self.bus.read_byte_data(self.address, reg)

    def shutdown(self):
        """Shutdown the Oximeter sensor."""
        logger.debug(f"Shutting down Oximeter 5 Sensor...")
        self.write_register(Oximeter5.REG_MODE_CONFIG, 0x80)

    def reset(self):
        """
        Reset the device, this will clear all settings."""
        # Run the setup again to initialize settings
        self.write_register(Oximeter5.REG_MODE_CONFIG, 0x40)

    def read_fifo(self):
        """Read IR and RED values from FIFO."""
        # Read 1 byte from registers (values are discarded)
        self.read_register(Oximeter5.REG_INTR_STATUS_1)
        self.read_register(Oximeter5.REG_INTR_STATUS_2)

        # Read 6-byte time_series from the device
        data = self.bus.read_i2c_block_data(self.address, Oximeter5.REG_FIFO_DATA, 6)

        # Mask MSB [23:18]
        red_led = (data[0] << 16 | data[1] << 8 | data[2]) & 0x03FFFF
        ir_led = (data[3] << 16 | data[4] << 8 | data[5]) & 0x03FFFF

        return red_led, ir_led

    def get_data_present(self):
        """Check whether time_series is present in the buffer and return the
        number of available samples."""
        read_ptr = self.bus.read_byte_data(self.address, Oximeter5.REG_FIFO_RD_PTR)
        write_ptr = self.bus.read_byte_data(self.address, Oximeter5.REG_FIFO_WR_PTR)
        if read_ptr == write_ptr:
            return 0
        else:
            num_samples = write_ptr - read_ptr

            # Account for the pointer wrap around
            if num_samples < 0:
                num_samples += 32
            return num_samples

    def read_sequential(self, amount=100):
        """Read the 'IR'-LED and 'Red'-LED buffer for the specified
        number of times."""
        # This will be a blocking function to read the buffer
        red_buf = []
        ir_buf = []
        count = amount
        while count > 0:
            num_bytes = self.get_data_present()
            while num_bytes > 0:
                red, ir = self.read_fifo()

                red_buf.append(red)
                ir_buf.append(ir)
                num_bytes -= 1
                count -= 1

        return red_buf, ir_buf

    def read_temperature(self):
        """Read the sensor board temperature"""
        try:
            temp_intr = self.read_register(Oximeter5.REG_TEMP_INTR)
            temperature = float(temp_intr)

            # Check the value is not greater than the maximum unsigned 8-bit time_series
            if temp_intr > 0x7F:
                temperature -= 256

            temp_frac = self.read_register(Oximeter5.REG_TEMP_FRAC)

            # Byte low nibble
            temp_frac = temp_frac & 0x0F

            # Temperature calculation
            temperature += float(temp_frac) * 0.0625
            return temperature

        except Exception as e:
            print(f"Error reading temperature: {e}")
            return None