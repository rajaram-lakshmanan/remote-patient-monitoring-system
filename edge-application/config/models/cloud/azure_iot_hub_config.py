#!/usr/bin/env python3
# -----------------------------------------------------------------------------
# Filename: azure_iot_hub_config.py
# Author: Rajaram Lakshmanan
# Description: Azure IoT hub configuration.
# License: MIT (see LICENSE)
# -----------------------------------------------------------------------------

from pydantic import BaseModel, field_validator
from pathlib import Path
import re

from pydantic_core.core_schema import FieldValidationInfo


class AzureIoTHubConfig(BaseModel):
    """Azure IoT Hub configuration."""
    host_name: str
    certificate_folder: str
    connection_timeout: int = 60
    retry_count: int = 3

    @field_validator('host_name') # noqa
    @staticmethod
    def validate_hostname(v, info: FieldValidationInfo): # noqa
        if not v or not re.match(r'^([a-z0-9]+(-[a-z0-9]+)*\.)+[a-z]{2,}$', v, re.IGNORECASE):
            raise ValueError("Invalid hostname or format")
        return v

    @field_validator('certificate_folder') # noqa
    @staticmethod
    def validate_cert_folder(v, info: FieldValidationInfo): # noqa
        if not v:
            raise ValueError("certificate_folder must be set")

        path = Path(v)
        if not path.is_dir():
            raise ValueError(f"certificate_folder does not exist or is not a directory: {v}")

        return v

    model_config = {
        "extra": "ignore"
    }
