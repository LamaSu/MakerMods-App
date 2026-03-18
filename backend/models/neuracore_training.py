"""Pydantic models for Neuracore cloud training integration."""

from typing import Any, Optional

from pydantic import BaseModel


class NeuracoreLoginRequest(BaseModel):
    """Login via email and password (generates API key)."""

    email: str
    password: str


class NeuracoreLoginKeyRequest(BaseModel):
    """Login with an existing API key."""

    api_key: str


class NeuracoreLoginStatus(BaseModel):
    """Authentication status."""

    authenticated: bool
    message: str


class ConnectRobotRequest(BaseModel):
    """Register or retrieve a robot in Neuracore."""

    robot_name: str


class ConnectRobotResponse(BaseModel):
    """Registered robot details."""

    robot_id: str
    robot_name: str


class ImportDatasetRequest(BaseModel):
    """Request to import an HF LeRobot dataset into Neuracore cloud."""

    hf_repo_id: str  # e.g. "username/my-dataset"
    neuracore_dataset_name: str
    robot_name: str
    joint_names: list[str]  # positional mapping for observation.state / action
    camera_names: list[str]  # observation.images.{name} keys
    frequency: int = 30  # dataset FPS
    dataset_source: str = "huggingface"  # "huggingface" | "local"
    local_dataset_path: Optional[str] = None  # used when dataset_source == "local"


class ImportStatusResponse(BaseModel):
    """Status of a background import task."""

    import_id: str
    status: str  # "pending" | "running" | "completed" | "failed"
    progress: float  # 0.0 – 1.0
    message: str
    error: Optional[str] = None


class StartTrainingRequest(BaseModel):
    """Request to launch a cloud training job on Neuracore."""

    job_name: str
    dataset_name: str
    algorithm_name: str
    algorithm_config: dict[str, Any]  # e.g. {batch_size, epochs, prediction_horizon}
    gpu_type: str = "NVIDIA_TESLA_V100"
    num_gpus: int = 1
    frequency: int = 30
    robot_name: str  # used to resolve the robot ID for data spec
    input_joint_names: list[str]
    input_camera_names: list[str]
    output_joint_names: list[str]


class TrainingJobInfo(BaseModel):
    """Summary of a Neuracore training job."""

    id: str
    name: str
    status: str
    created_at: Optional[str] = None


class AlgorithmInfo(BaseModel):
    """Neuracore training algorithm descriptor."""

    id: str
    name: str
    description: Optional[str] = None


class OrgInfo(BaseModel):
    """A Neuracore organisation the user belongs to."""

    id: str
    name: str


class SelectOrgRequest(BaseModel):
    """Request to set the active Neuracore organisation."""

    id_or_name: str


class RobotInfo(BaseModel):
    """A robot registered in Neuracore."""

    id: str
    name: str


class UpdateRobotRequest(BaseModel):
    """Request to rename a robot."""

    robot_key: str  # current name or ID
    new_name: str
