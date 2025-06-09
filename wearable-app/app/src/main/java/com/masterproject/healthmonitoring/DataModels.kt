package com.masterproject.healthmonitoring

import android.util.Log
import java.nio.ByteBuffer
import java.nio.ByteOrder

/**
 * Data models for sensor data with serialization methods. These models provide structured data objects
 * with efficient binary conversion for BLE transmission. Applies only for sensor data (read-only). So, not providing
 * any deserialization methods.
 *
 * Remarks:
 * Status value could be a byte for most part, but as Heart rate can be -999, selected all Status values to be Short.
 *
 */

/**
 * Accelerometer data model.
 * @param x Raw value of the x axis.
 * @param y Raw value of the y axis.
 * @param z Raw value of the z axis.
 * @param timeStamp Timestamp from the sensor.
 * Remarks:
 * Raw value(s) can be converted to m/s2 using: 9.81 / (16383.75 / 4.0)) * value.
 */
data class AccelerometerData(val x: Int, val y: Int, val z: Int, val timeStamp: Long) {
    companion object {
        private const val TAG = "AccelerometerData"
    }

    /**
     * Serialize all the accelerometer raw values (x, y, and z-axis) to byte array.
     */
    fun accelerometerDataToByteArray(): ByteArray {
        try {
            return ByteBuffer.allocate(20)
                .order(ByteOrder.LITTLE_ENDIAN)
                .putLong(timeStamp)
                .putInt(x)
                .putInt(y)
                .putInt(z)
                .array()
        } catch (e: Exception) {
            Log.e(TAG, "Error serializing accelerometer raw data (g): ${e.message}")
            // Return a safe default value in case of error
            return ByteBuffer.allocate(20)
                .order(ByteOrder.LITTLE_ENDIAN)
                .putLong(0)
                .putInt(0)
                .putInt(0)
                .putInt(0)
                .array()
        }
    }
}

/**
 * Heart rate data model.
 * @param heartRate Heart rate value in beats per minute.
 * @param status Status flag for heart rate measurement. The available values are:
 *  0   - Initial heart rate measuring state, or a higher priority sensor, such as BIA, is operating
 *  1   - Successful heart rate measurement
 * -2   - Wearable movement is detected
 * -3	- Wearable is detached
 * -8	- PPG signal is weak or the user moved
 * -10	- PPG signal is too weak or the user is moving around too much
 * -99	- flush() has been called but there is no data
 * -999	- A higher priority sensor, such as BIA, is operating
 * @param timeStamp Timestamp from the sensor.
 */
data class HeartRateData(val heartRate: Int, val status: Short, val timeStamp: Long) {
    companion object {
        private const val TAG = "HeartRateData"
    }

    /**
     * Serialize the timestamp, heart rate value, and status to byte array.
     */
    fun heartRateDataToByteArray(): ByteArray {
        try {
            return ByteBuffer.allocate(14)
                .order(ByteOrder.LITTLE_ENDIAN)
                .putLong(timeStamp)
                .putInt(heartRate)
                .putShort(status)
                .array()
        } catch (e: Exception) {
            Log.e(TAG, "Error serializing heart rate: ${e.message}")
            // Return a safe default value in case of error
            return ByteBuffer.allocate(14)
                .order(ByteOrder.LITTLE_ENDIAN)
                .putLong(0)
                .putInt(0)
                .putShort(0)
                .array()
        }
    }
}

/**
 * Temperature data model.
 * @param objectTemp Temperature of an object contacted with the Galaxy Watch. The value is in Celsius.
 * @param ambientTemp Ambient temperature around the Galaxy Watch. The value is in Celsius.
 * @param status Status flag for temperature measurement. The available values are:
 *  0   - Normal
 * -1   - Error
 * @param timeStamp Timestamp from the sensor.
 */
data class TemperatureData(val objectTemp: Float, val ambientTemp: Float, val status: Short, val timeStamp: Long) {
    companion object {
        private const val TAG = "TemperatureData"
    }

    /**
     * Serialize the timestamp, object temperature, ambient temperature, and status to byte array.
     */
    fun temperatureDataToByteArray(): ByteArray {
        try {
            return ByteBuffer.allocate(18)
                .order(ByteOrder.LITTLE_ENDIAN)
                .putLong(timeStamp)
                .putFloat(objectTemp)
                .putFloat(ambientTemp)
                .putShort(status)
                .array()
        } catch (e: Exception) {
            Log.e(TAG, "Error serializing temperature: ${e.message}")
            // Return a safe default value in case of error
            return ByteBuffer.allocate(18)
                .order(ByteOrder.LITTLE_ENDIAN)
                .putLong(0)
                .putFloat(0.0f)
                .putFloat(0.0f)
                .putShort(0)
                .array()
        }
    }
}

/**
 * Photoplethysmography (PPG) data model.
 * @param ppgGreen PPG green LED's ADC (analog-to-digital) value.
 * @param greenStatus Status flag for Photoplethysmogram (PPG) green data tracking. The available values (Continuous) are:
 *  0   - Normal value
 * -1   - A higher priority sensor, such as BIA, is operating
 * @param ppgRed PPG Red's raw value.
 * @param redStatus Status flag for PPG Red data tracking. The available values (Continuous) are:
 *  0   - Normal value
 * -1   - A higher priority sensor, such as BIA, is operating
 * @param ppgIR PPG IR's raw value.
 * @param irStatus Status flag for PPG Infrared (IR) data tracking. The available values (Continuous) are:
 *  0   - Normal value
 * -1   - A higher priority sensor, such as BIA, is operating
 * @param timeStamp Timestamp from the sensor.
 * Remarks:
 * As many continuous sensors will be enabled, the IR and RED values may return -1
 * Sending PPG Value and Status in three different characteristics as combining them will exceed the default payload of
 * 20 bytes, if the MTU size is not increased by the client.
 */
data class PpgData(
    val ppgGreen: Int,
    val greenStatus: Short,
    val ppgRed: Int,
    val redStatus: Short,
    val ppgIR: Int,
    val irStatus: Short,
    val timeStamp: Long
) {
    companion object {
        private const val TAG = "PpgData"
    }

    /**
     * Serialize the PPG green LED's ADC value to byte array.
     */
    fun ppgGreenDataToByteArray(): ByteArray {
        return ppgDataToByteArray(ppgGreen, greenStatus)
    }

    /**
     * Serialize the PPG Red's raw value to byte array.
     */
    fun ppgRedDataToByteArray(): ByteArray {
        return ppgDataToByteArray(ppgRed, redStatus)
    }

    /**
     * Serialize the PPG IR's raw value to byte array.
     */
    fun ppgIRDataToByteArray(): ByteArray {
        return ppgDataToByteArray(ppgIR, irStatus)
    }

    /**
     * Serialize the specified PPG value and its status to byte array.
     * @param ppgValue PPG value to be converted to byte array.
     * @param status PPG status to be converted to byte array.
     */
    private fun ppgDataToByteArray(ppgValue: Int, status: Short): ByteArray {
        try {
            return ByteBuffer.allocate(14)
                .order(ByteOrder.LITTLE_ENDIAN)
                .putLong(timeStamp)
                .putInt(ppgValue)
                .putShort(status)
                .array()
        } catch (e: Exception) {
            Log.e(TAG, "Error serializing PPG value: ${e.message}")
            // Return a safe default value in case of error
            return ByteBuffer.allocate(14)
                .order(ByteOrder.LITTLE_ENDIAN)
                .putLong(0)
                .putInt(0)
                .putShort(0)
                .array()
        }
    }
}

/**
 * SpO2 data model.
 * @param spo2 Oxygen saturation (SpO2) value as a percentage.
 * @param status Status flag for SpO2 measurement. The available values are:
 * -6  - Time out
 * -5  - Signal quality is low
 * -4  - Device moved during measurement
 *  0  - Calculating SpO2
 *  2  - SpO2 measurement was completed
 * @param timeStamp Timestamp from the sensor.
 * Remarks:
 * Measuring SpO2 usually takes 30 seconds.
 */
data class Spo2Data(val spo2: Int, val status: Short, val timeStamp: Long) {
    companion object {
        private const val TAG = "Spo2Data"
    }

    /**
     * Serialize the oxygen saturation (SpO2) value and status to byte array.
     */
    fun spo2DataToByteArray(): ByteArray {
        try {
            return ByteBuffer.allocate(14)
                .order(ByteOrder.LITTLE_ENDIAN)
                .putLong(timeStamp)
                .putInt(spo2)
                .putShort(status)
                .array()
        } catch (e: Exception) {
            Log.e(TAG, "Error serializing spo2: ${e.message}")
            // Return a safe default value in case of error
            return ByteBuffer.allocate(14)
                .order(ByteOrder.LITTLE_ENDIAN)
                .putLong(0)
                .putInt(0)
                .putShort(0)
                .array()
        }
    }
}

/**
 * Electrocardiogram (ECG) data model.
 * @param ecgMv ECG value in millivolts.
 * @param status Lead on or off flag, indicating whether the user is touching both of the electrode keys
 * on their Galaxy Watch. The available values are:
 *  0  - The Galaxy Watch's electrode key is in contact.
 *  Any other value - No Contact.
 * @param sequence Sequence number of the data (0 ~ 255).
 * @param timeStamp Timestamp from the sensor.
 */
data class EcgData(val ecgMv: Float, val status: Short, val sequence: Short, val timeStamp: Long) {
    companion object {
        private const val TAG = "EcgData"
    }

    /**
     * Serialize the Ecg data including the average ECG (mV), Sequence and the
     * Status to byte array.
     */
    fun ecgDataToByteArray(): ByteArray {
        try {
            return ByteBuffer.allocate(16)
                .order(ByteOrder.LITTLE_ENDIAN)
                .putLong(timeStamp)
                .putFloat(ecgMv)
                .putShort(status)
                .putShort(sequence)
                .array()
        } catch (e: Exception) {
            Log.e(TAG, "Error serializing millivolts: ${e.message}")
            // Return a safe default value in case of error
            return ByteBuffer.allocate(16)
                .order(ByteOrder.LITTLE_ENDIAN)
                .putLong(0)
                .putFloat(0f)
                .putShort(0)
                .putShort(0)
                .array()
        }
    }
}