"""System status API endpoints."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.models.system import SystemStatus
from backend.services.calibration_service import CalibrationService
from backend.services.config_manager import ConfigManager
from backend.services.hf_service import HuggingFaceService
from backend.services.port_lock_manager import port_lock_manager
from backend.services.port_permissions import (
    check_port_permission,
    fix_port_permission,
    has_udev_rule,
    install_udev_rule,
    is_user_in_dialout,
)
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


@router.get("/port-locks")
async def get_port_locks():
    """Return current port lock status for diagnostics."""
    return port_lock_manager.get_status()


class FixPortRequest(BaseModel):
    port: str


@router.post("/fix-port-permission")
async def fix_port_permission_endpoint(request: FixPortRequest):
    """Fix permissions for a single serial port.

    Shows a graphical password dialog (pkexec) on desktop Linux.
    """
    if check_port_permission(request.port):
        return {"success": True, "message": "Port is already accessible."}
    success, message = fix_port_permission(request.port)
    if not success:
        raise HTTPException(status_code=500, detail={"message": message})
    return {"success": True, "message": message}


@router.post("/fix-port-permissions-permanent")
async def fix_port_permissions_permanent():
    """Install a udev rule so serial ports are always accessible without sudo.

    Shows a graphical password dialog (pkexec) on desktop Linux.
    This is a one-time fix — after this, all serial ports will be accessible.
    """
    success, message = install_udev_rule()
    if not success:
        raise HTTPException(status_code=500, detail={"message": message})
    return {"success": True, "message": message}


@router.get("/port-permissions")
async def get_port_permissions_status():
    """Check if serial port permissions are properly configured."""
    return {
        "udev_rule_installed": has_udev_rule(),
        "user_in_dialout": is_user_in_dialout(),
    }
