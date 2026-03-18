"""Neuracore cloud training service.

Wraps the neuracore Python SDK (pip install neuracore) for robot registration,
HuggingFace LeRobot dataset import, and cloud training job management.
"""

from __future__ import annotations

import logging
import tempfile
import threading
import uuid
from pathlib import Path
from typing import Optional

import requests as http_requests
import yaml

from backend.models.neuracore_training import (
    AlgorithmInfo,
    ImportDatasetRequest,
    ImportStatusResponse,
    StartTrainingRequest,
)

logger = logging.getLogger(__name__)

NEURACORE_API_URL = "https://api.neuracore.com/api"

# Default SO101 joint names (single arm, 6 DoF).
# For bimanual datasets the user should supply 12 names with left_/right_ prefixes.
SO101_DEFAULT_JOINT_NAMES = [
    "shoulder_pan",
    "shoulder_lift",
    "elbow_flex",
    "wrist_flex",
    "wrist_roll",
    "gripper",
]


class _ImportTask:
    """Mutable state for a background import thread."""

    def __init__(self, import_id: str) -> None:
        self.import_id = import_id
        self.status = "pending"
        self.progress = 0.0
        self.message = "Queued…"
        self.error: Optional[str] = None


class NeuracoreService:
    """Singleton service for Neuracore platform integration."""

    def __init__(self) -> None:
        self._api_key: Optional[str] = None
        self._nc_logged_in: bool = False
        self._import_tasks: dict[str, _ImportTask] = {}
        self._lock = threading.Lock()

    # ──────────────────────────────── Auth ────────────────────────────────

    def generate_api_key(self, email: str, password: str) -> str:
        """Authenticate with email/password and return a new API key.

        Mirrors neuracore.core.cli.generate_api_key but without interactive prompts.
        """
        auth_resp = http_requests.post(
            f"{NEURACORE_API_URL}/auth/token",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={"username": email, "password": password},
            timeout=15,
        )
        if auth_resp.status_code == 401:
            raise ValueError("Incorrect email or password.")
        auth_resp.raise_for_status()

        access_token = auth_resp.json()["access_token"]

        key_resp = http_requests.get(
            f"{NEURACORE_API_URL}/auth/api-key",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=15,
        )
        key_resp.raise_for_status()
        api_key: str = key_resp.json()["key"]

        self._api_key = api_key
        self._nc_logged_in = False
        # Persist into neuracore's own config so subsequent nc.login() calls work
        try:
            import neuracore as nc
            nc.login(api_key=api_key)
            self._nc_logged_in = True
        except Exception:
            pass

        return api_key

    def login_with_key(self, api_key: str) -> None:
        """Login to Neuracore with an existing API key."""
        import neuracore as nc

        nc.login(api_key=api_key)
        self._api_key = api_key
        self._nc_logged_in = True

    def is_authenticated(self) -> bool:
        """Return True if an API key is stored in this session."""
        return self._api_key is not None

    def _ensure_auth(self) -> None:
        """Ensure the SDK session is active. Login only if not already done."""
        if not self._api_key:
            raise ValueError("Not authenticated. Please provide Neuracore credentials first.")
        if not self._nc_logged_in:
            import neuracore as nc
            nc.login(api_key=self._api_key)
            self._nc_logged_in = True

    # ─────────────────────────── Organizations ────────────────────────────

    def list_orgs(self) -> list[dict]:
        """Return all orgs the authenticated user belongs to."""
        self._ensure_auth()
        from neuracore.core.organizations import list_my_orgs

        orgs = list_my_orgs()
        return [{"id": o.id, "name": o.name} for o in orgs]

    def set_org(self, id_or_name: str) -> None:
        """Set the active Neuracore organisation without any interactive prompt."""
        self._ensure_auth()
        import neuracore as nc

        nc.set_organization(id_or_name)

    def get_current_org_id(self) -> Optional[str]:
        """Return the org_id stored in neuracore config, or None if not set."""
        try:
            from neuracore.core.config.config_manager import get_config_manager

            return get_config_manager().config.current_org_id
        except Exception:
            return None

    # ────────────────────────────── Robot ─────────────────────────────────

    def connect_robot(self, robot_name: str) -> dict:
        """Register or retrieve a robot in Neuracore.

        Returns a dict with robot_id and robot_name.
        """
        self._ensure_auth()
        import neuracore as nc

        robot = nc.connect_robot(robot_name)
        return {"robot_id": robot.id, "robot_name": robot.name}

    def list_robots(self) -> list[dict]:
        """List all robots in the current organisation."""
        self._ensure_auth()
        from neuracore.core.robot import list_organization_robots

        org_id = self.get_current_org_id()
        if not org_id:
            raise ValueError("No organisation selected. Please select an org first.")
        robots = list_organization_robots(org_id, is_shared=False, mode="current")
        return [{"id": r["id"], "name": r["name"]} for r in robots]

    def update_robot(self, robot_key: str, new_name: str) -> dict:
        """Rename a robot by its current name or ID."""
        self._ensure_auth()
        import neuracore as nc

        robot_id = nc.update_robot_name(robot_key, new_name)
        return {"robot_id": robot_id, "robot_name": new_name}

    # ─────────────────────────── Datasets ─────────────────────────────────

    def list_datasets(self) -> list[dict]:
        """List Neuracore datasets for the current organisation."""
        self._ensure_auth()
        from neuracore.core.auth import get_auth
        from neuracore.core.config.get_current_org import get_current_org
        from neuracore.core.const import API_URL

        auth = get_auth()
        org_id = get_current_org()
        resp = http_requests.get(
            f"{API_URL}/org/{org_id}/datasets",
            headers=auth.get_headers(),
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()

    # ──────────────────────────── Import ──────────────────────────────────

    def start_import(self, request: ImportDatasetRequest) -> str:
        """Kick off a background thread that imports an HF dataset into Neuracore.

        Returns the import_id for polling via get_import_status().
        """
        import_id = str(uuid.uuid4())
        task = _ImportTask(import_id)
        with self._lock:
            self._import_tasks[import_id] = task

        thread = threading.Thread(
            target=self._run_import,
            args=(task, request),
            daemon=True,
            name=f"nc-import-{import_id[:8]}",
        )
        thread.start()
        return import_id

    def get_import_status(self, import_id: str) -> ImportStatusResponse:
        """Return the current status of an import task."""
        with self._lock:
            task = self._import_tasks.get(import_id)
        if task is None:
            return ImportStatusResponse(
                import_id=import_id,
                status="not_found",
                progress=0.0,
                message="Import task not found",
                error="Task not found",
            )
        return ImportStatusResponse(
            import_id=task.import_id,
            status=task.status,
            progress=task.progress,
            message=task.message,
            error=task.error,
        )

    def _run_import(self, task: _ImportTask, request: ImportDatasetRequest) -> None:
        """Execute the LeRobot → Neuracore import in a background thread."""
        config_path: Optional[Path] = None
        try:
            import neuracore as nc
            from neuracore.core.data.dataset import Dataset  # needed for get_by_name
            # Bypass importer.py — it unconditionally imports tensorflow via rlds_tfds_importer
            from neuracore.importer.lerobot_importer import LeRobotDatasetImporter
            from neuracore_types.nc_data import DatasetImportConfig

            task.status = "running"
            task.message = "Authenticating with Neuracore…"
            nc.login(api_key=self._api_key)  # background thread needs its own login

            task.message = "Creating / resolving dataset…"
            task.progress = 0.1
            existing = Dataset.get_by_name(request.neuracore_dataset_name, non_exist_ok=True)
            if existing is None:
                try:
                    nc.create_dataset(name=request.neuracore_dataset_name)
                except Exception as create_exc:
                    # Name may already exist globally (in another org); try retrieving it
                    logger.warning(
                        "create_dataset failed (%s); trying to use existing dataset",
                        create_exc,
                    )
                    try:
                        nc.get_dataset(name=request.neuracore_dataset_name)
                    except Exception as get_exc:
                        # Name lookup also failed — last resort: list all datasets and match by
                        # name, then activate by ID (different API endpoint, bypasses name-lookup bug)
                        logger.warning(
                            "get_dataset(name=...) failed (%s); scanning dataset list for name match",
                            get_exc,
                        )
                        datasets = self.list_datasets()
                        match = next(
                            (d for d in datasets if d.get("name") == request.neuracore_dataset_name),
                            None,
                        )
                        if match is None:
                            raise ValueError(
                                f"Dataset '{request.neuracore_dataset_name}' could not be created or found. "
                                "The name may be reserved or tombstoned on Neuracore. "
                                "Try a different dataset name."
                            ) from get_exc
                        logger.info(
                            "Found dataset '%s' by list scan (id=%s); activating by ID",
                            request.neuracore_dataset_name,
                            match["id"],
                        )
                        nc.get_dataset(id=match["id"])
            else:
                logger.info(
                    "Dataset '%s' already exists; new episodes will be appended.",
                    request.neuracore_dataset_name,
                )
                # Set active dataset so start_recording() uses the right dataset
                nc.get_dataset(name=request.neuracore_dataset_name)

            task.message = "Registering robot…"
            task.progress = 0.15
            nc.connect_robot(request.robot_name)

            task.message = "Building import configuration…"
            task.progress = 0.2

            if request.dataset_source == "local" and request.local_dataset_path:
                dataset_dir = Path(request.local_dataset_path)
                input_dataset_name = dataset_dir.name
                if not dataset_dir.exists():
                    raise ValueError(f"Local dataset path not found: {dataset_dir}")
            else:
                # HuggingFace — use cache, or download if missing
                dataset_dir = (
                    Path.home() / ".cache" / "huggingface" / "lerobot" / request.hf_repo_id
                )
                input_dataset_name = request.hf_repo_id
                if not dataset_dir.exists():
                    task.message = f"Downloading {request.hf_repo_id} from HuggingFace Hub…"
                    task.progress = 0.22
                    from huggingface_hub import snapshot_download
                    snapshot_download(
                        repo_id=request.hf_repo_id,
                        repo_type="dataset",
                        local_dir=str(dataset_dir),
                    )

            yaml_config = self._build_yaml_config(request, input_dataset_name=input_dataset_name)
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".yaml", delete=False
            ) as fh:
                yaml.dump(yaml_config, fh, default_flow_style=False)
                config_path = Path(fh.name)

            task.message = f"Loading metadata from {dataset_dir}…"
            task.progress = 0.25

            dataconfig = DatasetImportConfig.from_file(config_path)

            task.message = "Preparing importer…"
            task.progress = 0.3

            importer = LeRobotDatasetImporter(
                input_dataset_name=input_dataset_name,
                output_dataset_name=request.neuracore_dataset_name,
                dataset_dir=dataset_dir,
                dataset_config=dataconfig,
            )

            # Use the low-level API (build_work_items → prepare_worker → import_item)
            # instead of import_all() so we can report per-episode progress.
            work_items = importer.build_work_items()
            num_episodes = max(len(work_items), 1)
            # Mirror what _worker_entry does before calling prepare_worker:
            # set _worker_id so nc.start_recording(instance=...) uses instance 0.
            importer._worker_id = 0
            importer.prepare_worker(0, work_items)

            episode_errors = 0
            for i, item in enumerate(work_items):
                task.progress = 0.3 + 0.65 * (i / num_episodes)
                task.message = f"Uploading episode {i + 1}/{num_episodes}…"
                try:
                    importer.import_item(item)
                except Exception as ep_exc:
                    logger.warning("Episode %d import failed: %s", i, ep_exc)
                    episode_errors += 1

            # Drain any errors queued via the internal _error_queue
            try:
                q = getattr(importer, "_error_queue", None)
                if q is not None:
                    while True:
                        try:
                            q.get_nowait()
                            episode_errors += 1
                        except Exception:
                            break
            except Exception:
                pass

            worker_err_count = episode_errors
            task.status = "completed"
            task.progress = 1.0
            task.message = (
                f"Import completed with {worker_err_count} warning(s) (server-side cleanup errors are normal)."
                if worker_err_count
                else "Import completed successfully!"
            )

        except Exception as exc:
            logger.exception("Neuracore import failed")
            task.status = "failed"
            task.error = str(exc)
            task.message = f"Import failed: {exc}"
        finally:
            if config_path and config_path.exists():
                config_path.unlink(missing_ok=True)

    @staticmethod
    def _build_yaml_config(request: ImportDatasetRequest, input_dataset_name: str | None = None) -> dict:
        """Construct the DatasetImportConfig YAML dict for an SO101 LeRobot dataset."""
        name = input_dataset_name or request.hf_repo_id
        joint_mapping = [{"name": n} for n in request.joint_names]

        data_import: dict = {
            "JOINT_POSITIONS": {
                "source": "observation.state",
                "units": "RADIANS",
                "mapping": joint_mapping,
            },
            "JOINT_TARGET_POSITIONS": {
                "source": "action",
                "units": "RADIANS",
                "mapping": joint_mapping,
            },
        }

        if request.camera_names:
            data_import["RGB_IMAGES"] = {
                "source": "observation.images",
                "format": {
                    "image_convention": "CHANNELS_FIRST",
                    "order_of_channels": "RGB",
                    "normalized_pixel_values": True,
                },
                "mapping": [
                    {"name": cam, "source_name": cam} for cam in request.camera_names
                ],
            }

        return {
            "input_dataset_name": name,
            "dataset_type": "LEROBOT",
            "output_dataset": {"name": request.neuracore_dataset_name},
            "robot": {"name": request.robot_name},
            "frequency": request.frequency,
            "data_import_config": data_import,
        }

    # ──────────────────────────── Training ────────────────────────────────

    def get_algorithms(self) -> list[AlgorithmInfo]:
        """Fetch available training algorithms from Neuracore."""
        self._ensure_auth()
        from neuracore.api.training import _get_algorithms

        raw = _get_algorithms()
        return [
            AlgorithmInfo(
                id=alg.get("id", alg.get("name", "")),
                name=alg.get("name", ""),
                description=alg.get("description"),
            )
            for alg in raw
        ]

    def start_training(self, request: StartTrainingRequest) -> dict:
        """Submit a cloud training job to Neuracore.

        Resolves the robot_id from the dataset, then builds the input/output
        data specs before calling nc.start_training_run().
        """
        self._ensure_auth()
        import neuracore as nc

        dataset = nc.get_dataset(name=request.dataset_name)
        if not dataset.robot_ids:
            raise ValueError(
                f"Dataset '{request.dataset_name}' has no associated robot. "
                "Ensure the import completed successfully."
            )
        robot_id = dataset.robot_ids[0]

        input_spec: dict = {robot_id: {}}
        if request.input_joint_names:
            input_spec[robot_id][nc.DataType.JOINT_POSITIONS] = request.input_joint_names
        if request.input_camera_names:
            input_spec[robot_id][nc.DataType.RGB_IMAGES] = request.input_camera_names

        output_spec: dict = {
            robot_id: {
                nc.DataType.JOINT_TARGET_POSITIONS: request.output_joint_names,
            }
        }

        job_data = nc.start_training_run(
            name=request.job_name,
            dataset_name=request.dataset_name,
            algorithm_name=request.algorithm_name,
            algorithm_config=request.algorithm_config,
            gpu_type=request.gpu_type,
            num_gpus=request.num_gpus,
            frequency=request.frequency,
            input_robot_data_spec=input_spec,
            output_robot_data_spec=output_spec,
            name_auto_increment=True,
        )
        return job_data

    def get_training_jobs(self) -> list[dict]:
        """List all training jobs for the current organisation."""
        self._ensure_auth()
        import neuracore as nc

        return nc.get_training_jobs()

    def get_training_job_status(self, job_id: str) -> str:
        """Get the status string for a training job."""
        self._ensure_auth()
        import neuracore as nc

        return nc.get_training_job_status(job_id)

    def get_training_job_logs(self, job_id: str, max_entries: int = 100) -> dict:
        """Fetch cloud logs for a training job."""
        self._ensure_auth()
        import neuracore as nc

        return nc.get_training_job_logs(job_id, max_entries=max_entries)

    def delete_training_job(self, job_id: str) -> None:
        """Delete a training job and free cloud resources."""
        self._ensure_auth()
        import neuracore as nc

        nc.delete_training_job(job_id)


# Module-level singleton — shared across all request handlers
neuracore_service = NeuracoreService()
