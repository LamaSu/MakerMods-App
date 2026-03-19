"""System status API endpoints."""

import subprocess
import sys

from fastapi import APIRouter, HTTPException

from backend.models.system import SystemStatus
from backend.services.calibration_service import CalibrationService
from backend.services.config_manager import ConfigManager
from backend.services.hf_service import HuggingFaceService
from backend.services.process_manager import process_manager

router = APIRouter()
config_manager = ConfigManager()
calibration_service = CalibrationService()
hf_service = HuggingFaceService()


@router.get("/status", response_model=SystemStatus)
async def get_system_status():
    """Get overall system status."""
    try:
        # Get active processes
        active_processes_dict = await process_manager.get_active_processes()
        active_processes = list(active_processes_dict.values())

        # Get HF login status
        hf_status = hf_service.check_login()

        # Get missing calibrations
        config = config_manager.load_config()
        missing_calibrations = calibration_service.list_missing_calibrations(config)

        return SystemStatus(
            active_processes=active_processes, hf_status=hf_status, missing_calibrations=missing_calibrations
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get system status: {e}")


@router.post("/pick-folder")
async def pick_folder():
    """Open a native OS folder-picker dialog and return the selected path.

    Uses AppleScript on macOS, PowerShell on Windows, zenity/kdialog on Linux.
    Returns {"path": null} if the user cancels.
    """
    try:
        path = None

        if sys.platform == "darwin":
            result = subprocess.run(
                ["osascript", "-e", "POSIX path of (choose folder)"],
                capture_output=True,
                text=True,
                timeout=120,
            )
            path = result.stdout.strip().rstrip("/") if result.returncode == 0 else None

        elif sys.platform == "win32":
            ps_script = (
                "Add-Type -AssemblyName System.Windows.Forms;"
                "$d = New-Object System.Windows.Forms.FolderBrowserDialog;"
                "$d.ShowNewFolderButton = $false;"
                "if ($d.ShowDialog() -eq 'OK') { $d.SelectedPath }"
            )
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps_script],
                capture_output=True,
                text=True,
                timeout=120,
            )
            path = result.stdout.strip() if result.returncode == 0 and result.stdout.strip() else None

        else:  # Linux
            for cmd in [
                ["zenity", "--file-selection", "--directory", "--title=Select Dataset Folder"],
                ["kdialog", "--getexistingdirectory", "."],
            ]:
                try:
                    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
                    if result.returncode == 0 and result.stdout.strip():
                        path = result.stdout.strip()
                        break
                except FileNotFoundError:
                    continue

        return {"path": path or None}

    except subprocess.TimeoutExpired:
        return {"path": None}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Folder picker failed: {e}")
