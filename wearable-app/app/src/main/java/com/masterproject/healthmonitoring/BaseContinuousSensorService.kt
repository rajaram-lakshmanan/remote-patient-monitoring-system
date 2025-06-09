package com.masterproject.healthmonitoring

import android.util.Log

/**
 * Base abstract class for all Continuous sensor service (Accelerometer, Heart rate, PPG, and Skin temperature) managers.
 */
abstract class BaseContinuousSensorService(service: HealthMonitoringService) : BaseSensorService(service), ContinuousSensorService {
    /**
     * Start the tracking of the continuous sensor.
     * Sensor must be initialized first before initiating the health tracker.
     */
    override fun startSensorTracking() {
        if (!isInitialized) {
            Log.e(getTAG(), "Cannot start ${getSensorType()} sensor tracking. Service manager is not initialized")
            return
        }
        startSensorService()
    }

    /**
     * Stop the tracking of the continuous sensor.
     * Remarks:
     * For continuous sensors, this method is typically called only when the application is closing down.
     */
    override fun stopSensorTracking() {
        stopSensorService()
    }

    /**
     * Pause the tracking of the continuous sensor.
     * Remarks:
     * Continuous sensors should not trigger any data collection when On-demand sensor (ECG or SpO2) is activated.
     */
    override fun pauseSensorTracking() {
        try {
            // There is no pause option available of the Samsung health tracker. Only option is to pause the
            // data collection and flush to gather data instantly
            healthTracker?.unsetEventListener()
            healthTracker?.flush()
            Log.i(getTAG(), "${getSensorType()} sensor tracking is paused")
        } catch (e: Exception) {
            Log.e(getTAG(), "Error pausing ${getSensorType()} sensor tracking: ${e.message}")
        }
    }

    /**
     * Resume the tracking of the continuous sensor.
     * Remarks:
     * Continuous sensors should not trigger any data collection when On-demand sensor (ECG or SpO2) is activated.
     */
    override fun resumeSensorTracking() {
        try {
            // Flush the gathered data before registering for data received event
            healthTracker?.flush()
            healthTracker?.setEventListener(createSensorListener())
            Log.i(getTAG(), "${getSensorType()} sensor tracking has resumed")
        } catch (e: Exception) {
            Log.e(getTAG(), "Error resuming ${getSensorType()} sensor tracking: ${e.message}")
        }
    }

    /**
     * Clean up resources.
     */
    override fun cleanup() {
        try {
            stopSensorTracking()
            super.cleanup()

            Log.i(getTAG(), "${getTAG()} cleaned up")
        } catch (e: Exception) {
            Log.e(getTAG(), "Error during cleanup: ${e.message}")
        }
    }
}