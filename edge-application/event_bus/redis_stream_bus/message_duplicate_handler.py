#!/usr/bin/env python3

from collections import deque
from datetime import datetime, timedelta, timezone
import json
import hashlib
from threading import Lock
from typing import Dict

class MessageDuplicationHandler:
    """
    Handles deduplication of messages within a rolling time window, scoped by the key (e.g., stream name).

    This class tracks message fingerprints per key to detect duplicates efficiently.
    Expired entries are removed periodically to limit memory usage.

    Attributes:
        _window_timedelta (timedelta): Duration to keep message fingerprints.
        _messages (Dict[str, Dict[str, datetime]]): Maps keys to dicts of fingerprint->timestamp.
        _queues (Dict[str, deque]): Maps keys to queues of (fingerprint, timestamp) for efficient expiry.
        _lock (Lock): Thread lock to protect the internal state.
    """

    def __init__(self, window_seconds: int = 3600):
        """
        Initialize the deduplication handler.

        Args:
            window_seconds (int): Time window in seconds during which duplicate messages are detected.
        """
        self._window_timedelta = timedelta(seconds=window_seconds)
        self._messages: Dict[str, Dict[str, datetime]] = {}
        self._queues: Dict[str, deque] = {}
        self._lock = Lock()

    def is_duplicate(self, key: str, payload: dict) -> bool:
        """
        Check if a message payload is a duplicate within the time window for the specified key.

        Args:
            key (str): Deduplication scope identifier (e.g., stream name).
            payload (dict): Message payload to check for duplicates.

        Returns:
            bool: True if the message is a duplicate within the time window; False otherwise.
        """
        with self._lock:
            current_time = datetime.now(timezone.utc)

            # Initialize per-key structures if not exist
            if key not in self._messages:
                self._messages[key] = {}
                self._queues[key] = deque()

            # Remove expired fingerprints for this key
            # Deque (double-ended queue) of tuples, where each tuple is: (fingerprint: str, timestamp: datetime)
            # 0 is fingerprint, 1 is datetime
            while self._queues[key] and (current_time - self._queues[key][0][1]) >= self._window_timedelta:
                fp, ts = self._queues[key].popleft()
                if self._messages[key].get(fp) == ts:
                    del self._messages[key][fp]

            fingerprint = self._create_fingerprint(payload)

            if fingerprint in self._messages[key]:
                return True

            # Store the new message fingerprint with timestamp
            self._messages[key][fingerprint] = current_time
            self._queues[key].append((fingerprint, current_time))
            return False

    @staticmethod
    def _create_fingerprint(payload: dict) -> str:
        """
        Create a deterministic SHA-256 fingerprint of the given payload.

        Args:
            payload (dict): The message payload to fingerprint.

        Returns:
            str: SHA-256 hexadecimal hash string representing the payload.
        """
        content = json.dumps(payload, sort_keys=True)
        return hashlib.sha256(content.encode()).hexdigest()