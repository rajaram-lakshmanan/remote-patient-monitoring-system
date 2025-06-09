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
 * Manager for the Heart rate continuous (streaming) BLE service.
 * Handles Heart rate data collection from device sensors using Samsung Health Sensor SDK and BLE notifications.
 */
class HeartRateContinuousService(service: HealthMonitoringService) : BaseContinuousSensorService(service) {
    override fun getTAG() = "HeartRateService"

    override val healthTrackerType = HealthTrackerType.HEART_RATE_CONTINUOUS

    /**
     * Return the type of the sensor (Heart rate) gathered by this service.
     */
    override fun getSensorType(): SensorType {
        return SensorType.HEART_RATE
    }

    // Characteristic which will contain both the measured heart rate value and the status
    private var heartRateDataCharacteristic: BluetoothGattCharacteristic? = null

    // Latest Heart rate values
    @Volatile
    private var latestHeartRateData = HeartRateData(0, 0, 0)

    /**
     * Setup the BLE Gatt Service to represent the Heart rate data.
     */
    override fun setupService() {
        // Create Heart Rate (Continuous) Service
        val heartRateService = createBluetoothGattService(BleConstants.HeartRateService.SERVICE_UUID)

        // Create Heart Rate Measurement and status Characteristic and add it to the service
        heartRateDataCharacteristic = createGattReadCharacteristicWithCccd(BleConstants.HeartRateService.DATA_UUID)
        heartRateDataCharacteristic?.let { heartRateService.addCharacteristic(it) }

        // Add service to GATT server via intent
        val intent = Intent(BleConstants.ACTION_GATT_ADD_SERVICE)
        intent.putExtra(BleConstants.INTENT_SERVICE, heartRateService)
        LocalBroadcastManager.getInstance(service.applicationContext).sendBroadcast(intent)
        Log.i(getTAG(), "Heart rate service setup complete")
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
            BleConstants.HeartRateService.DATA_UUID -> {
                latestHeartRateData.heartRateDataToByteArray()
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
            BleConstants.HeartRateService.DATA_UUID -> {
                val byteValue = latestHeartRateData.heartRateDataToByteArray()
                notifyCharacteristic(
                    BleConstants.HeartRateService.DATA_UUID.toString(),
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
            override fun onDataReceived(dataPoints: List<DataPoint>) {
                for (data in dataPoints) {
                    try {
                        val heartRateValue: Int = try {
                            data.getValue(ValueKey.HeartRateSet.HEART_RATE)
                        } catch (e: Exception) {
                            0 // Default value
                        }

                        // Get heart rate status if available
                        val status: Int = try {
                            data.getValue(ValueKey.HeartRateSet.HEART_RATE_STATUS)
                        } catch (e: Exception) {
                            0 // Default value
                        }

                        // Update the Heart rate data model (value, status, and timestamp in milliseconds) and
                        // broadcast the data to the client
                        latestHeartRateData = HeartRateData(heartRateValue, status.toShort(), data.timestamp)
                        broadcastSensorData()
                    } catch (e: Exception) {
                        Log.e(getTAG(), "Error processing heart rate data: ${e.message}")
                    }
                }
            }

            /**
             * Triggered when the Samsung's Health Tracking Service (Heart rate) encounters errors.
             * @param error Error typically occurs when there is a permission or SDK policy issues.
             */
            override fun onError(error: HealthTracker.TrackerError) {
                Log.e(getTAG(), "Heart rate tracker error: $error")
            }

            /**
             * Triggered when the gathered data from the Samsung's Health Tracking Service (Heart rate) is flushed. Flush
             * provides the functionality to collect the data instantly without waiting for the data received event.
             * Remarks:
             * Flush is not used in the application.
             */
            override fun onFlushCompleted() {
                Log.d(getTAG(), "Heart rate data flush completed")
            }
        }
    }

    /**
     * Broadcast the latest heart rate sensor data along with the timestamp to the connected devices.
     */
    override fun broadcastSensorData() {
        if (!isGattServerReady) return

        // Find devices that have notifications enabled for accelerometer and notify the change in the characteristic value
        synchronized(connectedDevices) {
            for (deviceAddress in connectedDevices) {
                // Notify heart rate measurement - Including timestamp, heart rate measurement value, and status
                val cccdHeartRateKey =
                    "${deviceAddress}:${BleConstants.HeartRateService.DATA_UUID}:${BleConstants.CCCD_UUID}"
                val heartRateCccdState = descriptorValueMap[cccdHeartRateKey]
                if (CccdState.isEnabled(heartRateCccdState)) {
                    val byteValue = latestHeartRateData.heartRateDataToByteArray()
                    notifyCharacteristic(
                        BleConstants.HeartRateService.DATA_UUID.toString(),
                        byteValue,
                        deviceAddress,
                        heartRateCccdState == CccdState.INDICATION_ENABLED
                    )
                }
            }
        }
    }

    /**
     * Clean up the resources used by the Heart rate continuous service.
     */
    override fun cleanupSensorResources() {
        // Clear characteristic references
        heartRateDataCharacteristic = null
    }
}