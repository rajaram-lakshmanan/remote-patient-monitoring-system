package com.masterproject.healthmonitoring

import android.bluetooth.BluetoothGattCharacteristic
import android.content.Intent
import android.os.CountDownTimer
import android.util.Log
import androidx.localbroadcastmanager.content.LocalBroadcastManager
import com.samsung.android.service.health.tracking.HealthTracker
import com.samsung.android.service.health.tracking.HealthTracker.TrackerEventListener
import com.samsung.android.service.health.tracking.data.DataPoint
import com.samsung.android.service.health.tracking.data.HealthTrackerType
import com.samsung.android.service.health.tracking.data.ValueKey
import java.util.UUID
import java.util.concurrent.atomic.AtomicBoolean

/**
 * Manager for the ECG on demand (trigger) BLE service.
 * Handles Ecg data collection from device sensors using Samsung Health Sensor SDK and BLE notifications.
 */
class EcgOnDemandService(service: HealthMonitoringService) : BaseOnDemandSensorService(service) {
    companion object {
        // Typically it requires at least 30 seconds to collect data for ECG
        private const val MEASUREMENT_DURATION = 45000

        // Typically sending 1 broadcast every second
        private const val MEASUREMENT_TICK = 1000
    }

    override fun getTAG() = "EcgService"

    override val healthTrackerType = HealthTrackerType.ECG_ON_DEMAND

    /**
     * Return the type of the sensor (ECG) gathered by this service.
     */
    override fun getSensorType(): SensorType {
        return SensorType.ECG
    }

    // Parameters used using the measurement of the ECG data
    private val isMeasurementRunning = AtomicBoolean(false)

    // Characteristic to represent raw data of the ecg value (mV), sequence, status, and
    // the trigger (only write characteristic)
    private var ecgDataCharacteristic: BluetoothGattCharacteristic? = null
    private var measureEcgTriggerCharacteristic: BluetoothGattCharacteristic? = null

    // Latest ECG values
    @Volatile
    private var latestEcgData = EcgData(0f, 0, 0, 0)

    /**
     * Setup the BLE Gatt Service to represent the ECG data.
     */
    override fun setupService() {
        // Create Ecg (on-demand) Service
        val ecgService = createBluetoothGattService(BleConstants.EcgService.SERVICE_UUID)

        // Create ECG value, sequence, status (lead-off) Characteristics and add it to the service
        ecgDataCharacteristic = createGattReadCharacteristicWithCccd(BleConstants.EcgService.ECG_DATA_UUID)
        ecgDataCharacteristic?.let { ecgService.addCharacteristic(it) }

        // Create Ecg measurement trigger Characteristic (write)
        measureEcgTriggerCharacteristic = createGattWriteCharacteristicWithCccd(BleConstants.EcgService.TRIGGER_UUID)
        measureEcgTriggerCharacteristic?.let { ecgService.addCharacteristic(it) }

        // Add service to GATT server via intent
        val intent = Intent(BleConstants.ACTION_GATT_ADD_SERVICE)
        intent.putExtra(BleConstants.INTENT_SERVICE, ecgService)
        LocalBroadcastManager.getInstance(service.applicationContext).sendBroadcast(intent)
        Log.i(getTAG(), "Ecg service setup complete")
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
            BleConstants.EcgService.ECG_DATA_UUID -> {
                latestEcgData.ecgDataToByteArray()
            }

            else -> {
                Log.w(getTAG(), "Received read request for unknown characteristic: $uuid")
                null
            }
        }

        sendCharacteristicReadResponse(deviceAddress, requestId, offset, value)
    }

    /**
     * Handle the write characteristics request from the client.
     * @param characteristicUuid The UUID of the specific characteristic the client is requesting to write.
     * @param deviceAddress The Bluetooth MAC address of the client device making the write request.
     * @param value Value of the characteristic to be updated.
     *
     * Write characteristic is mainly used to trigger the start of the measurement of ECG for the specified
     * time period, typically 30 seconds.
     */
    override fun handleCharacteristicWriteRequest(characteristicUuid: UUID, deviceAddress: String, value: ByteArray?) {
        when (characteristicUuid) {
            BleConstants.EcgService.TRIGGER_UUID -> {
                Log.d(getTAG(), "Trigger Ecg measurement")
                isMeasurementRunning.set(true)

                // Initiate the health tracker for ECG and pause all continuous sensors
                trigger()

                // Reset any existing countdown time and start the measurement
                countDownTimer.cancel()
                countDownTimer.start()
                Log.d(getTAG(), "Ecg measurement has started")
            }

            else -> {
                Log.w(getTAG(), "Received write request for unknown characteristic: $characteristicUuid")
            }
        }
    }

    /**
     * Handle the descriptor write request by sending current value of the characteristic when the received request from
     * the client is to enable notification or indication of the descriptor.
     * @param characteristicUuid The UUID of the specific characteristic the client is enabling the notification.
     * @param deviceAddress The Bluetooth MAC address of the client device making the read request.
     * @param state State of the CCCD: Notifications and indications disabled, Notifications enabled, and
     * Indications enabled.
     * Remarks:
     * Descriptor write for 'write characteristic - trigger' is not supported as these are only acting to trigger the
     * start of the measurement and notifications should not be supported (though CCCD is added to the characteristic).
     */
    override fun onDescriptorWriteRequest(characteristicUuid: UUID, deviceAddress: String, state: CccdState) {
        when (characteristicUuid) {
            BleConstants.EcgService.ECG_DATA_UUID -> {
                val byteValue = latestEcgData.ecgDataToByteArray()
                notifyCharacteristic(
                    BleConstants.EcgService.ECG_DATA_UUID.toString(),
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
    override fun createSensorListener(): TrackerEventListener {
        return object : TrackerEventListener {
            /**
             * Triggered when the Samsung's Health Tracking Service (Accelerometer) sends data to the application.
             * @param dataPoints DataPoint list for the ECG HealthTrackerType.
             */
            override fun onDataReceived(dataPoints: List<DataPoint>) {
                // Measured Electrocardiogram (ECG) data list has 5 or 10 DataPoints, depending on a sensor's
                // operation status
                // 1st DataPoint includes: ECG_MV, PPG_GREEN, LEAD_OFF, SEQUENCE, MAX_THRESHOLD_MV, and MIN_THRESHOLD_MV
                // 2nd DataPoint to 5th DataPoint and 7th to 10th DataPoint include only ECG_MV values
                // 6th DataPoint includes: ECG_MV and PPG_GREEN
                if (dataPoints.isEmpty()) return

                try {
                    // When there is no contact with the electrodes, do not need to respond, the client should determine
                    // there is no data and indicate the electrodes are not connected or in contact
                    val leadOffValue: Int = dataPoints[0].getValue(ValueKey.EcgSet.LEAD_OFF)

                    // Value of 5 is no contact
                    val isLeadOff : Boolean = leadOffValue == 5

                    // Sequence number of the data
                    val sequence: Int = dataPoints[0].getValue(ValueKey.EcgSet.SEQUENCE)
                    val timeStamp: Long = dataPoints[0].timestamp

                    // Take average of the 10 data points
                    var sum = 0f
                    for (data in dataPoints) {
                        val curEcg = data.getValue(ValueKey.EcgSet.ECG_MV)
                        sum += curEcg
                    }
                    val avgEcg = sum / dataPoints.size

                    // Broadcasting of the data is performed by the count down timer
                    latestEcgData = EcgData(avgEcg, if (isLeadOff) 1 else 0, sequence.toShort(), timeStamp)
                } catch (e: Exception) {
                    Log.e(getTAG(), "Error processing Ecg data: ${e.message}")
                }
            }

            /**
             * Triggered when the Samsung's Health Tracking Service (ECG) encounters errors.
             * @param error Error typically occurs when there is a permission or SDK policy issues.
             */
            override fun onError(error: HealthTracker.TrackerError) {
                Log.e(getTAG(), "Ecg tracker error: $error")
            }

            /**
             * Triggered when the gathered data from the Samsung's Health Tracking Service (ECG) is flushed. Flush
             * provides the functionality to collect the data instantly without waiting for the data received event.
             * Remarks:
             * Flush is not used in the application.
             */
            override fun onFlushCompleted() {
                Log.d(getTAG(), "Ecg data flush completed")
            }
        }
    }

    /**
     * Broadcast the latest ECG sensor data along with the timestamp to the connected devices.
     */
    override fun broadcastSensorData() {
        if (!isGattServerReady) return

        // Find devices that have notifications enabled for ECG and notify the change in the characteristic value
        synchronized(connectedDevices) {
            for (deviceAddress in connectedDevices) {
                // Notify Ecg value
                val cccdEcgDataKey =
                    "${deviceAddress}:${BleConstants.EcgService.ECG_DATA_UUID}:${BleConstants.CCCD_UUID}"
                val ecgDataCccdState = descriptorValueMap[cccdEcgDataKey]
                if (CccdState.isEnabled(ecgDataCccdState)) {
                    val byteValue = latestEcgData.ecgDataToByteArray()
                    notifyCharacteristic(
                        BleConstants.EcgService.ECG_DATA_UUID.toString(),
                        byteValue,
                        deviceAddress,
                        ecgDataCccdState == CccdState.INDICATION_ENABLED
                    )
                }
            }
        }
    }

    /**
     * Clean up the resources used by the ECG on-demand service.
     */
    override fun cleanupSensorResources() {
        // Cancel timer if active
        countDownTimer.cancel()
        isMeasurementRunning.set(false)

        // Clear characteristic references
        ecgDataCharacteristic = null
        measureEcgTriggerCharacteristic = null
    }

    /**
     * Timer that manages sensor data collection over the specified measurement duration.
     */
    private var countDownTimer: CountDownTimer = object : CountDownTimer(MEASUREMENT_DURATION.toLong(), MEASUREMENT_TICK.toLong()) {
        /**
         * The timer broadcasts sensor data at regular intervals defined by MEASUREMENT_TICK (100ms),
         * providing 10 updates per second. Data collection starts after a 2-second initialization
         * period to allow sensors to stabilize.
         * @param timeLeft Time left for the measurement.
         */
        override fun onTick(timeLeft: Long) {
            if (timeLeft > MEASUREMENT_DURATION - 2000) return
            if (isMeasurementRunning.get()) {
                broadcastSensorData()
            }
        }

        /**
         * When the timer completes (after MEASUREMENT_DURATION), the collection completed callback is triggered and final
         * sensor data is broadcast.
         */
        override fun onFinish() {
            collectionCompleted()
            isMeasurementRunning.set(false)

            broadcastSensorData()
            latestEcgData = EcgData(0f, 0, 0, 0)
        }
    }
}