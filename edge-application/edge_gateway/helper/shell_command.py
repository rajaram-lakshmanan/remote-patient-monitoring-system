#!/usr/bin/env python3
# -----------------------------------------------------------------------------
# Filename: shell_command.py
# Author: Rajaram Lakshmanan
# Description:  Helper class to execute the Shell command.
# License: MIT (see LICENSE)
# -----------------------------------------------------------------------------

import logging
import subprocess
from typing import List, Optional

logger = logging.getLogger("ShellCommand")

class ShellCommand:
    @staticmethod
    def execute(command: List[str], timeout=30) -> Optional[str]:
        """Execute a shell command and return its output.

        Args:
            command: Command to execute as a list of strings.
            timeout: Timeout to prevent the script from hanging indefinitely
            if a command takes too long, default is 30 seconds.

        Returns:
            Command output as a string if successful, None otherwise.

        """
        try:
            logger.debug(f"Executing command: {' '.join(command)}")

            if not command:
                logger.error("Command list is empty.")
                return None

            result = subprocess.run(command,
                                    stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE,
                                    text=True,
                                    check=True,
                                    timeout=timeout)

            return result.stdout.strip()
        except subprocess.CalledProcessError as e:
            logger.error(f"Error executing command {' '.join(command)}: {str(e)}")
            return None
        except subprocess.TimeoutExpired as e:
            logger.error(f"Command timed out: {' '.join(command)}: {str(e)}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error executing command: {e}")
            return None