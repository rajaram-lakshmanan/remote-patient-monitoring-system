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
 * Manager for the Temperature continuous (streaming) BLE service.
 * Handles temperature data collection from device sensors using Samsung Health Sensor SDK and BLE notifications.
 */
class TemperatureContinuousService(service: HealthMonitoringService) : BaseContinuousSensorService(service) {
    override fun getTAG() = "TemperatureService"

    override val healthTrackerType = HealthTrackerType.SKIN_TEMPERATURE_CONTINUOUS

    /**
     * Return the type of the sensor (Temperature) used by this service.
     */
    override fun getSensorType(): SensorType {
        return SensorType.SKIN_TEMPERATURE
    }

    // Characteristics to represent the object and ambient temperature values, and status of the measurement
    private var temperatureDataCharacteristic: BluetoothGattCharacteristic? = null

    // Latest temperature values
    @Volatile
    private var latestTemperatureData = TemperatureData(0f, 0f, 0, 0)

    /**
     * Setup the BLE Gatt Service to represent the Temperature data.
     */
    override fun setupService() {
        // Create Temperature (Continuous) Service
        val temperatureService = createBluetoothGattService(BleConstants.TemperatureService.SERVICE_UUID)

        // Create Object and Ambient temperature Characteristics and add it to the service
        temperatureDataCharacteristic =
            createGattReadCharacteristicWithCccd(BleConstants.TemperatureService.TEMPERATURE_DATA_UUID)
        temperatureDataCharacteristic?.let { temperatureService.addCharacteristic(it) }

        // Add service to GATT server via intent
        val intent = Intent(BleConstants.ACTION_GATT_ADD_SERVICE)
        intent.putExtra(BleConstants.INTENT_SERVICE, temperatureService)
        LocalBroadcastManager.getInstance(service.applicationContext).sendBroadcast(intent)
        Log.i(getTAG(), "Temperature service setup complete")
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
            BleConstants.TemperatureService.TEMPERATURE_DATA_UUID -> {
                latestTemperatureData.temperatureDataToByteArray()
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
            BleConstants.TemperatureService.TEMPERATURE_DATA_UUID -> {
                val byteValue = latestTemperatureData.temperatureDataToByteArray()
                notifyCharacteristic(
                    BleConstants.TemperatureService.TEMPERATURE_DATA_UUID.toString(),
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
             * Triggered when the Samsung's Health Tracking Service (Temperature) sends data to the application.
             * @param dataPoints DataPoint list for the Temperature HealthTrackerType.
             */
            override fun onDataReceived(dataPoints: List<DataPoint>) {
                for (data in dataPoints) {
                    try {
                        // Get object temperature value (in Celsius)
                        val objectTemperatureValue: Float = try {
                            data.getValue(ValueKey.SkinTemperatureSet.OBJECT_TEMPERATURE)
                        } catch (e: Exception) {
                            36.5f // Default to normal body temp if not available
                        }

                        // Get ambient temperature value (in Celsius)
                        val ambientTemperatureValue: Float = try {
                            data.getValue(ValueKey.SkinTemperatureSet.AMBIENT_TEMPERATURE)
                        } catch (e: Exception) {
                            24f // Default to normal ambient temp if not available
                        }

                        // Get temperature status if available
                        val status: Int = try {
                            data.getValue(ValueKey.SkinTemperatureSet.STATUS)
                        } catch (e: Exception) {
                            -1 // Default to unreliable if not available
                        }

                        // Update the temperature data model (processed values and timestamp in milliseconds) and
                        // broadcast the data to the client
                        latestTemperatureData = TemperatureData(objectTemperatureValue, ambientTemperatureValue, status.toShort(), data.timestamp)
                        broadcastSensorData()
                    } catch (e: Exception) {
                        Log.e(getTAG(), "Error processing temperature data: ${e.message}")
                    }
                }
            }

            /**
             * Triggered when the Samsung's Health Tracking Service (Temperature) encounters errors.
             * @param error Error typically occurs when there is a permission or SDK policy issues.
             */
            override fun onError(error: HealthTracker.TrackerError) {
                Log.e(getTAG(), "Temperature tracker error: $error")
            }

            /**
             * Triggered when the gathered data from the Samsung's Health Tracking Service (Temperature) is flushed. Flush
             * provides the functionality to collect the data instantly without waiting for the data received event.
             * Remarks:
             * Flush is not used in the application.
             */
            override fun onFlushCompleted() {
                Log.d(getTAG(), "Temperature data flush completed")
            }
        }
    }

    /**
     * Broadcast the latest temperature sensor data along with the timestamp to the connected devices.
     */
    override fun broadcastSensorData() {
        if (!isGattServerReady) return

        // Find devices that have notifications enabled for temperature and notify the change in the characteristic value
        synchronized(connectedDevices) {
            for (deviceAddress in connectedDevices) {
                // Notify temperature values (object and ambient) and status information incl. timestamp
                val cccdTemperatureDataKey =
                    "${deviceAddress}:${BleConstants.TemperatureService.TEMPERATURE_DATA_UUID}:${BleConstants.CCCD_UUID}"
                val temperatureDataCccdState = descriptorValueMap[cccdTemperatureDataKey]
                if (CccdState.isEnabled(temperatureDataCccdState)) {
                    val byteValue = latestTemperatureData.temperatureDataToByteArray()
                    notifyCharacteristic(
                        BleConstants.TemperatureService.TEMPERATURE_DATA_UUID.toString(),
                        byteValue,
                        deviceAddress,
                        temperatureDataCccdState == CccdState.INDICATION_ENABLED
                    )
                }
            }
        }
    }

    /**
     * Clean up the resources used by the Temperature continuous service.
     */
    override fun cleanupSensorResources() {
        // Clear characteristic references
        temperatureDataCharacteristic = null
    }
}