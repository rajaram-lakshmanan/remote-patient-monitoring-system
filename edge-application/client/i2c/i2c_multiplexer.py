#!/usr/bin/env python3
# -----------------------------------------------------------------------------
# Filename: i2c_multiplexer.py
# Author: Rajaram Lakshmanan
# Description:  I2C multiplexer to enable the channels required to communicate
# with the I2C sensor(s).
# License: MIT (see LICENSE)
# -----------------------------------------------------------------------------

import logging
import time

from smbus2 import SMBus

from config.models.i2c.i2c_client_config import I2CClientConfig
from event_bus.redis_stream_bus.redis_stream_bus import RedisStreamBus

logger = logging.getLogger("I2CClient")

class I2CMultiplexer:
    """
    I2C multiplexer to enable the channels required to communicate with the I2C sensor(s).

    Multiplexer configuration and its address are pre-requisite for the edge gateway (Raspberry PI or similar)
    to communicate to all sensors configured in a 'multi-drop' setup.
    """

    def __init__(self,
                 event_bus: RedisStreamBus,
                 config: I2CClientConfig):
        """
        Initialize the I2CMultiplexer.

        Args:
            event_bus (RedisStreamBus): The event bus for publishing events.
            config (I2CClientConfig): I2C client configuration.
        """
        self._event_bus = event_bus

        if not config.i2c_mux or not config.i2c_mux.address:
            raise ValueError("I2C multiplexer address is not configured")

        self._bus_id = config.bus_id

        # Convert the address string to integer
        self._mux_address = int(config.i2c_mux.address, 16)

    def enable_mux_channels(self, channels: list[int]):
        """
        Enable multiple I2C channels on the TCA9548A multiplexer.

        Args:
            channels List[int]: List of I2C channels in the multiplexer to enable.
        """
        # Ensure the channels input are between 0 and 7
        if any(channel < 0 or channel > 7 for channel in channels):
            print("Invalid channel. Must be between 0 and 7")
            return

        # Bitmask by OR-ing channels to enable multiple channels at the same time
        control_value = 0

        for channel in channels:
            control_value = control_value | (1 << channel)

        # Write the control value to the register to enable the channels
        with SMBus(self._bus_id) as bus:
            bus.write_byte(self._mux_address, control_value)
            # Wait for the channel to be enabled
            time.sleep(0.1)
        logger.info(f"Enabled MUX Channels {channels}")

    def disable_mux_channels(self, channels):
        """
        Disable the multiple I2C channels on the TCA9548A multiplexer.

        Args:
            channels List[int]: List of I2C channels in the multiplexer to disable
        """
        # Ensure the channels input are between 0 and 7
        if any(channel < 0 or channel > 7 for channel in channels):
            print("Invalid channel. Must be between 0 and 7")
            return

        # Bitmask by OR-ing channels to disable multiple channels at the same time
        control_value = 0

        for channel in channels:
            control_value = control_value & ~(1 << channel)

        # Write the control value to the register to disable the channels
        with SMBus(self._bus_id) as bus:
            bus.write_byte(self._mux_address, control_value)
            # Wait for the channel to be enabled
            time.sleep(0.1)
        logger.info(f"Disabled MUX Channels {channels}")

    def get_i2c_sensor_address(self):
        """
        Gets the list of the addresses of the I2C sensors connected to the Mux.

        Returns:
            List of the addresses of the connected I2C sensors.
        """
        i2c_sensor_address = []
        for addr in range(3, 128):
            try:
                with SMBus(self._bus_id) as bus:
                    bus.read_byte(addr, 0)  # Send a dummy byte
                    i2c_sensor_address.append(addr)
            except Exception as e:
                logger.debug(f"I2C sensors connected to the Mux does not have this address assigned {e}")
                pass

        return i2c_sensor_address



