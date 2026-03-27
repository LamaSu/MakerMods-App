"use client";

import { useEffect, useState } from "react";

let cached: string | null = null;

/**
 * Returns the backend host platform ("linux", "darwin", "windows").
 * Fetched once from /api/health and cached for the session.
 */
export function usePlatform(): string | null {
  const [platform, setPlatform] = useState<string | null>(cached);

  useEffect(() => {
    if (cached) return;
    fetch("/api/health")
      .then((r) => r.json())
      .then((data) => {
        cached = data.platform ?? null;
        setPlatform(cached);
      })
      .catch(() => {});
  }, []);

  return platform;
}
