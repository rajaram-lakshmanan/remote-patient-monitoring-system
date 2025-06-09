package com.masterproject.healthmonitoring

import android.os.Handler
import android.os.Looper
import android.util.Log

/**
 * Base abstract class for all On-Demand sensor service (ECG and SpO2) managers.
 */
abstract class BaseOnDemandSensorService(service: HealthMonitoringService) : BaseSensorService(service), OnDemandSensorService {

    /**
     * Initiate the On-Demand health tracker and start the measurement.
     * Remarks:
     * Triggers are typically time limited, once the time is elapsed, measurement will be completed.
     */
    override fun trigger() {
       // Pause all the continuous sensors before initiating the on-demand sensor (ECG or SpO2)
        service.pauseContinuousServiceManagers()

        // Arbitrary delay to ensure the continuous sensor events are stopped before initiating the on-demand sensor
        // Adding 5 seconds delay
        Handler(Looper.getMainLooper()).postDelayed({
            startSensorService()
        }, 5000)

        Log.i(getTAG(), "Triggered the measurement of the ${getSensorType()} sensor.")
    }

    /**
     * Stop the On-demand health tracker.
     */
    override fun collectionCompleted() {
        // Cleanup on-demand sensor
        stopSensorService()

        // Arbitrary delay to ensure the on-demand sensor is cleaned up before registering for events for the
        // continuous sensors
        // Adding 5 seconds delay
        Handler(Looper.getMainLooper()).postDelayed({
            service.resumeContinuousServiceManagers()
        }, 5000)

        Log.i(getTAG(), "Collection of the ${getSensorType()} sensor data is completed.")
    }
}