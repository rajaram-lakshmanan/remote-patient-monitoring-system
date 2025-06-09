package com.masterproject.healthmonitoring

/**
 * Common interface for all Continuous sensor service (Accelerometer, Heart rate, PPG, and Skin temperature) managers.
 */
interface ContinuousSensorService : SensorService{
    /**
     * Start the tracking of the continuous sensor.
     * Sensor must be initialized first before initiating the health tracker.
     */
    fun startSensorTracking()

    /**
     * Stop the tracking of the continuous sensor.
     * Remarks:
     * For continuous sensors, this method is typically called only when the application is closing down.
     */
    fun stopSensorTracking()

    /**
     * Pause the tracking of the continuous sensor.
     * Remarks:
     * Continuous sensors should not trigger any data collection when On-demand sensor (ECG or SpO2) is activated.
     */
    fun pauseSensorTracking()

    /**
     * Resume the tracking of the continuous sensor.
     * Remarks:
     * Continuous sensors should not trigger any data collection when On-demand sensor (ECG or SpO2) is activated.
     */
    fun resumeSensorTracking()
}