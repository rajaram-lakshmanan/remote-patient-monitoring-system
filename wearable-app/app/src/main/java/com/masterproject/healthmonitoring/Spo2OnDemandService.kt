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
 * Manager for the Blood Oxygen (SpO2) on demand (trigger) BLE service.
 * Handles SpO2 data collection from device sensors using Samsung Health Sensor SDK and BLE notifications.
 */
class Spo2OnDemandService(service: HealthMonitoringService) : BaseOnDemandSensorService(service) {
    companion object {
        // Typically it requires at least 30 seconds to collect data for SpO2
        // But it seems, when the trigger is activated when other sensors are streaming continuously, it is better to
        // wait for bit long. Additional delay will be added when pausing the active sensors and starting this sensor
        private const val MEASUREMENT_DURATION = 45000

        // Typically sending 1 broadcast every second
        private const val MEASUREMENT_TICK = 1000
    }

    override fun getTAG() = "Spo2Service"

    override val healthTrackerType = HealthTrackerType.SPO2_ON_DEMAND

    /**
     * Return the type of the sensor (SpO2) used by this service.
     */
    override fun getSensorType(): SensorType {
        return SensorType.SPO2
    }

    // Parameters used using the measurement of the SpO2 data
    private val isMeasurementRunning = AtomicBoolean(false)

    // Characteristics to represent the Spo2 data (processed value of SpO2 and status), and
    // the trigger (only write characteristic)
    private var spo2DataCharacteristic: BluetoothGattCharacteristic? = null
    private var measureSpo2TriggerCharacteristic: BluetoothGattCharacteristic? = null

    // Latest SpO2 values
    @Volatile
    private var latestSpo2Data = Spo2Data(0, 0, 0)

    /**
     * Setup the BLE Gatt Service to represent the SpO2 data.
     */
    override fun setupService() {
        // Create Spo2 (on-demand) Service
        val spo2Service = createBluetoothGattService(BleConstants.Spo2Service.SERVICE_UUID)

        // Create Spo2 Value and status Characteristics and add it to the service
        spo2DataCharacteristic = createGattReadCharacteristicWithCccd(BleConstants.Spo2Service.SPO2_DATA_UUID)
        spo2DataCharacteristic?.let { spo2Service.addCharacteristic(it) }

        // Create SpO2 measurement trigger Characteristic (write)
        measureSpo2TriggerCharacteristic = createGattWriteCharacteristicWithCccd(BleConstants.Spo2Service.TRIGGER_UUID)
        measureSpo2TriggerCharacteristic?.let { spo2Service.addCharacteristic(it) }

        // Add service to GATT server via intent
        val intent = Intent(BleConstants.ACTION_GATT_ADD_SERVICE)
        intent.putExtra(BleConstants.INTENT_SERVICE, spo2Service)
        LocalBroadcastManager.getInstance(service.applicationContext).sendBroadcast(intent)
        Log.i(getTAG(), "Spo2 service setup complete")
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
            BleConstants.Spo2Service.SPO2_DATA_UUID -> {
                latestSpo2Data.spo2DataToByteArray()
            }

            else -> {
                Log.w(getTAG(), "Received read request for unknown or write characteristic: $uuid")
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
     * Write characteristic is mainly used to trigger the start of the measurement of SpO2 for the specified
     * time period, typically 30 seconds.
     */
    override fun handleCharacteristicWriteRequest(characteristicUuid: UUID, deviceAddress: String, value: ByteArray?) {
        when (characteristicUuid) {
            BleConstants.Spo2Service.TRIGGER_UUID -> {
                Log.d(getTAG(), "Trigger Spo2 measurement")
                isMeasurementRunning.set(true)

                // Initiate the health tracker for SpO2 and pause all continuous sensors
                trigger()

                countDownTimer.cancel()
                countDownTimer.start()
                Log.d(getTAG(), "Spo2 measurement timer started")
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
            BleConstants.Spo2Service.SPO2_DATA_UUID -> {
                val byteValue = latestSpo2Data.spo2DataToByteArray()
                notifyCharacteristic(
                    BleConstants.Spo2Service.SPO2_DATA_UUID.toString(),
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
             * Triggered when the Samsung's Health Tracking Service (SpO2) sends data to the application.
             * @param dataPoints DataPoint list for the ECG HealthTrackerType.
             */
            override fun onDataReceived(dataPoints: List<DataPoint>) {
                if (dataPoints.isEmpty()) return

                for (data in dataPoints) {
                    try {
                        // Process SPO2 value
                        val value = try {
                             data.getValue(ValueKey.SpO2Set.SPO2)
                        } catch (e: Exception) {
                            0 // Default value
                        }

                        // Process status
                        val status = try {
                            data.getValue(ValueKey.SpO2Set.STATUS)
                        } catch (e: Exception) {
                            -6  // Timeout status code
                        }

                        // Broadcasting of the data is performed by the count down timer
                        latestSpo2Data = Spo2Data(value, status.toShort(), data.timestamp)
                    } catch (e: Exception) {
                        Log.e(getTAG(), "Error processing spo2 data: ${e.message}")
                    }
                }
            }

            /**
             * Triggered when the Samsung's Health Tracking Service (SpO2) encounters errors.
             * @param error Error typically occurs when there is a permission or SDK policy issues.
             */
            override fun onError(error: HealthTracker.TrackerError) {
                Log.e(getTAG(), "Spo2 tracker error: $error")
            }

            /**
             * Triggered when the gathered data from the Samsung's Health Tracking Service (SpO2) is flushed. Flush
             * provides the functionality to collect the data instantly without waiting for the data received event.
             * Remarks:
             * Flush is not used in the application.
             */
            override fun onFlushCompleted() {
                Log.d(getTAG(), "Spo2 data flush completed")
            }
        }
    }

    /**
     * Broadcast the latest SpO2 sensor data along with the timestamp to the connected devices.
     */
    override fun broadcastSensorData() {
        if (!isGattServerReady) return

        // Find devices that have notifications enabled for SpO2 and notify the change in the characteristic value
        synchronized(connectedDevices) {
            for (deviceAddress in connectedDevices) {
                // Notify Spo2 value
                val cccdSpO2DataKey =
                    "${deviceAddress}:${BleConstants.Spo2Service.SPO2_DATA_UUID}:${BleConstants.CCCD_UUID}"
                val spo2DataCccdState = descriptorValueMap[cccdSpO2DataKey]
                if (CccdState.isEnabled(spo2DataCccdState)) {
                    val byteValue = latestSpo2Data.spo2DataToByteArray()
                    notifyCharacteristic(
                        BleConstants.Spo2Service.SPO2_DATA_UUID.toString(),
                        byteValue,
                        deviceAddress,
                        spo2DataCccdState == CccdState.INDICATION_ENABLED
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

        // Reset measurement values
        latestSpo2Data = Spo2Data(0, 0, 0)

        // Clear characteristic references
        spo2DataCharacteristic = null
        measureSpo2TriggerCharacteristic = null
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
        }
    }
}