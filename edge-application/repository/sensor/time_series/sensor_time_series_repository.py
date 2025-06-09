#!/usr/bin/env python3
# -----------------------------------------------------------------------------
# Filename: sensor_time_series_repository.py
# Author: Rajaram Lakshmanan
# Description: Repository for storing and retrieving sensor time_series in InfluxDB.
# License: MIT (see LICENSE)
# -----------------------------------------------------------------------------

import logging
import threading
import time
from datetime import datetime
from queue import Queue, Full, Empty
from typing import Dict, List, Optional, Any

from influxdb_client import Point, WritePrecision
from influxdb_client.client.write_api import ASYNCHRONOUS

from event_bus.models.sensor.sensor_data_event import SensorDataEvent
from event_bus.models.sensor.sensor_metadata_event import SensorMetadataEvent
from event_bus.redis_stream_bus.redis_stream_bus import RedisStreamBus
from event_bus.stream_name import StreamName

# Import our custom modules
from repository.sensor.time_series.token_manager import TokenManager
from repository.sensor.time_series.influx_client_factory import InfluxClientFactory

logger = logging.getLogger("SensorTimeSeriesRepository")


class SensorTimeSeriesRepository:
    """
    Repository for storing and retrieving sensor time_series in InfluxDB.
    Optimized for high-concurrency environments with multiple sensors
    writing time_series simultaneously.

    This class provides methods for storing sensor time_series in InfluxDB and
    querying time_series by various parameters. It uses token-based authentication
    with secure token storage.
    """

    def __init__(self,
                 event_bus: RedisStreamBus,
                 url: str = 'http://localhost:8086',
                 token: Optional[str] = None,
                 org: str = 'health_monitoring',
                 bucket: str = 'sensor_data',
                 token_file: str = 'config/influx_token.enc',
                 key_file: str = 'config/influx_token.key',
                 write_buffer_size: int = 100000,
                 batch_size: int = 1000,
                 batch_interval_ms: int = 5000,
                 max_retries: int = 5):
        """
        Initialize the Sensor Data Repository.

        Args:
            event_bus: The event bus for subscribing to events
            url (str): The URL of the InfluxDB server
            token (str, optional): The API token for InfluxDB (only needed for first-time setup)
            org (str): The organization to use in InfluxDB
            bucket (str): The bucket to store time_series in
            token_file (str): Path to store the encrypted token
            key_file (str): Path to the encryption key file
            write_buffer_size (int): Max size of the write buffer (for batch processing)
            batch_size (int): Number of points to include in each batch write
            batch_interval_ms (int): Maximum time (ms) to wait before flushing a batch
            max_retries (int): Maximum number of retries for failed writes
        """
        self.event_bus = event_bus
        self.url = url
        self.org = org
        self.bucket = bucket

        # Initialize token manager
        self.token_manager = TokenManager(token_file, key_file)

        # Set up token access
        if token:
            # Direct token provided - use it and save for future use
            self.token = token
            self.token_manager.save_token(token)
        else:
            # Try to load the token from the file
            loaded_token = self.token_manager.load_token()
            if loaded_token:
                self.token = loaded_token
                logger.info("Using token loaded from encrypted file")
            else:
                # No token provided or loaded - raise error
                raise ValueError("No token provided or found in token file. "
                                 "Please run setup_influxdb.py first or provide a token directly.")

        # Initialize InfluxDB client factory
        self.influx_client_factory = InfluxClientFactory(url, self.token, org)

        # Create InfluxDB client
        self.client = self.influx_client_factory.create_influx_client()

        # Ensure bucket exists
        self.influx_client_factory.ensure_bucket_exists(bucket)

        # Create the asynchronous write API with optimized batching
        self.write_api = self.client.write_api(
            write_options=ASYNCHRONOUS,
            batch_size=batch_size,  # Points per batch
            flush_interval=batch_interval_ms,  # Milliseconds
            jitter_interval=2000,  # Add jitter to avoid thundering herd
            retry_interval=5000,  # 5 seconds between retries
            max_retries=max_retries,  # Maximum number of retries
            max_retry_delay=30000,  # Max 30 seconds between retries
            exponential_base=2  # Exponential backoff for retries
        )

        # Create the query API
        self.query_api = self.client.query_api()

        # Create a fallback buffer for cases when the write API is overloaded
        # This adds an extra layer of resilience
        self.fallback_buffer = Queue(maxsize=write_buffer_size)

        # Set up the fallback processor thread
        self.fallback_processor_running = True
        self.fallback_processor = threading.Thread(
            target=self._process_fallback_buffer,
            daemon=True,
            name="InfluxDB-Fallback-Processor"
        )
        self.fallback_processor.start()

        # Get the list of registered sensors to track their time_series streams
        self._registered_sensors = set()
        logger.info(f"SensorTimeSeriesRepository initialized with bucket {bucket} in high-concurrency mode")

    def subscribe_to_events(self) -> None:
        """Subscribe to relevant event streams."""
        # Define consumer group name for the web server
        logger.debug("Subscribing to events")

        try:
            # Subscribe to the sensor metadata stream to track new sensors
            self.event_bus.subscribe(
                StreamName.SENSOR_METADATA_CREATED.value,
                "time_series_repository",
                lambda metadata_event: self._handle_sensor_metadata_event(metadata_event)
            )
        except Exception as e:
            logger.error(f"Error subscribing to events: {e}", exc_info=True)

    def _handle_sensor_metadata_event(self, event: SensorMetadataEvent) -> None:
        """
        Handle sensor metadata events to register for new sensors' time_series streams.
        
        Args:
            event (SensorMetadataEvent): The sensor metadata event
        """
        try:
            sensor_id = event.sensor_id
            
            # Skip if we've already registered for this sensor's time_series
            if sensor_id in self._registered_sensors:
                return
                
            # Create the time_series stream name for this sensor
            data_stream_name = StreamName.get_sensor_stream_name(
                StreamName.SENSOR_DATA_PREFIX.value, 
                sensor_id
            )

            # Subscribe to the sensor time_series stream
            self.event_bus.subscribe(
                data_stream_name,
                "time_series_repository", 
                lambda data_event: self._handle_sensor_data_event(data_event)
            )

            # Add to our set of registered sensors
            self._registered_sensors.add(sensor_id)
            
            logger.info(f"Registered for time_series stream from sensor {sensor_id}")
            
        except Exception as e:
            logger.error(f"Error handling sensor metadata event: {e}")

    def _handle_sensor_data_event(self, event: SensorDataEvent) -> None:
        """
        Handle sensor time_series events by storing the time_series in InfluxDB.
        
        Args:
            event (SensorDataEvent): The sensor time_series event
        """
        try:
            sensor_id = event.sensor_id
            sensor_type = event.sensor_type
            sensor_name = event.sensor_name
            patient_id = event.patient_id
            data = event.data
            
            # Store in InfluxDB
            # Create a point for the measurement
            point = Point(sensor_type)
            
            # Add tags
            point.tag("sensor_id", sensor_id)
            point.tag("sensor_name", sensor_name)
            point.tag("patient_id", patient_id)
            
            # Extract timestamp and adjust if needed
            timestamp = event.timestamp.timestamp() * 1_000_000_000  # Convert to nanoseconds
            point.time(timestamp, WritePrecision.NS)
            
            # Add all time_series fields as measurement fields
            for field_name, field_value in data.items():
                if field_value is not None:
                    # Handle different time_series types
                    if isinstance(field_value, (int, float, bool, str)):
                        point.field(field_name, field_value)
                    else:
                        # Convert other types to string
                        point.field(field_name, str(field_value))
            
            # Write the point to InfluxDB
            try:
                self.write_api.write(bucket=self.bucket, record=point)
                logger.debug(f"Stored time_series point for sensor {sensor_id}, type: {sensor_type}")
            except Exception as e:
                logger.warning(f"Error writing to InfluxDB, using fallback buffer: {e}")
                
                # Try to use the fallback buffer
                try:
                    self.fallback_buffer.put(point, block=False)
                    logger.info(f"Added point for sensor {sensor_id} to fallback buffer")
                except Full:
                    logger.error(f"Fallback buffer full, dropping time_series point for sensor {sensor_id}")
                    
        except Exception as e:
            logger.error(f"Error handling sensor time_series event: {e}")

    def _process_fallback_buffer(self) -> None:
        """
        Process points from the fallback buffer.
        This runs in a separate thread and handles retry logic.
        """
        retry_interval = 5  # seconds
        max_batch_size = 1000

        while self.fallback_processor_running:
            try:
                # Get the number of items in the queue
                queue_size = self.fallback_buffer.qsize()
                if queue_size == 0:
                    # Sleep if the queue is empty
                    time.sleep(1.0)
                    continue

                # Process a batch from the fallback buffer
                batch = []
                batch_size = min(queue_size, max_batch_size)

                for _ in range(batch_size):
                    try:
                        point = self.fallback_buffer.get(block=False)
                        batch.append(point)
                        self.fallback_buffer.task_done()
                    except Empty:
                        break

                if batch:
                    # Try to write the batch
                    try:
                        logger.info(f"Attempting to write {len(batch)} points from fallback buffer")
                        self.write_api.write(bucket=self.bucket, record=batch)

                        logger.info(f"Successfully wrote {len(batch)} points from fallback buffer")
                    except Exception as e:
                        logger.error(f"Error writing points from fallback buffer: {e}")

                        # Put points back in the queue for retry
                        for point in batch:
                            try:
                                self.fallback_buffer.put(point, block=False)
                            except Full:
                                logger.error("Fallback buffer full, dropping point")

                        # Wait before retry
                        time.sleep(retry_interval)

            except Exception as e:
                logger.error(f"Error in fallback buffer processor: {e}")
                time.sleep(retry_interval)

    def store_sensor_data(self, sensor_type: str, sensor_name: str, sensor_id: str,
                          timestamp: int, values: Dict[str, Any]) -> bool:
        """
        Store sensor time_series in InfluxDB using an optimized approach for high concurrency.

        This method efficiently processes readings into InfluxDB points and writes them
        using the asynchronous write API.

        Args:
            sensor_type: Type of the sensor
            sensor_name: Human-readable name of the sensor
            sensor_id: Unique identifier for the sensor
            timestamp: Unix timestamp in nanoseconds (8-byte integer)
            values: Dictionary of field names and values to store

        Returns:
            bool: True if processing was successful (note: actual writing happens asynchronously)
        """
        try:
            # Validate inputs - minimal validation for performance
            if not sensor_type or not sensor_name or not sensor_id:
                logger.error(f"Missing required parameter: Sensor Type={sensor_type}, "
                             f"Sensor Name={sensor_name}, Sensor ID={sensor_id}")
                return False

            if not timestamp or not values or not isinstance(values, dict):
                logger.warning(f"No valid time_series to store for {sensor_name}")
                return False

            # Create a single point with multiple fields
            point = Point(sensor_type)
            point.tag("sensor_name", sensor_name)
            point.tag("sensor_id", sensor_id)
            point.time(timestamp, WritePrecision.NS)

            # Add all non-None values as fields
            has_fields = False
            for field_name, field_value in values.items():
                if field_value is not None:
                    point.field(field_name, field_value)
                    has_fields = True

            # Check if we have any fields to write
            if not has_fields:
                logger.warning(f"No valid fields to store for {sensor_name}")
                return False

            try:
                # Write the point to InfluxDB
                self.write_api.write(bucket=self.bucket, record=point)
                logger.debug(f"Queued point with {len([k for k, v in values.items() if v is not None])} "
                             f"fields for {sensor_type} from {sensor_name} (ID: {sensor_id})")
                return True
            except Exception as e:
                logger.warning(f"Error queueing points to write API, using fallback buffer: {e}")

                # Try to use the fallback buffer for the single point
                try:
                    self.fallback_buffer.put(point, block=False)
                    logger.info(f"Added point for {sensor_name} to fallback buffer")
                    return True
                except Full:
                    logger.error("Fallback buffer full, dropping point")
                    return False
        except Exception as e:
            logger.error(f"Error processing sensor time_series: {e}")
            return False

    def query_sensor_data(self, sensor_type: str, start_time: datetime,
                          end_time: Optional[datetime] = None,
                          sensor_name: str = None,
                          sensor_id: str = None) -> List[Dict[str, Any]]:
        """
        Query sensor time_series from InfluxDB.

        Args:
            sensor_type (str): The type of sensor
            start_time (datetime): The start time of the query
            end_time (datetime, optional): The end time of the query (default = now)
            sensor_name (str): The sensor name to filter by
            sensor_id (str): The sensor ID to filter by

        Returns:
            list: A list of readings
        """
        try:
            # Validate inputs
            if not isinstance(sensor_type, str) or not sensor_type:
                raise ValueError(f"Invalid sensor_type: {sensor_type}")

            if not isinstance(start_time, datetime):
                raise ValueError(f"start_time must be a datetime object, got {type(start_time)}")

            if end_time is not None and not isinstance(end_time, datetime):
                raise ValueError(f"end_time must be a datetime object, got {type(end_time)}")

            # At least one of sensor_name or sensor_id must be provided
            if not sensor_name and not sensor_id:
                raise ValueError("Either sensor_name or sensor_id must be provided")

            if sensor_name is not None and (not isinstance(sensor_name, str) or not sensor_name):
                raise ValueError(f"Invalid sensor_name: {sensor_name}")

            if sensor_id is not None and (not isinstance(sensor_id, str) or not sensor_id):
                raise ValueError(f"Invalid sensor_id: {sensor_id}")

            # Construct the base Flux query with placeholders
            query = '''
            from(bucket: v.bucket)
                |> range(start: v.start, stop: v.stop)
                |> filter(fn: (r) => r._measurement == v.measurement)
            '''

            # Prepare the parameter's dictionary
            params = {
                "bucket": self.bucket,
                "start": start_time.isoformat(),
                "stop": end_time.isoformat() if end_time else "now()",
                "measurement": sensor_type
            }

            # Add filters for sensor_name and sensor_id conditionally
            if sensor_name:
                query += ' |> filter(fn: (r) => r.sensor_name == v.sensor_name)'
                params["sensor_name"] = sensor_name

            if sensor_id:
                query += ' |> filter(fn: (r) => r.sensor_id == v.sensor_id)'
                params["sensor_id"] = sensor_id

            # Execute the query with parameters
            result = self.query_api.query(query=query, params=params, org=self.org)

            # Process the results
            readings = []
            for table in result:
                for record in table.records:
                    # Extract the timestamp and ensure it's in ISO format with UTC timezone
                    timestamp = record.get_time().strftime('%Y-%m-%dT%H:%M:%S.%fZ')

                    # Extract field and value
                    field = record.get_field()
                    value = record.get_value()

                    # Get sensor name and id from record
                    sensor_name_from_record = record.values.get('sensor_name', sensor_name)
                    sensor_id_from_record = record.values.get('sensor_id', sensor_id)

                    # Check if we already have a reading for this timestamp, sensor name and id
                    existing_reading = next(
                        (r for r in readings if
                         r['timestamp'] == timestamp and
                         r['sensor_name'] == sensor_name_from_record and
                         r['sensor_id'] == sensor_id_from_record),
                        None
                    )

                    if existing_reading:
                        # Add this field to an existing reading
                        existing_reading['values'][field] = value
                    else:
                        # Create a new reading
                        reading = {
                            'timestamp': timestamp,
                            'values': {field: value},
                            'sensor_name': sensor_name_from_record,
                            'sensor_id': sensor_id_from_record
                        }
                        readings.append(reading)

            logger.info(f"Retrieved {len(readings)} readings for {sensor_type}")
            return readings

        except Exception as e:
            logger.error(f"Error querying sensor time_series: {e}")
            return []

    def close(self) -> None:
        """
        Clean up resources and connections.
        Ensures all pending writes are processed before shutdown.
        """
        logger.info("Closing SensorTimeSeriesRepository...")

        # Stop the fallback processor
        if hasattr(self, 'fallback_processor') and self.fallback_processor.is_alive():
            logger.info("Stopping fallback processor thread...")
            self.fallback_processor_running = False
            self.fallback_processor.join(timeout=10.0)
            if self.fallback_processor.is_alive():
                logger.warning("Fallback processor thread did not terminate cleanly")
            else:
                logger.info("Fallback processor thread stopped")

        # Flush and close the write API
        if hasattr(self, 'write_api'):
            try:
                logger.info("Flushing remaining writes...")
                # The close() method on write_api will flush any pending writes
                self.write_api.close()
                logger.info("Write API closed successfully")
            except Exception as e:
                logger.error(f"Error closing write API: {e}")

        # Close the InfluxDB client
        if hasattr(self, 'influx_client_factory'):
            try:
                self.influx_client_factory.close()
                logger.info("InfluxDB client closed")
            except Exception as e:
                logger.error(f"Error closing InfluxDB client: {e}")

        logger.info("SensorTimeSeriesRepository closed successfully")
