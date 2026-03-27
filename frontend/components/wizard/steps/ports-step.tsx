"use client";

import { useState } from "react";
import { Loader2, Search, Hand, AlertTriangle, Shield, ShieldCheck } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { SINGLE_PORT_ROLES, BIMANUAL_PORT_ROLES } from "@/lib/wizard-types";
import { services } from "@/lib/services";
import { useWizard } from "../wizard-provider";
import { StepCard } from "../step-card";
import { DevErrorPanel } from "@/components/common/dev-error-panel";

const ROLE_LABELS: Record<string, string> = {
  follower: "Follower Arm",
  leader: "Leader Arm",
  left_follower: "Left Follower",
  right_follower: "Right Follower",
  left_leader: "Left Leader",
  right_leader: "Right Leader",
};

export function PortsStep() {
  const { state, dispatch } = useWizard();
  const [scanning, setScanning] = useState(false);
  const [hasScanned, setHasScanned] = useState(false);
  const [wigglingPort, setWigglingPort] = useState<string | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [fixingPermissions, setFixingPermissions] = useState(false);
  const [permissionMessage, setPermissionMessage] = useState<string | null>(null);

  const roles =
    state.robotMode === "bimanual" ? BIMANUAL_PORT_ROLES : SINGLE_PORT_ROLES;

  const allAssigned = roles.every(
    (role) => state.portAssignments[role] && state.portAssignments[role] !== ""
  );

  async function scanPorts() {
    setScanning(true);
    setError(null);
    try {
      const ports = await services.listPorts();
      dispatch({ type: "SET_DETECTED_PORTS", ports });
    } catch (err) {
      setError(err instanceof Error ? err : new Error("Failed to scan ports"));
    } finally {
      setScanning(false);
      setHasScanned(true);
    }
  }

  async function wiggle(port: string) {
    setWigglingPort(port);
    setError(null);
    try {
      await services.wiggleGripper(port);
    } catch (err) {
      setError(err instanceof Error ? err : new Error("Failed to wiggle gripper"));
    } finally {
      setWigglingPort(null);
    }
  }

  const hasInaccessiblePorts = state.detectedPorts.some((p) => p.accessible === false);

  async function fixPermissions() {
    setFixingPermissions(true);
    setError(null);
    setPermissionMessage(null);
    try {
      const result = await services.fixPortPermissionsPermanent();
      setPermissionMessage(result.message);
      // Re-scan to update accessible status
      const ports = await services.listPorts();
      dispatch({ type: "SET_DETECTED_PORTS", ports });
    } catch (err) {
      setError(err instanceof Error ? err : new Error("Failed to fix permissions"));
    } finally {
      setFixingPermissions(false);
    }
  }

  async function fixSinglePort(port: string) {
    setFixingPermissions(true);
    setError(null);
    setPermissionMessage(null);
    try {
      const result = await services.fixPortPermission(port);
      setPermissionMessage(result.message);
      // Re-scan to update accessible status
      const ports = await services.listPorts();
      dispatch({ type: "SET_DETECTED_PORTS", ports });
    } catch (err) {
      setError(err instanceof Error ? err : new Error("Failed to fix permissions"));
    } finally {
      setFixingPermissions(false);
    }
  }

  return (
    <StepCard
      title="Assign Device Ports"
      description={`Detect USB devices and assign them to each ${state.robotMode === "bimanual" ? "arm" : "device"}.`}
      nextDisabled={!allAssigned}
    >
      <div className="space-y-6">
        <Button
          variant="outline"
          onClick={scanPorts}
          disabled={scanning}
          className="w-full"
        >
          {scanning ? (
            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
          ) : (
            <Search className="mr-2 h-4 w-4" />
          )}
          {scanning ? "Scanning..." : "Scan Ports"}
        </Button>

        {state.detectedPorts.length > 0 && (
          <div className="space-y-4">
            <p className="text-sm text-muted-foreground">
              {state.detectedPorts.length} device(s) found. Assign each to a
              role. Use &quot;Wiggle&quot; to identify which arm is connected.
            </p>

            {hasInaccessiblePorts && (
              <div className="rounded-lg border border-orange-200 bg-orange-50 p-4 dark:border-orange-900 dark:bg-orange-950">
                <div className="flex items-center gap-2 text-orange-800 dark:text-orange-200">
                  <Shield className="h-5 w-5 shrink-0" />
                  <p className="font-medium">Port permissions required</p>
                </div>
                <p className="mt-1 pl-7 text-sm text-orange-700 dark:text-orange-300">
                  Some ports need elevated permissions to access. Click below to fix — you may be prompted for your password.
                </p>
                <div className="mt-3 pl-7">
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={fixPermissions}
                    disabled={fixingPermissions}
                    className="border-orange-300 dark:border-orange-700"
                  >
                    {fixingPermissions ? (
                      <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    ) : (
                      <ShieldCheck className="mr-2 h-4 w-4" />
                    )}
                    {fixingPermissions ? "Fixing..." : "Fix Permissions"}
                  </Button>
                </div>
              </div>
            )}

            {permissionMessage && (
              <div className="rounded-lg border border-green-200 bg-green-50 p-3 dark:border-green-900 dark:bg-green-950">
                <div className="flex items-center gap-2 text-green-800 dark:text-green-200">
                  <ShieldCheck className="h-4 w-4 shrink-0" />
                  <p className="text-sm">{permissionMessage}</p>
                </div>
              </div>
            )}

            {roles.map((role) => {
              const assignedPort = state.portAssignments[role];
              const assignedPortInfo = state.detectedPorts.find((p) => p.port === assignedPort);
              const isInaccessible = assignedPortInfo?.accessible === false;
              return (
                <div key={role} className="space-y-1.5">
                  <Label>{ROLE_LABELS[role]}</Label>
                  <div className="flex gap-2">
                    <Select
                      value={assignedPort || ""}
                      onValueChange={(port) =>
                        dispatch({
                          type: "SET_PORT_ASSIGNMENT",
                          role,
                          port,
                        })
                      }
                    >
                      <SelectTrigger className="flex-1">
                        <SelectValue placeholder="Select a port..." />
                      </SelectTrigger>
                      <SelectContent>
                        {state.detectedPorts.map((p) => (
                            <SelectItem key={p.port} value={p.port}>
                              <span className="font-mono text-xs">
                                {p.port.split(".").pop()}
                              </span>
                              {p.description && (
                                <span className="ml-2 text-muted-foreground">
                                  — {p.description}
                                </span>
                              )}
                              {p.accessible === false && (
                                <span className="ml-2 text-orange-500">
                                  (no permission)
                                </span>
                              )}
                            </SelectItem>
                          ))}
                      </SelectContent>
                    </Select>
                    {isInaccessible ? (
                      <Button
                        variant="outline"
                        size="icon"
                        disabled={fixingPermissions}
                        onClick={() => assignedPort && fixSinglePort(assignedPort)}
                        title="Fix permissions for this port"
                        className="border-orange-300 dark:border-orange-700"
                      >
                        {fixingPermissions ? (
                          <Loader2 className="h-4 w-4 animate-spin" />
                        ) : (
                          <Shield className="h-4 w-4 text-orange-500" />
                        )}
                      </Button>
                    ) : (
                      <Button
                        variant="outline"
                        size="icon"
                        disabled={!assignedPort || wigglingPort !== null}
                        onClick={() => assignedPort && wiggle(assignedPort)}
                        title="Wiggle gripper to identify this arm"
                      >
                        {wigglingPort === assignedPort ? (
                          <Loader2 className="h-4 w-4 animate-spin" />
                        ) : (
                          <Hand className="h-4 w-4" />
                        )}
                      </Button>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        )}

        {state.detectedPorts.length === 0 && !scanning && !hasScanned && (
          <p className="text-center text-sm text-muted-foreground">
            Click &quot;Scan Ports&quot; to detect connected USB devices.
          </p>
        )}

        {state.detectedPorts.length === 0 && !scanning && hasScanned && (
          <div className="rounded-lg border border-yellow-200 bg-yellow-50 p-4 dark:border-yellow-900 dark:bg-yellow-950">
            <div className="flex items-center gap-2 text-yellow-800 dark:text-yellow-200">
              <AlertTriangle className="h-5 w-5 shrink-0" />
              <p className="font-medium">No gripper detected</p>
            </div>
            <ul className="mt-2 list-disc pl-9 text-sm text-yellow-700 dark:text-yellow-300 space-y-1">
              <li>Check that your robot arms are powered on and USB cables are connected.</li>
              <li>Try unplugging and re-plugging the USB connections.</li>
              <li>Click &quot;Scan Ports&quot; again after reconnecting.</li>
            </ul>
          </div>
        )}

        <DevErrorPanel error={error} />
      </div>
    </StepCard>
  );
}
