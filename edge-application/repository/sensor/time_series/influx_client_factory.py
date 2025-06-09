#!/usr/bin/env python3
# -----------------------------------------------------------------------------
# Filename: influx_client_factory.py
# Author: Rajaram Lakshmanan
# Description: Factory for creating and configuring InfluxDB clients.
# License: MIT (see LICENSE)
# -----------------------------------------------------------------------------

import logging
import time
from typing import Optional

from influxdb_client import InfluxDBClient

logger = logging.getLogger("InfluxClientFactory")


class InfluxClientFactory:
    """
    Factory for creating and configuring InfluxDB clients.

    This class handles the creation and configuration of InfluxDB clients
    with proper connection management and bucket creation.
    """

    def __init__(self, url: str, token: str, org: str):
        """
        Initialize the InfluxDB Client Factory.

        Args:
            url (str): The URL of the InfluxDB server
            token (str): The API token for InfluxDB
            org (str): The organization to use in InfluxDB
        """
        self.url = url
        self.token = token
        self.org = org
        self.client = None

    def create_influx_client(self, max_retries=3, retry_delay=5) -> Optional[InfluxDBClient]:
        """
        Create an InfluxDB client with a retry mechanism.

        Args:
            max_retries (int): Maximum number of connection attempts
            retry_delay (int): Seconds to wait between retries

        Returns:
            InfluxDBClient: Configured InfluxDB client

        Raises:
            ConnectionError: If unable to establish connection after retries
        """
        retries = 0
        while retries < max_retries:
            try:
                # Create an InfluxDB client
                self.client = InfluxDBClient(
                    url=self.url,
                    token=self.token,
                    org=self.org
                )

                # Verify the connection is working
                if self.check_connection():
                    logger.info(f"Connected to InfluxDB at {self.url}")
                    return self.client
                else:
                    raise ConnectionError("Connection established but health check failed")

            except Exception as e:
                retries += 1
                if retries >= max_retries:
                    logger.error(f"Failed to connect to InfluxDB after {max_retries} attempts: {e}")
                    raise
                else:
                    logger.warning(f"Connection attempt {retries} failed: {e}. Retrying in {retry_delay} seconds...")
                    time.sleep(retry_delay)

        return None

    def ensure_bucket_exists(self, bucket_name: str) -> bool:
        """
        Check if the bucket exists and create it if it doesn't.

        Args:
            bucket_name (str): The name of the bucket to create or verify

        Returns:
            bool: True if the bucket exists or was created successfully

        Raises:
            ValueError: If the client is not initialized
        """
        if not self.client:
            raise ValueError("InfluxDB client not initialized. Call create_influx_client first.")

        try:
            # Get the buckets API
            buckets_api = self.client.buckets_api()

            # Find bucket by name
            bucket = buckets_api.find_bucket_by_name(bucket_name)

            if bucket is None:
                logger.info(f"Bucket '{bucket_name}' not found. Creating it...")

                # Create the bucket (default retention is infinite)
                # For a specific retention period, use retention_rules parameter
                buckets_api.create_bucket(bucket_name=bucket_name, org=self.org)
                logger.info(f"Bucket '{bucket_name}' created successfully")
            else:
                logger.info(f"Bucket '{bucket_name}' already exists")

            return True

        except Exception as e:
            logger.error(f"Error checking/creating bucket: {e}")
            return False

    def check_connection(self) -> bool:
        """
        Check if the connection to InfluxDB is healthy.

        Returns:
            bool: True if the connection is healthy, False otherwise
        """
        if not self.client:
            return False

        try:
            health = self.client.health()
            return health.status == "pass"
        except Exception as e:
            logger.error(f"InfluxDB connection check failed: {e}")
            return False

    def close(self) -> None:
        """Close the InfluxDB client connection"""
        if self.client:
            try:
                self.client.close()
                logger.debug("Closed InfluxDB client connection")
            except Exception as e:
                logger.warning(f"Error closing InfluxDB client: {e}")