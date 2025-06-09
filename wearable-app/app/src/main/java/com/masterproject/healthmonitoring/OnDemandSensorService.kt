package com.masterproject.healthmonitoring

/**
 * Marker interface for on-demand sensor services that should only collect
 * data when explicitly triggered.
 */
interface OnDemandSensorService : SensorService {
    /**
     * Initiate the On-Demand health tracker and start the measurement.
     * Remarks:
     * Triggers are typically time limited, once the time is elapsed, measurement will be completed.
     */
    fun trigger()

    /**
     * Stop the On-demand health tracker.
     */
    fun collectionCompleted()
}