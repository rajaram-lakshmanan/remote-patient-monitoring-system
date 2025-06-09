#!/usr/bin/env python3
# -----------------------------------------------------------------------------
# Filename: config_manager.py
# Author: Rajaram Lakshmanan
# Description:  Configuration manager for loading and validating application
# configuration.
# License: MIT (see LICENSE)
# -----------------------------------------------------------------------------

import os
import yaml
import json
import logging
from typing import Dict, Any, Optional

from config.models.health_monitoring_config import HealthMonitorConfig

logger = logging.getLogger("ConfigManager")

class ConfigManager:
    """
    Configuration manager for loading and validating application configuration.
    """

    def __init__(self):
        """Initialize a new configuration manager."""
        self._config: Optional[HealthMonitorConfig] = None
        self._config_file: Optional[str] = None
        self._raw_config: Dict[str, Any] = {}

    @property
    def config(self) -> HealthMonitorConfig:
        """
        Get the validated configuration.

        Returns:
            The validated configuration object.

        Raises:
            ValueError: If configuration hasn't been loaded.
        """
        if self._config is None:
            raise ValueError("Configuration is not loaded. Call load() first.")
        return self._config

    @property
    def raw_config(self) -> Dict[str, Any]:
        """
        Get the raw configuration dictionary.

        Returns:
            The raw configuration dictionary.

        Raises:
            ValueError: If configuration hasn't been loaded.
        """
        if not self._raw_config:
            raise ValueError("Configuration is not loaded. Call load() first.")
        return self._raw_config

    def load(self, config_file: str = "config/config.yaml") -> HealthMonitorConfig:
        """
        Load the configuration from a file.

        Args:
            config_file: Path to the configuration file.

        Returns:
            The validated configuration object.

        Raises:
            FileNotFoundError: If the configuration file doesn't exist.
            ValueError: If the configuration is invalid.
        """
        if not os.path.isfile(config_file):
            raise FileNotFoundError(f"Configuration file not found: {config_file}")

        self._config_file = config_file

        # Determine the file type based on the extension
        file_ext = os.path.splitext(config_file)[1].lower()

        # Load the configuration file
        try:
            with open(config_file, 'r') as f:
                if file_ext == '.yaml' or file_ext == '.yml':
                    self._raw_config = yaml.safe_load(f)
                elif file_ext == '.json':
                    self._raw_config = json.load(f)
                else:
                    raise ValueError(f"Unsupported configuration file format: {file_ext}")
        except Exception as e:
            logger.error(f"Error loading configuration file: {e}")
            raise

        # Validate the configuration
        try:
            # ** operator is unpacking the raw config dictionary
            self._config = HealthMonitorConfig(**self._raw_config)
            logger.info(f"Configuration loaded and validated successfully from {config_file}")
            return self._config
        except Exception as e:
            logger.error(f"Invalid configuration: {e}")
            raise ValueError(f"Invalid configuration: {e}")