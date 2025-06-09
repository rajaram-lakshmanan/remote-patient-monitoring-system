package com.masterproject.healthmonitoring

/**
 * List of types of sensors (continuous and On-demand) supported by the application.
 * @param displayName Display name of the type of the sensor.
 */
enum class SensorType(private val displayName: String) {
    HEART_RATE("Heart Rate"),
    ACCELEROMETER("Accelerometer"),
    PPG("Photoplethysmography (PPG)"),
    SKIN_TEMPERATURE("Skin Temperature"),
    ECG("Electrocardiogram (ECG)"),
    SPO2("Blood Oxygen (SpO2)");

    /**
     * Returns the display name of the sensor.
     * @return Display name.
     */
    override fun toString(): String {
        return displayName
    }
}