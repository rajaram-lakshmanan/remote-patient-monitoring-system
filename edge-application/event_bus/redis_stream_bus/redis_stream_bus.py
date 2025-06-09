#!/usr/bin/env python3
# -----------------------------------------------------------------------------
# Filename: redis_stream_bus.py
# Author: Rajaram Lakshmanan
# Description: Secure Event Bus based on Redis Streams with improved resilience,
# backpressure control, and retention management.
# License: MIT (see LICENSE)
# -----------------------------------------------------------------------------

import logging
import threading
import time
import uuid
import json
from datetime import datetime
from typing import Dict, Type, Callable, List, Optional, Generator, Tuple
from threading import Lock, Event
from contextlib import contextmanager

import redis
import redis.connection
from redis.exceptions import ConnectionError, RedisError
from pydantic import BaseModel, ValidationError

from event_bus.redis_stream_bus.circuit_breaker import CircuitBreaker
from event_bus.redis_stream_bus.consumer_metrics import ConsumerMetrics
from event_bus.redis_stream_bus.message_duplicate_handler import MessageDuplicationHandler

logger = logging.getLogger("RedisStreamBus")

class RedisStreamBus:
    """
    Production-ready Redis Stream Event Bus with enhanced reliability features:
    - Circuit breaker pattern for connection handling
    - Comprehensive metrics and monitoring
    - Graceful shutdown support
    - Message deduplication
    - Consumer group lag monitoring
    - Batch processing with timeout
    - Enhanced error handling and recovery
    """
    def __init__(self,
                 host: str,
                 port: int,
                 db: int = 0,
                 retry_delay: float = 2.0,
                 max_concurrent_handlers: int = 40,
                 message_rate_limit: int = 1000,
                 max_consumer_threads: int = 80,
                 batch_size: int = 10,
                 batch_timeout: float = 1.0,
                 deduplication_window: int = 3600,
                 shutdown_timeout: float = 30.0,
                 health_check_interval: float = 30.0):

        self._host = host
        self._port = port
        self._db = db
        self._retry_delay = retry_delay

        self._batch_size = batch_size
        self._batch_timeout = batch_timeout
        self._shutdown_timeout = shutdown_timeout
        self._health_check_interval = health_check_interval

        pool = redis.ConnectionPool(host=host,
                                    port=port,
                                    db=db,
                                    decode_responses=True,
                                    connection_class=redis.connection.Connection, # Force synchronous connections
                                    max_connections=max_concurrent_handlers * 2,
                                    health_check_interval=30,
                                    retry_on_timeout=True)

        # Initialize Redis client with the synchronous pool
        self._redis = redis.Redis(connection_pool=pool,
                                  socket_timeout=5.0,
                                  socket_connect_timeout=5.0,
                                  retry_on_timeout=True)

        # Infrastructure components
        self._circuit_breaker = CircuitBreaker()
        self._message_duplicate_handler = MessageDuplicationHandler(deduplication_window)
        self._metrics = ConsumerMetrics()

        # Initialize connection, all components must be initialized first before checking the connection
        if not self._connect_with_retry():
            raise RuntimeError("Failed to establish initial connection with the Redis server")

        # Thread management
        self._consumer_threads: Dict[Tuple[str, str], threading.Thread] = {}
        self._consumer_running: Dict[Tuple[str, str], bool] = {}
        self._maintenance_thread: Optional[threading.Thread] = None
        self._health_check_thread: Optional[threading.Thread] = None

        # Synchronization primitives
        self._thread_lock = Lock()
        self._shutdown_event = Event()
        self._handler_semaphore = threading.BoundedSemaphore(max_concurrent_handlers)
        self._consumer_thread_semaphore = threading.BoundedSemaphore(max_consumer_threads)

        # Message rate limiting
        self._rate_limit = message_rate_limit
        self._rate_window: List[float] = []
        self._rate_window_lock = Lock()

        # Stream and handler registration
        self._stream_models: Dict[str, Type[BaseModel]] = {}
        self._handlers: Dict[Tuple[str, str], List[Callable[[BaseModel], None]]] = {}
        self._consumer_ids: Dict[Tuple[str, str], str] = {}
        self._running = False

    # === Public API Functions ===

    @property
    def shutdown_active(self) -> bool:
        """Returns the flag to indicate whether the shutdown is in progress."""
        return self._shutdown_event is not None and self._shutdown_event.is_set()

    def initiate_shutdown(self):
        """The main application has initiated the shutdown. Events or streams will no longer
         be accepted to publish."""
        if self._shutdown_event and self._shutdown_event.is_set():
            self._shutdown_event.set()

    def start(self) -> None:
        """Start the Redis Stream Bus and its consumers"""
        if self._running:
            logger.warning("RedisStreamBus is already running")
            return

        logger.info("Starting RedisStreamBus")
        self._running = True
        self._shutdown_event.clear()

        # Start maintenance threads if not running
        if not self._maintenance_thread or not self._maintenance_thread.is_alive():
            self._start_maintenance_threads()

        # Start consumers for all registered handlers
        started_count = 0
        for stream_name, consumer_group_name in self._handlers.keys():
            consumer_key = (stream_name, consumer_group_name)
            if not self._consumer_running.get(consumer_key, False):
                self._start_consumer(stream_name, consumer_group_name)
                started_count += 1

        logger.info(f"RedisStreamBus started successfully ({started_count} consumers started)")

    def stop(self) -> None:
        """Gracefully stop all consumers and cleanup"""
        logger.info("Initiating graceful shutdown")
        self.initiate_shutdown()

        shutdown_start = time.time()

        # Stop all consumers
        with self._thread_lock:
            for consumer_key in list(self._consumer_running.keys()):
                self._consumer_running[consumer_key] = False

        # Wait for consumers to finish
        remaining_time = self._shutdown_timeout
        for thread in self._consumer_threads.values():
            thread_timeout = min(remaining_time, 5.0)  # Max 5 seconds per thread
            if thread_timeout <= 0:
                break
            thread.join(timeout=thread_timeout)
            remaining_time = self._shutdown_timeout - (time.time() - shutdown_start)

        # Cleanup Redis connection
        try:
            self._redis.close()
        except Exception as e:
            logger.error(f"Error during Redis cleanup: {e}")

        logger.info("Shutdown complete")

    def register_stream(self,
                        stream_name: str,
                        model_cls: Type[BaseModel]) -> None:
        """
        Register a stream with its corresponding Pydantic model.

        Args:
            stream_name: Name of the stream
            model_cls: Pydantic model class for message validation
        """
        if not issubclass(model_cls, BaseModel):
            raise ValueError("Model class must be a Pydantic BaseModel")

        self._stream_models[stream_name] = model_cls
        logger.debug(f"Registered stream: {stream_name} -> {model_cls.__name__}")

    def subscribe(self,
                  stream_name: str,
                  consumer_group_name: str,
                  handler: Callable[[BaseModel], None]) -> None:
        """
        Subscribe to a stream with a message handler.

        Args:
            stream_name: Name of the stream
            consumer_group_name: Consumer group name
            handler: Callback function to process messages
        """
        if stream_name not in self._stream_models:
            raise ValueError(f"Stream {stream_name} not registered")

        if not callable(handler):
            raise ValueError("Handler must be callable")

        try:
            with self._redis_error_handler(self._circuit_breaker, self._metrics):
                # Create the stream if it doesn't exist
                self._redis.xgroup_create(stream_name,
                                          consumer_group_name,
                                          mkstream=True,
                                          id="0")
        except redis.exceptions.ResponseError as e:
            if "BUSYGROUP" not in str(e):
                logger.warning(f"Consumer group {consumer_group_name} already exists for {stream_name}")
                raise

        # Create a consistent key (tuple) format for the handlers dictionary
        key = (stream_name, consumer_group_name)
        if key not in self._handlers:
            self._handlers[key] = []
        self._handlers[key].append(handler)

        logger.debug(f"Subscribed handler to {stream_name} with consumer group {consumer_group_name}")

    def publish(self,
                stream_name: str,
                payload: BaseModel,
                maxlen: Optional[int] = None,
                approximate: bool = True,
                check_for_duplicates: bool = False) -> Optional[str]:
        """
        Publish the message to Redis stream with deduplication and backpressure control.

        Args:
            stream_name: Name of the stream
            payload: Pydantic model instance
            maxlen: Optional maximum length for the stream
            approximate: Use approximate (~) trimming for better performance
            check_for_duplicates: Flag to indicate whether to check for duplicate messages being published

        Returns:
            Optional[str]: Message ID if successful, None otherwise
        """
        if self._shutdown_event.is_set():
            logging.debug(f"Skipping publishing to {stream_name} during shutdown")
            return None

        if stream_name not in self._stream_models:
            raise ValueError(f"Stream {stream_name} not registered")

        if not isinstance(payload, self._stream_models[stream_name]):
            raise ValueError(f"Invalid payload type for stream {stream_name}")

        try:
            message_data = self._prepare_message(payload)
            if check_for_duplicates:
                if self._message_duplicate_handler.is_duplicate(stream_name, message_data):
                    logger.debug(f"Duplicate message detected for {stream_name}")
                    return None

            with self._redis_error_handler(self._circuit_breaker, self._metrics):
                # Apply backpressure if needed
                self._apply_rate_limiting()

                # Publish message
                if maxlen is not None:
                    message_id = self._redis.xadd(stream_name,
                                                  message_data,
                                                  maxlen=maxlen,
                                                  approximate=approximate)
                else:
                    message_id = self._redis.xadd(stream_name, message_data)

                self._metrics.increment("publish_count")
                logger.debug(f"Published to {stream_name}: {message_id}")
                return message_id

        except Exception as e:
            logger.error(f"Error publishing to {stream_name}: {e}")
            raise

    def get_metrics(self) -> dict:
        """Get current metrics"""
        metrics = self._metrics.get_metrics()
        metrics.update({
            "circuit_breaker_state": self._circuit_breaker.get_state(),
            "active_streams": list(self._stream_models.keys()),
            "active_consumers": len(self._consumer_threads)
        })
        return metrics

    # === Local Functions ===

    @contextmanager
    def _redis_error_handler(self,
                             circuit_breaker: CircuitBreaker,
                             metrics: ConsumerMetrics) -> Generator[None, None, None]:
        """
        Context manager for handling Redis errors with the circuit breaker pattern

        Args:
            circuit_breaker: Circuit breaker instance to track failure(s)
            metrics: Metrics collector for monitoring

        Raises:
            ConnectionError: When Redis connection fails
            RedisError: When Redis operations fail
            Exception: For unexpected errors
        """
        try:
            yield
        except ConnectionError as e:
            metrics.increment("redis_errors")
            circuit_breaker.record_failure()
            metrics.set_error(f"Connection error: {e}")
            raise
        except RedisError as e:
            metrics.increment("redis_errors")
            metrics.set_error(f"Redis error: {e}")
            raise
        except Exception as e:
            metrics.set_error(f"Unexpected error: {e}")
            raise

    def _connect_with_retry(self, max_retries: int = 5) -> bool:
        """
        Attempts to establish a connection to Redis using exponential backoff.

        This method pings the Redis server and retries the connection on failure,
        with each retry delayed using exponential backoff. It also integrates with
        a circuit breaker and metrics tracking system to handle and monitor errors.

        Args:
            max_retries (int): Maximum number of retry attempts. Defaults to 5.

        Returns:
            bool: True if the connection is successfully established within the
                  retry limit, False otherwise.
        """
        retry_count = 0
        backoff = self._retry_delay

        while retry_count < max_retries:
            try:
                with self._redis_error_handler(self._circuit_breaker, self._metrics):
                    if self._redis.ping():
                        self._circuit_breaker.record_success()
                        return True
            except Exception as e:
                retry_count += 1
                logger.warning(f"Connection attempt {retry_count}/{max_retries} failed: {e}")
                time.sleep(backoff)
                backoff *= 2

        logger.error(f"Failed to connect to Redis after {max_retries} attempts")
        return False

    def _start_maintenance_threads(self) -> None:
        """Start maintenance and health check threads"""
        self._maintenance_thread = threading.Thread(target=self._maintenance_routine,
                                                    name="maintenance",
                                                    daemon=True)
        self._maintenance_thread.start()

        self._health_check_thread = threading.Thread(target=self._health_check_routine,
                                                     name="health_check",
                                                     daemon=True)
        self._health_check_thread.start()

    def _maintenance_routine(self) -> None:
        """Periodic maintenance tasks"""
        while not self._shutdown_event.is_set():
            try:
                self._clean_expired_messages()
                self._update_consumer_lag()
                self._check_consumer_health()
            except Exception as e:
                logger.error(f"Error in maintenance routine: {e}")
            finally:
                time.sleep(60)  # Run maintenance every minute

    def _health_check_routine(self) -> None:
        """Periodic health checks"""
        while not self._shutdown_event.is_set():
            try:
                if not self._circuit_breaker.is_closed():
                    logger.warning("Circuit breaker is open, attempting recovery")
                    if self._connect_with_retry(max_retries=1):
                        logger.info("Recovery successful")
                    else:
                        logger.error("Recovery failed")

                # Check Redis connection
                with self._redis_error_handler(self._circuit_breaker, self._metrics):
                    self._redis.ping()
                    self._metrics.record_success()

            except Exception as e:
                logger.error(f"Health check failed: {e}")
            finally:
                time.sleep(self._health_check_interval)

    def _clean_expired_messages(self) -> None:
        """Clean up expired messages from streams"""
        try:
            for stream_name in self._stream_models.keys():
                # Skip if no handlers are registered for this stream
                if not any(k[0] == stream_name for k in self._handlers):
                    continue

                with self._redis_error_handler(self._circuit_breaker, self._metrics):
                    stream_info = self._redis.xinfo_stream(stream_name)

                    # Defensive checks
                    if not stream_info or stream_info.get("length", 0) == 0:
                        continue

                    # Only trim if length exceeds 1000
                    if stream_info["length"] > 1000:
                        self._redis.xtrim(stream_name,
                                          maxlen=1000,
                                          approximate=True)
        except Exception as e:
            logger.error(f"Error cleaning expired messages: {e}")

    def _update_consumer_lag(self) -> None:
        """Update consumer lag metrics for each stream"""
        try:
            for stream_name in self._stream_models.keys():
                # Skip if no handlers are registered for this stream
                if not any(k[0] == stream_name for k in self._handlers):
                    continue

                with self._redis_error_handler(self._circuit_breaker, self._metrics):
                    try:
                        groups = self._redis.xinfo_groups(stream_name)
                    except redis.exceptions.ResponseError as e:
                        if "no such key" in str(e).lower():
                            logger.debug(f"Skipping lag update: stream '{stream_name}' does not exist.")
                            continue
                        raise

                    for group in groups:
                        lag = group.get("pending", 0)
                        self._metrics.update_lag(f"{stream_name}:{group['name']}", lag)
        except Exception as e:
            logger.error(f"Error updating consumer lag: {e}")

    def _check_consumer_health(self) -> None:
        """Check the health of consumer groups and recover if needed"""
        try:
            for stream_name in self._stream_models.keys():
                if not any(k[0] == stream_name for k in self._handlers):
                    continue

                with self._redis_error_handler(self._circuit_breaker, self._metrics):
                    try:
                        groups = self._redis.xinfo_groups(stream_name)
                    except redis.exceptions.ResponseError as e:
                        if "no such key" in str(e).lower():
                            logger.debug(f"Skipping health check: stream '{stream_name}' does not exist.")
                            continue
                        raise

                    for group in groups:
                        if group['consumers'] == 0 and group['pending'] > 0:
                            logger.warning(
                                f"Orphaned messages in group '{group['name']}' of stream '{stream_name}' "
                                f"(pending: {group['pending']}, consumers: {group['consumers']})"
                            )

                            # Get the consumer ID for this group or create a recovery-specific one
                            consumer_key = (stream_name, group['name'])
                            consumer_id = self._consumer_ids.get(consumer_key,
                                                                 f"recovery-{group['name']}-{str(uuid.uuid4())[:8]}")

                            self._recover_pending_messages(stream_name, group['name'], consumer_id)
        except Exception as e:
            logger.error(f"Error checking consumer health: {e}")

    def _recover_pending_messages(self, stream_name: str, group_name: str, consumer_id: str) -> None:
        """Recover pending messages from dead consumers"""
        try:
            with self._redis_error_handler(self._circuit_breaker, self._metrics):
                pending = self._redis.xpending_range(stream_name,
                                                     group_name,
                                                     min='-',
                                                     max='+',
                                                     count=100)

                for message in pending:
                    # Claim the message if it's been idle for too long
                    if message['idle'] > 30000:  # 30 seconds
                        self._redis.xclaim(stream_name,
                                           group_name,
                                           consumer_id,
                                           min_idle_time=30000,
                                           message_ids=[message['message_id']])
        except Exception as e:
            logger.error(f"Error recovering pending messages: {e}")

    @staticmethod
    def _prepare_message(payload: BaseModel) -> dict:
        """
        Prepare the message for Redis storage or publishing by converting non-Redis compatible types.

        Args:
            payload: Payload which contains the data to be stored or published in Redis

        Returns:
            dict: Redis-compatible dictionary
        """

        data = payload.model_dump()
        result = {}

        for key, value in data.items():
            if isinstance(value, datetime):
                result[key] = value.isoformat()
            elif isinstance(value, (list, dict)):
                result[key] = json.dumps(value)
            elif isinstance(value, bool):
                result[key] = int(value)
            elif isinstance(value, (int, float, str)):
                result[key] = value
            else:
                result[key] = str(value)

        return result

    @staticmethod
    def _parse_message(data: dict, model_cls: Type[BaseModel]) -> BaseModel:
        """
        Parses a Redis message dictionary into an instance of the given Pydantic model.

        This method maps raw Redis data to the appropriate types defined in the target
        Pydantic model, including support for common types like datetime, int, float,
        bool, and JSON-encoded strings. Unrecognized or unparseable fields are preserved
        in their original form, and any parsing errors are logged.

        Args:
            data (dict): The raw message data received from Redis.
            model_cls (Type[BaseModel]): The Pydantic model class to parse the data into.

        Returns:
            BaseModel: An instance of `model_cls` populated with the parsed data.
        """
        parsed_data = {}

        for key, value in data.items():
            field_info = model_cls.model_fields.get(key)
            if not field_info:
                continue

            try:
                if field_info.annotation == datetime:
                    parsed_data[key] = datetime.fromisoformat(value)
                elif field_info.annotation == bool:
                    parsed_data[key] = bool(int(value))
                elif field_info.annotation == int:
                    parsed_data[key] = int(value)
                elif field_info.annotation == float:
                    parsed_data[key] = float(value)
                elif isinstance(value, str) and value.startswith(('[', '{')):
                    try:
                        parsed_data[key] = json.loads(value)
                    except json.JSONDecodeError:
                        parsed_data[key] = value
                else:
                    parsed_data[key] = value
            except (ValueError, TypeError) as e:
                logger.warning(f"Error parsing field {key}: {e}")
                parsed_data[key] = value

        return model_cls(**parsed_data)

    def _apply_rate_limiting(self) -> None:
        """Apply rate limiting backpressure"""
        with self._rate_window_lock:
            current_time = time.time()
            # Remove timestamps older than 1 second
            self._rate_window = [t for t in self._rate_window if current_time - t <= 1.0]

            if len(self._rate_window) >= self._rate_limit:
                sleep_time = 1.0 - (current_time - self._rate_window[0])
                if sleep_time > 0:
                    time.sleep(sleep_time)

            self._rate_window.append(current_time)

    def _start_consumer(self, stream_name: str, group_name: str) -> None:
        """Start a consumer thread for the given stream and group"""
        try:
            consumer_key = (stream_name, group_name)  # Use tuple as a key

            with self._thread_lock:
                if (consumer_key in self._consumer_threads and
                        self._consumer_threads[consumer_key].is_alive()):
                    return

                # Generate a unique consumer ID for this thread
                consumer_id = f"consumer-{group_name}-{stream_name}-{str(uuid.uuid4())[:8]}"

                # Store the consumer ID for recovery
                self._consumer_ids[consumer_key] = consumer_id

                thread = threading.Thread(
                    target=self._consume_stream,
                    args=(stream_name, group_name, consumer_id),
                    name=f"consumer_{group_name}_{stream_name}",
                    daemon=True
                )
                self._consumer_threads[consumer_key] = thread
                self._consumer_running[consumer_key] = True
                thread.start()
                logger.debug(f"Started consumer thread for {stream_name} with group {group_name}")
        except Exception as e:
            logger.error(f"Error starting consumer {stream_name}:{group_name}: {e}")

    def _consume_stream(self, stream_name: str, group_name: str, consumer_id: str) -> None:
        """
        The main consumer loop for processing messages from a Redis stream in batches.

        This method continuously reads messages from the specified Redis stream and consumer group,
        processes them in batches, and handles errors, retries, and circuit breaker state.

        Args:
            stream_name (str): The name of the Redis stream to consume from.
            group_name (str): The name of the consumer group to which this consumer belongs.
            consumer_id (str): ID of the consumer.

        Behavior:
            - Uses semaphore to limit concurrent consumer threads.
            - Respects circuit breaker state to pause consumption when necessary.
            - Reads batches of messages with a timeout.
            - Passes batches to the message processing method.
            - Handles exceptions by logging and retrying after a delay.
        """
        consumer_key = (stream_name, group_name)

        while self._consumer_running.get(consumer_key) and not self._shutdown_event.is_set():
            try:
                with self._consumer_thread_semaphore:
                    if not self._circuit_breaker.is_closed():
                        time.sleep(self._retry_delay)
                        continue

                    with self._redis_error_handler(self._circuit_breaker, self._metrics):
                        # Read the batch of messages
                        messages = self._redis.xreadgroup(
                            groupname=group_name,
                            consumername=consumer_id,
                            streams={stream_name: ">"},
                            count=self._batch_size,
                            block=int(self._batch_timeout * 1000)
                        )

                        if not messages or not isinstance(messages, list):
                            continue

                        try:
                            stream_data = messages[0] if messages else None
                            if not stream_data or len(stream_data) < 2:
                                continue

                            stream_messages = stream_data[1]  # Safe access after validation
                            self._metrics.record_batch_size(len(stream_messages))

                            # Process messages in a batch
                            self._process_message_batch(stream_name, stream_messages, group_name)
                        except (IndexError, TypeError) as e:
                            logger.error(f"Error processing message batch structure: {e}")
                            continue


            except Exception as e:
                logger.error(f"Error in consumer {stream_name}: {e}")
                time.sleep(self._retry_delay)

    def _process_message_batch(self,
                               stream_name: str,
                               messages: List[tuple],
                               group_name: str) -> None:
        """
        Processes a batch of messages from the Redis stream with error handling and acknowledgment.

        Args:
            stream_name (str): The Redis stream name from which messages were read.
            messages (List[tuple]): A list of tuples, each containing (message_id, message_data).
            group_name (str): The consumer group name for acknowledgment purposes.

        Behavior:
            - Iterates over messages, parses them into models.
            - Invokes all registered handlers for each message within semaphore.
            - On handler success, marks the message for acknowledgment.
            - On validation failure, logs error and moves the message to a dead letter queue.
            - On other exceptions, logs errors and skips acknowledgment.
            - Acknowledges all successfully processed messages in batch at the end.
        """
        pending_acks = []

        for message_id, data in messages:
            try:
                # Parse message
                model = self._parse_message(data, self._stream_models[stream_name])

                # Process with all handlers
                with self._handler_semaphore:
                    start_time = time.time()
                    for handler in self._handlers[stream_name,group_name]:
                        try:
                            handler(model)
                        except Exception as e:
                            logger.error(f"Handler error for {message_id}: {e}")
                            self._metrics.increment("messages_failed")
                            break
                    else:
                        # All handlers successful
                        pending_acks.append(message_id)
                        self._metrics.increment("messages_processed")
                        self._metrics.set_processing_time(time.time() - start_time)

            except ValidationError as e:
                logger.error(f"Validation error for {message_id}: {e}")
                self._metrics.increment("messages_failed")
                # Move the invalid message to the dead letter queue
                self._move_to_dlq(stream_name, group_name, message_id, data, str(e))
                pending_acks.append(message_id)

            except Exception as e:
                logger.error(f"Processing error for {message_id}: {e}")
                self._metrics.increment("messages_failed")

        # Batch acknowledge, the processed messages
        if pending_acks:
            try:
                with self._redis_error_handler(self._circuit_breaker, self._metrics):
                    self._redis.xack(stream_name, group_name, *pending_acks)
            except Exception as e:
                logger.error(f"Error acknowledging messages: {e}")

    def _move_to_dlq(self,
                     stream_name: str,
                     group_name: str,
                     message_id: str,
                     data: dict,
                     error: str) -> None:
        """
        Move a failed message from a Redis stream consumer group to a dead letter queue (DLQ).

        This method adds metadata about the failure, including the original message ID,
        the error description, and a timestamp, before appending the message to a
        designated DLQ stream named `{stream_name}:{group_name}:dlq`.

        Args:
            stream_name (str): The name of the original Redis stream.
            group_name (str): The consumer group handling the message.
            message_id (str): The ID of the message that failed processing.
            data (dict): The original message data.
            error (str): A string describing the error that caused the failure.
        """
        dlq_name = f"{stream_name}:{group_name}:dlq"
        data['_error'] = error
        data['_original_id'] = message_id
        data['_timestamp'] = datetime.now().isoformat()

        try:
            with self._redis_error_handler(self._circuit_breaker, self._metrics):
                self._redis.xadd(dlq_name, data)
        except Exception as e:
            logger.error(f"Error moving message to DLQ: {e}")