#!/usr/bin/env python3
# -----------------------------------------------------------------------------
# Filename: web_server.py
# Author: Rajaram Lakshmanan
# Description: Web server for Remote Patient Monitoring System.
# License: MIT (see LICENSE)
# -----------------------------------------------------------------------------

import logging
import os
import time
import uuid
from threading import Lock
from typing import Optional

from flask import Flask, render_template, jsonify, request
from flask_socketio import SocketIO

from config.models.health_monitoring_config import HealthMonitorConfig
from event_bus.models.sensor.sensor_metadata_event import SensorMetadataEvent
from event_bus.models.sensor.sensor_trigger_event import SensorTriggerEvent
from event_bus.redis_stream_bus.redis_stream_bus import RedisStreamBus
from event_bus.stream_name import StreamName
from client.ble.ble_client_manager import BleClientManager
from client.i2c.i2c_client_manager import I2CClientManager
from event_bus.models.client.ble_client_event import BleClientEvent
from event_bus.models.client.i2c_client_event import I2CClientEvent
from event_bus.models.sensor.sensor_data_event import SensorDataEvent
from event_bus.models.sensor.sensor_state_event import SensorStateEvent

# Configure logging
logger = logging.getLogger("WebServer")

# Had to force this to be only error logs
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)  # or WARNING to allow some logs

# Get the absolute path to the current file (web_server.py)
current_dir = os.path.dirname(os.path.abspath(__file__))

# Define the template directory as an absolute path
template_dir = os.path.join(current_dir, 'templates')

# Debug logging
print(f"Current directory: {current_dir}")
print(f"Template directory: {template_dir}")
print(f"Template exists: {os.path.exists(os.path.join(template_dir, 'index.html'))}")

# Initialize Flask
app = Flask(__name__, template_folder=template_dir)
app.config['SECRET_KEY'] = 'health-monitoring-secret-key'
socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    async_mode='threading',
    engineio_logger=False,  # Enable detailed logging
    logger=False,
    transports=['polling']  # Try WebSocket first, fall back to polling
)

# Global state
clients_state = {
    "ble": {},
    "i2c": {}
}
sensors_state = {}
lock = Lock()  # Thread safety for accessing state


class WebServer:
    """Web server for Remote Patient Monitoring System."""

    def __init__(self, event_bus: RedisStreamBus, ble_manager: Optional[BleClientManager] = None,
                 i2c_manager: Optional[I2CClientManager] = None):
        """
        Initialize the web server.

        Args:
            event_bus (RedisStreamBus): The event bus for subscribing to events.
            ble_manager (BleClientManager, optional): The BLE client manager.
            i2c_manager (I2CClientManager, optional): The I2C client manager.
        """
        self._event_bus = event_bus
        self._ble_manager = ble_manager
        self._i2c_manager = i2c_manager

        # Thread for event processing
        self._running = False

    @property
    def redis_consumer_group_name(self) -> str:
        """Returns the name of the Consumer group in Redis Stream."""
        return "web_server_consumer"

    def start(self, host: str = "0.0.0.0", port: int = 5000, debug: bool = False) -> None:
        """
        Start the web server.

        Args:
            host (str): Host to bind the server to. Defaults to "0.0.0.0".
            port (int): Port to bind the server to. Defaults to 5000.
            debug (bool): Enable debug mode. Defaults to False.
        """
        # Initialize state from managers
        self._initialize_state()
        self._running = True

        # Add client managers and event bus to Flask app config
        app.config['BLE_MANAGER'] = self._ble_manager
        app.config['I2C_MANAGER'] = self._i2c_manager
        app.config['EVENT_BUS'] = self._event_bus

        # Start the web server
        logger.info(f"Starting web server on {host}:{port}")
        socketio.run(app, host=host, port=port, debug=debug, log_output=True)

    def stop(self) -> None:
        """Stop the web server."""
        self._running = False
        logger.info("Web server stopped")

    def _initialize_state(self) -> None:
        """Initialize state from client managers."""
        global clients_state, sensors_state

        # Initialize BLE clients state
        if self._ble_manager:
            ble_clients = self._ble_manager.get_all_clients()
            with lock:
                for client_id, client in ble_clients.items():
                    clients_state["ble"][client_id] = {
                        "client_id": client_id,
                        "is_connected": client.is_connected,
                        "device_name": client.device_name,
                        "device_address": client.device_address,
                        "device_type": client.device_type,
                        "sensors": client.sensors,
                        "last_update": time.time()
                    }
                    # Initialize sensors for this client
                    for sensor_id in client.sensors:
                        sensors_state[sensor_id] = {
                            "sensor_id": sensor_id,
                            "sensor_type": sensor_id.split("_")[-1],
                            "client_id": client_id,
                            "client_type": "ble",
                            "last_data": None,
                            "is_active": False,
                            "inactive_minutes": 0,
                            "last_update": time.time()
                        }

        # Initialize I2C clients state
        if self._i2c_manager:
            i2c_clients = self._i2c_manager.get_all_clients()
            with lock:
                for client_id, client in i2c_clients.items():
                    clients_state["i2c"][client_id] = {
                        "client_id": client_id,
                        "is_active": client.is_active,
                        "bus_id": client.bus_id,
                        "sensors": client.sensors,
                        "last_update": time.time()
                    }
                    # Initialize sensors for this client
                    for sensor_id in client.sensors:
                        sensors_state[sensor_id] = {
                            "sensor_id": sensor_id,
                            "sensor_type": sensor_id.split("_")[-1],
                            "client_id": client_id,
                            "client_type": "i2c",
                            "last_data": None,
                            "is_active": False,
                            "inactive_minutes": 0,
                            "last_update": time.time()
                        }

    def subscribe_to_events(self, health_monitor_config: HealthMonitorConfig) -> None:
        """Subscribe to relevant event streams."""

        # Subscribe to sensor metadata event, this is application wide and always initialized
        self._event_bus.subscribe(StreamName.SENSOR_METADATA_CREATED.value,
                                  self.redis_consumer_group_name,
                                  lambda event: self._handle_sensor_metadata_event(event))

        # Only if the BLE client manager is enabled
        if health_monitor_config.ble_client_manager.is_enabled:
            self._event_bus.subscribe(StreamName.BLE_CLIENT_CONNECTION_INFO_UPDATED.value,
                                      self.redis_consumer_group_name,
                                      lambda event: self._handle_ble_client_connection_event(event))

            for client in health_monitor_config.ble_client_manager.clients:
                if not client.is_enabled:
                    continue
                for sensor in client.sensors:
                    if not sensor.is_enabled:
                        continue
                    self._subscribe_sensor_streams(sensor.sensor_id)

        # Only if the I2C client manager is enabled
        if health_monitor_config.i2c_client_manager.is_enabled:
            self._event_bus.subscribe(StreamName.I2C_CLIENT_CONNECTION_INFO_UPDATED.value,
                                      self.redis_consumer_group_name,
                                      lambda event: self._handle_i2c_client_connection_event(event))

            for client in health_monitor_config.i2c_client_manager.clients:
                if not client.is_enabled:
                    continue
                for sensor in client.sensors:
                    if not sensor.is_enabled:
                        continue
                    self._subscribe_sensor_streams(sensor.sensor_id)

    def _subscribe_sensor_streams(self, sensor_id: str) -> None:
        """ Subscribe to the sensor time_series and status streams on the event bus.

        Args:
            sensor_id (str): ID of the sensor.
        """
        # Subscribe to the Sensor status stream
        sensor_status_stream_name = StreamName.get_sensor_stream_name(StreamName.SENSOR_STATUS_PREFIX.value,
                                                                      sensor_id)
        self._event_bus.subscribe(sensor_status_stream_name,
                                  self.redis_consumer_group_name,
                                  lambda event: self._handle_sensor_status_event(event))

        # Create the time_series stream name for this sensor
        data_stream_name = StreamName.get_sensor_stream_name(StreamName.SENSOR_DATA_PREFIX.value, sensor_id)

        # Subscribe to the sensor time_series stream
        self._event_bus.subscribe(data_stream_name,
                                  self.redis_consumer_group_name,
                                  lambda data_event: self._handle_sensor_data_event(data_event))


    @staticmethod
    def _handle_ble_client_connection_event(ble_client_event: BleClientEvent) -> None:
        """
        Handle BLE client connection events.

        Args:
            ble_client_event (BleClientEvent): The BLE client connection event.
        """
        logger.debug(f"Received BLE client connection event: {ble_client_event}")

        client_id = ble_client_event.client_id

        if not client_id:
            return

        # Update client state
        with lock:
            if client_id not in clients_state["ble"]:
                clients_state["ble"][client_id] = {}

            clients_state["ble"][client_id].update({
                "client_id": client_id,
                "is_connected": ble_client_event.is_connected,
                "device_name": ble_client_event.target_device_name,
                "device_address": ble_client_event.target_device_mac_address,
                "device_type": ble_client_event.target_device_type,
                "sensors": ble_client_event.sensors,
                "last_update": time.time(),
                "message": ble_client_event.message
            })

        # Emit update to clients
        socketio.emit('client_update', {
            "client_type": "ble",
            "client_id": client_id,
            "state": clients_state["ble"][client_id]
        })

        # Add to recent updates
        socketio.emit('recent_update', {
            "timestamp": time.time(),
            "message": f"BLE Client {client_id} update: {ble_client_event.message}"
        })

    @staticmethod
    def _handle_i2c_client_connection_event(i2c_client_event: I2CClientEvent) -> None:
        """
        Handle I2C client connection events.

        Args:
            i2c_client_event (I2CClientEvent): The I2C client connection event.
        """
        logger.debug(f"Received I2C client connection event: {i2c_client_event}")

        client_id = i2c_client_event.client_id

        if not client_id:
            return

        # Update client state
        with lock:
            if client_id not in clients_state["i2c"]:
                clients_state["i2c"][client_id] = {}

            clients_state["i2c"][client_id].update({
                "client_id": client_id,
                "is_active": i2c_client_event.is_connected,
                "bus_id": i2c_client_event.i2c_bus_id,
                "sensors": i2c_client_event.sensors,
                "last_update": time.time(),
                "message": i2c_client_event.message
            })

        # Emit update to clients
        socketio.emit('client_update', {
            "client_type": "i2c",
            "client_id": client_id,
            "state": clients_state["i2c"][client_id]
        })

        # Add to recent updates
        socketio.emit('recent_update', {
            "timestamp": time.time(),
            "message": f"I2C Client {client_id} update: {i2c_client_event.message}"
        })

    @staticmethod
    def _handle_sensor_data_event(sensor_data_event: SensorDataEvent) -> None:
        """
        Handle sensor time_series events.

        Args:
            sensor_data_event (SensorDataEvent): The sensor time_series event.
        """
        logger.debug(f"Received sensor time_series event: {sensor_data_event}")

        sensor_id = sensor_data_event.sensor_id
        if not sensor_id:
            return

        # Get client registry from the sensor ID
        sensor = sensors_state.get(sensor_id, {})
        client_type = sensor.get("client_type")
        client_id = sensor.get("client_id")
        sensor_type = sensor.get("sensor_type")

        # Fallback to parsing from sensor_id if not found in the state
        if not client_type or not client_id or not sensor_type:
            parts = sensor_id.split("_")
            if len(parts) < 3:
                return
            client_type = parts[0]  # "ble" or "i2c"
            client_id = f"{client_type}_{parts[1]}"
            sensor_type = parts[2]

        # Check if this is a batch update
        data = sensor_data_event.data
        is_batch = data.get('batch', False) if isinstance(data, dict) else False

        # Update sensor state
        with lock:
            if sensor_id not in sensors_state:
                sensors_state[sensor_id] = {}

            if is_batch:
                # For batch time_series, keep the batch structure but also extract the latest value
                if data.get('timestamps') and data.get('values_list'):
                    # Get the last value from the batch for a simple display
                    last_timestamp = data['timestamps'][-1] if data['timestamps'] else None
                    last_values = data['values_list'][-1] if data['values_list'] else None

                    # Create a standard format time_series point for a simple display
                    single_data_point = {
                        'timestamp': last_timestamp,
                        'values': last_values
                    }

                    # Store both the batch time_series and the latest single point
                    sensors_state[sensor_id].update({
                        "sensor_id": sensor_id,
                        "sensor_type": sensor_type,
                        "sensor_name": sensor_data_event.sensor_name,
                        "client_id": client_id,
                        "client_type": client_type,
                        "last_data": single_data_point,  # For compatibility with the existing UI
                        "batch_data": data,  # Store the full batch
                        "is_batch": True,
                        "batch_size": len(data.get('timestamps', [])),
                        "last_update": time.time(),
                        "is_active": True,
                        "inactive_minutes": 0
                    })
            else:
                # Standard single time_series point update
                sensors_state[sensor_id].update({
                    "sensor_id": sensor_id,
                    "sensor_type": sensor_type,
                    "sensor_name": sensor_data_event.sensor_name,
                    "client_id": client_id,
                    "client_type": client_type,
                    "last_data": data,
                    "is_batch": False,
                    "last_update": time.time(),
                    "is_active": True,
                    "inactive_minutes": 0
                })

        # Emit update to clients
        socketio.emit('sensor_data_update', {
            "sensor_id": sensor_id,
            "state": sensors_state[sensor_id]
        })

        # Add to recent updates
        batch_info = f" (batch of {len(data.get('timestamps', []))} readings)" if is_batch else ""
        socketio.emit('recent_update', {
            "timestamp": time.time(),
            "message": f"Sensor {sensor_id} time_series updated{batch_info}"
        })

    @staticmethod
    def _handle_sensor_status_event(sensor_state_event: SensorStateEvent) -> None:
        """
        Handle sensor status events.

        Args:
            sensor_state_event (SensorStateEvent): The sensor status event.
        """
        logger.debug(f"Received sensor status event: {sensor_state_event}")

        sensor_id = sensor_state_event.sensor_id
        if not sensor_id:
            return

        # Update sensor state
        with lock:
            if sensor_id not in sensors_state:
                sensors_state[sensor_id] = {}

            sensors_state[sensor_id].update({
                "is_active": sensor_state_event.is_active,
                "inactive_minutes": sensor_state_event.inactive_minutes,
                "last_status_update": time.time()
            })

        # Emit update to clients
        socketio.emit('sensor_status_update', {
            "sensor_id": sensor_id,
            "state": sensors_state[sensor_id]
        })

        # Add to recent updates
        status_text = "active" if sensor_state_event.is_active else f"inactive for {sensor_state_event.inactive_minutes:.1f} minutes"
        socketio.emit('recent_update', {
            "timestamp": time.time(),
            "message": f"Sensor {sensor_id} status changed: {status_text}"
        })

    @staticmethod
    def _handle_sensor_metadata_event(sensor_metadata_event: SensorMetadataEvent) -> None:
        """
        Handle sensor metadata events.

        Args:
            sensor_metadata_event (SensorMetadataEvent): The sensor metadata event.
        """
        logger.debug(f"Received sensor metadata event: {sensor_metadata_event}")

        sensor_id = sensor_metadata_event.sensor_id
        if not sensor_id:
            return

        # Update sensor state with metadata
        with lock:
            if sensor_id not in sensors_state:
                sensors_state[sensor_id] = {}

            sensors_state[sensor_id].update({
                "sensor_id": sensor_id,
                "sensor_name": sensor_metadata_event.sensor_name,
                "sensor_type": sensor_metadata_event.sensor_type,
                "patient_id": sensor_metadata_event.patient_id,
                "manufacturer": sensor_metadata_event.manufacturer,
                "model": sensor_metadata_event.model,
                "firmware_version": sensor_metadata_event.firmware_version,
                "hardware_version": sensor_metadata_event.hardware_version,
                "description": sensor_metadata_event.description,
                "measurement_units": sensor_metadata_event.measurement_units,
                "location": sensor_metadata_event.location,
                "metadata_received": True
            })

        # Emit update to clients
        socketio.emit('sensor_metadata_update', {
            "sensor_id": sensor_id,
            "state": sensors_state[sensor_id]
        })

        # Add to recent updates
        socketio.emit('recent_update', {
            "timestamp": time.time(),
            "message": f"Sensor {sensor_id} metadata received"
        })


# Flask routes
@app.route('/')
def index():
    """Render the main dashboard page."""
    return render_template('index.html')


@app.route('/api/clients')
def get_clients():
    """API endpoint to get all clients."""
    with lock:
        return jsonify({
            "ble": clients_state["ble"],
            "i2c": clients_state["i2c"]
        })


@app.route('/api/sensors')
def get_sensors():
    """API endpoint to get all sensors."""
    with lock:
        return jsonify(sensors_state)


@app.route('/api/clients/<client_type>/<client_id>')
def get_client(client_type, client_id):
    """API endpoint to get a specific client."""
    with lock:
        if client_type in clients_state and client_id in clients_state[client_type]:
            return jsonify(clients_state[client_type][client_id])
        return jsonify({"error": "Client not found"}), 404


@app.route('/api/sensors/<sensor_id>')
def get_sensor(sensor_id):
    """API endpoint to get a specific sensor."""
    with lock:
        if sensor_id in sensors_state:
            return jsonify(sensors_state[sensor_id])
        return jsonify({"error": "Sensor not found"}), 404


@app.route('/api/sensors/<sensor_id>/trigger', methods=['POST'])
def trigger_sensor_measurement(sensor_id):
    """API endpoint to trigger a measurement for a specific sensor."""
    # Check if the sensor exists
    if sensor_id not in sensors_state:
        return jsonify({"success": False, "message": "Sensor not found"}), 404
        
    # Get the sensor type to check if it's triggerable
    sensor = sensors_state[sensor_id]
    sensor_type = sensor.get("sensor_type", "").lower()
    
    # Only certain sensor types support triggering
    if sensor_type not in ["spo2", "ecg"]:
        message = f"Sensor type {sensor_type} does not support triggering"
        socketio.emit('recent_update', {
            "timestamp": time.time(),
            "message": f"Trigger request for sensor {sensor_id}: {message}"
        })
        return jsonify({"success": False, "message": message})

    # Check if we have access to the event bus
    event_bus = app.config.get('EVENT_BUS')
    if not event_bus:
        message = "Event bus not initialized"
        socketio.emit('recent_update', {
            "timestamp": time.time(),
            "message": f"Trigger request for sensor {sensor_id}: {message}"
        })
        return jsonify({"success": False, "message": message})

    # Create and publish a trigger event
    try:
        # Generate the trigger stream name for this sensor
        trigger_stream_name = StreamName.get_sensor_stream_name(StreamName.SENSOR_TRIGGER_PREFIX.value, sensor_id)
        
        # Create the trigger event
        trigger_event = SensorTriggerEvent(
            sensor_id=sensor_id,
            trigger_source="web_ui",
            request_id=str(uuid.uuid4()),
            user_id=request.remote_addr  # Use the IP address or some other identifier
        )
        
        # Publish the event to the event bus
        event_bus.publish(trigger_stream_name, trigger_event)
        
        success = True
        message = f"{sensor_type.upper()} measurement trigger request sent"
        
        # Log the trigger
        logger.info(f"Triggered measurement for sensor {sensor_id} from {request.remote_addr}")
    except Exception as e:
        logger.error(f"Error triggering measurement for sensor {sensor_id}: {e}")
        success = False
        message = f"Error triggering measurement: {str(e)}"
    
    # Add to recent updates
    socketio.emit('recent_update', {
        "timestamp": time.time(),
        "message": f"Trigger request for sensor {sensor_id}: {message}"
    })
    
    return jsonify({"success": success, "message": message})


# Dashboard stats endpoint
@app.route('/api/stats')
def get_stats():
    """API endpoint to get dashboard statistics."""
    with lock:
        # Count clients by type and status
        ble_client_count = len(clients_state["ble"])
        ble_connected_count = sum(1 for c in clients_state["ble"].values() if c.get("is_connected", False))
        ble_disconnected_count = ble_client_count - ble_connected_count

        i2c_client_count = len(clients_state["i2c"])
        i2c_active_count = sum(1 for c in clients_state["i2c"].values() if c.get("is_active", False))
        i2c_inactive_count = i2c_client_count - i2c_active_count

        # Count sensors by type and status
        total_sensor_count = len(sensors_state)
        active_sensor_count = sum(1 for s in sensors_state.values() if s.get("is_active", True))
        inactive_sensor_count = total_sensor_count - active_sensor_count
        ble_sensor_count = sum(1 for s in sensors_state.values() if s.get("client_type") == "ble")
        i2c_sensor_count = sum(1 for s in sensors_state.values() if s.get("client_type") == "i2c")

        return jsonify({
            "clients": {
                "ble": {
                    "total": ble_client_count,
                    "connected": ble_connected_count,
                    "disconnected": ble_disconnected_count
                },
                "i2c": {
                    "total": i2c_client_count,
                    "active": i2c_active_count,
                    "inactive": i2c_inactive_count
                }
            },
            "sensors": {
                "total": total_sensor_count,
                "active": active_sensor_count,
                "inactive": inactive_sensor_count,
                "ble": ble_sensor_count,
                "i2c": i2c_sensor_count
            }
        })
