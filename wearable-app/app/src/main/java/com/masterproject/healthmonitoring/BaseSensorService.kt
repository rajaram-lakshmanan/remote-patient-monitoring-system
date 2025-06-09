package com.masterproject.healthmonitoring

import android.Manifest
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.bluetooth.BluetoothGatt
import android.bluetooth.BluetoothGattCharacteristic
import android.bluetooth.BluetoothGattDescriptor
import android.bluetooth.BluetoothGattService
import android.content.pm.PackageManager
import android.util.Log
import androidx.core.content.ContextCompat
import androidx.localbroadcastmanager.content.LocalBroadcastManager
import com.samsung.android.service.health.tracking.HealthTracker
import com.samsung.android.service.health.tracking.data.HealthTrackerType
import java.util.Collections
import java.util.UUID
import java.util.concurrent.ConcurrentHashMap

/**
 * Base abstract class for all sensor service managers.
 */
abstract class BaseSensorService(protected val service: HealthMonitoringService) : SensorService {
    companion object {
        /**
         * Create a Bluetooth GATT primary service with the specified UUID.
         *
         * @param uuid The UUID for the BLE service to be created.
         */
        fun createBluetoothGattService(uuid: UUID): BluetoothGattService {
            return BluetoothGattService(uuid, BluetoothGattService.SERVICE_TYPE_PRIMARY)
        }

        /**
         * Create a Bluetooth GATT characteristic with the specified UUID and read permission with the
         * Client Characteristic Configuration Descriptor added to the characteristic by default.
         *
         * @param uuid The UUID for the BLE characteristic to be created.
         */
        fun createGattReadCharacteristicWithCccd(uuid: UUID): BluetoothGattCharacteristic {
            val bluetoothGattCharacteristic = BluetoothGattCharacteristic(
                uuid,
                BluetoothGattCharacteristic.PROPERTY_READ or BluetoothGattCharacteristic.PROPERTY_NOTIFY,
                BluetoothGattCharacteristic.PERMISSION_READ
            )
            bluetoothGattCharacteristic.addDescriptor(createBluetoothGattDescriptor())
            return bluetoothGattCharacteristic
        }

        /**
         * Create a Bluetooth GATT characteristic with the specified UUID and write permission with the
         * Client Characteristic Configuration Descriptor added to the characteristic by default.
         * Characteristic can be written without a response.
         * @param uuid The UUID for the BLE characteristic to be created.
         */
        fun createGattWriteCharacteristicWithCccd(uuid: UUID): BluetoothGattCharacteristic {
            val bluetoothGattCharacteristic = BluetoothGattCharacteristic(
                uuid,
                BluetoothGattCharacteristic.PROPERTY_WRITE_NO_RESPONSE,
                BluetoothGattCharacteristic.PERMISSION_WRITE
            )
            bluetoothGattCharacteristic.addDescriptor(createBluetoothGattDescriptor())
            return bluetoothGattCharacteristic
        }

        /**
         * Create a Bluetooth GATT descriptor with the common UUID, read, and write permissions
         *
         * This method is common with the same UUID for CCCD descriptor to all BLE
         * GATT characteristics in all sensors
         *
         * Remarks:
         * BluetoothGattDescriptor is added to each Bluetooth characteristic, especially the
         * Client Characteristic Configuration Descriptor (CCCD) to control notifications and indications
         * 1) ENABLE_NOTIFICATION_VALUE : The peripheral will send a notification whenever the characteristic value changes
         * 2) ENABLE_INDICATION_VALUE: The peripheral sends indications (similar to notifications but with acknowledgment)
         * 3) DISABLE_NOTIFICATION_VALUE: Notifications/indications are turned off
         * @return BluetoothGattDescriptor(CCCD) instance
         */
        private fun createBluetoothGattDescriptor(): BluetoothGattDescriptor {
            return BluetoothGattDescriptor(
                BleConstants.CCCD_UUID,
                BluetoothGattDescriptor.PERMISSION_READ or BluetoothGattDescriptor.PERMISSION_WRITE
            )
        }
    }

    // Service tag for logging
    protected abstract fun getTAG(): String

    // Type of the sensor (Continuous and On-Demand)
    protected abstract fun getSensorType(): SensorType

    // Health tracker type - must be provided by subclasses
    protected abstract val healthTrackerType: HealthTrackerType

    // (Samsung Health Sensor SDK) Enables an application to set an event listener and receive the Galaxy Watch's sensor
    // data for a specific HealthTrackerType
    protected var healthTracker: HealthTracker? = null
        private set

    // List of connected devices via BLE GATT Service
    protected val connectedDevices: MutableSet<String> = Collections.synchronizedSet(mutableSetOf<String>())

    // Cache the descriptor and the corresponding CCCD state
    protected val descriptorValueMap = ConcurrentHashMap<String, CccdState>()

    protected var isGattServerReady = false
    protected var isInitialized = false

    /**
     * Initialize the service manager.
     */
    override fun initialize() {
        if (isInitialized) return
        isInitialized = true

        // Register for GATT server events
        val filter = IntentFilter().apply {
            addAction(BleConstants.ACTION_GATT_SERVER_READY)
            addAction(BleConstants.ACTION_GATT_CHARACTERISTIC_READ_REQUEST)
            addAction(BleConstants.ACTION_GATT_CHARACTERISTIC_WRITE_REQUEST)
            addAction(BleConstants.ACTION_GATT_DESCRIPTOR_READ_REQUEST)
            addAction(BleConstants.ACTION_GATT_DESCRIPTOR_WRITE_REQUEST)
            addAction(BleConstants.ACTION_GATT_DEVICE_CONNECTED)
            addAction(BleConstants.ACTION_GATT_DEVICE_DISCONNECTED)
        }

        LocalBroadcastManager.getInstance(service.applicationContext).registerReceiver(gattServerReceiver, filter)
        Log.i(getTAG(), "Initialized ${getTAG()}")
    }

    /**
     * Clean up resources.
     */
    override fun cleanup() {
        try {
            // Unregister receiver
            try {
                LocalBroadcastManager.getInstance(service.applicationContext).unregisterReceiver(gattServerReceiver)
            } catch (e: IllegalArgumentException) {
                // Receiver might not be registered
                Log.w(getTAG(), "Receiver was not registered: ${e.message}")
            }

            // Clear collections
            connectedDevices.clear()
            descriptorValueMap.clear()

            // Reset state
            isGattServerReady = false
            isInitialized = false

            // Call subclass cleanup
            cleanupSensorResources()

            Log.i(getTAG(), "${getTAG()} cleaned up")
        } catch (e: Exception) {
            Log.e(getTAG(), "Error during cleanup: ${e.message}")
        }
    }

    /**
     * Handle device connection event.
     * @param deviceAddress Device (MAC) address of the connected client.
     */
    override fun onDeviceConnected(deviceAddress: String) {
        Log.d(getTAG(), "Device with address: $deviceAddress connected to ${getTAG()}")
        connectedDevices.add(deviceAddress)
    }

    /**
     * Handle device disconnection event.
     * @param deviceAddress Device (MAC) address of the disconnected client.
     */
    override fun onDeviceDisconnected(deviceAddress: String) {
        Log.d(getTAG(), "Device with address: $deviceAddress disconnected from ${getTAG()}")
        connectedDevices.remove(deviceAddress)

        // Clean up any descriptor maps for this device
        val keysToRemove = descriptorValueMap.keys.filter { it.contains(deviceAddress) }
        keysToRemove.forEach { descriptorValueMap.remove(it) }
    }

    /**
     * Create the event listener for the specific sensor.
     * @return Samsung track event listener.
     */
    protected abstract fun createSensorListener(): HealthTracker.TrackerEventListener

    /**
     * Set up the BLE GATT service with characteristics and descriptors for the sensor.
     */
    protected abstract fun setupService()

    /**
     * Process the read request of the BLE GATT characteristic of the sensor from a client.
     * @param uuid The UUID of the specific characteristic the client is requesting to read.
     * @param deviceAddress The Bluetooth MAC address of the client device making the read request.
     * @param requestId A unique identifier for this specific read request.
     * @param offset The starting position (array) within the characteristic value from which to read, typically 0.
     */
    protected abstract fun handleCharacteristicReadRequest(uuid: UUID, deviceAddress: String, requestId: Int, offset: Int)

    /**
     * Handle the descriptor write request by sending current value of the characteristic when the received request from
     * the client is to enable notification or indication of the descriptor.
     * @param characteristicUuid The UUID of the specific characteristic the client is enabling the notification.
     * @param deviceAddress The Bluetooth MAC address of the client device making the read request.
     * @param state State of the CCCD: Notifications and indications disabled, Notifications enabled, and
     * Indications enabled.
     */
    protected abstract fun onDescriptorWriteRequest(characteristicUuid: UUID, deviceAddress: String, state: CccdState)

    /**
     * Broadcast updated sensor data to all the connected devices using notification.
     */
    protected abstract fun broadcastSensorData()

    /**
     * Clean up sensor-specific resources.
     */
    protected abstract fun cleanupSensorResources()

    /**
     * Create the health tracker for the specified tracker type.
     * Remarks:
     * This function is ONLY overridden in PPG as the instantiation of the tracker for PPG must specify
     * the PpgSet: Green, Red, or IR.
     */
    protected open fun createHealthTracker(): HealthTracker? {
        return service.healthTracking!!.getHealthTracker(healthTrackerType)
    }

    /**
     * Initialize the health tracker based on the type of the sensor and start collecting sensor data once the check for
     * the permissions, health tracking capability, and supported health tracker types is successful.
     */
    protected fun startSensorService() {
        // Check for permissions
        if (ContextCompat.checkSelfPermission(
                service,
                Manifest.permission.BODY_SENSORS
            ) != PackageManager.PERMISSION_GRANTED
        ) {
            Log.e(getTAG(), "Missing BODY_SENSORS permission, cannot start health tracking")
            return
        }

        if (ContextCompat.checkSelfPermission(
                service,
                Manifest.permission.ACTIVITY_RECOGNITION
            ) != PackageManager.PERMISSION_GRANTED
        ) {
            Log.e(getTAG(), "Missing ACTIVITY_RECOGNITION permission, cannot start health tracking")
            return
        }

        try {
            // Start Health tracking
            if (service.healthTracking == null) {
                Log.e(getTAG(), "Health tracking service is not initialized")
                return
            }

            // Initialize the Samsung health tracker based on the type of the sensor
            if (service.healthTracking!!.trackingCapability.supportHealthTrackerTypes.contains(healthTrackerType)) {
                healthTracker = createHealthTracker()
                healthTracker?.setEventListener(createSensorListener())
                Log.i(getTAG(), "{Tracking of the ${getSensorType()} sensor has started")
            } else {
                Log.w(getTAG(), "{$healthTrackerType} tracking is not supported on this device")
            }

        } catch (e: Exception) {
            Log.e(getTAG(), "Error initializing the Health tracking: ${e.message}")
        }
    }

    /**
     * Stop listening for new sensor data and de-initialize the health tracker.
     */
    protected fun stopSensorService() {
        try {
            // Stop the Health tracking
            healthTracker?.unsetEventListener()
            healthTracker = null
            Log.i(getTAG(), "{Tracking of the ${getSensorType()} sensor has stopped")
        } catch (e: Exception) {
            Log.e(getTAG(), "Error stopping the ${getSensorType()} sensor tracking: ${e.message}")
        }
    }

    /**
     * Handle the descriptor read request from the Client.
     * @param characteristicUuid The UUID of the characteristic to which the descriptor belongs to.
     * @param descriptorUuid The UUID of the descriptor requested to be read by the client.
     * @param deviceAddress The Bluetooth MAC address of the client device making the read request.
     * @param requestId A unique identifier for this specific read request.
     * @param offset The starting position (array) within the descriptor value from which to read, typically 0.
     * Remarks:
     * Only CCCD is supported descriptor in all the characteristics which is used to determine the state of the indication or
     * notification.
     */
    protected fun handleDescriptorReadRequest(
        characteristicUuid: UUID,
        descriptorUuid: UUID,
        deviceAddress: String,
        requestId: Int,
        offset: Int
    ) {
        var status = BluetoothGatt.GATT_FAILURE
        var value: ByteArray? = null

        if (descriptorUuid == BleConstants.CCCD_UUID) {
            // Create a unique key for this descriptor
            val key = "${deviceAddress}:${characteristicUuid}:${descriptorUuid}"

            // Get the CCCD state from our map, default to DISABLED. Initially the map will be empty and only set or updated
            // when a client send a descriptor request, so default is Disabled (Notification and Indication)
            val cccdState = descriptorValueMap[key] ?: CccdState.DISABLED
            value = cccdState.toByteArray()
            status = BluetoothGatt.GATT_SUCCESS
        }

        // Send response via the GATT connection service
        val responseIntent = Intent(BleConstants.ACTION_GATT_READ_RESPONSE)
        responseIntent.putExtra(BleConstants.INTENT_DEVICE_ADDRESS, deviceAddress)
        responseIntent.putExtra(BleConstants.INTENT_REQUEST_ID, requestId)
        responseIntent.putExtra(BleConstants.INTENT_STATUS, status)
        responseIntent.putExtra(BleConstants.INTENT_OFFSET, offset)
        responseIntent.putExtra(BleConstants.INTENT_VALUE, value)
        LocalBroadcastManager.getInstance(service.applicationContext).sendBroadcast(responseIntent)

        Log.d(getTAG(), "Sent descriptor read response for ${characteristicUuid}:${descriptorUuid}")
    }

    /**
     * Process the descriptor write request from the Client.
     * @param characteristicUuid The UUID of the characteristic to which the descriptor belongs to.
     * @param descriptorUuid The UUID of the descriptor requested to be updated by the client.
     * @param deviceAddress The Bluetooth MAC address of the client device making the write request.
     * @param value Value of the descriptor sent by the client.
     * Remarks:
     * Only CCCD is supported descriptor in all the characteristics which is used to determine the state of the indication or
     * notification.
     */
    protected fun handleDescriptorWriteRequest(
        characteristicUuid: UUID,
        descriptorUuid: UUID,
        deviceAddress: String,
        value: ByteArray?
    ) {
        if (descriptorUuid == BleConstants.CCCD_UUID) {
            // Create a unique key for this descriptor
            // Value of the descriptor is stored ONLY in this map
            val key = "${deviceAddress}:${characteristicUuid}:${descriptorUuid}"

            // Update our map with the new value from the client
            val state = CccdState.fromByteArray(value)
            descriptorValueMap[key] = state

            Log.d(getTAG(), "Updated CCCD state for $key to $state")

            // If notifications were just enabled, send the current value of the corresponding sensor
            // characteristic to the client
            if (CccdState.isEnabled(state) && connectedDevices.contains(deviceAddress)) {
                onDescriptorWriteRequest(characteristicUuid, deviceAddress, state)
            }
        }
    }

    /**
     * Process the characteristic write request from the Client.
     * @param characteristicUuid The UUID of the characteristic being written from the client.
     * @param deviceAddress The Bluetooth MAC address of the client device making the write request.
     * @param value Value of the characteristic sent by the client.
     * Remarks:
     * Typically the Health application does not support or have any write characteristics. Only characteristic which
     * is supported is the trigger to initiate the on-demand health tracking - ECG or SpO2
     */
    protected open fun handleCharacteristicWriteRequest(
        characteristicUuid: UUID,
        deviceAddress: String,
        value: ByteArray?
    ) {
        // Will be overridden in the supported sensors
        Log.d(getTAG(), "${getTAG()} does not handle characteristic write requests for $characteristicUuid")
    }

    /**
     * Notify of change in the value of the characteristic sent to the client.
     * @param characteristicUuid The UUID of the characteristic being notified to the client.
     * @param value Value of the characteristic to be sent to the client.
     * @param deviceAddress The Bluetooth MAC address of the client device to which the notification will be sent.
     * @param confirm Flag to indicate whether the client should send an acknowledgement to the server once the
     * notification is received.
     */
    protected fun notifyCharacteristic(
        characteristicUuid: String,
        value: ByteArray,
        deviceAddress: String,
        confirm: Boolean
    ) {
        // Notify via the connection service
        val intent = Intent(BleConstants.ACTION_GATT_NOTIFY_CHARACTERISTIC_CHANGED)
        intent.putExtra(BleConstants.INTENT_CHARACTERISTIC_UUID, characteristicUuid)
        intent.putExtra(BleConstants.INTENT_DEVICE_ADDRESS, deviceAddress)
        intent.putExtra(BleConstants.INTENT_VALUE, value)
        intent.putExtra(BleConstants.INTENT_CONFIRM, confirm)
        LocalBroadcastManager.getInstance(service.applicationContext).sendBroadcast(intent)

        Log.d(getTAG(), "Notified device $deviceAddress for characteristic $characteristicUuid")
    }

    /**
     * Send the characteristic response to the client.
     * @param deviceAddress The Bluetooth MAC address of the client device to which the response will be sent.
     * @param requestId A unique identifier for this specific read request sent by the client.
     * @param offset The starting position (array) within the characteristic value from which to read, typically 0.
     * @param value Value of the characteristic to be sent to the client.
     */
    protected fun sendCharacteristicReadResponse(
        deviceAddress: String,
        requestId: Int,
        offset: Int,
        value: ByteArray?
    ) {
        val status = if (value == null) BluetoothGatt.GATT_FAILURE else BluetoothGatt.GATT_SUCCESS

        val responseIntent = Intent(BleConstants.ACTION_GATT_READ_RESPONSE)
        responseIntent.putExtra(BleConstants.INTENT_DEVICE_ADDRESS, deviceAddress)
        responseIntent.putExtra(BleConstants.INTENT_REQUEST_ID, requestId)
        responseIntent.putExtra(BleConstants.INTENT_STATUS, status)
        responseIntent.putExtra(BleConstants.INTENT_OFFSET, offset)
        responseIntent.putExtra(BleConstants.INTENT_VALUE, value)
        LocalBroadcastManager.getInstance(service.applicationContext).sendBroadcast(responseIntent)
    }

    /**
     * Receiver that handles broadcast intents of the GATT Server (from BleGattConnectionService).
     */
    private val gattServerReceiver = object : BroadcastReceiver() {

        /**
         * Event when a new broadcast intent is received.
         * @param context Context in which the receiver (BLE GATT Service) is running.
         * @param intent The Intent being received.
         */
        override fun onReceive(context: Context?, intent: Intent?) {
            when (intent?.action) {
                BleConstants.ACTION_GATT_SERVER_READY -> {
                    Log.i(getTAG(), "GATT server is ready, setting up service")
                    isGattServerReady = true

                    // Setup the BØE GATT service of individual sensor services
                    setupService()
                }

                // Handling of different intents supported (mainly BLE GATT Server actions)
                BleConstants.ACTION_GATT_CHARACTERISTIC_READ_REQUEST -> {
                    val characteristicUuidString =
                        intent.getStringExtra(BleConstants.INTENT_CHARACTERISTIC_UUID) ?: return
                    val characteristicUuid = UUID.fromString(characteristicUuidString)
                    val deviceAddress =
                        intent.getStringExtra(BleConstants.INTENT_DEVICE_ADDRESS) ?: return
                    val requestId = intent.getIntExtra(BleConstants.INTENT_REQUEST_ID, 0)
                    val offset = intent.getIntExtra(BleConstants.INTENT_OFFSET, 0)
                    handleCharacteristicReadRequest(characteristicUuid, deviceAddress, requestId, offset)
                }

                BleConstants.ACTION_GATT_CHARACTERISTIC_WRITE_REQUEST -> {
                    val characteristicUuidString = intent.getStringExtra(BleConstants.INTENT_CHARACTERISTIC_UUID) ?: return
                    val characteristicUuid = UUID.fromString(characteristicUuidString)
                    val deviceAddress = intent.getStringExtra(BleConstants.INTENT_DEVICE_ADDRESS) ?: return
                    val value = intent.getByteArrayExtra(BleConstants.INTENT_VALUE)
                    handleCharacteristicWriteRequest(characteristicUuid, deviceAddress, value)
                }

                BleConstants.ACTION_GATT_DESCRIPTOR_READ_REQUEST -> {
                    val characteristicUuidString = intent.getStringExtra(BleConstants.INTENT_CHARACTERISTIC_UUID) ?: return
                    val characteristicUuid = UUID.fromString(characteristicUuidString)
                    val descriptorUuidString = intent.getStringExtra(BleConstants.INTENT_DESCRIPTOR_UUID) ?: return
                    val descriptorUuid = UUID.fromString(descriptorUuidString)
                    val deviceAddress = intent.getStringExtra(BleConstants.INTENT_DEVICE_ADDRESS) ?: return
                    val requestId = intent.getIntExtra(BleConstants.INTENT_REQUEST_ID, 0)
                    val offset = intent.getIntExtra(BleConstants.INTENT_OFFSET, 0)
                    handleDescriptorReadRequest(characteristicUuid, descriptorUuid, deviceAddress, requestId, offset)
                }

                BleConstants.ACTION_GATT_DESCRIPTOR_WRITE_REQUEST -> {
                    val characteristicUuidString = intent.getStringExtra(BleConstants.INTENT_CHARACTERISTIC_UUID) ?: return
                    val characteristicUuid = UUID.fromString(characteristicUuidString)
                    val descriptorUuidString = intent.getStringExtra(BleConstants.INTENT_DESCRIPTOR_UUID) ?: return
                    val descriptorUuid = UUID.fromString(descriptorUuidString)
                    val deviceAddress = intent.getStringExtra(BleConstants.INTENT_DEVICE_ADDRESS) ?: return
                    val value = intent.getByteArrayExtra(BleConstants.INTENT_VALUE)
                    handleDescriptorWriteRequest(characteristicUuid, descriptorUuid, deviceAddress, value)
                }

                BleConstants.ACTION_GATT_DEVICE_CONNECTED -> {
                    val deviceAddress = intent.getStringExtra(BleConstants.INTENT_DEVICE_ADDRESS) ?: return
                    onDeviceConnected(deviceAddress)
                }

                BleConstants.ACTION_GATT_DEVICE_DISCONNECTED -> {
                    val deviceAddress = intent.getStringExtra(BleConstants.INTENT_DEVICE_ADDRESS) ?: return
                    onDeviceDisconnected(deviceAddress)
                }
            }
        }
    }
}