package com.masterproject.healthmonitoring

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Bundle
import android.util.Log
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat

/**
 * MainActivity serves as the entry point for the Health Monitoring application.
 *
 * This activity handles the critical permission management required for health monitoring
 * functionality and initializes the background monitoring service. It presents minimal UI
 * as the app is designed to operate primarily as a background service.
 *
 * The activity will:
 * 1. Check for all required permissions related to Bluetooth and health sensors
 * 2. Request any missing permissions from the user
 * 3. Start the HealthMonitoringService if all permissions are granted
 * 4. Close itself after starting the service or if permissions are denied
 *
 * Required permissions include:
 * - Bluetooth scanning, advertising, and connection permissions
 * - Body sensors access
 * - Activity recognition
 */
class MainActivity : ComponentActivity() {
    companion object {
        private const val TAG = "MainActivity"
        private const val REQUEST_PERMISSIONS = 1001
        private val REQUIRED_PERMISSIONS = arrayOf(
            Manifest.permission.BLUETOOTH_SCAN,
            Manifest.permission.BLUETOOTH_ADVERTISE,
            Manifest.permission.BLUETOOTH_CONNECT,
            Manifest.permission.BODY_SENSORS,
            Manifest.permission.ACTIVITY_RECOGNITION
        )
    }

    /**
     * Create the Main activity, check for all required permissions by the application, and initiate the Health
     * monitoring service.
     */
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        // Minimal UI as this is a background service app
        setContentView(R.layout.activity_main)

        // Check and request permissions
        if (allPermissionsGranted()) {
            startHealthMonitoringService()
        } else {
            ActivityCompat.requestPermissions(this, REQUIRED_PERMISSIONS, REQUEST_PERMISSIONS)
        }
    }

    /**
     * Handles the result of permission requests made with ActivityCompat.requestPermissions().
     *
     * This method is called when the user responds to the permission request dialog.
     * It determines whether to start the health monitoring service or exit the app
     * based on whether all required permissions were granted.
     * @param requestCode The code passed to requestPermissions() identifying the request.
     * @param permissions Array of permission strings that were requested.
     * @param grantResults Array of grant results for each requested permission.
     */
    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<String>,grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)

        if (requestCode == REQUEST_PERMISSIONS) {
            if (allPermissionsGranted()) {
                startHealthMonitoringService()
            } else {
                // Show which permissions are missing
                val missingPermissions = getMissingPermissions()
                if (missingPermissions.isNotEmpty()) {
                    val permissionString = missingPermissions.joinToString(", ")
                    Toast.makeText(
                        this,
                        "The following permissions are required: $permissionString",
                        Toast.LENGTH_LONG
                    ).show()
                    Log.e(TAG, "Missing permissions: $permissionString")
                } else {
                    Toast.makeText(
                        this,
                        "Required permissions are necessary for this app to function.",
                        Toast.LENGTH_LONG
                    ).show()
                }
                finish()
            }
        }
    }

    /**
     * Checks if all the required permissions have been granted by the user.
     * @return Boolean True if all required permissions are granted, false if any permission is denied.
     */
    private fun allPermissionsGranted() = REQUIRED_PERMISSIONS.all {
        ContextCompat.checkSelfPermission(baseContext, it) == PackageManager.PERMISSION_GRANTED
    }

    /**
     * Identifies and returns a list of permissions that have not been granted.
     * @return List<String> A list containing the string identifiers of all permissions that
     *                     have not been granted. Returns an empty list if all permissions are granted.
     */
    private fun getMissingPermissions(): List<String> {
        return REQUIRED_PERMISSIONS.filter {
            ContextCompat.checkSelfPermission(baseContext, it) != PackageManager.PERMISSION_GRANTED
        }
    }

    /**
     * Initializes and starts the HealthMonitoringService as a foreground service.
     *
     * Remarks:
     * This method assumes all necessary permissions have been granted before it is called.
     */
    private fun startHealthMonitoringService() {
        // Start the combined health monitoring service
        val serviceIntent = Intent(this, HealthMonitoringService::class.java)
        startForegroundService(serviceIntent)

        // App can close after starting the service
        Toast.makeText(this, "Health Monitoring service started", Toast.LENGTH_SHORT).show()
        Log.i(TAG, "Health Monitoring service started successfully")
        finish()
    }
}