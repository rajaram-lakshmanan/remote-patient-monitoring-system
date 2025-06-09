#!/usr/bin/env python3
# -----------------------------------------------------------------------------
# Filename: heart_rate_and_spo2_calculation.py
# Author: Rajaram Lakshmanan
# Description:  Helper (static) class used to calculate the heart rate and SpO2
# from the raw IR and Red time_series.
# License: MIT (see LICENSE)
# -----------------------------------------------------------------------------

import logging

import numpy as np
from scipy import signal

logger = logging.getLogger("HeartRateSp02Calculation")

class HeartRateSp02Calculation:
    """
     Helper (static) class used to calculate the heart rate and SpO2 from the raw IR and Red time_series.

     Note: This is a code converted to Python from the original cpp implementation (from MikroE).
    """

    @staticmethod
    def get_heartrate_sp02(ir_data, red_data):
        """
        Get the Heartrate and Spo2 by detecting the peaks of the PPG cycle and corresponding
        AC/DC of red/infra-red signal, the an_ratio for the SPO2 is computed.

        Args:
            ir_data (list): Raw IR (infrared) light intensity readings from the sensor.
            red_data (list): Raw RED light intensity readings from the sensor.

        Returns:
            heart_rate (float): Estimated heart rate in beats per minute (BPM). Returns NaN if not computable.
            spo2 (float): Estimated oxygen saturation percentage (%SpO₂). Returns NaN if not computable.
        """
        # 25 samples per second
        sample_freq = 25

        # Taking moving average of 4 samples when calculating HR
        ma_size = 4

        # Sampling frequency * 4 (for 4 seconds of time_series)
        buffer_size = 100

        # Default values of the Heartrate and Sp02
        heart_rate = np.nan
        spo2 = np.nan

        # The raw IR signal (time_series) contains both DC (steady part) and AC (pulsatile part).
        # DC component represents constant absorption from tissue, bones and venous blood.
        # AC component represents fluctuations due to arterial blood flow (heartbeat).
        # Calculate the mean (DC mean) to isolate AC signal
        ir_mean = int(np.mean(ir_data))

        # IR absorption increases with blood volume, photodiode receives less light.
        # IR absorption decreases when blood volume is lower, photodiode receives more light.
        # This means peaks in blood volume appear as valleys in the raw IR signal
        # Inverting the IR signal will make the heartbeats appear as positive peaks,
        # making it easier to detect systolic peaks
        ir_inverted = -1 * (np.array(ir_data) - ir_mean)

        # 4 point moving average
        # ir_inverted is np.array with int values, so automatically cast it to int
        for i in range(ir_inverted.shape[0] - ma_size):
            ir_inverted[i] = np.sum(ir_inverted[i: i +ma_size]) / ma_size

        # Calculate threshold to detect valid peaks and valleys
        # 30 and 60 are the selected range based on empirical observations
        threshold = int(np.mean(ir_inverted))
        threshold = 30 if threshold < 30 else threshold  # min allowed
        threshold = 60 if threshold > 60 else threshold  # max allowed

        # Find Indices (locations) of valleys (minima) in the IR signal and peaks
        ir_filtered = HeartRateSp02Calculation.bandpass_filter(ir_inverted)
        ir_valley_locs, no_of_peaks = HeartRateSp02Calculation._find_peaks(ir_filtered,
                                                                           buffer_size,
                                                                           threshold,
                                                                           6,
                                                                           10)
        # =============== Calculation of the Heartrate (BPM) =========
        peak_interval_sum = 0
        if no_of_peaks >= 2:
            for i in range(1, no_of_peaks):
                peak_interval_sum += (ir_valley_locs[i] - ir_valley_locs[ i -1])

            peak_interval_sum = int(peak_interval_sum / (no_of_peaks - 1))
            heart_rate = int(sample_freq * 60 / peak_interval_sum)

        # ================== Calculation of the spo2 =================
        # Find precise min near IR valley location (ir_valley_locs)
        exact_ir_valley_locs_count = no_of_peaks

        # Find ir-red DC and ir-red AC for SPO2 calibration ratio and find the AC/DC maximum of raw
        for i in range(exact_ir_valley_locs_count):
            if ir_valley_locs[i] > buffer_size:
                # Unable to calculate sp02, return default NaN for Spo2
                return heart_rate, spo2

        ratio = []

        # Find max between two valley locations and use the ratio between the
        # AC component of Ir and Red DC component of Ir and Red for SpO2
        red_dc_max_index = -1
        ir_dc_max_index = -1

        for k in range(exact_ir_valley_locs_count -1):
            red_dc_max = -16777216
            ir_dc_max = -16777216

            if ir_valley_locs[ k +1] - ir_valley_locs[k] > 3:
                for i in range(ir_valley_locs[k], ir_valley_locs[ k +1]):
                    if ir_data[i] > ir_dc_max:
                        ir_dc_max = ir_data[i]
                        ir_dc_max_index = i

                    if red_data[i] > red_dc_max:
                        red_dc_max = red_data[i]
                        red_dc_max_index = i

                red_ac = int((red_data[ir_valley_locs[ k +1]] - red_data[ir_valley_locs[k]]) *
                            (red_dc_max_index - ir_valley_locs[k]))
                red_ac = red_data[ir_valley_locs[k]] + int(red_ac / (ir_valley_locs[k + 1] - ir_valley_locs[k]))

                # Subtract linear DC components from raw
                red_ac = red_data[red_dc_max_index] - red_ac

                ir_ac = int(
                    (ir_data[ir_valley_locs[k + 1]] - ir_data[ir_valley_locs[k]]) * (ir_dc_max_index - ir_valley_locs[k]))
                ir_ac = ir_data[ir_valley_locs[k]] + int(ir_ac / (ir_valley_locs[k + 1] - ir_valley_locs[k]))

                # Subtract linear DC components from raw
                ir_ac = ir_data[ir_dc_max_index] - ir_ac

                numerator = red_ac * ir_dc_max
                denominator = ir_ac * red_dc_max

                # Better approach for ratio handling
                ratio_value = (numerator * 100) / denominator if denominator != 0 else 0
                # Typical R values for pulse oximetry should be between 0.4 and 3.0
                if 40 < ratio_value < 300:  # Scaled by 100 in the code
                    ratio.append(ratio_value)

        # Choose a median value since PPG signal may vary from beat to beat
        ratio = sorted(ratio)  # sort to ascending order
        ratio_count = len(ratio)
        ratio_ave = 0

        if ratio:  # If ratio list has any values
            if len(ratio) % 2 == 0 and len(ratio) > 1:  # Even number of values
                mid_idx = len(ratio) // 2
                ratio_ave = (ratio[mid_idx - 1] + ratio[mid_idx]) / 2
            else:  # Odd number of values
                ratio_ave = ratio[len(ratio) // 2]

        # A more standard SpO2 calibration formula
        if 40 < ratio_ave < 300:
            r = ratio_ave / 100.0  # Convert back to decimal
            spo2 = 110.0 - 25.0 * r  # Simple linear approximation
            # Clamp to physiological range
            spo2 = min(100.0, max(70.0, spo2))

        return heart_rate, spo2

    @staticmethod
    def bandpass_filter(data, fs=25):
        """
        Apply a bandpass filter to isolate heart rate frequency band (0.5Hz to 4Hz).

        Args:
            data (np.ndarray): Signal time_series to filter
            fs (int): Sampling frequency (default: 25 Hz)

        Returns:
            np.ndarray: Filtered signal
        """
        nyquist = 0.5 * fs
        low = 0.5 / nyquist
        high = 4.0 / nyquist

        # Use sosfilt approach which works on all SciPy versions
        sos = signal.butter(2, [low, high], btype='band', output='sos')
        return signal.sosfilt(sos, data)

    @staticmethod
    def _find_peaks(ir_inverted, size, min_height, min_dist, max_num):
        """
        Detects up to max_num peaks in the given signal that are higher than min_height
        and separated by at least min_dist samples.

        Args:
            ir_inverted (np.ndarray): Inverted IR signal for peak detection.
            size (int): Number of samples to consider in the signal.
            min_height (int): Minimum value a peak must exceed to be considered.
            min_dist (int): Minimum required distance (in samples) between peaks.
            max_num (int): Maximum number of peaks to detect.

        Returns:
            ir_valley_locs (list[int]): List of peak indices.
            no_of_peaks (int): Total number of valid peaks found.
        """
        ir_valley_locs, no_of_peaks = HeartRateSp02Calculation._find_peaks_above_min_height(ir_inverted, size, min_height, max_num)
        ir_valley_locs, no_of_peaks = HeartRateSp02Calculation._remove_close_peaks(no_of_peaks, ir_valley_locs, ir_inverted, min_dist)
        no_of_peaks = min([no_of_peaks, max_num])
        return ir_valley_locs, no_of_peaks


    @staticmethod
    def _find_peaks_above_min_height(ir_inverted, size, min_height, max_num):
        """
        Find at most max num peaks above min height separated by at least min distance.

        Args:
            ir_inverted (np.ndarray): Inverted IR signal.
            size (int): Number of elements to search.
            min_height (int): Minimum peak height to be considered valid.
            max_num (int): Maximum number of peaks to detect.

        Returns:
            ir_valley_locs (list[int]): List of detected peak indices.
            no_of_peaks (int): Count of peaks found.
        """
        i = 0
        no_of_peaks = 0
        ir_valley_locs = []
        while i < size - 1:
            # Find the left edge of potential peaks
            if ir_inverted[i] > min_height and ir_inverted[i] > ir_inverted[i - 1]:
                width = 1

                # Find flat peaks
                while i + width < size - 1 and ir_inverted[i] == ir_inverted[i + width]:
                    width += 1

                # Find the right edge of peaks
                if ir_inverted[i] > ir_inverted[i + width] and no_of_peaks < max_num:
                    ir_valley_locs.append(i)
                    no_of_peaks += 1
                    i += width + 1
                else:
                    i += width
            else:
                i += 1

        return ir_valley_locs, no_of_peaks


    @staticmethod
    def _remove_close_peaks(no_of_peaks, ir_valley_locs, ir_inverted, min_dist):
        """
        Removes peaks that are too close to each other (less than min_dist apart)
        and keeps the most prominent ones.

        Args:
            no_of_peaks (int): Initial number of detected peaks.
            ir_valley_locs (list[int]): Initial list of peak indices.
            ir_inverted (np.ndarray): Inverted IR signal used to assess prominence.
            min_dist (int): Minimum allowed distance between peaks.

        Returns:
            ir_valley_locs_filtered (list[int]): Filtered list of valid peak indices.
            new_no_of_peaks (int): Updated peak count after filtering.
        """
        sorted_indices = sorted(ir_valley_locs, key=lambda index: ir_inverted[index])
        sorted_indices.reverse()

        i = -1
        while i < no_of_peaks:
            old_n_peaks = no_of_peaks
            no_of_peaks = i + 1

            j = i + 1
            while j < old_n_peaks:
                # lag-zero peak of autocorr is at index -1
                n_dist = (sorted_indices[j] - sorted_indices[i]) if i != -1 else (sorted_indices[j] + 1)
                if n_dist > min_dist or n_dist < -1 * min_dist:
                    sorted_indices[no_of_peaks] = sorted_indices[j]
                    no_of_peaks += 1
                j += 1
            i += 1

        sorted_indices[:no_of_peaks] = sorted(sorted_indices[:no_of_peaks])
        return sorted_indices, no_of_peaks