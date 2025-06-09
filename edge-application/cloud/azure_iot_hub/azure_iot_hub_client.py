#!/usr/bin/env python3
# -----------------------------------------------------------------------------
# Filename: azure_iot_hub_client.py
# Author: Rajaram Lakshmanan
# Description:  Helper class for Azure IoT Hub communication using MQTT protocol
# with X.509 authentication.
# License: MIT (see LICENSE)
# -----------------------------------------------------------------------------

import json
import logging
import os
import threading
from typing import Dict, Any, Optional

from azure.iot.device import IoTHubDeviceClient, X509
from azure.iot.device import Message, MethodResponse

logger = logging.getLogger("AzureIoTHubClient")
logging.getLogger("azure.iot.device").setLevel(logging.WARNING)

class AzureIoTHubClient:
    """
    Client for Azure IoT Hub communication using MQTT protocol with X.509 authentication.
    Handles device-to-cloud messaging for sensor data and cloud-to-device
    commands for triggering measurements.
    """
    
    def __init__(self, 
                 host_name: str, 
                 device_id: str, 
                 x509_cert_file: str, 
                 x509_key_file: str,
                 connection_timeout: int,
                 retry_count: int):
        """
        Initialize the Azure IoT Hub client with X.509 authentication.
        
        Args:
            host_name (str): Azure IoT Hub hostname (e.g., "your-hub.azure-devices.net")
            device_id (str): Device identifier
            x509_cert_file (str): Path to X.509 certificate file
            x509_key_file (str): Path to X.509 private key file
            connection_timeout: Connection timeout in seconds
            retry_count: Number of connection retries before giving up

        Raises:
            ValueError: If certificate or key files are missing or invalid.
        """
        self._host_name = host_name
        self._device_id = device_id
        self._x509_cert_file = x509_cert_file
        self._x509_key_file = x509_key_file
        self._connection_timeout = connection_timeout
        self._retry_count = retry_count

        if not AzureIoTHubClient._check_cert_and_key(self._x509_cert_file, self._x509_key_file):
           raise ValueError("Missing certificate or key. Cannot initialize Azure IoT Hub client.")

        self._client = None
        self._connected = False
        self._command_handlers = {}
        self._lock = threading.RLock()

        # Handling commands from the cloud to the device
        self._command_handlers = {}
        
        logger.info(f"AzureIoTHubClient initialized for device {self._device_id}")
    
    def start(self) -> bool:
        """
        Connect to Azure IoT Hub using X.509 certificate authentication.
        
        Returns:
            bool: True if connected successfully, False otherwise
        """
        with self._lock:
            if self._connected and self._client:
                logger.warning("Already connected to Azure IoT Hub")
                return True
            
            try:
                logger.debug(f"Connecting to Azure IoT Hub for device {self._device_id}")

                x509 = X509(cert_file=self._x509_cert_file,
                            key_file=self._x509_key_file)
                
                self._client = IoTHubDeviceClient.create_from_x509_certificate(x509=x509,
                                                                               hostname=self._host_name,
                                                                               device_id=self._device_id)
                self._client.connection_timeout = self._connection_timeout
                self._client.retry_total = self._retry_count
                self._client.connect()
                
                # Set up direct method handler
                self._client.on_method_request_received = self._on_method_request_received
                
                self._connected = True
                logger.info(f"Connected to Azure IoT Hub for device {self._device_id}")
                
                # Send device info and online status
                self._send_device_status("online")
                
                return True
                
            except Exception as e:
                logger.debug(f"Error connecting to Azure IoT Hub: {e}")
                self._connected = False
                
                if self._client:
                    try:
                        self._client.shutdown()
                    except Exception as e:
                        logger.debug(f"Error shutting down IoT Hub client: {e}")
                        pass
                    self._client = None
                
                return False
    
    def stop(self) -> bool:
        """
        Disconnect from Azure IoT Hub.
        
        Returns:
            bool: True if disconnected successfully, False otherwise
        """
        with self._lock:
            if not self._connected or not self._client:
                logger.warning("Not connected to Azure IoT Hub")
                self._connected = False
                return True
            
            try:
                logger.info(f"Disconnecting from Azure IoT Hub for device {self._device_id}")
                
                # Send offline status before disconnecting
                self._send_device_status("offline")

                self._client.disconnect()
                self._client.shutdown()
                self._client = None
                self._connected = False
                
                logger.info(f"Disconnected from Azure IoT Hub for device {self._device_id}")
                return True
                
            except Exception as e:
                logger.debug(f"Error disconnecting from Azure IoT Hub: {e}")
                self._client = None
                self._connected = False
                return False

    def send_message(self,
                     data: Dict[str, Any],
                     properties: Optional[Dict[str, str]] = None) -> bool:
        """
        Send a message to Azure IoT Hub.
        
        Args:
            data (dict): The data to send
            properties (dict, optional): Message properties
        
        Returns:
            bool: True if the message was sent successfully, False otherwise
        """
        with self._lock:
            if not self._connected or not self._client:
                logger.error("Not connected to Azure IoT Hub")
                return False
            
            try:
                message = Message(json.dumps(data))
                message.content_type = "application/json"
                message.content_encoding = "utf-8"
                
                # Add custom properties
                if properties:
                    for key, value in properties.items():
                        message.custom_properties[key] = value
                
                self._client.send_message(message)
                logger.debug(f"Sent message to Azure IoT Hub: {data}")
                return True
                
            except Exception as e:
                logger.error(f"Error sending message to Azure IoT Hub: {e}")
                return False

    def send_device_properties(self, properties: Dict[str, Any]) -> bool:
        """
        Send a batch of device properties to Azure IoT Hub as reported properties.
        This updates the device twin.

        Args:
            properties: Dictionary of property names and values to report

        Returns:
            bool: True if the properties were sent successfully, False otherwise
        """
        with self._lock:
            if not self._connected or not self._client:
                logger.error("Not connected to Azure IoT Hub")
                return False

            try:
                self._client.patch_twin_reported_properties(properties)
                logger.info(f"Sent {len(properties)} device properties to Azure IoT Hub")
                return True

            except Exception as e:
                logger.error(f"Error sending device properties to Azure IoT Hub: {e}")
                return False

    def send_device_property(self, property_name: str, property_value: Any) -> bool:
        """
        Send a single device property to Azure IoT Hub as a reported property.
        This is a convenience wrapper around send_device_properties.

        Args:
            property_name: The property name
            property_value: The property value

        Returns:
            bool: True if the property was sent successfully, False otherwise
        """
        return self.send_device_properties({property_name: property_value})

    def is_connected(self) -> bool:
        """
        Check if the client is connected to Azure IoT Hub.

        Returns:
            bool: True if connected, False otherwise
        """
        with self._lock:
            return self._connected and self._client is not None

    def register_method_handler(self, method_name: str, handler_fn):
        """
        Register a handler for a specific direct method.

        Args:
            method_name (str): The method name from Azure IoT Hub.
            handler_fn (callable): Function that takes (method_name, payload) and returns a dict or False on failure.
        """
        with self._lock:
            self._command_handlers[method_name] = handler_fn
            logger.info(f"Registered handler for method: {method_name}")

    def _send_device_status(self, status: str) -> bool:
        """
        Send device status to Azure IoT Hub.

        Args:
            status (str): Device status ("online" or "offline")

        Returns:
            bool: True if the status was sent successfully, False otherwise
        """

        return self.send_device_property("status", status)

    @staticmethod
    def _check_cert_and_key(cert_path, key_path):
        """
        Check if the certificate and key files exist.

        Args:
            cert_path: File path to the certificate file.
            key_path: File path to the key file.

        Returns:
            True if the files exist, False otherwise.
        """
        if not os.path.exists(cert_path):
            print(f"Certificate file not found: {cert_path}")
            return False
        if not os.path.exists(key_path):
            print(f"Key file not found: {key_path}")
            return False
        return True

    def _on_method_request_received(self, method_request) -> None:
        """
        Callback for direct method requests from Azure IoT Hub.

        Args:
            method_request: Azure IoT Hub method request
        """
        try:
            method_name = method_request.name
            payload = method_request.payload
            request_id = method_request.request_id

            logger.info(f"Received direct method call: {method_name}")
            logger.debug(f"Method payload: {payload}")

            # Find handler for the method
            with self._lock:
                logger.info("Message handler")
                handler = self._command_handlers.get(method_name)
                if handler:
                    try:
                        # Since the handler typically publish an event, there is no need to wait for the response
                        handler(method_name, payload)
                    except Exception as e:
                        logger.error(f"Error in method handler for {method_name}: {e}")
                        response_status = 500
                        response_payload = {"success": False, "message": f"Exception in method handler: {str(e)}"}
                else:
                    logger.warning(f"No handler registered for method: {method_name}")
                    response_status = 404
                    response_payload = {"success": False, "message": f"Method {method_name} not implemented"}

                # Send response
                method_response = MethodResponse(request_id, response_status, json.dumps(response_payload))
                self._client.send_method_response(method_response)

        except Exception as e:
            logger.error(f"Error processing method request: {e}")

            try:
                error_response = MethodResponse(
                    method_request.request_id,
                    500,
                    json.dumps({"success": False, "message": f"Internal error: {str(e)}"})
                )
                self._client.send_method_response(error_response)
            except Exception as ex:
                logger.error(f"Error sending error response: {ex}")