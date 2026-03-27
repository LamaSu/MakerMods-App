"""Port permission checking and fixing for Linux serial devices.

On Linux, serial ports like /dev/ttyACM* often require elevated privileges.
This module detects permission issues and attempts to fix them, either
per-port (via pkexec/sudo) or permanently (via udev rule).
"""

import grp
import logging
import os
import platform
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

UDEV_RULE_PATH = "/etc/udev/rules.d/99-lerobot-serial.rules"
UDEV_RULE_CONTENT = (
    '# Allow all users to access USB serial devices (Feetech motor controllers)\n'
    'SUBSYSTEM=="tty", KERNEL=="ttyACM[0-9]*", MODE="0666"\n'
    'SUBSYSTEM=="tty", KERNEL=="ttyUSB[0-9]*", MODE="0666"\n'
)


def check_port_permission(port: str) -> bool:
    """Return True if the current process can read/write the port."""
    return os.access(port, os.R_OK | os.W_OK)


def is_user_in_dialout() -> bool:
    """Check if the current user is in the dialout group."""
    try:
        dialout = grp.getgrnam("dialout")
        return os.getlogin() in dialout.gr_mem or os.getgid() == dialout.gr_gid
    except (KeyError, OSError):
        return False


def has_udev_rule() -> bool:
    """Check if our udev rule is already installed."""
    return Path(UDEV_RULE_PATH).exists()


def fix_port_permission(port: str) -> tuple[bool, str]:
    """Attempt to chmod 666 a single port using pkexec or sudo.

    pkexec shows a graphical password dialog on desktop Linux (Jetson, etc).
    Falls back to sudo if pkexec is not available.

    Returns (success, message).
    """
    if platform.system() != "Linux":
        return False, "Port permission fixing is only supported on Linux."

    if check_port_permission(port):
        return True, "Port is already accessible."

    # Try pkexec first (shows graphical auth dialog)
    if shutil.which("pkexec"):
        try:
            result = subprocess.run(
                ["pkexec", "chmod", "666", port],
                capture_output=True,
                text=True,
                timeout=60,
            )
            if result.returncode == 0:
                logger.info("Fixed permissions for %s via pkexec", port)
                return True, f"Permissions fixed for {port}."
            logger.warning("pkexec chmod failed: %s", result.stderr.strip())
        except subprocess.TimeoutExpired:
            return False, "Authentication dialog timed out."
        except Exception as e:
            logger.warning("pkexec failed: %s", e)

    # Fall back to sudo (works if user has passwordless sudo or is root)
    try:
        result = subprocess.run(
            ["sudo", "-n", "chmod", "666", port],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            logger.info("Fixed permissions for %s via sudo -n", port)
            return True, f"Permissions fixed for {port}."
    except Exception:
        pass

    return False, (
        f"Could not fix permissions for {port}. "
        f"Run manually: sudo chmod 666 {port}"
    )


def install_udev_rule() -> tuple[bool, str]:
    """Install a udev rule so serial ports are always accessible.

    Uses pkexec for graphical auth, falls back to sudo -n.
    Returns (success, message).
    """
    if platform.system() != "Linux":
        return False, "Udev rules are only supported on Linux."

    if has_udev_rule():
        return True, "Udev rule is already installed."

    # Write the rule file via pkexec tee
    if shutil.which("pkexec"):
        try:
            result = subprocess.run(
                ["pkexec", "bash", "-c",
                 f"echo '{UDEV_RULE_CONTENT.strip()}' > {UDEV_RULE_PATH} && "
                 "udevadm control --reload-rules && udevadm trigger"],
                capture_output=True,
                text=True,
                timeout=60,
            )
            if result.returncode == 0:
                logger.info("Installed udev rule via pkexec")
                return True, (
                    "Udev rule installed. Serial ports will now be accessible "
                    "without sudo. You may need to unplug and replug your devices."
                )
        except subprocess.TimeoutExpired:
            return False, "Authentication dialog timed out."
        except Exception as e:
            logger.warning("pkexec udev install failed: %s", e)

    # Fall back to sudo -n
    try:
        result = subprocess.run(
            ["sudo", "-n", "bash", "-c",
             f"echo '{UDEV_RULE_CONTENT.strip()}' > {UDEV_RULE_PATH} && "
             "udevadm control --reload-rules && udevadm trigger"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            logger.info("Installed udev rule via sudo -n")
            return True, (
                "Udev rule installed. Serial ports will now be accessible "
                "without sudo. You may need to unplug and replug your devices."
            )
    except Exception:
        pass

    return False, (
        "Could not install udev rule automatically. Run this command manually:\n"
        f"echo '{UDEV_RULE_CONTENT.strip()}' | sudo tee {UDEV_RULE_PATH} && "
        "sudo udevadm control --reload-rules && sudo udevadm trigger"
    )


def ensure_port_accessible(port: str) -> None:
    """Check port permissions and attempt to fix if needed.

    Raises PermissionError with a helpful message if the port cannot be made
    accessible.
    """
    if check_port_permission(port):
        return

    logger.warning("Port %s is not accessible, attempting to fix permissions", port)
    success, message = fix_port_permission(port)

    if success and check_port_permission(port):
        return

    raise PermissionError(
        f"Permission denied for {port}. {message}"
    )
