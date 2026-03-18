"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  AlertTriangle,
  CheckCircle,
  ChevronDown,
  ChevronRight,
  Cloud,
  Loader2,
  RefreshCw,
  Trash2,
} from "lucide-react";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { services } from "@/lib/services";
import { useWizard } from "../wizard-provider";
import { StepCard } from "../step-card";

// ── Default joint names for SO-101 ──────────────────────────────────────────

const SO101_SINGLE_JOINTS = [
  "shoulder_pan",
  "shoulder_lift",
  "elbow_flex",
  "wrist_flex",
  "wrist_roll",
  "gripper",
];

const SO101_BIMANUAL_JOINTS = [
  "left_shoulder_pan",
  "left_shoulder_lift",
  "left_elbow_flex",
  "left_wrist_flex",
  "left_wrist_roll",
  "left_gripper",
  "right_shoulder_pan",
  "right_shoulder_lift",
  "right_elbow_flex",
  "right_wrist_flex",
  "right_wrist_roll",
  "right_gripper",
];

const GPU_TYPES = [
  { value: "NVIDIA_TESLA_V100", label: "V100" },
  { value: "NVIDIA_A100", label: "A100" },
  { value: "NVIDIA_H100", label: "H100" },
];

type JobStatus = "pending" | "queued" | "running" | "completed" | "failed" | string;

function statusBadgeVariant(status: JobStatus): "default" | "secondary" | "destructive" | "outline" {
  if (status === "completed") return "default";
  if (status === "failed") return "destructive";
  if (status === "running") return "secondary";
  return "outline";
}

// ── Simple inline progress bar ────────────────────────────────────────────────

function ProgressBar({ value }: { value: number }) {
  return (
    <div className="h-2 w-full overflow-hidden rounded-full bg-muted">
      <div
        className="h-full bg-primary transition-all duration-300"
        style={{ width: `${Math.round(value * 100)}%` }}
      />
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

export function TrainStep() {
  const { state, dispatch } = useWizard();
  const nc = state.neuracoreConfig;

  // ── derived from wizard state
  const defaultJointNames =
    state.robotMode === "bimanual" ? SO101_BIMANUAL_JOINTS : SO101_SINGLE_JOINTS;
  const configuredCameraNames = state.cameraSelections
    .filter((c) => c.included && c.name)
    .map((c) => c.name);

  // Default robot name: follower calibration ID or bimanual base
  const defaultRobotName =
    state.robotMode === "bimanual"
      ? (state.calibrationSelections.left_follower ?? "").replace(/_left\.json$/, "").replace(/\.json$/, "") || "so101_robot"
      : (state.calibrationSelections.follower ?? "").replace(/\.json$/, "") || "so101_robot";

  // ── local UI state ─────────────────────────────────────────────────────────
  const [authTab, setAuthTab] = useState<"credentials" | "apikey">("credentials");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [authLoading, setAuthLoading] = useState(false);
  const [authError, setAuthError] = useState<string | null>(null);
  const [authenticated, setAuthenticated] = useState(false);

  // Organisation selection
  const [orgs, setOrgs] = useState<Array<{ id: string; name: string }>>([]);
  const [selectedOrgId, setSelectedOrgId] = useState(nc.orgId || "");
  const [orgLoading, setOrgLoading] = useState(false);
  const [orgError, setOrgError] = useState<string | null>(null);
  const orgSelected = !!selectedOrgId;

  const [robotName, setRobotName] = useState(nc.robotName || defaultRobotName);
  const [robotConnecting, setRobotConnecting] = useState(false);
  const [robotId, setRobotId] = useState<string | null>(null);
  const [robotError, setRobotError] = useState<string | null>(null);

  // Import state
  const [hfRepoId, setHfRepoId] = useState(
    nc.importedDatasetName ? "" : (state.recordingConfig.repoId || "")
  );
  const [neuracoreDatasetName, setNeuracoreDatasetName] = useState(
    nc.importedDatasetName ||
      (state.recordingConfig.repoId || "").replace(/\//g, "_").replace(/-/g, "_") ||
      ""
  );
  const [jointNamesText, setJointNamesText] = useState(defaultJointNames.join("\n"));
  const [importFrequency, setImportFrequency] = useState(
    state.recordingConfig.cameraFps || 30
  );
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [importing, setImporting] = useState(false);
  const [importId, setImportId] = useState<string | null>(nc.importId);
  const [importStatus, setImportStatus] = useState<{
    status: string;
    progress: number;
    message: string;
    error: string | null;
  } | null>(null);

  // Training config
  const [algorithms, setAlgorithms] = useState<Array<{ id: string; name: string; description?: string }>>([]);
  const [algorithmName, setAlgorithmName] = useState("CNNMLP");
  const [batchSize, setBatchSize] = useState(32);
  const [epochs, setEpochs] = useState(100);
  const [predictionHorizon, setPredictionHorizon] = useState(16);
  const [gpuType, setGpuType] = useState("NVIDIA_TESLA_V100");
  const [numGpus, setNumGpus] = useState(1);
  const [trainingFrequency, setTrainingFrequency] = useState(30);
  const [trainingLoading, setTrainingLoading] = useState(false);
  const [trainingError, setTrainingError] = useState<string | null>(null);

  // Jobs
  const [jobs, setJobs] = useState<Array<{ id: string; name: string; status: string; created_at?: string }>>([]);
  const [jobsLoading, setJobsLoading] = useState(false);
  const [expandedJobId, setExpandedJobId] = useState<string | null>(null);
  const [jobLogs, setJobLogs] = useState<Record<string, string>>({});

  const importPollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const jobsPollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // ── Sync NeuracoreConfig back into wizard state ───────────────────────────

  const persistConfig = useCallback(
    (patch: Partial<typeof nc>) => {
      dispatch({ type: "SET_NEURACORE_CONFIG", config: patch });
    },
    [dispatch]
  );

  // ── Auto-detect existing auth on mount ───────────────────────────────────

  useEffect(() => {
    services.neuracoreStatus().then(async (res) => {
      if (res.authenticated) {
        setAuthenticated(true);
        await fetchOrgs();
        // Restore persisted org selection if present
        if (nc.orgId) setSelectedOrgId(nc.orgId);
        fetchJobs();
        fetchAlgorithms();
      }
    }).catch(() => {});
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ── Poll import status ────────────────────────────────────────────────────

  useEffect(() => {
    if (!importId) return;
    if (importPollRef.current) clearInterval(importPollRef.current);

    const poll = async () => {
      try {
        const res = await services.neuracoreImportStatus(importId);
        setImportStatus({ status: res.status, progress: res.progress, message: res.message, error: res.error ?? null });
        if (res.status === "completed" || res.status === "failed" || res.status === "not_found") {
          clearInterval(importPollRef.current!);
          importPollRef.current = null;
          setImporting(false);
          if (res.status === "completed") {
            persistConfig({ importedDatasetName: neuracoreDatasetName, importId });
          }
        }
      } catch {
        clearInterval(importPollRef.current!);
        importPollRef.current = null;
        setImporting(false);
      }
    };

    poll();
    importPollRef.current = setInterval(poll, 3000);
    return () => {
      if (importPollRef.current) clearInterval(importPollRef.current);
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [importId]);

  // ── Poll jobs list every 10 s when any job is running ────────────────────

  useEffect(() => {
    if (!authenticated) return;
    const hasRunning = jobs.some((j) => j.status === "running" || j.status === "pending" || j.status === "queued");
    if (!hasRunning) return;

    if (jobsPollRef.current) clearInterval(jobsPollRef.current);
    jobsPollRef.current = setInterval(fetchJobs, 10_000);
    return () => {
      if (jobsPollRef.current) clearInterval(jobsPollRef.current);
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobs, authenticated]);

  // ── Cleanup ───────────────────────────────────────────────────────────────

  useEffect(() => {
    return () => {
      if (importPollRef.current) clearInterval(importPollRef.current);
      if (jobsPollRef.current) clearInterval(jobsPollRef.current);
    };
  }, []);

  // ── Actions ───────────────────────────────────────────────────────────────

  const fetchOrgs = async () => {
    try {
      const list = await services.neuracoreListOrgs();
      setOrgs(list);
      // If only one org, auto-select it
      if (list.length === 1 && !selectedOrgId) {
        await handleSelectOrg(list[0].id, list);
      }
    } catch {
      // non-fatal; user can retry
    }
  };

  const handleSelectOrg = async (orgId: string, orgList?: Array<{ id: string; name: string }>) => {
    setOrgLoading(true);
    setOrgError(null);
    try {
      await services.neuracoreSelectOrg(orgId);
      setSelectedOrgId(orgId);
      persistConfig({ orgId });
      // Reset downstream state when org changes
      setRobotId(null);
      fetchJobs();
      fetchAlgorithms();
    } catch (e: unknown) {
      setOrgError(e instanceof Error ? e.message : String(e));
    } finally {
      setOrgLoading(false);
    }
  };

  const handleLoginCredentials = async () => {
    setAuthLoading(true);
    setAuthError(null);
    try {
      const res = await services.neuracoreLogin(email, password);
      if (res.authenticated) {
        setAuthenticated(true);
        persistConfig({ apiKey: "***" });
        await fetchOrgs();
        fetchJobs();
        fetchAlgorithms();
      } else {
        setAuthError(res.message);
      }
    } catch (e: unknown) {
      setAuthError(e instanceof Error ? e.message : String(e));
    } finally {
      setAuthLoading(false);
    }
  };

  const handleLoginWithKey = async () => {
    if (!nc.apiKey && !email) return;
    const keyToUse = authTab === "apikey" ? email : nc.apiKey;
    setAuthLoading(true);
    setAuthError(null);
    try {
      const res = await services.neuracoreLoginWithKey(keyToUse);
      if (res.authenticated) {
        setAuthenticated(true);
        persistConfig({ apiKey: keyToUse });
        await fetchOrgs();
        fetchJobs();
        fetchAlgorithms();
      } else {
        setAuthError(res.message);
      }
    } catch (e: unknown) {
      setAuthError(e instanceof Error ? e.message : String(e));
    } finally {
      setAuthLoading(false);
    }
  };

  const handleConnectRobot = async () => {
    setRobotConnecting(true);
    setRobotError(null);
    try {
      const res = await services.neuracoreConnectRobot(robotName);
      setRobotId(res.robot_id);
      persistConfig({ robotName });
    } catch (e: unknown) {
      setRobotError(e instanceof Error ? e.message : String(e));
    } finally {
      setRobotConnecting(false);
    }
  };

  const handleImport = async () => {
    setImporting(true);
    setImportStatus(null);
    const jointNames = jointNamesText
      .split("\n")
      .map((s) => s.trim())
      .filter(Boolean);
    try {
      const res = await services.neuracoreImportDataset({
        hfRepoId,
        neuracoreDatasetName,
        robotName,
        jointNames,
        cameraNames: configuredCameraNames,
        frequency: importFrequency,
      });
      setImportId(res.import_id);
      persistConfig({ importId: res.import_id });
    } catch (e: unknown) {
      setImporting(false);
      setImportStatus({
        status: "failed",
        progress: 0,
        message: "Failed to start import",
        error: e instanceof Error ? e.message : String(e),
      });
    }
  };

  const fetchAlgorithms = async () => {
    try {
      const res = await services.neuracoreGetAlgorithms();
      setAlgorithms(res);
      if (res.length > 0 && !algorithmName) setAlgorithmName(res[0].name);
    } catch {
      // keep empty, user can type manually
    }
  };

  const handleStartTraining = async () => {
    setTrainingLoading(true);
    setTrainingError(null);
    const jointNames = jointNamesText
      .split("\n")
      .map((s) => s.trim())
      .filter(Boolean);
    try {
      const job = await services.neuracoreStartTraining({
        jobName: `${neuracoreDatasetName || "so101"}_training`,
        datasetName: neuracoreDatasetName,
        algorithmName,
        algorithmConfig: {
          batch_size: batchSize,
          epochs,
          output_prediction_horizon: predictionHorizon,
        },
        gpuType,
        numGpus,
        frequency: trainingFrequency,
        robotName,
        inputJointNames: jointNames,
        inputCameraNames: configuredCameraNames,
        outputJointNames: jointNames,
      });
      persistConfig({ jobId: job.id });
      await fetchJobs();
    } catch (e: unknown) {
      setTrainingError(e instanceof Error ? e.message : String(e));
    } finally {
      setTrainingLoading(false);
    }
  };

  const fetchJobs = async () => {
    setJobsLoading(true);
    try {
      const res = await services.neuracoreGetJobs();
      setJobs(res);
    } catch {
      // ignore
    } finally {
      setJobsLoading(false);
    }
  };

  const handleExpandJob = async (jobId: string) => {
    if (expandedJobId === jobId) {
      setExpandedJobId(null);
      return;
    }
    setExpandedJobId(jobId);
    try {
      const res = await services.neuracoreGetJobLogs(jobId, 200);
      const obj = res as Record<string, unknown>;
      // API returns { logs: [{timestamp, severity, message}, ...], ... } — logs are newest-first
      const rawEntries = (obj.logs ?? obj.entries ?? obj.results ?? res) as unknown[];
      const entries = Array.isArray(rawEntries) ? [...rawEntries].reverse() : [];
      let text = "";
      if (entries.length > 0) {
        text = entries.map((e) => {
          if (typeof e === "string") return e;
          const entry = e as Record<string, unknown>;
          const ts = typeof entry.timestamp === "number"
            ? new Date(entry.timestamp * 1000).toISOString().replace("T", " ").slice(0, 19)
            : "";
          const sev = typeof entry.severity === "string" ? entry.severity : "";
          const msg = String(entry.message ?? entry.text_payload ?? entry.text ?? entry.log ?? JSON.stringify(e));
          return ts ? `[${ts}] ${sev}: ${msg}` : `${sev}: ${msg}`.trimStart();
        }).join("\n");
      } else {
        text = JSON.stringify(res, null, 2);
      }
      setJobLogs((prev) => ({ ...prev, [jobId]: text || "(no logs available)" }));
    } catch {
      setJobLogs((prev) => ({ ...prev, [jobId]: "Could not load logs." }));
    }
  };

  const handleDeleteJob = async (jobId: string) => {
    try {
      await services.neuracoreDeleteJob(jobId);
      setJobs((prev) => prev.filter((j) => j.id !== jobId));
      if (expandedJobId === jobId) setExpandedJobId(null);
    } catch {
      // ignore
    }
  };

  // ── Computed state ─────────────────────────────────────────────────────────
  const importDone = importStatus?.status === "completed" || !!nc.importedDatasetName;
  const importRunning = importing || (importStatus?.status === "running");

  // ── Render ─────────────────────────────────────────────────────────────────

  return (
    <StepCard
      title="Train"
      description="Train a policy on Neuracore cloud infrastructure using your recorded dataset."
    >
      {/* ── Provider selector ─────────────────────────────────────────── */}
      <div className="flex gap-3 mb-6">
        <button
          onClick={() => persistConfig({ provider: "neuracore" })}
          className={`flex-1 rounded-xl border-2 px-4 py-3 text-left transition-all ${
            nc.provider === "neuracore"
              ? "border-primary bg-primary/5"
              : "border-muted hover:border-muted-foreground/30"
          }`}
        >
          <div className="flex items-center gap-2 mb-1">
            <Cloud className="h-4 w-4" />
            <span className="font-medium text-sm">Neuracore</span>
          </div>
          <p className="text-xs text-muted-foreground">Cloud training with diffusion, ACT, and more</p>
        </button>
        <button
          disabled
          className="flex-1 rounded-xl border-2 border-muted px-4 py-3 text-left opacity-50 cursor-not-allowed"
        >
          <div className="flex items-center gap-2 mb-1">
            <Cloud className="h-4 w-4" />
            <span className="font-medium text-sm">Qualia</span>
            <Badge variant="outline" className="text-xs">Coming Soon</Badge>
          </div>
          <p className="text-xs text-muted-foreground">Qualia cloud training</p>
        </button>
      </div>

      {nc.provider !== "neuracore" && (
        <Alert>
          <AlertDescription>Qualia training support is coming soon.</AlertDescription>
        </Alert>
      )}

      {nc.provider === "neuracore" && (
        <div className="space-y-5">
          {/* ── 1. Authentication ───────────────────────────────────────── */}
          <section className="rounded-xl border bg-card p-5 space-y-4">
            <div className="flex items-center justify-between">
              <h3 className="font-semibold text-sm">1. Authentication</h3>
              {authenticated && (
                <Badge variant="default" className="gap-1">
                  <CheckCircle className="h-3 w-3" /> Authenticated
                </Badge>
              )}
            </div>

            {!authenticated && (
              <Tabs value={authTab} onValueChange={(v) => setAuthTab(v as "credentials" | "apikey")}>
                <TabsList className="w-full">
                  <TabsTrigger value="credentials" className="flex-1">Email &amp; Password</TabsTrigger>
                  <TabsTrigger value="apikey" className="flex-1">API Key</TabsTrigger>
                </TabsList>

                <TabsContent value="credentials" className="space-y-3 pt-3">
                  <div className="space-y-1">
                    <Label>Email</Label>
                    <Input
                      type="email"
                      placeholder="you@example.com"
                      value={email}
                      onChange={(e) => setEmail(e.target.value)}
                    />
                  </div>
                  <div className="space-y-1">
                    <Label>Password</Label>
                    <Input
                      type="password"
                      placeholder="••••••••"
                      value={password}
                      onChange={(e) => setPassword(e.target.value)}
                      onKeyDown={(e) => e.key === "Enter" && handleLoginCredentials()}
                    />
                  </div>
                  {authError && (
                    <Alert variant="destructive">
                      <AlertTriangle className="h-4 w-4" />
                      <AlertDescription>{authError}</AlertDescription>
                    </Alert>
                  )}
                  <Button
                    onClick={handleLoginCredentials}
                    disabled={authLoading || !email || !password}
                    className="w-full"
                  >
                    {authLoading ? (
                      <><Loader2 className="mr-2 h-4 w-4 animate-spin" /> Generating API Key…</>
                    ) : (
                      "Generate API Key & Connect"
                    )}
                  </Button>
                </TabsContent>

                <TabsContent value="apikey" className="space-y-3 pt-3">
                  <div className="space-y-1">
                    <Label>Neuracore API Key</Label>
                    <Input
                      type="password"
                      placeholder="nc_…"
                      value={email}
                      onChange={(e) => setEmail(e.target.value)}
                    />
                    <p className="text-xs text-muted-foreground">
                      Find your key at{" "}
                      <span className="text-foreground">app.neuracore.com → Settings → API Keys</span>
                    </p>
                  </div>
                  {authError && (
                    <Alert variant="destructive">
                      <AlertTriangle className="h-4 w-4" />
                      <AlertDescription>{authError}</AlertDescription>
                    </Alert>
                  )}
                  <Button
                    onClick={handleLoginWithKey}
                    disabled={authLoading || !email}
                    className="w-full"
                  >
                    {authLoading ? (
                      <><Loader2 className="mr-2 h-4 w-4 animate-spin" /> Connecting…</>
                    ) : (
                      "Connect"
                    )}
                  </Button>
                </TabsContent>
              </Tabs>
            )}
          </section>

          {/* ── 2. Organisation ─────────────────────────────────────────── */}
          {authenticated && (
            <section className="rounded-xl border bg-card p-5 space-y-4">
              <div className="flex items-center justify-between">
                <h3 className="font-semibold text-sm">2. Organisation</h3>
                {orgSelected && (
                  <Badge variant="default" className="gap-1">
                    <CheckCircle className="h-3 w-3" />
                    {orgs.find((o) => o.id === selectedOrgId)?.name ?? selectedOrgId}
                  </Badge>
                )}
              </div>

              {orgs.length === 0 ? (
                <p className="text-sm text-muted-foreground">Loading organisations…</p>
              ) : (
                <div className="space-y-2">
                  <Label>Select Organisation</Label>
                  <Select
                    value={selectedOrgId}
                    onValueChange={(v) => handleSelectOrg(v)}
                    disabled={orgLoading}
                  >
                    <SelectTrigger>
                      <SelectValue placeholder="Choose an organisation…" />
                    </SelectTrigger>
                    <SelectContent>
                      {orgs.map((o) => (
                        <SelectItem key={o.id} value={o.id}>
                          {o.name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  {orgError && (
                    <Alert variant="destructive">
                      <AlertTriangle className="h-4 w-4" />
                      <AlertDescription>{orgError}</AlertDescription>
                    </Alert>
                  )}
                </div>
              )}
            </section>
          )}

          {/* ── 3. Robot ─────────────────────────────────────────────────── */}
          {authenticated && orgSelected && (
            <section className="rounded-xl border bg-card p-5 space-y-4">
              <div className="flex items-center justify-between">
                <h3 className="font-semibold text-sm">3. Robot</h3>
                {robotId && (
                  <Badge variant="default" className="gap-1">
                    <CheckCircle className="h-3 w-3" /> Connected
                  </Badge>
                )}
              </div>
              <div className="flex gap-2">
                <div className="flex-1 space-y-1">
                  <Label>Robot Name</Label>
                  <Input
                    value={robotName}
                    onChange={(e) => setRobotName(e.target.value)}
                    placeholder="my_so101_robot"
                  />
                </div>
                <div className="flex items-end">
                  <Button
                    onClick={handleConnectRobot}
                    disabled={robotConnecting || !robotName}
                    variant={robotId ? "outline" : "default"}
                  >
                    {robotConnecting ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : robotId ? (
                      "Reconnect"
                    ) : (
                      "Connect"
                    )}
                  </Button>
                </div>
              </div>
              {robotId && (
                <p className="text-xs text-muted-foreground">Robot ID: {robotId}</p>
              )}
              {robotError && (
                <Alert variant="destructive">
                  <AlertTriangle className="h-4 w-4" />
                  <AlertDescription>{robotError}</AlertDescription>
                </Alert>
              )}
            </section>
          )}

          {/* ── 4. Dataset Import ─────────────────────────────────────────── */}
          {authenticated && orgSelected && robotId && (
            <section className="rounded-xl border bg-card p-5 space-y-4">
              <div className="flex items-center justify-between">
                <h3 className="font-semibold text-sm">4. Dataset Import</h3>
                {importDone && (
                  <Badge variant="default" className="gap-1">
                    <CheckCircle className="h-3 w-3" /> Imported
                  </Badge>
                )}
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1">
                  <Label>HuggingFace Repo ID</Label>
                  <Input
                    value={hfRepoId}
                    onChange={(e) => setHfRepoId(e.target.value)}
                    placeholder="username/my-dataset"
                  />
                </div>
                <div className="space-y-1">
                  <Label>Neuracore Dataset Name</Label>
                  <Input
                    value={neuracoreDatasetName}
                    onChange={(e) => setNeuracoreDatasetName(e.target.value)}
                    placeholder="my_so101_dataset"
                  />
                </div>
              </div>

              {/* Advanced options */}
              <button
                className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
                onClick={() => setShowAdvanced((v) => !v)}
              >
                {showAdvanced ? (
                  <ChevronDown className="h-3 w-3" />
                ) : (
                  <ChevronRight className="h-3 w-3" />
                )}
                Advanced: Joint &amp; Camera Mapping
              </button>

              {showAdvanced && (
                <div className="space-y-3 rounded-lg bg-muted/40 p-4">
                  <div className="space-y-1">
                    <Label>
                      Joint Names{" "}
                      <span className="text-xs text-muted-foreground">(one per line, positional)</span>
                    </Label>
                    <Textarea
                      value={jointNamesText}
                      onChange={(e) => setJointNamesText(e.target.value)}
                      rows={Math.max(4, jointNamesText.split("\n").length)}
                      className="font-mono text-xs"
                    />
                  </div>

                  {configuredCameraNames.length > 0 && (
                    <div className="space-y-1">
                      <Label>Camera Names</Label>
                      <div className="flex flex-wrap gap-1">
                        {configuredCameraNames.map((n) => (
                          <Badge key={n} variant="secondary">{n}</Badge>
                        ))}
                      </div>
                      <p className="text-xs text-muted-foreground">
                        Derived from cameras configured in step 2.
                      </p>
                    </div>
                  )}

                  <div className="space-y-1 w-32">
                    <Label>Frequency (Hz)</Label>
                    <Input
                      type="number"
                      min={1}
                      max={200}
                      value={importFrequency}
                      onChange={(e) => setImportFrequency(Number(e.target.value))}
                    />
                  </div>
                </div>
              )}

              {/* Import status */}
              {importStatus && (
                <div className="space-y-2">
                  <div className="flex items-center justify-between text-xs">
                    <span className="text-muted-foreground">{importStatus.message}</span>
                    <Badge
                      variant={
                        importStatus.status === "completed"
                          ? "default"
                          : importStatus.status === "failed"
                          ? "destructive"
                          : "secondary"
                      }
                    >
                      {importStatus.status}
                    </Badge>
                  </div>
                  {importStatus.status !== "failed" && (
                    <ProgressBar value={importStatus.progress} />
                  )}
                  {importStatus.error && (
                    <Alert variant="destructive">
                      <AlertTriangle className="h-4 w-4" />
                      <AlertDescription>{importStatus.error}</AlertDescription>
                    </Alert>
                  )}
                </div>
              )}

              {!importDone && (
                <Button
                  onClick={handleImport}
                  disabled={importRunning || !hfRepoId || !neuracoreDatasetName}
                  className="w-full"
                >
                  {importRunning ? (
                    <><Loader2 className="mr-2 h-4 w-4 animate-spin" /> Importing…</>
                  ) : (
                    "Import Dataset to Neuracore"
                  )}
                </Button>
              )}

              {importDone && (
                <Button
                  variant="outline"
                  onClick={handleImport}
                  disabled={importRunning}
                  className="w-full"
                >
                  Re-import Dataset
                </Button>
              )}
            </section>
          )}

          {/* ── 5. Training Configuration ─────────────────────────────────── */}
          {authenticated && orgSelected && robotId && importDone && (
            <section className="rounded-xl border bg-card p-5 space-y-4">
              <h3 className="font-semibold text-sm">5. Training Configuration</h3>

              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1">
                  <Label>Dataset</Label>
                  <Input value={neuracoreDatasetName} readOnly className="bg-muted" />
                </div>
                <div className="space-y-1">
                  <Label>Algorithm</Label>
                  {algorithms.length > 0 ? (
                    <Select value={algorithmName} onValueChange={setAlgorithmName}>
                      <SelectTrigger>
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {algorithms.map((a) => (
                          <SelectItem key={a.id} value={a.name}>
                            {a.name}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  ) : (
                    <Input
                      value={algorithmName}
                      onChange={(e) => setAlgorithmName(e.target.value)}
                      placeholder="CNNMLP"
                    />
                  )}
                </div>
              </div>

              <div className="grid grid-cols-3 gap-3">
                <div className="space-y-1">
                  <Label>Batch Size</Label>
                  <Input
                    type="number"
                    min={1}
                    value={batchSize}
                    onChange={(e) => setBatchSize(Number(e.target.value))}
                  />
                </div>
                <div className="space-y-1">
                  <Label>Epochs</Label>
                  <Input
                    type="number"
                    min={1}
                    value={epochs}
                    onChange={(e) => setEpochs(Number(e.target.value))}
                  />
                </div>
                <div className="space-y-1">
                  <Label>Prediction Horizon</Label>
                  <Input
                    type="number"
                    min={1}
                    value={predictionHorizon}
                    onChange={(e) => setPredictionHorizon(Number(e.target.value))}
                  />
                </div>
              </div>

              <div className="grid grid-cols-3 gap-3">
                <div className="space-y-1 col-span-2">
                  <Label>GPU Type</Label>
                  <Select value={gpuType} onValueChange={setGpuType}>
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {GPU_TYPES.map((g) => (
                        <SelectItem key={g.value} value={g.value}>
                          {g.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-1">
                  <Label>Num GPUs</Label>
                  <Select value={String(numGpus)} onValueChange={(v) => setNumGpus(Number(v))}>
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {[1, 2, 4].map((n) => (
                        <SelectItem key={n} value={String(n)}>
                          {n}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              </div>

              <div className="space-y-1 w-32">
                <Label>Frequency (Hz)</Label>
                <Input
                  type="number"
                  min={1}
                  max={200}
                  value={trainingFrequency}
                  onChange={(e) => setTrainingFrequency(Number(e.target.value))}
                />
              </div>

              {trainingError && (
                <Alert variant="destructive">
                  <AlertTriangle className="h-4 w-4" />
                  <AlertDescription>{trainingError}</AlertDescription>
                </Alert>
              )}

              <Button
                onClick={handleStartTraining}
                disabled={trainingLoading || !algorithmName}
                className="w-full"
              >
                {trainingLoading ? (
                  <><Loader2 className="mr-2 h-4 w-4 animate-spin" /> Submitting Job…</>
                ) : (
                  "Start Training"
                )}
              </Button>
            </section>
          )}

          {/* ── 5. Training Jobs ─────────────────────────────────────────── */}
          {authenticated && (
            <section className="rounded-xl border bg-card p-5 space-y-4">
              <div className="flex items-center justify-between">
                <h3 className="font-semibold text-sm">Training Jobs</h3>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={fetchJobs}
                  disabled={jobsLoading}
                >
                  <RefreshCw className={`h-3.5 w-3.5 ${jobsLoading ? "animate-spin" : ""}`} />
                </Button>
              </div>

              {jobs.length === 0 ? (
                <p className="text-sm text-muted-foreground text-center py-4">
                  No training jobs yet. Submit your first job above.
                </p>
              ) : (
                <div className="space-y-2">
                  {jobs.map((job) => (
                    <div
                      key={job.id}
                      className="rounded-lg border bg-muted/30 overflow-hidden"
                    >
                      <div className="flex items-center justify-between px-4 py-3">
                        <div className="flex items-center gap-3">
                          <button
                            className="text-muted-foreground hover:text-foreground"
                            onClick={() => handleExpandJob(job.id)}
                          >
                            {expandedJobId === job.id ? (
                              <ChevronDown className="h-4 w-4" />
                            ) : (
                              <ChevronRight className="h-4 w-4" />
                            )}
                          </button>
                          <span className="text-sm font-medium">{job.name}</span>
                        </div>
                        <div className="flex items-center gap-2">
                          <Badge variant={statusBadgeVariant(job.status)}>
                            {job.status}
                          </Badge>
                          {job.created_at && (
                            <span className="text-xs text-muted-foreground">
                              {new Date(job.created_at).toLocaleDateString()}
                            </span>
                          )}
                          <button
                            className="text-muted-foreground hover:text-destructive transition-colors"
                            onClick={() => handleDeleteJob(job.id)}
                            title="Delete job"
                          >
                            <Trash2 className="h-3.5 w-3.5" />
                          </button>
                        </div>
                      </div>

                      {expandedJobId === job.id && (
                        <>
                          <Separator />
                          <div className="bg-black/90 text-green-400 font-mono text-xs p-4 max-h-60 overflow-y-auto whitespace-pre-wrap">
                            {jobLogs[job.id] ?? "Loading logs…"}
                          </div>
                        </>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </section>
          )}
        </div>
      )}
    </StepCard>
  );
}
