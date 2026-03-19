"""Neuracore cloud training service.

Wraps the neuracore Python SDK (pip install neuracore) for robot registration,
HuggingFace LeRobot dataset import, and cloud training job management.
"""

from __future__ import annotations

import logging
import multiprocessing as mp
import threading
import uuid
from pathlib import Path
from typing import Optional

import requests as http_requests

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


# ── Subprocess worker (module-level so multiprocessing can pickle it) ──────────
#
# The neuracore SDK creates ZMQ PUSH sockets in Producer objects for each data
# stream.  cleanup_producer() updates recording state but does NOT close the
# socket; the socket accumulates across episodes and imports.  Running each
# import in a fresh subprocess guarantees the OS reclaims all file descriptors
# on exit, making re-imports safe.

def _nc_import_subprocess(
    queue: "mp.Queue[dict]",
    api_key: str,
    org_id: str,
    request_dict: dict,
) -> None:
    """Execute a LeRobot→Neuracore import inside a clean subprocess.

    Communicates progress back to the parent via *queue* using dicts with keys:
      {"type": "progress", "value": float, "msg": str}
      {"type": "done", "warnings": int}
      {"type": "error", "msg": str}
    """
    import tempfile
    import traceback
    import yaml
    from pathlib import Path as _Path

    config_path: Optional[str] = None
    try:
        import neuracore as nc
        from neuracore.core.data.dataset import Dataset
        from neuracore.importer.lerobot_importer import LeRobotDatasetImporter
        from neuracore_types.nc_data import DatasetImportConfig

        def _put(progress: float, msg: str) -> None:
            queue.put({"type": "progress", "value": progress, "msg": msg})

        _put(0.05, "Authenticating with Neuracore…")
        nc.login(api_key=api_key)
        nc.set_organization(org_id)

        dataset_name = request_dict["neuracore_dataset_name"]
        _put(0.1, "Creating / resolving dataset…")
        existing = Dataset.get_by_name(dataset_name, non_exist_ok=True)
        if existing is None:
            try:
                nc.create_dataset(name=dataset_name)
            except Exception as create_exc:
                try:
                    nc.get_dataset(name=dataset_name)
                except Exception as get_exc:
                    # List-scan fallback
                    from neuracore.core.auth import get_auth
                    from neuracore.core.config.get_current_org import get_current_org
                    from neuracore.core.const import API_URL
                    auth = get_auth()
                    oid = get_current_org()
                    resp = http_requests.get(
                        f"{API_URL}/org/{oid}/datasets",
                        headers=auth.get_headers(),
                        timeout=15,
                    )
                    resp.raise_for_status()
                    match = next(
                        (d for d in resp.json() if d.get("name") == dataset_name),
                        None,
                    )
                    if match is None:
                        raise ValueError(
                            f"Dataset '{dataset_name}' could not be created or found. "
                            "Try a different dataset name."
                        ) from get_exc
                    nc.get_dataset(id=match["id"])
        else:
            nc.get_dataset(name=dataset_name)

        _put(0.15, "Registering robot…")
        nc.connect_robot(request_dict["robot_name"])

        _put(0.2, "Building import configuration…")
        dataset_source = request_dict.get("dataset_source", "huggingface")
        local_path = request_dict.get("local_dataset_path")
        hf_repo_id = request_dict.get("hf_repo_id", "")

        if dataset_source == "local" and local_path:
            dataset_dir = _Path(local_path)
            input_dataset_name = dataset_dir.name
            if not dataset_dir.exists():
                raise ValueError(f"Local dataset path not found: {dataset_dir}")
        else:
            dataset_dir = _Path.home() / ".cache" / "huggingface" / "lerobot" / hf_repo_id
            input_dataset_name = hf_repo_id
            if not dataset_dir.exists():
                _put(0.22, f"Downloading {hf_repo_id} from HuggingFace Hub…")
                from huggingface_hub import snapshot_download
                snapshot_download(
                    repo_id=hf_repo_id,
                    repo_type="dataset",
                    local_dir=str(dataset_dir),
                )

        joint_names = request_dict.get("joint_names", [])
        camera_names = request_dict.get("camera_names", [])
        frequency = request_dict.get("frequency", 30)
        joint_mapping = [{"name": n} for n in joint_names]
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
        if camera_names:
            data_import["RGB_IMAGES"] = {
                "source": "observation.images",
                "format": {
                    "image_convention": "CHANNELS_FIRST",
                    "order_of_channels": "RGB",
                    "normalized_pixel_values": True,
                },
                "mapping": [{"name": cam, "source_name": cam} for cam in camera_names],
            }
        yaml_config = {
            "input_dataset_name": input_dataset_name,
            "dataset_type": "LEROBOT",
            "output_dataset": {"name": dataset_name},
            "robot": {"name": request_dict["robot_name"]},
            "frequency": frequency,
            "data_import_config": data_import,
        }

        import tempfile as _tempfile
        with _tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as fh:
            yaml.dump(yaml_config, fh, default_flow_style=False)
            config_path = fh.name

        _put(0.25, f"Loading metadata from {dataset_dir}…")
        dataconfig = DatasetImportConfig.from_file(config_path)

        _put(0.3, "Preparing importer…")
        importer = LeRobotDatasetImporter(
            input_dataset_name=input_dataset_name,
            output_dataset_name=dataset_name,
            dataset_dir=dataset_dir,
            dataset_config=dataconfig,
        )
        work_items = importer.build_work_items()
        num_episodes = max(len(work_items), 1)
        importer._worker_id = 0
        importer.prepare_worker(0, work_items)

        episode_errors = 0
        for i, item in enumerate(work_items):
            _put(0.3 + 0.65 * (i / num_episodes), f"Uploading episode {i + 1}/{num_episodes}…")
            try:
                importer.import_item(item)
            except Exception:
                episode_errors += 1

        # Drain internal error queue
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

        queue.put({"type": "done", "warnings": episode_errors})

    except Exception as exc:
        queue.put({"type": "error", "msg": str(exc), "tb": traceback.format_exc()})
    finally:
        if config_path:
            try:
                _Path(config_path).unlink(missing_ok=True)
            except Exception:
                pass


# ── Task tracking ──────────────────────────────────────────────────────────────

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
        """Authenticate with email/password and return a new API key."""
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
        return self._api_key is not None

    def _ensure_auth(self) -> None:
        if not self._api_key:
            raise ValueError("Not authenticated. Please provide Neuracore credentials first.")
        if not self._nc_logged_in:
            import neuracore as nc
            nc.login(api_key=self._api_key)
            self._nc_logged_in = True

    # ─────────────────────────── Organizations ────────────────────────────

    def list_orgs(self) -> list[dict]:
        self._ensure_auth()
        from neuracore.core.organizations import list_my_orgs

        orgs = list_my_orgs()
        return [{"id": o.id, "name": o.name} for o in orgs]

    def set_org(self, id_or_name: str) -> None:
        self._ensure_auth()
        import neuracore as nc

        nc.set_organization(id_or_name)

    def get_current_org_id(self) -> Optional[str]:
        try:
            from neuracore.core.config.config_manager import get_config_manager

            return get_config_manager().config.current_org_id
        except Exception:
            return None

    # ────────────────────────────── Robot ─────────────────────────────────

    def connect_robot(self, robot_name: str) -> dict:
        self._ensure_auth()
        import neuracore as nc

        robot = nc.connect_robot(robot_name)
        return {"robot_id": robot.id, "robot_name": robot.name}

    def list_robots(self) -> list[dict]:
        self._ensure_auth()
        from neuracore.core.robot import list_organization_robots

        org_id = self.get_current_org_id()
        if not org_id:
            raise ValueError("No organisation selected. Please select an org first.")
        robots = list_organization_robots(org_id, is_shared=False, mode="current")
        return [{"id": r["id"], "name": r["name"]} for r in robots]

    def update_robot(self, robot_key: str, new_name: str) -> dict:
        self._ensure_auth()
        import neuracore as nc

        robot_id = nc.update_robot_name(robot_key, new_name)
        return {"robot_id": robot_id, "robot_name": new_name}

    # ─────────────────────────── Datasets ─────────────────────────────────

    def list_datasets(self) -> list[dict]:
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
        """Kick off a subprocess that imports a LeRobot dataset into Neuracore.

        Returns the import_id for polling via get_import_status().
        """
        org_id = self.get_current_org_id() or ""
        import_id = str(uuid.uuid4())
        task = _ImportTask(import_id)
        with self._lock:
            self._import_tasks[import_id] = task

        thread = threading.Thread(
            target=self._run_import,
            args=(task, request, org_id),
            daemon=True,
            name=f"nc-import-{import_id[:8]}",
        )
        thread.start()
        return import_id

    def get_import_status(self, import_id: str) -> ImportStatusResponse:
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

    def _run_import(
        self, task: _ImportTask, request: ImportDatasetRequest, org_id: str
    ) -> None:
        """Spawn a subprocess for the import so every run gets a clean OS process.

        The neuracore SDK leaks ZMQ PUSH sockets (one per data type per episode)
        because Producer.cleanup_producer() updates recording state but does not
        close the socket.  A subprocess guarantees the OS reclaims all FDs on exit,
        making re-imports safe without patching the SDK.
        """
        task.status = "running"
        task.message = "Starting import subprocess…"

        ctx = mp.get_context("spawn")
        queue: mp.Queue = ctx.Queue()
        proc = ctx.Process(
            target=_nc_import_subprocess,
            args=(queue, self._api_key, org_id, request.model_dump()),
            daemon=False,
            name="nc-import-proc",
        )
        proc.start()

        try:
            while proc.is_alive():
                try:
                    msg = queue.get(timeout=2.0)
                except Exception:
                    continue

                if msg["type"] == "progress":
                    task.progress = msg["value"]
                    task.message = msg["msg"]
                elif msg["type"] == "done":
                    w = msg.get("warnings", 0)
                    task.status = "completed"
                    task.progress = 1.0
                    task.message = (
                        f"Import completed with {w} warning(s)." if w
                        else "Import completed successfully!"
                    )
                    break
                elif msg["type"] == "error":
                    task.status = "failed"
                    task.error = msg["msg"]
                    task.message = f"Import failed: {msg['msg']}"
                    logger.error("Import subprocess error:\n%s", msg.get("tb", ""))
                    break

            # Drain any remaining messages after subprocess exits
            while True:
                try:
                    msg = queue.get_nowait()
                    if msg["type"] == "progress":
                        task.progress = msg["value"]
                        task.message = msg["msg"]
                    elif msg["type"] == "done":
                        w = msg.get("warnings", 0)
                        task.status = "completed"
                        task.progress = 1.0
                        task.message = (
                            f"Import completed with {w} warning(s)." if w
                            else "Import completed successfully!"
                        )
                    elif msg["type"] == "error":
                        task.status = "failed"
                        task.error = msg["msg"]
                        task.message = f"Import failed: {msg['msg']}"
                except Exception:
                    break

        except Exception as exc:
            task.status = "failed"
            task.error = str(exc)
            task.message = f"Import monitor error: {exc}"
        finally:
            proc.join(timeout=10)
            if proc.is_alive():
                proc.terminate()
                proc.join(timeout=5)

        # If process died without sending a terminal message, mark as failed
        if task.status == "running":
            task.status = "failed"
            task.error = f"Import subprocess exited unexpectedly (code {proc.exitcode})"
            task.message = task.error

    # ──────────────────────────── Training ────────────────────────────────

    def get_algorithms(self) -> list[AlgorithmInfo]:
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
        self._ensure_auth()
        import neuracore as nc

        return nc.get_training_jobs()

    def get_training_job_status(self, job_id: str) -> str:
        self._ensure_auth()
        import neuracore as nc

        return nc.get_training_job_status(job_id)

    def get_training_job_logs(self, job_id: str, max_entries: int = 100) -> dict:
        self._ensure_auth()
        import neuracore as nc

        return nc.get_training_job_logs(job_id, max_entries=max_entries)

    def get_model_download_url(self, job_id: str) -> str:
        """Return a signed download URL for the trained model archive of a completed job."""
        self._ensure_auth()
        from neuracore.core.auth import get_auth
        from neuracore.core.config.get_current_org import get_current_org
        from neuracore.core.const import API_URL

        auth = get_auth()
        org_id = get_current_org()
        resp = http_requests.get(
            f"{API_URL}/org/{org_id}/training/jobs/{job_id}/model_url",
            headers=auth.get_headers(),
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()["url"]

    def delete_training_job(self, job_id: str) -> None:
        self._ensure_auth()
        import neuracore as nc

        nc.delete_training_job(job_id)


# Module-level singleton — shared across all request handlers
neuracore_service = NeuracoreService()
