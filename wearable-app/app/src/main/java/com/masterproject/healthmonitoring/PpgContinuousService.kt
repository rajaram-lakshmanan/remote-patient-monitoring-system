package com.masterproject.healthmonitoring

import android.bluetooth.BluetoothGattCharacteristic
import android.content.Intent
import android.util.Log
import androidx.localbroadcastmanager.content.LocalBroadcastManager
import com.samsung.android.service.health.tracking.HealthTracker
import com.samsung.android.service.health.tracking.data.DataPoint
import com.samsung.android.service.health.tracking.data.HealthTrackerType
import com.samsung.android.service.health.tracking.data.PpgType
import com.samsung.android.service.health.tracking.data.ValueKey
import java.util.UUID

/**
 * Manager for the Photoplethysmogram (PPG) continuous (streaming) BLE service.
 * Handles PPG data collection from device sensors using Samsung Health Sensor SDK and BLE notifications.
 */
class PpgContinuousService(service: HealthMonitoringService) : BaseContinuousSensorService(service) {
    override fun getTAG() = "PpgService"

    override val healthTrackerType = HealthTrackerType.PPG_CONTINUOUS

    /**
     * Return the type of the sensor (PPG) gathered by this service.
     */
    override fun getSensorType(): SensorType {
        return SensorType.PPG
    }

    // Characteristics to represent raw data of the PPG Green, Red, and IR values and statuses
    // Note: Status will return -1 if other the device is busy with other sensors. As the watch
    // is used to track all continuous sensors, PPG may return -1
    private var ppgGreenDataCharacteristic: BluetoothGattCharacteristic? = null
    private var ppgRedDataCharacteristic: BluetoothGattCharacteristic? = null
    private var ppgIrDataCharacteristic: BluetoothGattCharacteristic? = null

    // Latest PPG values
    @Volatile
    private var latestPpgData = PpgData(0, 0, 0, 0, 0, 0, 0)

    // Rate limiting for BLE notifications
    private var lastNotificationTime = 0L

    // As per Samsung Health Sensor SDK, PPG values are measured with a 25 Hz frequency
    private val minNotificationIntervalMs = 40

    /**
     * Creates the PPG Health tracker. For PPG health tracker, it is mandatory to pass the PPG type set.
     *
     * Hence, this has to be overridden to create the health tracker by specifying PPG green type set.
     *
     * Remarks:
     * Set an event listener for this HealthTracker instance. If it succeeds, the event listener exists and
     * retrieves sensor data until the unsetEventListener() call.
     *
     * Only 1 HealthTrackerType's event listener can be set in 1 application.
     *
     * Adding multiple event listeners for the same HealthTrackerType in 1 application is unavailable.
     */
    override fun createHealthTracker() : HealthTracker?{
        return service.healthTracking!!.getHealthTracker(healthTrackerType, setOf(PpgType.GREEN))
    }

    /**
     * Setup the BLE Gatt Service to represent the PPG data.
     */
    override fun setupService() {
        // Create PPG (Continuous) Service
        val ppgService = createBluetoothGattService(BleConstants.PpgService.SERVICE_UUID)

        // Create PPG Green, Red, and IR (Values and Statuses) Characteristics and add it to the service
        ppgGreenDataCharacteristic = createGattReadCharacteristicWithCccd(BleConstants.PpgService.PPG_GREEN_DATA_UUID)
        ppgGreenDataCharacteristic?.let { ppgService.addCharacteristic(it) }

        ppgRedDataCharacteristic = createGattReadCharacteristicWithCccd(BleConstants.PpgService.PPG_RED_DATA_UUID)
        ppgRedDataCharacteristic?.let { ppgService.addCharacteristic(it) }

        ppgIrDataCharacteristic = createGattReadCharacteristicWithCccd(BleConstants.PpgService.PPG_IR_DATA_UUID)
        ppgIrDataCharacteristic?.let { ppgService.addCharacteristic(it) }

        // Add service to GATT server via intent
        val intent = Intent(BleConstants.ACTION_GATT_ADD_SERVICE)
        intent.putExtra(BleConstants.INTENT_SERVICE, ppgService)
        LocalBroadcastManager.getInstance(service.applicationContext).sendBroadcast(intent)
        Log.i(getTAG(), "PPG service setup complete")
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
            BleConstants.PpgService.PPG_GREEN_DATA_UUID -> {
                latestPpgData.ppgGreenDataToByteArray()
            }

            BleConstants.PpgService.PPG_RED_DATA_UUID -> {
                latestPpgData.ppgRedDataToByteArray()
            }

            BleConstants.PpgService.PPG_IR_DATA_UUID -> {
                latestPpgData.ppgIRDataToByteArray()
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
            BleConstants.PpgService.PPG_GREEN_DATA_UUID -> {
                val byteValue = latestPpgData.ppgGreenDataToByteArray()
                notifyCharacteristic(
                    BleConstants.PpgService.PPG_GREEN_DATA_UUID.toString(),
                    byteValue,
                    deviceAddress,
                    state == CccdState.INDICATION_ENABLED
                )
            }

            BleConstants.PpgService.PPG_RED_DATA_UUID -> {
                val byteValue = latestPpgData.ppgRedDataToByteArray()
                notifyCharacteristic(
                    BleConstants.PpgService.PPG_RED_DATA_UUID.toString(),
                    byteValue,
                    deviceAddress,
                    state == CccdState.INDICATION_ENABLED
                )
            }

            BleConstants.PpgService.PPG_IR_DATA_UUID -> {
                val byteValue = latestPpgData.ppgIRDataToByteArray()
                notifyCharacteristic(
                    BleConstants.PpgService.PPG_IR_DATA_UUID.toString(),
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
             * Triggered when the Samsung's Health Tracking Service (PPG) sends data to the application.
             * @param dataPoints DataPoint list for the PPG HealthTrackerType.
             */
            override fun onDataReceived(dataPoints: List<DataPoint>) {
                for (data in dataPoints) {
                    try {
                        // Get PPG green value
                        val greenValue: Int = try {
                            data.getValue(ValueKey.PpgSet.PPG_GREEN)
                        } catch (e: Exception) {
                            0 // Default value
                        }

                        // Get PPG green status
                        val greenStatus: Int = try {
                            data.getValue(ValueKey.PpgSet.GREEN_STATUS)
                        } catch (e: Exception) {
                            -1 // Default value
                        }

                        // Get PPG red value
                        val redValue: Int = try {
                            data.getValue(ValueKey.PpgSet.PPG_RED)
                        } catch (e: Exception) {
                            0 // Default if not available
                        }

                        // Get PPG red status
                        val redStatus: Int = try {
                            data.getValue(ValueKey.PpgSet.RED_STATUS)
                        } catch (e: Exception) {
                            -1 // Default value
                        }

                        // Get PPG IR value
                        val irValue: Int = try {
                            data.getValue(ValueKey.PpgSet.PPG_IR)
                        } catch (e: Exception) {
                            0 // Default value
                        }

                        // Get PPG ir status
                        val irStatus: Int = try {
                            data.getValue(ValueKey.PpgSet.IR_STATUS)
                        } catch (e: Exception) {
                            -1 // Default value
                        }

                        // Update the PPG data model (raw values, statuses, and timestamp in milliseconds) and
                        // broadcast the data to the client
                        latestPpgData = PpgData(greenValue, greenStatus.toShort(), redValue, redStatus.toShort(), irValue, irStatus.toShort(), data.timestamp)
                        broadcastSensorData()
                    } catch (e: Exception) {
                        Log.e(getTAG(), "Error processing PPG data: ${e.message}")
                    }
                }
            }

            /**
             * Triggered when the Samsung's Health Tracking Service (PPG) encounters errors.
             * @param error Error typically occurs when there is a permission or SDK policy issues.
             */
            override fun onError(error: HealthTracker.TrackerError) {
                Log.e(getTAG(), "PPG tracker error: $error")
            }

            /**
             * Triggered when the gathered data from the Samsung's Health Tracking Service (PPG) is flushed. Flush
             * provides the functionality to collect the data instantly without waiting for the data received event.
             * Remarks:
             * Flush is not used in the application.
             */
            override fun onFlushCompleted() {
                Log.d(getTAG(), "PPG data flush completed")
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

        // Find devices that have notifications enabled for PPG and notify the change in the characteristic value
        synchronized(connectedDevices) {
            for (deviceAddress in connectedDevices) {
                // Notify PPG Green value & status
                val cccdGreenDataKey = "${deviceAddress}:${BleConstants.PpgService.PPG_GREEN_DATA_UUID}:${BleConstants.CCCD_UUID}"
                val greenDataCccdState = descriptorValueMap[cccdGreenDataKey]
                if (CccdState.isEnabled(greenDataCccdState)) {
                    val byteValue = latestPpgData.ppgGreenDataToByteArray()
                    notifyCharacteristic(
                        BleConstants.PpgService.PPG_GREEN_DATA_UUID.toString(),
                        byteValue,
                        deviceAddress,
                        greenDataCccdState == CccdState.INDICATION_ENABLED
                    )
                }

                // Notify PPG Red value & status
                val cccdRedDataKey = "${deviceAddress}:${BleConstants.PpgService.PPG_RED_DATA_UUID}:${BleConstants.CCCD_UUID}"
                val redDataCccdState = descriptorValueMap[cccdRedDataKey]
                if (CccdState.isEnabled(redDataCccdState)) {
                    val byteValue = latestPpgData.ppgRedDataToByteArray()
                    notifyCharacteristic(
                        BleConstants.PpgService.PPG_RED_DATA_UUID.toString(),
                        byteValue,
                        deviceAddress,
                        redDataCccdState == CccdState.INDICATION_ENABLED
                    )
                }

                // Notify PPG IR value & status
                val cccdIrDataKey = "${deviceAddress}:${BleConstants.PpgService.PPG_IR_DATA_UUID}:${BleConstants.CCCD_UUID}"
                val irDataCccdState = descriptorValueMap[cccdIrDataKey]
                if (CccdState.isEnabled(irDataCccdState)) {
                    val byteValue = latestPpgData.ppgIRDataToByteArray()
                    notifyCharacteristic(
                        BleConstants.PpgService.PPG_IR_DATA_UUID.toString(),
                        byteValue,
                        deviceAddress,
                        irDataCccdState == CccdState.INDICATION_ENABLED
                    )
                }
            }
        }
    }

    /**
     * Clean up the resources used by the PPG continuous service.
     */
    override fun cleanupSensorResources() {
        // Clear characteristic references
        ppgGreenDataCharacteristic = null
        ppgRedDataCharacteristic = null
        ppgIrDataCharacteristic = null
    }
}