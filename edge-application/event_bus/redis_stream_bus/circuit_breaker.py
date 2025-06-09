#!/usr/bin/env python3

import logging
import time
from threading import Lock

logger = logging.getLogger("CircuitBreaker")

class CircuitBreaker:
    """Circuit breaker pattern implementation for Redis connections"""
    def __init__(self, failure_threshold: int = 5, reset_timeout: float = 60.0):
        self._failure_count = 0
        self._failure_threshold = failure_threshold
        self._reset_timeout = reset_timeout
        self._last_failure_time = 0
        self._state = "CLOSED"  # CLOSED, OPEN, HALF_OPEN
        self._lock = Lock()

    def record_failure(self) -> None:
        with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.time()
            if self._failure_count >= self._failure_threshold:
                self._state = "OPEN"
                logger.warning("Redis Stream Circuit breaker opened")

    def record_success(self) -> None:
        with self._lock:
            if self._state != "CLOSED":
                logger.info("Redis Stream Circuit breaker closing")
            self._failure_count = 0
            self._state = "CLOSED"

    def is_closed(self) -> bool:
        with self._lock:
            if self._state == "OPEN":
                if time.time() - self._last_failure_time > self._reset_timeout:
                    self._state = "HALF_OPEN"
                    return True
                return False
            return True

    def get_state(self) -> str:
        with self._lock:
            return self._state