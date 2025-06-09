#!/usr/bin/env python3
# -----------------------------------------------------------------------------
# Filename: redis_manager.py
# Author: Rajaram Lakshmanan
# Description: Redis server management and connection handling
# License: MIT (see LICENSE)
# -----------------------------------------------------------------------------

import subprocess
import logging
import time
import tempfile
import os
import redis

from config.models.event_bus.redis_config import RedisConfig

logger = logging.getLogger("RedisManager")

class RedisManager:
    """
    Redis server management and connection handling.
    Ensures Redis is running with the correct configuration before the application uses it.
    """

    def __init__(self, redis_config: RedisConfig, retry_attempts: int = 5, retry_delay: float = 2.0):
        """
        Initialize the Redis manager with application configuration.

        Args:
            redis_config: Redis configuration from the application config
            retry_attempts: Number of connection retry attempts
            retry_delay: Delay between retry attempts in seconds
        """
        self.host = redis_config.host
        self.port = redis_config.port
        self.db = redis_config.db
        self.retry_attempts = retry_attempts
        self.retry_delay = retry_delay
        self.redis_process = None
        self._redis = None

        logger.info(f"RedisManager initialized with host={self.host}, port={self.port}, db={self.db}")

    def start(self) -> bool:
        """
        Ensures Redis server is running, attempts to start it if not.
        Returns True if Redis is running (or successfully started), False otherwise.
        """
        # First, check if Redis is already running at the configured port
        if self._check_redis_running():
            logger.info(f"Redis server is already running on {self.host}:{self.port}")
            return True

        # If we're here, Redis is not running, so try to start it
        logger.info(f"Redis server not running on {self.host}:{self.port}, attempting to start...")
        try:
            logger.info(f"Attempting to start Redis server directly on port {self.port}...")
            temp_config = tempfile.NamedTemporaryFile(mode='w+', delete=False)
            temp_config.write(f"port {self.port}\n")

            # Only bind to the specific host if it's not localhost
            if self.host != 'localhost' and self.host != '127.0.0.1':
                temp_config.write(f"bind {self.host}\n")
            temp_config.write(f"databases {max(16, self.db + 1)}\n")

            # Add basic security
            temp_config.write("protected-mode yes\n")
            temp_config.close()

            # Start Redis with the temp config
            self.redis_process = subprocess.Popen(["redis-server", temp_config.name],
                                                  stdout=subprocess.DEVNULL,
                                                  stderr=subprocess.DEVNULL)
            # Give it a moment to start
            time.sleep(2)

            # Clean up the temp file
            os.unlink(temp_config.name)

            if self._check_redis_running():
                logger.info(f"Successfully started Redis server on port {self.port}")
                return True
            else:
                if self.redis_process:
                    self.redis_process.terminate()
                    self.redis_process = None
                logger.error(f"Redis server started but not responding on port {self.port}")

        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            logger.warning(f"Failed to start Redis directly: {e}")

        logger.error("All attempts to start Redis server failed")
        return False

    def stop(self):
        """Clean up the Redis process if the application has started it."""
        if self.redis_process:
            logger.info(f"Shutting down Redis server on port {self.port}...")
            self.redis_process.terminate()
            try:
                self.redis_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.redis_process.kill()
            self.redis_process = None

    def _check_redis_running(self) -> bool:
        """
        Check if Redis server is running by attempting to connect.

        Returns:
            True if Redis is running and responds to ping, False otherwise
        """
        try:
            redis_server = redis.Redis(host=self.host,
                                       port=self.port,
                                       db=self.db,
                                       socket_connect_timeout=2.0)
            return redis_server.ping()
        except (redis.ConnectionError, redis.TimeoutError):
            return False
        except Exception as e:
            logger.error(f"Error checking Redis connection: {e}")
            return False