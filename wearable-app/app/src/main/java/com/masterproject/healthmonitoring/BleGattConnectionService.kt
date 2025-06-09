package com.masterproject.healthmonitoring

import android.Manifest
import android.annotation.SuppressLint
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.bluetooth.BluetoothAdapter
import android.bluetooth.BluetoothDevice
import android.bluetooth.BluetoothGatt
import android.bluetooth.BluetoothGattCharacteristic
import android.bluetooth.BluetoothGattDescriptor
import android.bluetooth.BluetoothGattServer
import android.bluetooth.BluetoothGattServerCallback
import android.bluetooth.BluetoothGattService
import android.bluetooth.BluetoothManager
import android.bluetooth.BluetoothProfile
import android.bluetooth.le.AdvertiseCallback
import android.bluetooth.le.AdvertiseData
import android.bluetooth.le.AdvertiseSettings
import android.bluetooth.le.BluetoothLeAdvertiser
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.PackageManager
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.os.ParcelUuid
import android.util.Log
import androidx.core.app.NotificationCompat
import androidx.core.content.ContextCompat
import androidx.lifecycle.LifecycleService
import androidx.localbroadcastmanager.content.LocalBroadcastManager
import java.util.Collections
import java.util.UUID
import java.util.concurrent.ConcurrentHashMap

/**
 * Core BLE GATT server service responsible for:
 * - Setting up and managing the BLE GATT server
 * - Advertising services (Each sensor will have its own BLE GATT Service)
 * - Handling connected devices
 * - Processing BLE operations
 * 
 * This service provides a single connection point for all sensors and forwards read/write requests
 * to the appropriate service managers.
 */
class BleGattConnectionService : LifecycleService() {
    companion object {
        private const val TAG = "BleGattConnectionService"
        private const val NOTIFICATION_ID = 1001
        private const val CHANNEL_ID = "ble_gatt_connection_channel"
        private const val MAX_RECONNECTION_ATTEMPTS = 5
        private const val RECONNECTION_DELAY_MS = 1000L
    }

    // Bluetooth components
    private lateinit var bluetoothManager: BluetoothManager
    private var bluetoothAdapter: BluetoothAdapter? = null
    private var bluetoothLeAdvertiser: BluetoothLeAdvertiser? = null
    private var gattServer: BluetoothGattServer? = null

    // List of connected devices
    private val connectedDevices = Collections.synchronizedSet(mutableSetOf<BluetoothDevice>())

    // List of service UUIDs (contains all the sensor UUIDs) to advertise
    private val serviceUuids = Collections.synchronizedList(mutableListOf<UUID>())

    // Map of UUID strings to BluetoothGattCharacteristic objects (For easy look-up)
    private val characteristicMap = ConcurrentHashMap<String, BluetoothGattCharacteristic>()

    // Service state
    private var isServiceRunning = false
    private var reconnectionAttempts = 0
    private val handler = Handler(Looper.getMainLooper())

    /**
     * Create the BLE GATT connection service, register for all the required broadcast receivers (using Intents),
     * and initialize the bluetooth connectivity to enable connection to external Bluetooth devices (BLE GATT Clients).
     */
    override fun onCreate() {
        super.onCreate()
        isServiceRunning = true

        createNotificationChannel()
        startForeground()

        // Register receivers
        LocalBroadcastManager.getInstance(applicationContext).registerReceiver(
            addServiceReceiver,
            IntentFilter(BleConstants.ACTION_GATT_ADD_SERVICE)
        )
        LocalBroadcastManager.getInstance(applicationContext).registerReceiver(
            notifyCharacteristicReceiver,
            IntentFilter(BleConstants.ACTION_GATT_NOTIFY_CHARACTERISTIC_CHANGED)
        )
        LocalBroadcastManager.getInstance(applicationContext).registerReceiver(
            readResponseReceiver,
            IntentFilter(BleConstants.ACTION_GATT_READ_RESPONSE)
        )

        initBluetooth()
    }

    /**
     * Start the BLE GATT Service.
     * @param intent The intent provided to start the service.
     * @param flags Additional flags to start this service.
     * @param startId A unique ID representing this specific request to start.
     */
    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        // Let LifecycleService handle onStartCommand
        super.onStartCommand(intent, flags, startId)
        return START_STICKY
    }

    /**
     * Overrides the Bind call as the BLE GATT service does not support binding.
     * @return Explicitly returning NULL this service doesn't provide an interface for components
     * (e.g. activities) to bind to it.
     *
     * Remarks:
     * This service is designed to run as a foreground service and communicate with other components using the
     * LocalBroadcastManager system.
     */
    override fun onBind(intent: Intent): IBinder? {
        super.onBind(intent)
        return null
    }

    /**
     * Performs the cleanup when the service is being terminated.
     */
    override fun onDestroy() {
        isServiceRunning = false
        handler.removeCallbacksAndMessages(null)

        // Unregister receivers
        try {
            LocalBroadcastManager.getInstance(applicationContext).unregisterReceiver(addServiceReceiver)
        } catch (e: IllegalArgumentException) {
            Log.w(TAG, "addServiceReceiver was not registered: ${e.message}")
        }

        try {
            LocalBroadcastManager.getInstance(applicationContext).unregisterReceiver(notifyCharacteristicReceiver)
        } catch (e: IllegalArgumentException) {
            Log.w(TAG, "notifyCharacteristicReceiver was not registered: ${e.message}")
        }

        try {
            LocalBroadcastManager.getInstance(applicationContext).unregisterReceiver(readResponseReceiver)
        } catch (e: IllegalArgumentException) {
            Log.w(TAG, "readResponseReceiver was not registered: ${e.message}")
        }

        stopAdvertising()
        closeGattServer()

        // Clear collections
        connectedDevices.clear()
        serviceUuids.clear()
        characteristicMap.clear()

        super.onDestroy()
    }

    /**
     * Creates a low-importance notification channel for the BLE GATT service's foreground notification.
     */
    private fun createNotificationChannel() {
        val channel = NotificationChannel(
            CHANNEL_ID,
            getString(R.string.notification_channel_name),
            NotificationManager.IMPORTANCE_LOW
        ).apply {
            description = getString(R.string.notification_channel_description)
        }

        val notificationManager = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        notificationManager.createNotificationChannel(channel)
    }

    /**
     * Creates and displays a notification that allows the BLE GATT server to run as a foreground service, preventing
     * it from being killed by the system when under memory pressure.
     */
    private fun startForeground() {
        val notificationIntent = Intent(this, MainActivity::class.java)
        val pendingIntent = PendingIntent.getActivity(
            this, 0, notificationIntent,
            PendingIntent.FLAG_IMMUTABLE
        )

        val notification = NotificationCompat.Builder(this, CHANNEL_ID)
            .setContentTitle(getString(R.string.notification_title))
            .setContentText(getString(R.string.notification_text))
            .setSmallIcon(android.R.drawable.ic_dialog_info)
            .setContentIntent(pendingIntent)
            .build()

        startForeground(NOTIFICATION_ID, notification)
    }

    /**
     * Initializes Bluetooth components required for BLE GATT server operation.
     */
    private fun initBluetooth() {
        Log.i(TAG, "Initializing the Bluetooth")
        bluetoothManager = getSystemService(Context.BLUETOOTH_SERVICE) as BluetoothManager
        bluetoothAdapter = bluetoothManager.adapter

        if (bluetoothAdapter == null) {
            Log.e(TAG, "Bluetooth is not available on this device")
            stopSelf()
            return
        }

        if (!bluetoothAdapter!!.isEnabled) {
            Log.e(TAG, "Bluetooth is not enabled")
            // Instead of stopping, wait for Bluetooth to be enabled
            val filter = IntentFilter(BluetoothAdapter.ACTION_STATE_CHANGED)
            LocalBroadcastManager.getInstance(applicationContext).registerReceiver(object : BroadcastReceiver() {
                override fun onReceive(context: Context?, intent: Intent?) {
                    if (intent?.action == BluetoothAdapter.ACTION_STATE_CHANGED) {
                        val state = intent.getIntExtra(BluetoothAdapter.EXTRA_STATE, BluetoothAdapter.ERROR)
                        if (state == BluetoothAdapter.STATE_ON) {
                            Log.i(TAG, "Bluetooth has been enabled, initializing BLE")
                            initBluetooth()
                            LocalBroadcastManager.getInstance(applicationContext).unregisterReceiver(this)
                        }
                    }
                }
            }, filter)
            return
        }

        bluetoothLeAdvertiser = bluetoothAdapter?.bluetoothLeAdvertiser
        if (bluetoothLeAdvertiser == null) {
            Log.e(TAG, "Bluetooth LE Advertising not supported on this device")
            stopSelf()
            return
        }

        setupGattServer()
    }

    /**
     * Sets up and initialize the BLE GATT server with retry capability with configurable exponential backoff.
     *
     * Initialization of the BLE GATT server include permission verification, opening GATT server with system's bluetooth
     * manager, and notification other components in the application the server is ready.
     */
    private fun setupGattServer() {
        Log.i(TAG, "Setting up GATT server")
        if (!hasBluetoothConnectPermission()) {
            Log.e(TAG, "Missing BLUETOOTH_CONNECT permission, cannot set up GATT server")
            return
        }

        try {
            gattServer = bluetoothManager.openGattServer(this, gattServerCallback)
            if (gattServer != null) {
                // Notify other services that GATT server is ready
                LocalBroadcastManager.getInstance(applicationContext).sendBroadcast(Intent(BleConstants.ACTION_GATT_SERVER_READY))
                Log.i(TAG, "GATT server initialized and ready")
            } else {
                // Retry setup with exponential backoff
                reconnectionAttempts++
                if (reconnectionAttempts <= MAX_RECONNECTION_ATTEMPTS) {
                    val delay = RECONNECTION_DELAY_MS * (1 shl (reconnectionAttempts - 1))
                    Log.w(TAG, "GATT server initialization failed, retrying in $delay ms")
                    handler.postDelayed({ setupGattServer() }, delay)
                } else {
                    Log.e(TAG, "Failed to initialize GATT server after $MAX_RECONNECTION_ATTEMPTS attempts")
                    stopSelf()
                }
            }
        } catch (e: SecurityException) {
            Log.e(TAG, "Security exception when setting up GATT server: ${e.message}")
            gattServer = null
        }
    }

    /**
     * Shuts down the BLE GATT server and terminates all active connections.
     *
     * Remarks:
     * Suppresses MissingPermission lint warnings as permission checks are performed within the method.
     */
    @SuppressLint("MissingPermission")
    private fun closeGattServer() {
        if (gattServer == null) {
            return
        }

        if (!hasBluetoothConnectPermission()) {
            Log.e(TAG, "Missing BLUETOOTH_CONNECT permission, cannot close GATT server cleanly")
            // Still attempt to nullify the reference
            gattServer = null
            return
        }

        // First notify all connected devices that we're shutting down
        if (connectedDevices.isNotEmpty() && hasBluetoothConnectPermission()) {
            try {
                synchronized(connectedDevices) {
                    val iterator = connectedDevices.iterator()
                    while (iterator.hasNext()) {
                        val device = iterator.next()
                        try {
                            gattServer?.cancelConnection(device)
                            Log.d(TAG, "Cancelled connection with device: ${device.address}")
                        } catch (e: Exception) {
                            Log.e(TAG, "Error cancelling connection with device ${device.address}: ${e.message}")
                        }
                        iterator.remove()
                    }
                }
            } catch (e: Exception) {
                Log.e(TAG, "Error disconnecting devices: ${e.message}")
            }
        }

        // Once all the active connections are terminated, close the BLE GATT server
        try {
            gattServer?.close()
            Log.i(TAG, "GATT server closed")
        } catch (e: SecurityException) {
            Log.e(TAG, "Security exception when closing GATT server: ${e.message}")
        } catch (e: Exception) {
            Log.e(TAG, "Error closing GATT server: ${e.message}")
        } finally {
            gattServer = null
        }
    }

    /**
     * Broadcast message sent by the Sensor services once the setup is complete to add the service to the
     * BLE GATT profile and advertise to the connected devices.
     */
    private val addServiceReceiver = object : BroadcastReceiver() {
        /**
         * Receiver for adding services to the BLE GATT server.
         * @param context The context in which the receiver is running.
         * @param intent The intent containing the action and service to be added.
         */
        override fun onReceive(context: Context?, intent: Intent?) {
            if (intent?.action == BleConstants.ACTION_GATT_ADD_SERVICE) {
                val service = intent.getParcelableExtra(
                    BleConstants.INTENT_SERVICE,
                    BluetoothGattService::class.java
                )
                if (service != null) {
                    Log.i(TAG, "Received new Service ${service.uuid}")
                    addService(service)
                } else
                    Log.i(TAG, "Service is NULL")
            }
        }
    }

    /**
     * Add a service to the BLE GATT server and register its UUID for advertising to the connected devices.
     * @param service BLE GATT service to be added to the BLE GATT profile.
     */
    private fun addService(service: BluetoothGattService) {
        if (gattServer == null) {
            Log.i(TAG, "BLE GATT server is not initialized")
            return
        }

        if (!hasBluetoothConnectPermission()) {
            Log.e(TAG, "Missing BLUETOOTH_CONNECT permission, cannot add service")
            return
        }

        try {
            if (gattServer?.addService(service) == true) {
                Log.i(TAG, "Added service ${service.uuid} to the BLE GATT server")
                serviceUuids.add(service.uuid)

                // Store all characteristics from this service for quick lookup
                service.characteristics.forEach { characteristic ->
                    characteristicMap[characteristic.uuid.toString()] = characteristic
                    Log.d(TAG, "Registered characteristic ${characteristic.uuid} in map")
                }

                // Update advertising with new service
                restartAdvertising()
            } else {
                Log.e(TAG, "Failed to add service ${service.uuid} to the BLE GATT server")
            }
        } catch (e: SecurityException) {
            Log.e(TAG, "Security exception when adding the BLE GATT service: ${e.message}")
        }
    }

    /**
     * Receives read response data for BLE GATT characteristics and descriptors and sends the response to the
     * requesting device from the corresponding sensor service.
     *
     * This broadcast receiver is triggered when a service manager provides a response to a read request.
     * The receiver extracts the necessary parameters from the intent and uses them to send
     * the appropriate response back to the requesting BLE client device.
     *
     */
    private val readResponseReceiver = object : BroadcastReceiver() {
        /**
         * Receiver for sending response to the target client based on the device address.
         * @param context The context in which the receiver is running.
         * @param intent The intent containing the BLE GATT response parameters and the device information.
         */
        override fun onReceive(context: Context?, intent: Intent?) {
            if (intent?.action == BleConstants.ACTION_GATT_READ_RESPONSE) {
                val deviceAddress = intent.getStringExtra(BleConstants.INTENT_DEVICE_ADDRESS) ?: return
                val device = connectedDevices.find { it.address == deviceAddress }
                if (device != null && hasBluetoothConnectPermission()) {
                    val requestId = intent.getIntExtra(BleConstants.INTENT_REQUEST_ID, 0)
                    val status = intent.getIntExtra(BleConstants.INTENT_STATUS, BluetoothGatt.GATT_SUCCESS)
                    val offset = intent.getIntExtra(BleConstants.INTENT_OFFSET, 0)
                    val value = intent.getByteArrayExtra(BleConstants.INTENT_VALUE)

                    try {
                        gattServer?.sendResponse(device, requestId, status, offset, value)

                        // It is not expected to get many characteristic read requests from the client(s). Logging will
                        // not have any impact on the performance due to this rationale
                        Log.d(
                            TAG, "Sent BLE GATT response for request $requestId to ${device.address}"
                        )
                    } catch (e: SecurityException) {
                        Log.e(TAG, "Security exception when sending BLE GATT response: ${e.message}")
                    }
                }
            }
        }
    }

    /**
     * Receives notification of change in value for a BLE GATT characteristic from the (sensor) service.
     *
     * This broadcast receiver is triggered when a service manager sends notification.
     * The receiver extracts the necessary parameters from the intent and uses them to notify all the connected devices.
     */
    private val notifyCharacteristicReceiver = object : BroadcastReceiver() {
        /**
         * Receiver for sending notification to all the connected devices and expecting confirmation or acknowledgement
         * based on the flag set by the sensor service.
         * @param context The context in which the receiver is running.
         * @param intent The intent containing the BLE GATT notification parameters.
         */
        override fun onReceive(context: Context?, intent: Intent?) {
            if (intent?.action == BleConstants.ACTION_GATT_NOTIFY_CHARACTERISTIC_CHANGED) {
                val characteristicUuid = intent.getStringExtra(BleConstants.INTENT_CHARACTERISTIC_UUID) ?: return
                val value = intent.getByteArrayExtra(BleConstants.INTENT_VALUE) ?: return
                val confirm = intent.getBooleanExtra(BleConstants.INTENT_CONFIRM, true)

                val characteristic = characteristicMap[characteristicUuid]
                characteristic?.let { notifyCharacteristicChanged(it, value, confirm) }
            }
        }
    }

    /**
     * Notify all the connected devices about the change in the value of the BLE GATT characteristic.
     * @param characteristic BLE GATT characteristic that has changed.
     * @param value Updated value of the BLE GATT characteristic.
     * @param confirm Flag to indicate whether acknowledgement or confirmation is expected from the BLE GATT Client once
     * the notification is sent.
     */
    @SuppressLint("MissingPermission")
    private fun notifyCharacteristicChanged(characteristic: BluetoothGattCharacteristic, value: ByteArray, confirm: Boolean) {
        if (gattServer == null || connectedDevices.isEmpty()) return

        if (!hasBluetoothConnectPermission()) {
            Log.e(TAG, "Missing BLUETOOTH_CONNECT permission, cannot notify characteristic")
            return
        }

        try {
            // Notify all the connected devices
            synchronized(connectedDevices) {
                for (device in connectedDevices) {
                    try {
                        gattServer?.notifyCharacteristicChanged(device, characteristic, confirm, value)
                    } catch (e: Exception) {
                        Log.e(TAG, "Error notifying device ${device.address}: ${e.message}")
                        // If there's an error with this device, remove it from connected devices
                        connectedDevices.remove(device)
                    }
                }
            }
            Log.d(TAG, "Notified ${connectedDevices.size} devices of change in ${characteristic.uuid}")
        } catch (e: Exception) {
            Log.e(TAG, "Error notifying characteristic: ${e.message}")
        }
    }

    /**
     * BLE advertising callbacks, to process and handle advertising connection or operation status.
     */
    private val advertiseCallback = object : AdvertiseCallback() {
        /**
         * Indicating the advertising of the BLE services has started successfully.
         * @param settingsInEffect Actual settings used for advertising, which may be different
         * from what has been requested.
         */
        override fun onStartSuccess(settingsInEffect: AdvertiseSettings?) {
            Log.i(TAG, "LE Advertise Started Successfully")
            // Reset reconnection attempts on success
            reconnectionAttempts = 0
        }

        /**
         * Indicating the advertising of the BLE services could not be started. BLE connection service will
         * try few attempts to restart the advertising.
         * @param errorCode Error code of the advertising start failures.
         */
        override fun onStartFailure(errorCode: Int) {
            val errorMessage: String = when (errorCode) {
                ADVERTISE_FAILED_ALREADY_STARTED -> "ADVERTISE_FAILED_ALREADY_STARTED"
                ADVERTISE_FAILED_DATA_TOO_LARGE -> "ADVERTISE_FAILED_DATA_TOO_LARGE"
                ADVERTISE_FAILED_FEATURE_UNSUPPORTED -> "ADVERTISE_FAILED_FEATURE_UNSUPPORTED"
                ADVERTISE_FAILED_INTERNAL_ERROR -> "ADVERTISE_FAILED_INTERNAL_ERROR"
                ADVERTISE_FAILED_TOO_MANY_ADVERTISERS -> "ADVERTISE_FAILED_TOO_MANY_ADVERTISERS"
                else -> "Unknown error code: $errorCode"
            }
            Log.e(TAG, "LE Advertise Failed: $errorMessage")

            // Try to restart advertising with exponential backoff
            if (reconnectionAttempts < MAX_RECONNECTION_ATTEMPTS && isServiceRunning) {
                reconnectionAttempts++
                val delay = RECONNECTION_DELAY_MS * (1 shl (reconnectionAttempts - 1))
                Log.i(TAG, "Attempting to restart advertising in $delay ms (attempt $reconnectionAttempts)")

                handler.postDelayed({
                    if (isServiceRunning) {
                        startAdvertising()
                    }
                }, delay)
            }
        }
    }

    /**
     * Initiates BLE advertising for registered GATT services with optimized settings.
     *
     * Configures and starts Bluetooth Low Energy (BLE) advertising to make the device's GATT services discoverable
     * by nearby client devices with permission checks, using low-latency mode, prioritizing 3 health services, and automatic
     * try with configurable exponential backoff.
     */
    private fun startAdvertising() {
        if (serviceUuids.isEmpty()) {
            Log.i(TAG, "No services to advertise")
            return
        }

        if (!hasBluetoothAdvertisePermission()) {
            Log.e(TAG, "Missing BLUETOOTH_ADVERTISE permission, cannot start advertising")
            return
        }

        try {
            // Setup settings for advertising
            val settings = AdvertiseSettings.Builder()
                .setAdvertiseMode(AdvertiseSettings.ADVERTISE_MODE_LOW_LATENCY)
                .setConnectable(true)
                .setTimeout(0)
                .setTxPowerLevel(AdvertiseSettings.ADVERTISE_TX_POWER_MEDIUM)
                .build()

            // Create advertise data with all service UUIDs
            val dataBuilder = AdvertiseData.Builder()
                .setIncludeDeviceName(false) // Don't include device name to save space

            // Add up to 3 service UUIDs (to avoid packet size limits)
            // Prioritize standard services first
            val prioritizedServices = serviceUuids.sortedWith(compareBy {
                when (it) {
                    BleConstants.HeartRateService.SERVICE_UUID -> 0
                    BleConstants.TemperatureService.SERVICE_UUID -> 1
                    else -> 2
                }
            }).take(3)

            prioritizedServices.forEach { uuid ->
                dataBuilder.addServiceUuid(ParcelUuid(uuid))
            }

            val data = dataBuilder.build()

            // Start advertising
            bluetoothLeAdvertiser?.startAdvertising(settings, data, advertiseCallback)
            Log.i(TAG, "Started advertising ${prioritizedServices.size} services: $prioritizedServices")
        } catch (e: SecurityException) {
            Log.e(TAG, "Security exception when starting advertising: ${e.message}")
        } catch (e: Exception) {
            Log.e(TAG, "Error starting advertising: ${e.message}")
            // Try to restart advertising with exponential backoff
            if (reconnectionAttempts < MAX_RECONNECTION_ATTEMPTS && isServiceRunning) {
                reconnectionAttempts++
                val delay = RECONNECTION_DELAY_MS * (1 shl (reconnectionAttempts - 1))
                Log.i(TAG, "Attempting to restart advertising in $delay ms (attempt $reconnectionAttempts)")

                handler.postDelayed({
                    if (isServiceRunning) {
                        startAdvertising()
                    }
                }, delay)
            }
        }
    }

    /**
     * Stops BLE advertising if currently active.
     */
    private fun stopAdvertising() {
        if (!hasBluetoothAdvertisePermission()) {
            Log.e(TAG, "Missing BLUETOOTH_ADVERTISE permission, cannot stop advertising")
            return
        }

        try {
            bluetoothLeAdvertiser?.stopAdvertising(advertiseCallback)
            Log.i(TAG, "Stopped advertising")
        } catch (e: SecurityException) {
            Log.e(TAG, "Security exception when stopping advertising: ${e.message}")
        } catch (e: Exception) {
            Log.e(TAG, "Error stopping advertising: ${e.message}")
        }
    }

    /**
     * Restart the BLE advertising.
     */
    private fun restartAdvertising() {
        stopAdvertising()
        startAdvertising()
    }

    /**
     * Callback for handling BLE GATT server events.
     *
     * Processes connection events, MTU negotiations, and client read/write requests for characteristics and descriptors.
     * Manage communication between connected BLE clients and the appropriate sensor service handlers.
     */
    private val gattServerCallback = object : BluetoothGattServerCallback() {
        /**
         * Manage the state of the device connection by adding or removing the device, broadcasting the connection state
         * change to all the sensor services.
         * @param device The BluetoothDevice whose connection state changed
         * @param status The status of the operation
         * @param newState The new connection state (connected or disconnected)
         * Remarks:
         * It is expected the BLE Client should request the increase of the MTU size to support larger
         * characteristic values. The client device needs to explicitly request MTU change.
         */
        override fun onConnectionStateChange(device: BluetoothDevice, status: Int, newState: Int) {
            if (newState == BluetoothProfile.STATE_CONNECTED) {
                Log.i(TAG, "Device connected: ${device.address}")

                // Add the device to our connected set with extra care to avoid conflicts
                synchronized(connectedDevices) {
                    // First check if it's already there
                    if (!connectedDevices.contains(device)) {
                        connectedDevices.add(device)

                        // Broadcast connection only if still connected
                        if (isServiceRunning && connectedDevices.contains(device)) {
                            // Notify service managers about connected devices
                            val intent = Intent(BleConstants.ACTION_GATT_DEVICE_CONNECTED)
                            intent.putExtra(BleConstants.INTENT_DEVICE_ADDRESS, device.address)
                            LocalBroadcastManager.getInstance(applicationContext).sendBroadcast(intent)
                        }
                    }
                }
            } else if (newState == BluetoothProfile.STATE_DISCONNECTED) {
                Log.i(TAG, "Device disconnected: ${device.address}")

                // Important: synchronize access to avoid race conditions
                synchronized(connectedDevices) {
                    if (connectedDevices.remove(device)) {
                        // Notify service managers about disconnected devices
                        val intent = Intent(BleConstants.ACTION_GATT_DEVICE_DISCONNECTED)
                        intent.putExtra(BleConstants.INTENT_DEVICE_ADDRESS, device.address)
                        LocalBroadcastManager.getInstance(applicationContext).sendBroadcast(intent)
                    }
                }
            }
        }

        /**
         * Handles the callback when a connected BLE client device successfully negotiates a new MTU size
         * with the GATT server. The MTU determines the maximum data payload size that can be transferred in a
         * single BLE transaction.
         * @param device The connected BluetoothDevice that negotiated the MTU change
         * @param mtu The new MTU size in bytes that was negotiated with the device
         *
         * Remarks:
         * The default MTU size in BLE is 23 bytes (20 bytes of ATT payload). Larger MTU sizes allow for
         * more efficient data transfer with fewer packets, resulting in better throughput and lower power
         * consumption. The maximum theoretical MTU size in BLE is 517 bytes, but practical limitations
         * often exist based on device capabilities.
         *
         */
        override fun onMtuChanged(device: BluetoothDevice, mtu: Int) {
            Log.i(TAG, "MTU changed to $mtu for device ${device.address}")
        }

        /**
         * Handles the callback when a connected BLE client device attempts to read the value of a characteristic.
         * Corresponding sensor service will be responsible for handling the read request.
         * @param device The BluetoothDevice requesting to read the characteristic.
         * @param requestId Unique identifier for this read request, used to match the response.
         * @param offset Byte offset within the characteristic value to start reading from.
         * @param characteristic The BluetoothGattCharacteristic being read.
         */
        override fun onCharacteristicReadRequest(device: BluetoothDevice, requestId: Int,
                                                 offset: Int, characteristic: BluetoothGattCharacteristic) {
            processReadRequest(
                device, requestId, offset,
                BleConstants.ACTION_GATT_CHARACTERISTIC_READ_REQUEST, characteristic.uuid
            )
        }

        /**
         * Handles the callback when a connected BLE client device attempts to read the value of a descriptor.
         * Corresponding sensor service will be responsible for handling the read request.
         * @param device The BluetoothDevice requesting to read the descriptor.
         * @param requestId Unique identifier for this read request, used to match the response.
         * @param offset Byte offset within the descriptor value to start reading from.
         * @param descriptor The BluetoothGattDescriptor being read.
         */
        override fun onDescriptorReadRequest(device: BluetoothDevice, requestId: Int,
                                             offset: Int, descriptor: BluetoothGattDescriptor) {
            processReadRequest(
                device, requestId, offset, BleConstants.ACTION_GATT_DESCRIPTOR_READ_REQUEST,
                descriptor.characteristic.uuid, descriptor.uuid
            )
        }

        /**
         * Handles the callback when a connected BLE client device attempts to write to the value of a characteristic.
         * Corresponding sensor service will be responsible for handling the write request.
         * This callback immediately sends a success response to the client if responseNeeded is true,
         * then broadcasts the write request to the appropriate service handler for processing.
         * The method validates that the requesting device is authorized before proceeding.
         * @param device The BluetoothDevice requesting to write to the characteristic.
         * @param requestId Unique identifier for this write request, used to match the response.
         * @param characteristic The BluetoothGattCharacteristic being updated.
         * @param preparedWrite Flag indicating if this write operation is part of a reliable write transaction.
         * @param responseNeeded Flag indicating if the client requires a response to this write request.
         * @param offset Byte offset within the characteristic value to start writing from.
         * @param value The new value to write to the characteristic.
         */
        override fun onCharacteristicWriteRequest(device: BluetoothDevice, requestId: Int,
                                                  characteristic: BluetoothGattCharacteristic, preparedWrite: Boolean,
                                                  responseNeeded: Boolean, offset: Int, value: ByteArray) {
            if (!hasBluetoothConnectPermission()) {
                Log.e(TAG, "Missing BLUETOOTH_CONNECT permission for characteristic write")
                return
            }

            try {
                // Send response if needed, this can be sent immediately before the broadcast to services, client
                // can always read the characteristic to ensure the write is successful
                if (responseNeeded) {
                    // Check if device with the same address exists in the set
                    if (connectedDevices.none { it.address == device.address }) {
                        // Respond with error if no device with matching address is found
                        gattServer?.sendResponse(device, requestId, BluetoothGatt.GATT_FAILURE, 0, null)
                        Log.e(TAG, "Read request from unauthorized device: ${device.address}")
                        return
                    } else {
                        gattServer?.sendResponse(device, requestId, BluetoothGatt.GATT_SUCCESS, 0, null)
                    }
                }

                // Forward write request to appropriate service manager
                val intent = Intent(BleConstants.ACTION_GATT_CHARACTERISTIC_WRITE_REQUEST)
                intent.putExtra(BleConstants.INTENT_CHARACTERISTIC_UUID, characteristic.uuid.toString())
                intent.putExtra(BleConstants.INTENT_DEVICE_ADDRESS, device.address)
                intent.putExtra(BleConstants.INTENT_VALUE, value)
                LocalBroadcastManager.getInstance(applicationContext).sendBroadcast(intent)

                Log.d(TAG, "Write request for ${characteristic.uuid} with ${value.size} bytes")
            } catch (e: SecurityException) {
                Log.e(TAG, "Security exception in onCharacteristicWriteRequest: ${e.message}")
            }
        }

        /**
         * Handles requests from BLE client devices to write to a descriptor value.
         * This callback is triggered when a connected BLE client attempts to update a descriptor's value.
         * The current implementation specifically handles Client Characteristic Configuration Descriptor (CCCD)
         * writes, which are used to enable or disable notifications/indications for characteristics.
         * Sensor service can then update their notification state tracking for the specific device
         * and characteristic.
         * @param device The BluetoothDevice requesting to write to the descriptor.
         * @param requestId Unique identifier for this write request, used to match the response.
         * @param descriptor The BluetoothGattDescriptor being updated.
         * @param preparedWrite Flag indicating if this write operation is part of a reliable write transaction.
         * @param responseNeeded Flag indicating if the client requires a response to this write request.
         * @param offset Byte offset within the descriptor value to start writing from.
         * @param value The new value to write to the descriptor (typically 0x00 to disable or 0x01/0x02 to
         * enable notifications/indications).
         */
        override fun onDescriptorWriteRequest(device: BluetoothDevice, requestId: Int, descriptor: BluetoothGattDescriptor,
            preparedWrite: Boolean, responseNeeded: Boolean, offset: Int, value: ByteArray) {
            if (!hasBluetoothConnectPermission()) {
                Log.e(TAG, "Missing BLUETOOTH_CONNECT permission for descriptor write")
                return
            }

            try {
                // Handle descriptor write requests only supports enabling or disabling notification
                if (descriptor.uuid == BleConstants.CCCD_UUID) {
                    // Send response if needed, this can be sent immediately before the broadcast to services, client
                    // can always read the descriptor to ensure the write is successful
                    if (responseNeeded) {
                        // Check if device with the same address exists in the set
                        if (connectedDevices.none { it.address == device.address }) {
                            // Respond with error if no device with matching address is found
                            gattServer?.sendResponse(device, requestId, BluetoothGatt.GATT_FAILURE, 0, null)
                            Log.e(TAG, "Read request from unauthorized device: ${device.address}")
                            return
                        } else {
                            gattServer?.sendResponse(device, requestId, BluetoothGatt.GATT_SUCCESS, 0, null)
                        }
                    }

                    // Notify service managers about notification subscription changes
                    val intent = Intent(BleConstants.ACTION_GATT_DESCRIPTOR_WRITE_REQUEST)
                    val characteristic = descriptor.characteristic
                    intent.putExtra(BleConstants.INTENT_CHARACTERISTIC_UUID, characteristic.uuid.toString())
                    intent.putExtra(BleConstants.INTENT_DESCRIPTOR_UUID, descriptor.uuid.toString())
                    intent.putExtra(BleConstants.INTENT_DEVICE_ADDRESS, device.address)
                    intent.putExtra(BleConstants.INTENT_REQUEST_ID, requestId)
                    intent.putExtra(BleConstants.INTENT_VALUE, value)
                    LocalBroadcastManager.getInstance(applicationContext).sendBroadcast(intent)
                }
            } catch (e: SecurityException) {
                Log.e(TAG, "Security exception in onDescriptorWriteRequest: ${e.message}")
            }
        }

        /**
         * Processes read requests for both characteristics and descriptors once the permission and the device is
         * identified. Broadcasts the read request to the appropriate sensor service handler via LocalBroadcastManager.
         * @param device The BluetoothDevice requesting to read the characteristic or descriptor.
         * @param requestId Unique identifier for this read request, used to match the response.
         * @param offset Byte offset within the value to start reading from.
         * @param action The broadcast action to use (characteristic or descriptor read).
         * @param characteristicUuid UUID of the characteristic being accessed.
         * @param descriptorUuid Optional UUID of the descriptor being read, null for characteristic reads.
         */
        @SuppressLint("MissingPermission")
        private fun processReadRequest(device: BluetoothDevice, requestId: Int, offset: Int, action: String,
                                       characteristicUuid: UUID, descriptorUuid: UUID? = null) {
            if (!hasBluetoothConnectPermission()) {
                Log.e(TAG, "Missing BLUETOOTH_CONNECT permission for read operation")
                return
            }

            // Check if device with the same address exists in the set
            if (connectedDevices.none { it.address == device.address }) {
                // Respond with error if no device with matching address is found
                gattServer?.sendResponse(device, requestId, BluetoothGatt.GATT_FAILURE, 0, null)
                Log.e(TAG, "Read request from unauthorized device: ${device.address}")
                return
            }

            // Pass the read request to other components via broadcast
            val intent = Intent(action)
            intent.putExtra(BleConstants.INTENT_CHARACTERISTIC_UUID, characteristicUuid.toString())
            intent.putExtra(BleConstants.INTENT_DEVICE_ADDRESS, device.address)
            intent.putExtra(BleConstants.INTENT_REQUEST_ID, requestId)
            intent.putExtra(BleConstants.INTENT_OFFSET, offset)

            // Add descriptor UUID if this is a descriptor read request
            if (descriptorUuid != null) {
                intent.putExtra(BleConstants.INTENT_DESCRIPTOR_UUID, descriptorUuid.toString())
            }

            // Services will deal with the request and respond back with the requested value
            LocalBroadcastManager.getInstance(applicationContext).sendBroadcast(intent)

            // Log appropriate message
            if (descriptorUuid != null) {
                Log.d(
                    TAG,
                    "Broadcast descriptor read request for $descriptorUuid on characteristic " +
                            "$characteristicUuid from ${device.address}"
                )
            } else {
                Log.d(
                    TAG, "Broadcast characteristic read request for $characteristicUuid from ${device.address}"
                )
            }
        }
    }

    /**
     * Checks if the app has BLUETOOTH_CONNECT permission.
     *
     * @return True if the permission is granted, otherwise false.
     */
    private fun hasBluetoothConnectPermission(): Boolean {
        return ContextCompat.checkSelfPermission(
            this,
            Manifest.permission.BLUETOOTH_CONNECT
        ) == PackageManager.PERMISSION_GRANTED
    }

    /**
     * Checks if the app has BLUETOOTH_ADVERTISE permission.
     *
     * @return True if the permission is granted, otherwise false.
     */
    private fun hasBluetoothAdvertisePermission(): Boolean {
        return ContextCompat.checkSelfPermission(
            this,
            Manifest.permission.BLUETOOTH_ADVERTISE
        ) == PackageManager.PERMISSION_GRANTED
    }
}