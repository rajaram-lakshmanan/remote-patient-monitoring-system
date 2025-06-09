#!/usr/bin/env python3

import logging
import time
from typing import Dict, List, Optional
from dataclasses import dataclass
from threading import Lock

logger = logging.getLogger("ConsumerMetrics")

@dataclass
class ConsumerMetrics:
    """Thread-safe metrics storage for consumer operations"""
    def __init__(self):
        self._lock = Lock()
        self._messages_processed = 0
        self._messages_failed = 0
        self._publish_count = 0
        self._redis_errors = 0
        self._last_success = 0.0
        self._processing_time = 0.0
        self._last_error: Optional[str] = None
        self._consumer_lag: Dict[str, int] = {}
        self._batch_sizes: List[int] = []

    def increment(self, metric: str, value: int = 1) -> None:
        with self._lock:
            if hasattr(self, f"_{metric}"):
                setattr(self, f"_{metric}", getattr(self, f"_{metric}") + value)

    def set_error(self, error: str) -> None:
        with self._lock:
            self._last_error = error

    def record_success(self) -> None:
        with self._lock:
            self._last_success = time.time()

    def update_lag(self, stream: str, lag: int) -> None:
        with self._lock:
            self._consumer_lag[stream] = lag

    def record_batch_size(self, size: int) -> None:
        with self._lock:
            self._batch_sizes.append(size)
            if len(self._batch_sizes) > 100:
                self._batch_sizes.pop(0)

    def set_processing_time(self, duration: float) -> None:
        with self._lock:
            self._processing_time = duration

    def get_metrics(self) -> dict:
        with self._lock:
            avg_batch_size = sum(self._batch_sizes) / len(self._batch_sizes) if self._batch_sizes else 0
            return {
                "messages_processed": self._messages_processed,
                "messages_failed": self._messages_failed,
                "publish_count": self._publish_count,
                "redis_errors": self._redis_errors,
                "last_success": self._last_success,
                "processing_time": self._processing_time,
                "last_error": self._last_error,
                "consumer_lag": self._consumer_lag.copy(),
                "average_batch_size": avg_batch_size
            }