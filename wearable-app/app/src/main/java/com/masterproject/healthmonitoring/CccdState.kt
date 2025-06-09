package com.masterproject.healthmonitoring

/**
 * Enumeration representing the possible states of a Client Characteristic Configuration Descriptor.
 */
enum class CccdState {
    DISABLED,
    NOTIFICATION_ENABLED,
    INDICATION_ENABLED;

    /**
     * Get the byte array value for the CCCD state.
     * @return Byte array of the CCCD state.
     */
    fun toByteArray(): ByteArray {
        return when (this) {
            DISABLED -> byteArrayOf(0x00, 0x00)
            NOTIFICATION_ENABLED -> byteArrayOf(0x01, 0x00)
            INDICATION_ENABLED -> byteArrayOf(0x02, 0x00)
        }
    }

    companion object {
        /**
         * Convert a byte array to its corresponding CccdState.
         * @param bytes Byte array to be converted to CCCD state.
         * @return Returns converted CCCD state, DISABLED for null or unrecognized values.
         */
        fun fromByteArray(bytes: ByteArray?): CccdState {
            if (bytes == null) return DISABLED

            return when {
                bytes.contentEquals(byteArrayOf(0x00, 0x00)) -> DISABLED
                bytes.contentEquals(byteArrayOf(0x01, 0x00)) -> NOTIFICATION_ENABLED
                bytes.contentEquals(byteArrayOf(0x02, 0x00)) -> INDICATION_ENABLED
                else -> DISABLED // Default to disabled for safety
            }
        }

        /**
         * Determines if notifications or indications are enabled for the specified state.
         * @param state CCCD state to be evaluated.
         * @return Returns true if notification or indication is enabled, otherwise false.
         */
        fun isEnabled(state: CccdState?): Boolean {
            return state == NOTIFICATION_ENABLED || state == INDICATION_ENABLED
        }
    }
}