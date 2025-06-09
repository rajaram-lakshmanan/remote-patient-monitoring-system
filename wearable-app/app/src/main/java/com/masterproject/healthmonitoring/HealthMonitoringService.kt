package com.masterproject.healthmonitoring

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.os.Handler
import android.os.IBinder
import android.os.PowerManager
import android.util.Log
import androidx.core.app.NotificationCompat
import androidx.lifecycle.LifecycleService
import androidx.localbroadcastmanager.content.LocalBroadcastManager
import com.samsung.android.service.health.tracking.ConnectionListener
import com.samsung.android.service.health.tracking.HealthTrackerException
import com.samsung.android.service.health.tracking.HealthTrackingService

/**
 * HealthMonitoringService is the central coordinator for all BLE health monitoring functionality. This service manages
 * connections to the Samsung Health Platform and coordinates multiple sensor services for both continuous and on-demand
 * health data collection. It runs as a foreground service with wake lock to ensure reliable background operation.
 *
 * The service supports continuous monitoring for heart rate, temperature, accelerometer,
 * and PPG data, as well as on-demand measurements for SpO2 and ECG when requested.
 */
class HealthMonitoringService : LifecycleService() {
    companion object {
        private const val TAG = "HealthMonitoringService"
        private const val NOTIFICATION_ID = 2001
        private const val CHANNEL_ID = "health_monitoring_channel"
        private const val MAX_HEALTH_PLATFORM_RETRIES = 3
    }

    // Samsung Health component. All the Continuous and On demand services will use the
    // same tracking service to connect to the health platform
    var healthTracking: HealthTrackingService? = null
        private set

    // Add this as a class property in HealthMonitoringService
    private var wakeLock: PowerManager.WakeLock? = null

    // Parameters used for the status of the initialization and connection with the Samsung Health Platform
    // It is essential the connection is established as this is a pre-requisite for all the sensor services
    private var isHealthPlatformConnected = false
    private var isInitialized = false
    private var healthPlatformRetryCount = 0

    // Service managers for each sensor type - using a common interface
    private val serviceManagers = mutableListOf<SensorService>()

    /**
     * Create the Health monitoring service and initializes connection to Samsung Health tracking platform. The
     * service remains in foreground to ensure reliable health monitoring even when the app is not in the foreground.
     */
    override fun onCreate() {
        super.onCreate()

        Log.i(TAG, "Starting HealthMonitoringService")

        createNotificationChannel()
        startForeground()

        // Acquire wake lock
        val powerManager = getSystemService(Context.POWER_SERVICE) as PowerManager
        wakeLock = powerManager.newWakeLock(
            PowerManager.PARTIAL_WAKE_LOCK,
            "HealthMonitoring::MainServiceWakeLock"
        ).apply {
            acquire(4 * 60 * 60 * 1000L) // 4 hour timeout as safety measure
        }

        // Initialize Samsung health platform
        initHealthTracking()

        Log.i(TAG, "Health Monitoring Service started")
    }

    /**
     * Start the Health monitoring Service.
     * @param intent The intent provided to start the service.
     * @param flags Additional flags to start this service.
     * @param startId A unique ID representing this specific request to start.
     */
    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        // Let LifecycleService handle onStartCommand
        super.onStartCommand(intent, flags, startId)
        return START_STICKY
    }

    /**
     * Overrides the Bind call as the Health monitoring service does not support binding.
     * @return Explicitly returning NULL this service doesn't provide an interface for components
     * (e.g. activities) to bind to it.
     *
     * Remarks:
     * This service is designed to run as a foreground service and communicate with other components using the
     * LocalBroadcastManager system.
     */
    override fun onBind(intent: Intent): IBinder? {
        super.onBind(intent)
        return null
    }

    /**
     * Performs the cleanup when the service is being terminated.
     */
    override fun onDestroy() {
        // Clean up service managers
        cleanupServiceManagers()

        // Disconnect from the Samsung health service
        try {
            healthTracking?.disconnectService()
            healthTracking = null
        } catch (e: Exception) {
            Log.e(TAG, "Error disconnecting health service: ${e.message}")
        }

        // Stop the BLE GATT connection service
        val gattServiceIntent = Intent(this, BleGattConnectionService::class.java)
        stopService(gattServiceIntent)

        // Release wake lock
        wakeLock?.let {
            if (it.isHeld) {
                it.release()
            }
            wakeLock = null
        }

        Log.i(TAG, "Health Monitoring Service destroyed")
        super.onDestroy()
    }

    /**
     * Pauses all continuous sensor tracking services.
     *
     * This method iterates through all service managers and temporarily suspends data collection
     * for continuous monitoring services (like heart rate, temperature, accelerometer, etc.).
     * For Samsung Health trackers, since there's no direct pause functionality, this operation:
     * 1. Unregisters event listeners to stop receiving data
     * 2. Flushes any buffered data to ensure it's not lost
     */
    fun pauseContinuousServiceManagers() {

        // Pause all the service managers which provides functionality to continuously monitor sensor data
        serviceManagers.forEach { manager ->
            try {
                manager.initialize()
                if (manager is ContinuousSensorService) {
                    // For continuous services, pause data collection
                    manager.pauseSensorTracking()
                }
            } catch (e: Exception) {
                Log.e(TAG, "Error pausing service manager: ${e.message}")
            }
        }

        Log.i(TAG, "All continuous sensors service managers are paused")
    }

    /**
     * Resumes all continuous sensor tracking services that were previously paused.
     *
     * This method iterates through all service managers and restarts data collection
     * for continuous monitoring services (like heart rate, temperature, accelerometer, etc.).
     * For Samsung Health trackers, this operation:
     * 1. Flushes any pending data to ensure a clean state
     * 2. Reattaches the event listeners to start receiving sensor data again
     */
    fun resumeContinuousServiceManagers() {

        // Resume all the service managers which provides functionality to continuously monitor sensor data
        serviceManagers.forEach { manager ->
            try {
                manager.initialize()
                if (manager is ContinuousSensorService) {
                    // For continuous services, resume data collection
                    manager.resumeSensorTracking()
                }
            } catch (e: Exception) {
                Log.e(TAG, "Error resuming service manager: ${e.message}")
            }
        }

        Log.i(TAG, "All continuous sensors service managers are resumed")
    }

    /**
     * Creates a low-importance notification channel for the Health monitoring service's foreground notification.
     */
    private fun createNotificationChannel() {
        val channel = NotificationChannel(
            CHANNEL_ID,
            getString(R.string.notification_channel_name),
            NotificationManager.IMPORTANCE_LOW
        ).apply {
            description = getString(R.string.notification_channel_description)
        }

        val notificationManager =
            getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        notificationManager.createNotificationChannel(channel)
    }

    /**
     * Creates and displays a notification that allows the Health monitoring service to run as a foreground service,
     * preventing it from being killed by the system when under memory pressure.
     */
    private fun startForeground() {
        val notificationIntent = Intent(this, MainActivity::class.java)
        val pendingIntent = PendingIntent.getActivity(
            this, 0, notificationIntent,
            PendingIntent.FLAG_IMMUTABLE
        )

        val notification = NotificationCompat.Builder(this, CHANNEL_ID)
            .setContentTitle(getString(R.string.notification_title))
            .setContentText(getString(R.string.notification_text))
            .setSmallIcon(android.R.drawable.ic_dialog_info)
            .setContentIntent(pendingIntent)
            .build()

        startForeground(NOTIFICATION_ID, notification)
    }

    /**
     * Initializes all sensor service managers and starts data collection for continuous sensors.
     *
     * The method is called after successful connection to the Samsung Health Platform
     * and sets up the entire health monitoring infrastructure. Any initialization errors
     * for individual services are caught and logged without interrupting the setup of
     * other services.
     * Supported sensors include: heart rate, temperature, accelerometer, PPG, SpO2, and ECG.
     */
    private fun initServiceManagers() {
        // Create and add service managers
        serviceManagers.add(HeartRateContinuousService(this))
        serviceManagers.add(TemperatureContinuousService(this))
        serviceManagers.add(AccelerometerContinuousService(this))
        serviceManagers.add(PpgContinuousService(this))
        serviceManagers.add(Spo2OnDemandService(this))
        serviceManagers.add(EcgOnDemandService(this))

        // Initialize all service managers
        serviceManagers.forEach { manager ->
            try {
                manager.initialize()
                if (manager is ContinuousSensorService) {
                    // For continuous services, start data collection
                    manager.startSensorTracking()
                }
            } catch (e: Exception) {
                Log.e(TAG, "Error initializing service manager: ${e.message}")
            }
        }

        Log.i(TAG, "All service managers initialized")

        // Start the BLE GATT connection service first
        val gattServiceIntent = Intent(this, BleGattConnectionService::class.java)
        startService(gattServiceIntent)
    }

    /**
     * Cleans up and releases resources used by all sensor service managers.
     */
    private fun cleanupServiceManagers() {
        for (manager in serviceManagers) {
            try {
                manager.cleanup()
            } catch (e: Exception) {
                Log.e(TAG, "Error cleaning up service manager: ${e.message}")
            }
        }

        serviceManagers.clear()
        Log.i(TAG, "All service managers cleaned up")
    }

    /**
     * SAMSUNG HEALTH PLATFORM INITIALIZATION AND CONNECTION LISTENERS
     */

    /**
     * Initialize and connect to the Samsung Health Tracking service.
     */
    private fun initHealthTracking() {
        try {
            // Initialize Samsung Health SDK
            if (healthTracking == null) {
                healthTracking = HealthTrackingService(connectionListener, this)
            }
            healthTracking?.connectService()
            Log.i(TAG, "Health tracking service initialization requested")
        } catch (e: Exception) {
            Log.e(TAG, "Error initializing health tracking: ${e.message}")
        }
    }

    /**
     * Listener that handles Samsung Health Platform connection events.
     */
    private val connectionListener = object : ConnectionListener {
        /**
         * Called when connection to Samsung Health Platform is established. Once the connection is established, initializes
         * all sensor service managers.
         */
        override fun onConnectionSuccess() {
            Log.i(TAG, "Connected to the Samsung Health Platform")
            isHealthPlatformConnected = true
            initServiceManagers()
            healthPlatformRetryCount = 0
        }

        /**
         * Called when connection to Samsung Health Platform is terminated.
         */
        override fun onConnectionEnded() {
            Log.i(TAG, "Disconnected from the Samsung Health Platform")
            isHealthPlatformConnected = false
        }

        /**
         * Called when connection to the Samsung Health Platform fails.
         *
         * This method handles connection failures by:
         * - Checking if the exception has a resolution that requires user interaction
         * - Broadcasting resolution requirements to the UI when needed
         * - Implementing exponential backoff retry logic for recoverable failures
         * - Limiting retry attempts to avoid excessive reconnection attempts
         *
         * @param e Samsung health tracker exception which contains error details and potential resolution actions
         */
        override fun onConnectionFailed(e: HealthTrackerException) {
            Log.e(TAG, "Failed to connect to the Samsung Health Platform: ${e.message}")

            if (e.hasResolution()) {
                // Define the action string locally
                val actionHealthResolutionNeeded = "${packageName}.ACTION_HEALTH_RESOLUTION_NEEDED"
                val extraErrorCode = "${packageName}.EXTRA_ERROR_CODE"

                // Create and send the broadcast
                val intent = Intent(actionHealthResolutionNeeded)
                intent.putExtra(extraErrorCode, e.errorCode)
                LocalBroadcastManager.getInstance(applicationContext).sendBroadcast(intent)

                Log.i(TAG, "Broadcast sent for health resolution")
            } else {
                // Try to reconnect with exponential backoff
                if (healthPlatformRetryCount < MAX_HEALTH_PLATFORM_RETRIES && isInitialized) {
                    healthPlatformRetryCount++
                    val delayMillis = 1000L * (1 shl (healthPlatformRetryCount - 1))
                    Log.i(
                        TAG,
                        "Trying to reconnect to Health Platform in $delayMillis ms (attempt $healthPlatformRetryCount)"
                    )

                    Handler(mainLooper).postDelayed({
                        if (isInitialized) {
                            initHealthTracking()
                        }
                    }, delayMillis)
                }
            }
        }
    }
}