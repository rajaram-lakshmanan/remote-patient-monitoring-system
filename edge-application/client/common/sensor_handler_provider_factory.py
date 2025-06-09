#!/usr/bin/env python3
# -----------------------------------------------------------------------------
# Filename: sensor_handler_provider_factory.py
# Author: Rajaram Lakshmanan
# Description:  Factory to create sensor handler providers based on device type.
# License: MIT (see LICENSE)
# -----------------------------------------------------------------------------

from client.common.base_sensor_handler_provider import BaseSensorHandlerProvider
from client.ble.ble_sensor_handler.galaxy_watch.galaxy_watch_ble_sensor_handler_provider import GalaxyWatchBleSensorHandlerProvider
from client.i2c.i2c_sensor_handler.click_board.click_board_i2c_sensor_handler_provider import ClickBoardI2CSensorHandlerProvider
from client.common.device_sensor_classification_types import DeviceTypes

class SensorHandlerProviderFactory:
    """
    Factory to create sensor handler providers based on device type.
    """

    @staticmethod
    def create_provider(device_type: str, event_bus) -> BaseSensorHandlerProvider:
        """
        Create and return the appropriate sensor handler provider based on the device type.

        Args:
            device_type (str): Type of the device ("galaxy_watch", "clickboard", etc.)
            event_bus: Event bus for sensor handlers

        Returns:
            An instance of BaseSensorHandlerProvider or raises ValueError if the type is unsupported
        """
        try:
            device_type = DeviceTypes(device_type)
        except ValueError:
            raise ValueError(f"Device type '{device_type}' is not supported by the application.")

        if device_type == DeviceTypes.GALAXY_WATCH:
            return GalaxyWatchBleSensorHandlerProvider(event_bus)
        elif device_type == DeviceTypes.CLICK_BOARD:
            return ClickBoardI2CSensorHandlerProvider(event_bus)

        raise ValueError(f"Device type '{device_type.value}' is not supported by the application.")