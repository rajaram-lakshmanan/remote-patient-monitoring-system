#!/usr/bin/env python3
# -----------------------------------------------------------------------------
# Filename: cpu_telemetry.py
# Author: Rajaram Lakshmanan
# Description:  Retrieves the telemetry registry of the CPU.
# License: MIT (see LICENSE)
# -----------------------------------------------------------------------------

import logging
from abc import ABC

from edge_gateway.base_collector_publisher import BaseCollectorPublisher
from edge_gateway.helper.shell_command import ShellCommand
from event_bus.models.edge_gateway.telemetry.cpu_telemetry_event import CpuTelemetryEvent
from event_bus.redis_stream_bus.redis_stream_bus import RedisStreamBus
from event_bus.stream_name import StreamName

logger = logging.getLogger("CpuTelemetry")

class CpuTelemetry(BaseCollectorPublisher, ABC):
    """
    A utility class for gathering and publishing CPU telemetry time_series from Linux systems.

    This class collects real-time registry about the CPU hardware from any Linux system,
    including the temperature and frequency. After collection, it publishes this
    registry to a Redis stream for downstream consumption by other services.

    The time_series is collected from system files in the /sys filesystem, which requires
    appropriate read permissions to access the thermal and frequency registry.

    CPU telemetry time_series provides health metrics for system performance analysis,
    thermal management, and power consumption monitoring in the digital twin.
    """

    def __init__(self, event_bus: RedisStreamBus):
        """
        Initialize the CPU Telemetry.

        Args:
            event_bus (RedisStreamBus): The event bus for publishing events.

         Initializes local variables to store cpu telemetry.
        """
        super().__init__(event_bus)

        self._event_bus.register_stream(StreamName.EDGE_GW_CPU_TELEMETRY.value, CpuTelemetryEvent)

        self._temperature = None
        self._frequency = None

        logger.debug("Successfully initialized CPU Telemetry")

    def collect(self):
        """Collect the current CPU telemetry time_series."""
        try:
            logger.debug("Collecting CPU telemetry")
            self._information_available = False
            self._collection_in_progress = True

            self._temperature = CpuTelemetry._get_temperature()
            self._frequency = CpuTelemetry._get_frequency()

            self._information_available = True
            logger.debug("Successfully collected CPU telemetry")
        except Exception as e:
            logger.exception(f"Failed to retrieve CPU telemetry: {e}", exc_info=True)
        finally:
            self._collection_in_progress = False

    def publish(self) -> None:
        """
        Publish the collected CPU telemetry to event bus.

        Creates a CpuTelemetryEvent with the collected time_series and publishes it to the appropriate stream.
        """
        try:
            logger.info("Publishing CPU inventory event")
            event = CpuTelemetryEvent(temperature_celsius=self._temperature,
                                      frequency_mhz=self._frequency)
            self._publish_to_stream(StreamName.EDGE_GW_CPU_TELEMETRY.value, event)
            logger.info(f"Published CPU telemetry event: {event.event_id}")
        except Exception as e:
            logger.error(f"Error publishing Edge Gateway CPU Telemetry to Redis Stream: {e}")

    @staticmethod
    def _get_temperature() -> float:
        try:
            raw = ShellCommand.execute(["cat", "/sys/class/thermal/thermal_zone0/temp"])
            return round(float(raw.strip()) / 1000, 1) if raw else 0
        except Exception as e:
            logger.exception(f"Failed to read CPU temperature: {e}", exc_info=True)
            raise

    @staticmethod
    def _get_frequency() -> float:
        try:
            raw = ShellCommand.execute(["cat", "/sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq"])
            return round(int(raw.strip()) / 1000) if raw else 0
        except Exception as e:
            logger.exception(f"Failed to read CPU frequency: {e}", exc_info=True)
            raise