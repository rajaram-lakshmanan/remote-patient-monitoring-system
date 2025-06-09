package com.masterproject.healthmonitoring

import java.util.UUID

/**
 * Constants used in BLE GATT connection operations, BLE GATT services, BLE GATT characteristics, and BLE GATT descriptors.
 * Includes standard UUIDs (from Bluetooth standard), where applicable and custom UUIDs for our specific needs.
 */
object BleConstants {
    // Actions used by the GATT server to broadcast events within the application
    const val ACTION_GATT_SERVER_READY = "com.masterproject.healthmonitoring.ACTION_GATT_SERVER_READY"
    const val ACTION_GATT_ADD_SERVICE = "com.masterproject.healthmonitoring.GATT_ADD_SERVICE"
    const val ACTION_GATT_DEVICE_CONNECTED = "com.masterproject.healthmonitoring.DEVICE_CONNECTED"
    const val ACTION_GATT_DEVICE_DISCONNECTED = "com.masterproject.healthmonitoring.DEVICE_DISCONNECTED"
    const val ACTION_GATT_CHARACTERISTIC_READ_REQUEST = "com.masterproject.healthmonitoring.CHARACTERISTIC_READ_REQUEST"
    const val ACTION_GATT_DESCRIPTOR_READ_REQUEST = "com.masterproject.healthmonitoring.DESCRIPTOR_READ_REQUEST"
    const val ACTION_GATT_READ_RESPONSE = "com.masterproject.healthmonitoring.READ_RESPONSE"
    const val ACTION_GATT_CHARACTERISTIC_WRITE_REQUEST = "com.masterproject.healthmonitoring.CHARACTERISTIC_WRITE_REQUEST"
    const val ACTION_GATT_NOTIFY_CHARACTERISTIC_CHANGED = "com.masterproject.healthmonitoring.NOTIFY_CHARACTERISTIC_CHANGED"
    const val ACTION_GATT_DESCRIPTOR_WRITE_REQUEST = "com.masterproject.healthmonitoring.DESCRIPTOR_WRITE_REQUEST"

    // Intents used for Broadcast between the services
    const val INTENT_SERVICE = "service"
    const val INTENT_CHARACTERISTIC_UUID = "characteristic_uuid"
    const val INTENT_DESCRIPTOR_UUID = "descriptor_uuid"
    const val INTENT_DEVICE_ADDRESS = "device_address"
    const val INTENT_REQUEST_ID = "request_id"
    const val INTENT_STATUS = "status"
    const val INTENT_VALUE = "value"
    const val INTENT_OFFSET = "offset"
    const val INTENT_CONFIRM = "confirm"

    // CCCD UUID (Client Characteristic Configuration Descriptor) Used to enable/disable notifications or indications
    val CCCD_UUID : UUID = UUID.fromString("00002902-0000-1000-8000-00805f9b34fb")

    // UUID for the BLE GATT Service, Characteristic, and Descriptor for different Services in the BLE GATT Profile
    object HeartRateService {
        // UUID for Heartrate Bluetooth Low Energy (BLE) service
        val SERVICE_UUID : UUID = UUID.fromString("0000180d-0000-1000-8000-00805f9b34fb")

        // UUID for Heart rate measurement characteristic - Includes the value and the status of the measurement
        val DATA_UUID : UUID = UUID.fromString("00002a37-0000-1000-8000-00805f9b34fb")
    }

    object TemperatureService {
        // UUID for Temperature Bluetooth Low Energy (BLE) service
        val SERVICE_UUID : UUID = UUID.fromString("00001809-0000-1000-8000-00805f9b34fb")

        // UUID to represent the temperature data including object (skin), ambient temperature values, and the measurement
        // status information
        val TEMPERATURE_DATA_UUID : UUID = UUID.fromString("00002a1c-0000-1000-8000-00805f9b34fb")
    }

    object AccelerometerService {
        // UUID for the Accelerometer Bluetooth Low Energy (BLE) service
        val SERVICE_UUID : UUID = UUID.fromString("8899b3a3-38fb-42f5-9955-59c52b5d53f2")

        // UUID to represent the characteristic of the Accelerometer's X, Y, and Z axes values
        val ACCELEROMETER_DATA_UUID : UUID = UUID.fromString("8899b3a4-38fb-42f5-9955-59c52b5d53f2")
    }

    object PpgService {
        // UUID for the PPG Bluetooth Low Energy (BLE) service
        val SERVICE_UUID : UUID = UUID.fromString("8899b3a7-38fb-42f5-9955-59c52b5d53f2")

        // UUID to represent the characteristic of the PPG Green measurement and the status
        val PPG_GREEN_DATA_UUID : UUID = UUID.fromString("8899b3a8-38fb-42f5-9955-59c52b5d53f2")

        // UUID to represent the characteristic of the PPG IR measurement and the status
        val PPG_IR_DATA_UUID : UUID = UUID.fromString("8899b3aa-38fb-42f5-9955-59c52b5d53f2")

        // UUID to represent the characteristic of the PPG Red measurement and the status
        val PPG_RED_DATA_UUID : UUID = UUID.fromString("8899b3ac-38fb-42f5-9955-59c52b5d53f2")
    }

    object Spo2Service {
        // UUID for Spo2 Bluetooth Low Energy (BLE) service
        val SERVICE_UUID : UUID = UUID.fromString("00001822-0000-1000-8000-00805f9b34fb")

        // UUID to represent the characteristic of the SpO2 measurement and the status information
        val SPO2_DATA_UUID : UUID = UUID.fromString("00002a5e-0000-1000-8000-00805f9b34fb")

        // UUID for the characteristic which is used to trigger the on-demand SpO2 measurement
        val TRIGGER_UUID : UUID = UUID.fromString("00002a5f-0000-1000-8000-00805f9b34fb")
    }

    object EcgService {
        // UUID for ECG Bluetooth Low Energy (BLE) service
        val SERVICE_UUID : UUID = UUID.fromString("8899b3b0-38fb-42f5-9955-59c52b5d53f2")

        // UUID to represent the characteristic of the ECG measurement (average values of ECG, sequence number) and the
        // status information
        val ECG_DATA_UUID : UUID = UUID.fromString("8899b3b1-38fb-42f5-9955-59c52b5d53f2")

        // UUID for the characteristic which is used to trigger the on-demand ECG measurement
        val TRIGGER_UUID : UUID = UUID.fromString("8899b3b3-38fb-42f5-9955-59c52b5d53f2")
    }
}