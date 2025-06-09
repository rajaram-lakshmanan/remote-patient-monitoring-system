package com.masterproject.healthmonitoring

/**
 * Common interface for all sensor service managers.
 * This provides a consistent way to manage lifecycle and operations
 * for different types of sensor services.
 */
interface SensorService {
    /**
     * Initialize the service manager
     */
    fun initialize()

    /**
     * Clean up resources when the service is being destroyed
     */
    fun cleanup()
    
    /**
     * Handle device connection events
     * @param deviceAddress The MAC address of the connected device
     */
    fun onDeviceConnected(deviceAddress: String)
    
    /**
     * Handle device disconnection events
     * @param deviceAddress The MAC address of the disconnected device
     */
    fun onDeviceDisconnected(deviceAddress: String)
}