"""Neuracore cloud training API routes."""

from fastapi import APIRouter, HTTPException

from backend.models.neuracore_training import (
    AlgorithmInfo,
    ConnectRobotRequest,
    ConnectRobotResponse,
    ImportDatasetRequest,
    ImportStatusResponse,
    NeuracoreLoginKeyRequest,
    NeuracoreLoginRequest,
    NeuracoreLoginStatus,
    OrgInfo,
    RobotInfo,
    SelectOrgRequest,
    StartTrainingRequest,
    UpdateRobotRequest,
)
from backend.services.neuracore_service import neuracore_service

router = APIRouter()


def _http_error(status: int, msg: str) -> HTTPException:
    return HTTPException(status_code=status, detail=msg)


# ─── Authentication ───────────────────────────────────────────────────────────


@router.post("/login", response_model=NeuracoreLoginStatus)
async def login_with_credentials(body: NeuracoreLoginRequest):
    """Generate a Neuracore API key from email + password credentials."""
    try:
        api_key = neuracore_service.generate_api_key(body.email, body.password)
        return NeuracoreLoginStatus(
            authenticated=True,
            message=f"API key generated successfully. Key: {api_key[:8]}…",
        )
    except ValueError as exc:
        return NeuracoreLoginStatus(authenticated=False, message=str(exc))
    except Exception as exc:
        raise _http_error(500, f"Authentication failed: {exc}") from exc


@router.post("/login-with-key", response_model=NeuracoreLoginStatus)
async def login_with_key(body: NeuracoreLoginKeyRequest):
    """Login to Neuracore using an existing API key."""
    try:
        neuracore_service.login_with_key(body.api_key)
        return NeuracoreLoginStatus(authenticated=True, message="Authenticated successfully.")
    except Exception as exc:
        raise _http_error(500, f"Login failed: {exc}") from exc


@router.get("/status", response_model=NeuracoreLoginStatus)
async def get_auth_status():
    """Check whether the backend is authenticated with Neuracore."""
    authenticated = neuracore_service.is_authenticated()
    return NeuracoreLoginStatus(
        authenticated=authenticated,
        message="Authenticated." if authenticated else "Not authenticated.",
    )


# ─── Organizations ────────────────────────────────────────────────────────────


@router.get("/orgs", response_model=list[OrgInfo])
async def list_orgs():
    """List all Neuracore organisations the authenticated user belongs to."""
    try:
        return neuracore_service.list_orgs()
    except Exception as exc:
        raise _http_error(500, f"Failed to list organisations: {exc}") from exc


@router.get("/orgs/current")
async def get_current_org():
    """Return the currently active organisation ID (from neuracore config)."""
    org_id = neuracore_service.get_current_org_id()
    return {"org_id": org_id}


@router.post("/orgs/select")
async def select_org(body: SelectOrgRequest):
    """Set the active Neuracore organisation."""
    try:
        neuracore_service.set_org(body.id_or_name)
        return {"message": f"Organisation set to '{body.id_or_name}'."}
    except Exception as exc:
        raise _http_error(500, f"Failed to set organisation: {exc}") from exc


# ─── Robot ────────────────────────────────────────────────────────────────────


@router.post("/connect-robot", response_model=ConnectRobotResponse)
async def connect_robot(body: ConnectRobotRequest):
    """Register or retrieve a robot in Neuracore."""
    try:
        result = neuracore_service.connect_robot(body.robot_name)
        return ConnectRobotResponse(**result)
    except Exception as exc:
        raise _http_error(500, f"Failed to connect robot: {exc}") from exc


@router.get("/robots", response_model=list[RobotInfo])
async def list_robots():
    """List all robots in the current organisation."""
    try:
        return neuracore_service.list_robots()
    except Exception as exc:
        raise _http_error(500, f"Failed to list robots: {exc}") from exc


@router.put("/robots/{robot_id}", response_model=ConnectRobotResponse)
async def update_robot(robot_id: str, body: UpdateRobotRequest):
    """Rename a robot by its current name or ID."""
    try:
        result = neuracore_service.update_robot(body.robot_key, body.new_name)
        return ConnectRobotResponse(**result)
    except Exception as exc:
        raise _http_error(500, f"Failed to update robot: {exc}") from exc


# ─── Datasets ─────────────────────────────────────────────────────────────────


@router.get("/datasets")
async def list_datasets():
    """List Neuracore datasets for the current organisation."""
    try:
        return neuracore_service.list_datasets()
    except Exception as exc:
        raise _http_error(500, f"Failed to list datasets: {exc}") from exc


# ─── Dataset Import ───────────────────────────────────────────────────────────


@router.post("/import-dataset")
async def import_dataset(body: ImportDatasetRequest):
    """Start importing a HuggingFace LeRobot dataset into Neuracore (background)."""
    import_id = neuracore_service.start_import(body)
    return {"import_id": import_id, "message": "Import started in background."}


@router.get("/import-status/{import_id}", response_model=ImportStatusResponse)
async def get_import_status(import_id: str):
    """Poll the status of a background dataset import."""
    return neuracore_service.get_import_status(import_id)


# ─── Algorithms ───────────────────────────────────────────────────────────────


@router.get("/algorithms", response_model=list[AlgorithmInfo])
async def list_algorithms():
    """List training algorithms available to the current organisation."""
    try:
        return neuracore_service.get_algorithms()
    except Exception as exc:
        raise _http_error(500, f"Failed to fetch algorithms: {exc}") from exc


# ─── Training Jobs ────────────────────────────────────────────────────────────


@router.post("/training/start")
async def start_training(body: StartTrainingRequest):
    """Submit a cloud training job to Neuracore."""
    try:
        job_data = neuracore_service.start_training(body)
        return job_data
    except Exception as exc:
        raise _http_error(500, f"Failed to start training: {exc}") from exc


@router.get("/training/jobs")
async def list_training_jobs():
    """List all training jobs for the current organisation."""
    try:
        return neuracore_service.get_training_jobs()
    except Exception as exc:
        raise _http_error(500, f"Failed to list training jobs: {exc}") from exc


@router.get("/training/jobs/{job_id}")
async def get_training_job(job_id: str):
    """Get full details for a specific training job."""
    try:
        jobs = neuracore_service.get_training_jobs()
        for job in jobs:
            if job.get("id") == job_id:
                return job
        raise _http_error(404, f"Job {job_id} not found.")
    except HTTPException:
        raise
    except Exception as exc:
        raise _http_error(500, f"Failed to get training job: {exc}") from exc


@router.get("/training/jobs/{job_id}/logs")
async def get_training_job_logs(job_id: str, max_entries: int = 100):
    """Retrieve cloud logs for a training job."""
    try:
        return neuracore_service.get_training_job_logs(job_id, max_entries=max_entries)
    except Exception as exc:
        raise _http_error(500, f"Failed to get training logs: {exc}") from exc


@router.get("/training/jobs/{job_id}/model-url")
async def get_model_download_url(job_id: str):
    """Return a signed download URL for the trained model archive of a completed job."""
    try:
        url = neuracore_service.get_model_download_url(job_id)
        return {"url": url}
    except Exception as exc:
        raise _http_error(500, f"Failed to get model download URL: {exc}") from exc


@router.delete("/training/jobs/{job_id}")
async def delete_training_job(job_id: str):
    """Delete a training job and free its cloud resources."""
    try:
        neuracore_service.delete_training_job(job_id)
        return {"message": f"Job {job_id} deleted."}
    except Exception as exc:
        raise _http_error(500, f"Failed to delete training job: {exc}") from exc
