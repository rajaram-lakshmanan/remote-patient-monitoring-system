package com.masterproject.healthmonitoring

import android.bluetooth.BluetoothGattCharacteristic
import android.content.Intent
import android.util.Log
import androidx.localbroadcastmanager.content.LocalBroadcastManager
import com.samsung.android.service.health.tracking.HealthTracker
import com.samsung.android.service.health.tracking.data.DataPoint
import com.samsung.android.service.health.tracking.data.HealthTrackerType
import com.samsung.android.service.health.tracking.data.ValueKey
import java.util.UUID

/**
 * Manager for the Accelerometer continuous (streaming) BLE service.
 * Handles accelerometer data collection from device sensors using Samsung Health Sensor SDK and BLE notifications.
 */
class AccelerometerContinuousService(service: HealthMonitoringService) : BaseContinuousSensorService(service) {
    override fun getTAG() = "AccelerometerService"

    override val healthTrackerType = HealthTrackerType.ACCELEROMETER_CONTINUOUS

    /**
     * Return the type of the sensor (Accelerometer) gathered by this service.
     */
    override fun getSensorType(): SensorType {
        return SensorType.ACCELEROMETER
    }

    // Characteristic to represent raw data of the X, Y, and Z axes
    // Note: On the client end, this values can be converted into m/s2 with: 9.81 / (16383.75 / 4.0)) * value
    private var accelerometerDataCharacteristic: BluetoothGattCharacteristic? = null

    // Latest accelerometer values
    @Volatile
    private var latestAccelerometerData = AccelerometerData(0, 0, 0, 0)

    // Rate limiting for BLE notifications
    private var lastNotificationTime = 0L

    // As per Samsung Health Sensor SDK, accelerometer values are measured with a 25 Hz frequency
    private val minNotificationIntervalMs = 40

    /**
     * Setup the BLE Gatt Service to represent the Accelerometer data.
     */
    override fun setupService() {
        // Create Accelerometer (Continuous) Service
        val accelerometerService = createBluetoothGattService(BleConstants.AccelerometerService.SERVICE_UUID)

        // Create Accelerometer X,Y, and Z Characteristics and add it to the service
        accelerometerDataCharacteristic =
            createGattReadCharacteristicWithCccd(BleConstants.AccelerometerService.ACCELEROMETER_DATA_UUID)
        accelerometerDataCharacteristic?.let { accelerometerService.addCharacteristic(it) }

        // Add service to GATT server via intent
        val intent = Intent(BleConstants.ACTION_GATT_ADD_SERVICE)
        intent.putExtra(BleConstants.INTENT_SERVICE, accelerometerService)
        LocalBroadcastManager.getInstance(service.applicationContext).sendBroadcast(intent)
        Log.i(getTAG(), "Accelerometer service setup complete")
    }

    /**
     * Handle the read characteristics request from the client.
     * @param uuid The UUID of the specific characteristic the client is requesting to read.
     * @param deviceAddress The Bluetooth MAC address of the client device making the read request.
     * @param requestId A unique identifier for this specific read request.
     * @param offset The starting position (array) within the characteristic value from which to read, typically 0.
     */
    override fun handleCharacteristicReadRequest(uuid: UUID, deviceAddress: String, requestId: Int, offset: Int) {
        // Prepare response based on the requested characteristic
        val value: ByteArray? = when (uuid) {
            BleConstants.AccelerometerService.ACCELEROMETER_DATA_UUID -> {
                latestAccelerometerData.accelerometerDataToByteArray()
            }

            else -> {
                Log.w(getTAG(), "Received read request for unknown characteristic: $uuid")
                null
            }
        }

        sendCharacteristicReadResponse(deviceAddress, requestId, offset, value)
    }

    /**
     * Handle the descriptor write request by sending current value of the characteristic when the received request from
     * the client is to enable notification or indication of the descriptor.
     * @param characteristicUuid The UUID of the specific characteristic the client is enabling the notification.
     * @param deviceAddress The Bluetooth MAC address of the client device making the read request.
     * @param state State of the CCCD: Notifications and indications disabled, Notifications enabled, and
     * Indications enabled.
     */
    override fun onDescriptorWriteRequest(characteristicUuid: UUID, deviceAddress: String, state: CccdState) {
        when (characteristicUuid) {
            BleConstants.AccelerometerService.ACCELEROMETER_DATA_UUID -> {
                val byteValue = latestAccelerometerData.accelerometerDataToByteArray()
                notifyCharacteristic(
                    BleConstants.AccelerometerService.ACCELEROMETER_DATA_UUID.toString(),
                    byteValue,
                    deviceAddress,
                    state == CccdState.INDICATION_ENABLED
                )
            }
        }
    }

    /**
     * Create the listener for the sensor data event callback (Samsung Health Sensor SDK).
     * @return Samsung track event listener.
     */
    override fun createSensorListener(): HealthTracker.TrackerEventListener {
        return object : HealthTracker.TrackerEventListener {
            /**
             * Triggered when the Samsung's Health Tracking Service (Accelerometer) sends data to the application.
             * @param dataPoints DataPoint list for the Accelerometer HealthTrackerType.
             */
            override fun onDataReceived(dataPoints: List<DataPoint>) {
                for (data in dataPoints) {
                    try {
                        // Get accelerometer values if available
                        val accX: Int = try {
                            data.getValue(ValueKey.AccelerometerSet.ACCELEROMETER_X)
                        } catch (e: Exception) {
                            0 // Default value
                        }
                        val accY: Int = try {
                            data.getValue(ValueKey.AccelerometerSet.ACCELEROMETER_Y)
                        } catch (e: Exception) {
                            0 // Default value
                        }
                        val accZ: Int = try {
                            data.getValue(ValueKey.AccelerometerSet.ACCELEROMETER_Z)
                        } catch (e: Exception) {
                            0 // Default value
                        }

                        // Update the accelerometer data model (raw values and timestamp in milliseconds) and
                        // broadcast the data to the client
                        latestAccelerometerData = AccelerometerData(accX, accY, accZ, data.timestamp)
                        broadcastSensorData()
                    } catch (e: Exception) {
                        Log.e(getTAG(), "Error processing accelerometer data: ${e.message}")
                    }
                }
            }

            /**
             * Triggered when the Samsung's Health Tracking Service (Accelerometer) encounters errors.
             * @param error Error typically occurs when there is a permission or SDK policy issues.
             */
            override fun onError(error: HealthTracker.TrackerError) {
                Log.e(getTAG(), "Accelerometer tracker error: $error")
            }

            /**
             * Triggered when the gathered data from the Samsung's Health Tracking Service (Accelerometer) is flushed. Flush
             * provides the functionality to collect the data instantly without waiting for the data received event.
             * Remarks:
             * Flush is not used in the application.
             */
            override fun onFlushCompleted() {
                Log.d(getTAG(), "Accelerometer data flush completed")
            }
        }
    }

    /**
     * Broadcast the latest accelerometer sensor data along with the timestamp to the connected devices.
     */
    override fun broadcastSensorData() {
        if (!isGattServerReady) return

        // Get current time to check notification rate limit
        val currentTime = System.currentTimeMillis()
        if (currentTime - lastNotificationTime < minNotificationIntervalMs) {
            return  // Skip this update to maintain rate limit
        }
        lastNotificationTime = currentTime

        // Find devices that have notifications enabled for accelerometer and notify the change in the characteristic value
        synchronized(connectedDevices) {
            for (deviceAddress in connectedDevices) {
                // Notify accelerometer X data
                val cccdAccDataKey =
                    "${deviceAddress}:${BleConstants.AccelerometerService.ACCELEROMETER_DATA_UUID}:${BleConstants.CCCD_UUID}"
                val accDataCccdState = descriptorValueMap[cccdAccDataKey]
                if (CccdState.isEnabled(accDataCccdState)) {
                    val byteValue = latestAccelerometerData.accelerometerDataToByteArray()
                    notifyCharacteristic(
                        BleConstants.AccelerometerService.ACCELEROMETER_DATA_UUID.toString(),
                        byteValue,
                        deviceAddress,
                        accDataCccdState == CccdState.INDICATION_ENABLED
                    )
                }
            }
        }
    }

    /**
     * Clean up the resources used by the Accelerometer continuous service.
     */
    override fun cleanupSensorResources() {
        // Clear characteristic references
        accelerometerDataCharacteristic = null
    }
}