# xLeRobot Web UI - Implementation Progress

---

## 2026-03-18 — Per-Episode Progress Bar for Neuracore Dataset Import

Replaced `importer.import_all()` with a manual episode loop using `build_work_items()` + `prepare_worker()` + `import_item()`. This allows the backend to update `task.progress` and `task.message` after each episode, so the frontend progress bar advances continuously instead of staying stuck at 30% for the entire upload.

Progress range: 0.30 (start of upload) → 0.95 (last episode), then 1.0 on completion.
Message example: `"Uploading episode 5/42…"`

### Files Modified
- `backend/services/neuracore_service.py`

---

## 2026-03-18 — Flexible Dataset Source for Neuracore Import (Local path + HuggingFace auto-download)

Added two dataset source options to the Neuracore import flow:
- **Local path**: import from any directory on disk containing a LeRobot dataset
- **HuggingFace**: use local cache if present, otherwise `snapshot_download` from the Hub automatically

### Changes
- **Backend**: Added `dataset_source` (`"huggingface"` | `"local"`) and `local_dataset_path` fields to `ImportDatasetRequest`
- **Backend**: `_run_import` now resolves `dataset_dir` based on source — for local, validates the path exists; for HF, downloads via `snapshot_download` if cache is missing
- **Backend**: `_build_yaml_config` accepts an optional `input_dataset_name` override (used to set the correct name for local datasets)
- **Frontend**: `neuracoreImportDataset` service function extended with `datasetSource` and `localDatasetPath` params
- **Frontend**: Dataset Import section now shows a HuggingFace / Local Path toggle; conditionally renders the appropriate input with helper text; Import button disabled when the relevant field is empty

### Files Modified
- `backend/models/neuracore_training.py`
- `backend/services/neuracore_service.py`
- `frontend/lib/services.ts`
- `frontend/components/wizard/steps/train-step.tsx`

---

## 2026-03-18 — Robot Management in Neuracore Training Step

Added full robot management to the train step: select existing robot, create new robot, and edit/rename an existing robot inline.

### Changes
- **Backend**: Added `list_robots()` and `update_robot()` to `NeuracoreService`, wrapping `list_organization_robots()` and `nc.update_robot_name()` from the Neuracore SDK
- **Backend**: Added `RobotInfo` and `UpdateRobotRequest` Pydantic models
- **Backend**: Added `GET /api/neuracore/robots` and `PUT /api/neuracore/robots/{robot_id}` endpoints
- **Frontend**: Added `neuracoreListRobots` and `neuracoreUpdateRobot` service functions
- **Frontend**: Replaced simple robot name input with a dropdown selector (existing robots + "Create new"), inline create form, and Edit Name flow with save/cancel

### Files Modified
- `backend/services/neuracore_service.py`
- `backend/models/neuracore_training.py`
- `backend/api/neuracore_training.py`
- `frontend/lib/services.ts`
- `frontend/components/wizard/steps/train-step.tsx`

---

## 2026-03-18 — Fix Training Job Log Parsing

Confirmed actual API response shape via curl: `{ job_id, logs: [{timestamp, severity, message}], total_entries, retrieved_at }`. Logs come newest-first from the API.

Updated `handleExpandJob` in `train-step.tsx` to:
- Explicitly read `obj.logs` (with `obj.entries`/`obj.results` as fallbacks)
- Reverse entries to show oldest-first (chronological order)
- Format each entry as `[YYYY-MM-DD HH:MM:SS] SEVERITY: message`
- Fall back to raw JSON only if none of the known array keys are present

### Files Modified
- `frontend/components/wizard/steps/train-step.tsx`

---

## 2026-03-18 — Fix Tombstoned Dataset Name Fallback (list-by-ID)

Added a third-level fallback in `_run_import` for dataset names that are "tombstoned" on Neuracore — where both `create_dataset()` and `get_dataset(name=...)` fail (name rejected for creation, name-based lookup returns nothing).

### Fix
When `get_dataset(name=...)` also fails, the code now calls `self.list_datasets()` (direct REST call to `GET /org/{org_id}/datasets`) and scans for a name match. If found, activates via `nc.get_dataset(id=match["id"])` which uses a different endpoint (`/org/{org_id}/datasets/{id}`) that bypasses the broken name-lookup. If no match is found in the list, raises a clear error suggesting the user try a different dataset name.

### Files Modified
- `backend/services/neuracore_service.py`

---

## 2026-03-18 — Fix Three Neuracore Import/Training Issues

Fixed three bugs discovered during dataset import and training job monitoring.

### Issues fixed

**1. Dataset name collision** — `nc.create_dataset()` crashed when a dataset of the same name existed globally on Neuracore (even if not in the queried org), because `Dataset.get_by_name(..., non_exist_ok=True)` returned `None` for globally-taken names not visible in the current org. Fixed by wrapping `create_dataset` in a try/except that falls back to `nc.get_dataset()` on failure.

**2. Worker error count in import message** — After `importer.import_all()` returns, the completion message now includes a warning count if `importer.worker_errors` is non-empty (e.g. 404 on `traces/active` from the last episode). The data is already uploaded in this case; the message clarifies it's a server-side cleanup warning.

**3. Training job logs blank** — Frontend assumed `{ entries: [...] }` shape but actual Neuracore API response may differ. Now handles: direct array, `entries`/`logs`/`results` key, or falls back to raw `JSON.stringify` so the user can see the actual structure.

### Files Modified
- `backend/services/neuracore_service.py`
- `frontend/components/wizard/steps/train-step.tsx`

---

## 2026-03-18 — Neuracore Organisation Selection

Fixed 500 error on `GET /api/neuracore/training/jobs` caused by `get_current_org()` blocking on interactive stdin when multiple orgs exist.

### Root cause
`_ensure_auth()` called `nc.login()` before every SDK call. SDK calls (e.g. `nc.get_training_jobs()`) internally invoke `get_current_org()`, which prompts interactively on stdin when no org is set in config — blocking FastAPI indefinitely.

### Fix
- `_ensure_auth()` now calls `nc.login()` only once per session (tracked via `_nc_logged_in` flag)
- Added `list_orgs()`, `set_org()`, `get_current_org_id()` to `NeuracoreService` using `nc.list_my_orgs()` and `nc.set_organization()` (non-interactive)
- New API endpoints: `GET /api/neuracore/orgs`, `GET /api/neuracore/orgs/current`, `POST /api/neuracore/orgs/select`
- Frontend: new "Organisation" section (step 2) appears after login with a dropdown; auto-selects if only one org; changing org resets robot/downstream state
- Sections renumbered: Auth → Org → Robot → Dataset Import → Training Config

### Files Modified
- `backend/services/neuracore_service.py`
- `backend/models/neuracore_training.py`
- `backend/api/neuracore_training.py`
- `frontend/lib/wizard-types.ts`
- `frontend/lib/services.ts`
- `frontend/components/wizard/steps/train-step.tsx`

---

## 2026-03-17 — Standalone Distribution (ComfyUI-style)

Added a zero-dependency distribution bundle so end-users can run the app without installing Python or Node.js.

### Features
- `install.sh` / `install.bat` — bootstraps a standalone Python 3.11 via `uv` (no system Python required) and installs all deps into a local `.venv`
- `run.sh` / `run.bat` — activates `.venv` and starts `python -m backend.main` on port 8000
- `build_frontend.sh` — developer-only script (requires Node.js) that produces `frontend/out/` via `NEXT_STATIC_EXPORT=1 npm run build`
- FastAPI serves pre-built static frontend from `frontend/out/` when that directory exists (standalone mode); dev mode (Next.js on port 3000) is unaffected
- `requirements-standalone.txt` — complete dependency list including `lerobot` and `neuracore` (~2-4GB install with PyTorch)

### Files Created
- `install.sh` — macOS/Linux installer using `uv`
- `install.bat` — Windows installer using `uv`
- `run.sh` — macOS/Linux launcher
- `run.bat` — Windows launcher
- `build_frontend.sh` — developer frontend build script
- `requirements-standalone.txt` — standalone dependency list

### Files Modified
- `backend/main.py` — added port 8000 CORS origins; added conditional static file serving from `frontend/out/` after all API routers (catch-all route only active when `frontend/out/` exists)
- `frontend/next.config.ts` — conditional config: `output: "export"` when `NEXT_STATIC_EXPORT=1`, dev rewrites otherwise

### Notes
- WebSocket URL in `use-websocket.ts` already hardcodes `ws://localhost:8000` — correct for standalone, no change needed
- `frontend/out/` must be built by developer (`./build_frontend.sh`) and included in the distribution zip
- API routes registered before the catch-all take priority, so `/api/*` and `/ws/*` are unaffected in standalone mode

---

## 2026-03-17 — Neuracore Cloud Training Step

Added a new **Train** step (step 6) between Record and Inference, integrating Neuracore's cloud training platform.

### Features
- Provider selector UI: Neuracore (fully implemented) + Qualia (Coming Soon placeholder)
- Authentication via email/password (generates API key) or direct API key entry
- Robot registration: `neuracore.connect_robot(robot_name)` with wizard-derived default name
- HuggingFace → Neuracore dataset import using `LeRobotDatasetImporter` (background thread with progress polling)
  - SO101 default joint names hardcoded, user-overridable via textarea
  - Camera names auto-derived from wizard camera selections
  - Configurable FPS/frequency
- Training job configuration: algorithm selector, batch size, epochs, prediction horizon, GPU type/count
- Training job list with status badges, log viewer (expandable), and delete
- Auto-refresh jobs every 10 s when a job is actively running

### Files Modified
- `backend/models/neuracore_training.py` — **new**: Pydantic models for all Neuracore API types
- `backend/services/neuracore_service.py` — **new**: NeuracoreService singleton (auth, robot, import, training)
- `backend/api/neuracore_training.py` — **new**: FastAPI router at `/api/neuracore/*`
- `backend/main.py` — registered `neuracore_training` router
- `frontend/lib/wizard-types.ts` — added `NeuracoreConfig`, `INITIAL_NEURACORE_CONFIG`, Train step in `STEPS`, 8-step `WizardState`
- `frontend/lib/services.ts` — added all `neuracore*` API client functions
- `frontend/components/wizard/wizard-provider.tsx` — added `trainStepVisited`, `neuracoreConfig` state + reducer cases
- `frontend/components/wizard/wizard-layout.tsx` — inserted `TrainStep` at index 6
- `frontend/components/wizard/steps/train-step.tsx` — **new**: full Train step UI component

### Notes
- `neuracore` must be `pip install neuracore` in the backend environment
- Dataset import runs in a background daemon thread; frontend polls `/api/neuracore/import-status/{id}`
- Inference step is now step 7 (shifted from step 6)

---

## Architecture
- **Frontend**: Next.js 16 (App Router) + shadcn/ui + Tailwind CSS v4
- **Backend**: FastAPI (Python) + WebSocket for real-time logs
- **State**: React Context wizard state (client-side) + local JSON file (`webui_config.json`) for backend

---

## Backend (Complete)

### Services
- [x] `services/config_manager.py` - JSON config persistence (load/save/reset)
- [x] `services/process_manager.py` - Subprocess lifecycle (start/stop/logs/status)
- [x] `services/port_scanner.py` - Serial port detection via pyserial
- [x] `services/camera_scanner.py` - OpenCV camera detection + preview capture
- [x] `services/calibration_service.py` - Calibration file checking + command builder
- [x] `services/hf_service.py` - HuggingFace CLI integration (login/repos/create)

### Models
- [x] `models/config.py` - Config, CameraConfig, SingleArmConfig, BimanualConfig
- [x] `models/system.py` - ProcessStatus, CalibrationStatus, HFLoginStatus, SystemStatus
- [x] `models/setup.py` - PortInfo, CameraInfo, CameraPreview
- [x] `models/recording.py` - RecordingRequest, HFRepoInfo, CreateRepoRequest
- [x] `models/teleoperation.py` - TeleoperationRequest/Response
- [x] `models/inference.py` - InferenceRequest/Response

### API Routes
- [x] `api/config.py` - GET/POST/DELETE /api/config
- [x] `api/setup.py` - GET ports, GET cameras, POST camera previews, POST wiggle gripper, GET camera MJPEG stream
- [x] `api/calibration.py` - GET status, GET missing, GET files, POST start/stop
- [x] `api/teleoperation.py` - POST start/stop, GET status
- [x] `api/recording.py` - POST start/stop, GET status, DELETE cache
- [x] `api/inference.py` - POST start/stop, GET status
- [x] `api/huggingface.py` - GET whoami, GET/POST repos
- [x] `api/system.py` - GET system status

### Infrastructure
- [x] `main.py` - FastAPI app with CORS, static files, routers
- [x] `websockets/logs.py` - WebSocket log streaming endpoint
- [x] Entry point added to `pyproject.toml` (`lerobot-webui`)
- [x] `.gitignore` updated for webui files

---

## Frontend - Wizard Setup UI (Complete)

### Architecture
The frontend is a single-page wizard with 7 sequential steps. One centered card per step with a sidebar for navigation. Mock data layer with easy swap to real API.

### Core Infrastructure
- [x] `lib/wizard-types.ts` - All TypeScript interfaces, constants, initial state
- [x] `lib/services.ts` - Service layer with `USE_MOCK` toggle
- [x] `lib/mock-data.ts` - Mock responses for ports, cameras, calibration files
- [x] `lib/api.ts` - Real API client (used when `USE_MOCK=false`)
- [x] `lib/utils.ts` - Utility functions (cn)
- [x] `hooks/use-websocket.ts` - WebSocket hook for log streaming

### Wizard Components
- [x] `components/wizard/wizard-provider.tsx` - React Context + reducer for all wizard state
- [x] `components/wizard/wizard-layout.tsx` - Main shell: sidebar + topbar + centered card
- [x] `components/wizard/wizard-sidebar.tsx` - Step list with checkmarks, click navigation
- [x] `components/wizard/wizard-topbar.tsx` - "Clear Values" + "Restart" buttons
- [x] `components/wizard/step-card.tsx` - Shared card wrapper with Continue button

### Step Components
- [x] `components/wizard/steps/robot-type-step.tsx` - Step 1: Single/Bimanual selection cards
- [x] `components/wizard/steps/ports-step.tsx` - Step 2: Port scanning + role assignment + gripper wiggle to identify arms
- [x] `components/wizard/steps/cameras-step.tsx` - Step 3: Browser-native camera detection + live video feeds + naming
- [x] `components/wizard/steps/calibration-step.tsx` - Step 4: Calibration file selection per arm
- [x] `components/wizard/steps/teleoperate-step.tsx` - Step 5: Config summary + start/stop + logs
- [x] `components/wizard/steps/record-step.tsx` - Step 6: Recording form + start/stop + logs
- [x] `components/wizard/steps/inference-step.tsx` - Step 7: Inference with trained policy + start/stop + logs

### Shared Components (Reused)
- [x] `components/common/log-viewer.tsx` - Real-time log display with auto-scroll
- [x] `components/common/process-status.tsx` - Process status badge
- [x] `components/ui/` - 16 shadcn/ui components

### Pages
- [x] `app/layout.tsx` - Minimal root layout (fonts + TooltipProvider)
- [x] `app/page.tsx` - Single page wizard host with WizardProvider

---

## Changelog

### 2026-03-16
- **Feature: Inference step (Step 7) — Run trained policies on the robot** — Added a new wizard step for running inference with trained policies. The robot is controlled autonomously by a policy (no teleoperator needed). Uses `lerobot-record` with `--policy.path` and without `--teleop.*` flags.
  - **Model selector dropdown** — Dropdown with ACT (active), SmolVLA, Diffusion Policy, TD-MPC, and VQ-BeT (greyed out with "Coming Soon" badges). Only ACT is currently supported.
  - **Policy path input** — Accepts local folder path or HuggingFace repo ID of the trained policy.
  - **Evaluation config** — Repo ID for eval results, task description (should match training), episode count, episode duration, display data toggle.
  - **Real-time monitoring** — Live camera feeds, motor position sliders, WebSocket log streaming, and process crash detection (same patterns as Record step).
  - Created: `backend/models/inference.py` (InferenceRequest/InferenceResponse), `backend/api/inference.py` (start/stop/status endpoints + command builder), `frontend/components/wizard/steps/inference-step.tsx`
  - Modified: `backend/main.py` (registered inference router), `frontend/lib/wizard-types.ts` (InferenceConfig, INFERENCE_MODELS, step 7 definition, state fields), `frontend/components/wizard/wizard-provider.tsx` (inference actions/reducer/reset/completion), `frontend/lib/services.ts` (startInference/stopInference/getInferenceStatus), `frontend/components/wizard/wizard-layout.tsx` (registered InferenceStep)

### 2026-03-15
- **Fix: Bimanual teleoperation — calibration ID and path mismatch** — Bimanual teleoperation was crashing because (1) commands passed per-arm IDs instead of lerobot's expected base IDs, and (2) calibration files were stored under `bi_so101_*` directories instead of the `so101_*` directories that sub-arms actually look in. Root cause: lerobot's bimanual wrappers create `SO101Follower`/`SO101Leader` sub-arm instances that derive IDs as `{base}_left`/`{base}_right` and look for calibration files in `so101_follower/`/`so101_leader/`.
  - Replaced 4 per-arm ID fields (`left_follower_id`, etc.) with 2 base IDs (`follower_id`, `leader_id`) in `BimanualConfig`
  - Commands now pass `--robot.id={base}` and `--teleop.id={base}` matching lerobot docs
  - `getCalibrationPaths()` now uses `so101_follower`/`so101_leader` (sub-arm types)
  - Backend `list_missing_calibrations` and `get_calibration_status` updated to derive sub-arm IDs from base
  - Modified: `backend/models/config.py`, `backend/api/teleoperation.py`, `backend/api/recording.py`, `backend/api/calibration.py`, `backend/services/calibration_service.py`, `frontend/lib/wizard-types.ts`
- **Enhancement: Bimanual calibration naming validation** — Calibration step now validates that left/right arm pairs share the same base ID prefix with `_left`/`_right` suffixes. Shows info alert explaining the naming rule, and validation errors when names don't match. Base IDs are derived automatically from the calibration names via `validateBimanualCalibrationNames()`. Next button and teleoperation/recording are blocked until validation passes.
  - Modified: `frontend/lib/wizard-types.ts`, `frontend/components/wizard/wizard-provider.tsx`, `frontend/components/wizard/steps/calibration-step.tsx`, `frontend/lib/services.ts`, `frontend/components/wizard/steps/teleoperate-step.tsx`
- **Enhancement: Teleoperation error diagnostics** — When teleoperation crashes, the UI now parses logs for common failures (calibration mismatch, no motor movement, port access denied, device not found) and shows an actionable amber alert with diagnosis and suggested fix.
  - Modified: `frontend/components/wizard/steps/teleoperate-step.tsx`

### 2026-03-07
- **Feature: Configurable camera FPS and resolution** — Added FPS and resolution dropdowns to the Record step with recommended defaults (30 fps, 640×480). Options: FPS 15/24/30/60, resolution 320×240/640×480/1280×720/1920×1080. Values flow through `saveConfig` to the backend camera config instead of being hardcoded.
  - Modified: `frontend/lib/wizard-types.ts` (added `cameraFps`, `cameraWidth`, `cameraHeight` to `RecordingConfig`)
  - Modified: `frontend/components/wizard/steps/record-step.tsx` (camera settings UI)
  - Modified: `frontend/lib/services.ts` (pass configurable values in `saveConfig`)

### 2026-03-03
- **Feature: Recording step enhancements** — Major UX overhaul of the recording step (Step 6):
  1. **Recording phase status banner** — Parses `lerobot-record` log output to detect current phase (`recording`, `resetting`, `encoding`, `done`) and shows a contextual status card with phase-appropriate icon, message, and stop button. Recognises: `"Recording episode N"`, `"Reset the environment"`, `"Encoding videos"`, `"Stop recording"`.
  2. **Live camera + motor feeds** — When "Display data while recording" is enabled, shows camera feeds and motor position sliders (same as teleoperation step) during recording. Uses the shared `robot-display.tsx` components.
  3. **Collapsible terminal logs** — Replaced the always-visible `LogViewer` with a collapsible "Show Logs" dropdown (same pattern as teleoperation). Auto-opens on error.
  4. **Process crash detection** — Added 2s polling for process status to detect crashes and show an error banner with dismiss.
  5. **Repo ID duplicate warning** — Tracks used repo IDs in `localStorage`. If a previously-used repo ID is entered, shows an inline amber warning. On start, clears the HF cache (`DELETE /api/recording/cache`) to replace the old dataset cleanly.
  - Created: `frontend/components/common/robot-display.tsx` (shared `useMotorState`, `MotorPanel`, `CameraFeed`, `CameraFeedPanel`)
  - Modified: `frontend/components/wizard/steps/record-step.tsx`, `frontend/components/wizard/steps/teleoperate-step.tsx` (now imports from `robot-display`), `frontend/lib/services.ts` (added `clearCache`)

### 2026-02-28 (4)
- **Feature: Live camera feeds in teleoperation step** — Added a "Show camera feeds" toggle using browser `getUserMedia` with the exact `deviceId` from the cameras step (guarantees the same camera the user selected). Camera feeds are available before and during teleoperation. Backend always passes `--display_data=true` (needed for motor position stdout printing) but sets `RERUN_ENABLED=false` env var so the Rerun viewer window doesn't launch. Motor position sliders and camera feeds now coexist without Rerun.
  - Modified: `frontend/components/wizard/steps/teleoperate-step.tsx`, `backend/api/teleoperation.py`

### 2026-02-28 (3)
- **Redesign: Motor position sliders for teleoperation** — Replaced the dark table with a clean slider-based display. Each motor shows a labeled horizontal bar with a thumb indicator and numeric value on the right. Bar fills from center (0) outward to show positive/negative range. Uses a throttled `useMotorState` hook (~12Hz updates) with locked motor ordering to eliminate glitching from rapid re-renders and entry reordering.
  - Modified: `frontend/components/wizard/steps/teleoperate-step.tsx`

### 2026-02-28 (2)
- **Fix: Teleoperation motor table stuck / not updating** — Two bugs: (1) Subprocess stdout was block-buffered (Python default when stdout is a pipe), so `print()` calls were not flushed in real-time — fixed by setting `PYTHONUNBUFFERED=1` in subprocess env. (2) `stream_logs()` tracked new log lines by comparing `len(deque)`, but the deque has `maxlen=1000`, so once full (~2s at 60Hz), `len()` stays constant and the WebSocket stops delivering new lines — fixed by adding a monotonic `log_seq` counter + `asyncio.Event` to wake up the stream immediately. Also strips ANSI cursor-up escape sequences from teleoperate output.
  - Modified: `backend/services/process_manager.py`

### 2026-02-28
- **Feature: Live motor position table during teleoperation** — Parses motor position lines from the `lerobot-teleoperate` subprocess stdout (e.g. `shoulder_pan.pos | 12.45`) and displays them in a real-time encoder table (same dark theme as calibration step). Shows motor names, current normalized positions, and loop frequency (Hz). Table updates as new log lines arrive via WebSocket.
  - Modified: `frontend/components/wizard/steps/teleoperate-step.tsx`

### 2026-02-27 (3)
- **Redesign: Clean teleoperation UI** — Replaced raw log viewer with clean status banners: green "Teleoperation is running" banner with stop button when active, red error banner with dismiss when failed. Logs are hidden behind a collapsible "Show Logs" toggle (auto-opens on error). Added process status polling (every 2s) to detect crashes and show error state with message.
  - Modified: `frontend/components/wizard/steps/teleoperate-step.tsx`, `frontend/lib/services.ts`
- **Fix: Calibration EEPROM mismatch auto-accept** — Process manager now pipes stdin with newlines so interactive calibration prompts ("Press ENTER to use provided calibration file") are auto-accepted instead of hanging.
  - Modified: `backend/services/process_manager.py`
- **Fix: Calibration IDs in teleoperation command** — Robot/teleoperator IDs were hardcoded (`single_follower`/`single_leader`). Now uses the calibration file name selected in the wizard (e.g. `testing_1`) so the correct calibration file is loaded.
  - Modified: `backend/api/teleoperation.py`, `backend/models/config.py`, `frontend/lib/services.ts`

### 2026-02-27 (2)
- **Fix: Teleoperation 400 Bad Request** — Frontend wizard state (ports, mode, cameras) was never persisted to the backend `webui_config.json`. The teleoperation endpoint loaded an empty default config with null ports, failing validation. Added `saveConfig()` to `services.ts` that syncs wizard state to `POST /api/config` before starting teleoperation.
  - Modified: `frontend/lib/services.ts`, `frontend/components/wizard/steps/teleoperate-step.tsx`

### 2026-02-27
- **Feature: Step-by-step manual calibration UI** — Replaced the subprocess-based calibration (which spawned `lerobot-calibrate` and streamed logs) with a two-phase guided calibration flow that directly controls the motor bus via WebSocket. Step 1: user places arm in middle position, clicks "Connect & Set Middle Position" to set homing offsets. Step 2: live encoder table shows min/current/max values for all 6 motors (shoulder_pan, shoulder_lift, elbow_flex, wrist_flex, wrist_roll, gripper) updating at ~10Hz as user moves joints through their range. User clicks "Done" to save calibration to file and write to motor EEPROM. Includes phase indicator, success banner with file path, and error handling via DevErrorPanel.
  - Created: `backend/services/manual_calibration.py`, `frontend/hooks/use-manual-calibration.ts`
  - Modified: `backend/api/calibration.py`, `frontend/components/wizard/steps/calibration-step.tsx`
- **Fix: Backend connection error message** — When the backend is not running, API calls now show "Cannot connect to backend server" with a hint to start the backend, instead of silently failing. Port scanning errors are also now caught and displayed.
  - Modified: `frontend/lib/services.ts`, `frontend/components/wizard/steps/ports-step.tsx`

### 2026-02-25
- **Feature: Developer-friendly error panel for wiggle failures** — When wiggling an arm fails, the UI now shows a structured error panel with: (1) the short error message in red, (2) a human-friendly hint for common SO101/Feetech errors (wrong port, USB failure, port in use), and (3) a collapsible "Show technical details" section with the full Python traceback in a monospace code block and a copy button. Backend now returns `{ message, traceback, hint }` as structured JSON instead of a plain string. Added `DevError` class in `services.ts` that carries all three fields. `DevErrorPanel` is a reusable component for future use across the app.
  - Modified: `backend/api/setup.py`, `frontend/lib/services.ts`, `frontend/components/wizard/steps/ports-step.tsx`
  - Created: `frontend/components/common/dev-error-panel.tsx`

### 2026-02-22
- **Feature: "No gripper detected" warning after port scan** — When the user clicks "Scan Ports" and no USB devices are found, the UI now shows a yellow warning banner with "No gripper detected" and troubleshooting tips (check power, re-plug USB, scan again). Previously the UI showed the same generic prompt as before scanning. Also added inline error display when the wiggle gripper action fails.
  - Modified: `frontend/components/wizard/steps/ports-step.tsx`

### 2026-02-21
- **Feature: New Calibration panel in wizard** — When user selects "+ New Calibration" for a role, an expandable panel appears below with: (1) a text input for the calibration file name (used as robot/teleoperator ID in teleoperation and recording), (2) a dashed image placeholder for a reference photo of the robot calibration position (to be added later), (3) a "Start Calibration" button that calls `POST /api/calibration/start` with the correct device type, ID, robot type, and port from wizard state. Includes real-time log viewer via WebSocket during calibration and a stop button. Only one calibration can run at a time across all roles. Step completion now requires a non-empty name when "new" is selected.
  - Modified: `frontend/components/wizard/steps/calibration-step.tsx`, `frontend/lib/wizard-types.ts`, `frontend/components/wizard/wizard-provider.tsx`, `frontend/lib/services.ts`
- **Feature: Auto-calibration backend** — Added `services/auto_calibration.py` with `AutoCalibrationService` that programmatically drives servos to find physical limits by detecting encoder stall. Algorithm: reset calibration, set homing offset, enable torque, step servo in one direction until encoder stops changing (stall detection), then reverse. Starts with gripper motor support. Added REST (`POST /api/calibration/auto/start`, `POST /api/calibration/auto/cancel`) and WebSocket (`/api/calibration/auto/ws`) endpoints for real-time progress streaming. Saves results to calibration JSON file and writes to motor EEPROM.
  - Created: `backend/services/auto_calibration.py`
  - Modified: `backend/api/calibration.py`

### 2025-02-20
- **Feature: Gripper wiggle for port identification** — Added POST `/api/setup/wiggle` endpoint that connects to a Feetech motor bus and wiggles the gripper servo (motor ID 6) using raw position values (no calibration needed). Frontend shows a hand icon button next to each port dropdown. Port assignment now supports auto-swap (changing one port swaps with the role that had it).
  - Modified: `backend/api/setup.py`, `frontend/components/wizard/steps/ports-step.tsx`, `frontend/components/wizard/wizard-provider.tsx`, `frontend/lib/services.ts`
- **Feature: Browser-native camera detection with live video feeds** — Replaced backend OpenCV camera detection with browser `navigator.mediaDevices.enumerateDevices()`. Camera labels now match actual devices (fixes system_profiler/OpenCV index mismatch). Live video feeds use `getUserMedia` with `<video>` elements. Built-in/phone cameras (FaceTime, iPhone, iPad, MacBook, IR) are automatically filtered out by label.
  - Modified: `frontend/components/wizard/steps/cameras-step.tsx`, `frontend/lib/wizard-types.ts`, `frontend/components/wizard/wizard-provider.tsx`, `frontend/lib/mock-data.ts`
- **Feature: Calibration files listing endpoint** — Added GET `/api/calibration/files` endpoint and `list_calibration_files` service method. Switched `USE_MOCK` to `false` in `services.ts` for real API integration.
  - Modified: `backend/api/calibration.py`, `backend/services/calibration_service.py`, `frontend/lib/services.ts`
- **Feature: MJPEG camera streaming endpoint** — Added GET `/api/setup/cameras/stream/{index}` with shared OpenCV capture per camera (auto-start/stop based on client connections). Not currently used by frontend (replaced by browser getUserMedia) but available for non-browser clients.
  - Modified: `backend/api/setup.py`

### 2025-02-18
- **Major: Replaced multi-page UI with wizard-style setup flow** — Inspired by Shopify's onboarding. Single-page app with 6 steps (Robot Type → Ports → Cameras → Calibration → Teleoperate → Record). One centered card per step, sidebar navigation with checkmarks, Clear Values + Restart buttons. Mock data layer with `USE_MOCK` flag for easy swap to real API.
  - Deleted: old multi-page routes (setup, calibration, teleoperation, recording), dashboard, old sidebar, mode-toggle, old types.ts
  - Created: wizard-provider (React Context + reducer), wizard-layout, wizard-sidebar, wizard-topbar, step-card, 6 step components, wizard-types, services layer, mock-data
  - Key features: step invalidation (changing early step resets later ones), port deduplication, camera name deduplication, calibration files filtered by robot type, config summary in teleoperate step, real-time logs via WebSocket

### 2025-02-17
- **Feature: Built-in camera filtering (macOS)** — Camera detection now uses `system_profiler SPCameraDataType -json` to identify built-in cameras. A "Hide built-in cameras" toggle (default: on) was added to the Setup page camera configuration section.

---

## How to Run

### Prerequisites
```bash
# Install backend dependencies
pip install fastapi uvicorn websockets python-multipart

# Install frontend dependencies
cd src/lerobot/webui/frontend
npm install
```

### Development
```bash
# Terminal 1: Start backend (port 8000)
cd /path/to/lerobot
python -m lerobot.webui.backend.main

# Terminal 2: Start frontend (port 3000)
cd src/lerobot/webui/frontend
npm run dev

# Open: http://localhost:3000
```

---

## File Inventory

```
src/lerobot/webui/
├── __init__.py
├── PROGRESS.md
├── backend/
│   ├── __init__.py
│   ├── main.py
│   ├── api/
│   │   ├── __init__.py
│   │   ├── calibration.py
│   │   ├── config.py
│   │   ├── huggingface.py
│   │   ├── recording.py
│   │   ├── setup.py
│   │   ├── system.py
│   │   ├── teleoperation.py
│   │   └── inference.py
│   ├── models/
│   │   ├── __init__.py
│   │   ├── config.py
│   │   ├── recording.py
│   │   ├── setup.py
│   │   ├── system.py
│   │   ├── teleoperation.py
│   │   └── inference.py
│   ├── services/
│   │   ├── __init__.py
│   │   ├── auto_calibration.py
│   │   ├── calibration_service.py
│   │   ├── camera_scanner.py
│   │   ├── config_manager.py
│   │   ├── hf_service.py
│   │   ├── port_scanner.py
│   │   └── process_manager.py
│   └── websockets/
│       ├── __init__.py
│       └── logs.py
└── frontend/
    ├── package.json
    ├── next.config.ts
    ├── app/
    │   ├── layout.tsx
    │   ├── page.tsx              (Wizard host)
    │   └── globals.css
    ├── components/
    │   ├── ui/                   (16 shadcn components)
    │   ├── common/
    │   │   ├── log-viewer.tsx
    │   │   └── process-status.tsx
    │   └── wizard/
    │       ├── wizard-provider.tsx
    │       ├── wizard-layout.tsx
    │       ├── wizard-sidebar.tsx
    │       ├── wizard-topbar.tsx
    │       ├── step-card.tsx
    │       └── steps/
    │           ├── robot-type-step.tsx
    │           ├── ports-step.tsx
    │           ├── cameras-step.tsx
    │           ├── calibration-step.tsx
    │           ├── teleoperate-step.tsx
    │           ├── record-step.tsx
    │           └── inference-step.tsx
    ├── hooks/
    │   └── use-websocket.ts
    └── lib/
        ├── api.ts
        ├── wizard-types.ts
        ├── services.ts
        ├── mock-data.ts
        └── utils.ts
```

