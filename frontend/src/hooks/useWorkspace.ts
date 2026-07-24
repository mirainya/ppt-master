import { useCallback, useEffect, useMemo, useState } from "react";

import type { ApiClient } from "../api";
import {
  type Artifact,
  type AssetRole,
  type Job,
  type JobEvent,
  type JobMessage,
  type JobStatus,
  type PendingFile,
  terminalStatuses,
} from "../types";
import { eventMessageLabels } from "../lib/jobDisplay";

const WAITING_STATUSES: JobStatus[] = [
  "awaiting_confirmation",
  "awaiting_asset",
];
const REFRESH_TRIGGERS: JobStatus[] = [
  "awaiting_confirmation",
  "awaiting_asset",
  "succeeded",
  "failed",
  "cancelled",
];

/** Everything the workspace UI needs: job list, live stream, and job actions. */
export function useWorkspace(client: ApiClient | null) {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [events, setEvents] = useState<JobEvent[]>([]);
  const [messages, setMessages] = useState<JobMessage[]>([]);
  const [artifacts, setArtifacts] = useState<Artifact[]>([]);
  const [message, setMessage] = useState("");
  const [files, setFiles] = useState<PendingFile[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [streamVersion, setStreamVersion] = useState(0);
  const [now, setNow] = useState(() => Date.now());

  const selectedJob = jobs.find((job) => job.id === selectedId) || null;
  const isRunning = Boolean(
    selectedJob &&
    !terminalStatuses.has(selectedJob.status) &&
    !WAITING_STATUSES.includes(selectedJob.status),
  );

  const refreshJob = useCallback(
    async (jobId: string) => {
      if (!client) return;
      const [job, nextArtifacts, nextMessages] = await Promise.all([
        client.getJob(jobId),
        client.listArtifacts(jobId),
        client.listMessages(jobId),
      ]);
      setJobs((current) => {
        const others = current.filter((item) => item.id !== job.id);
        return [job, ...others].sort(
          (left, right) =>
            Date.parse(right.updated_at) - Date.parse(left.updated_at),
        );
      });
      setArtifacts(nextArtifacts);
      setMessages(nextMessages);
    },
    [client],
  );

  useEffect(() => {
    if (!client) return;
    let active = true;
    // An admin opening another user's job via ?job=<id> selects it directly;
    // refreshJob then fetches it (backend allows admin read) and adds it in.
    const requestedId = new URLSearchParams(window.location.search).get("job");
    client
      .listJobs()
      .then((nextJobs) => {
        if (!active) return;
        setJobs(nextJobs);
        setSelectedId((current) => current || requestedId || nextJobs[0]?.id || null);
      })
      .catch((reason: unknown) => {
        if (active)
          setError(reason instanceof Error ? reason.message : "任务读取失败");
      });
    return () => {
      active = false;
    };
  }, [client]);

  useEffect(() => {
    if (!client || !selectedId) {
      setEvents([]);
      setArtifacts([]);
      setMessages([]);
      return;
    }
    const controller = new AbortController();
    setEvents([]);
    setArtifacts([]);
    setMessages([]);
    refreshJob(selectedId).catch((reason: unknown) => {
      setError(reason instanceof Error ? reason.message : "任务读取失败");
    });
    client
      .streamEvents(
        selectedId,
        (event) => {
          setEvents((current) =>
            current.some((item) => item.id === event.id)
              ? current
              : [...current, event],
          );
          if (event.event_type !== "status") return;
          const progress = Number(event.data.progress ?? 0);
          setJobs((current) =>
            current.map((job) => {
              if (job.id !== selectedId) return job;
              if (Date.parse(event.created_at) < Date.parse(job.updated_at))
                return job;
              return {
                ...job,
                status: event.stage as JobStatus,
                stage: event.stage,
                progress,
                updated_at: event.created_at,
              };
            }),
          );
          if (REFRESH_TRIGGERS.includes(event.stage as JobStatus)) {
            refreshJob(selectedId).catch(() => undefined);
          }
        },
        controller.signal,
      )
      .catch((reason: unknown) => {
        if (!(reason instanceof DOMException && reason.name === "AbortError")) {
          setError(reason instanceof Error ? reason.message : "进度连接失败");
        }
      });
    return () => controller.abort();
  }, [client, refreshJob, selectedId, streamVersion]);

  useEffect(() => {
    if (!client || !selectedId) return;
    const timer = window.setInterval(() => {
      refreshJob(selectedId).catch(() => undefined);
    }, 4000);
    return () => window.clearInterval(timer);
  }, [client, refreshJob, selectedId]);

  useEffect(() => {
    if (!isRunning) return;
    setNow(Date.now());
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [isRunning, selectedId]);

  const derived = useMemo(() => {
    const reversed = [...events].reverse();
    const referenceEvent = reversed.find((e) => e.event_type === "references");
    const latestPageEvent = reversed.find(
      (e) => typeof e.data.page_count === "number",
    );
    const runStartedEvent = reversed.find(
      (e) => e.event_type === "status" && e.stage === selectedJob?.status,
    );
    const latestEvent = events.length > 0 ? events[events.length - 1] : null;
    const timelineEvents = events.filter(
      (e) =>
        e.event_type === "activity" ||
        Object.hasOwn(eventMessageLabels, e.message),
    );
    const previewArtifacts = artifacts.filter((a) => a.kind === "preview");
    const downloadableArtifacts = artifacts.filter((a) => a.kind !== "preview");
    return {
      referenceEvent,
      latestPageEvent,
      runStartedEvent,
      latestEvent,
      timelineEvents,
      previewArtifacts,
      downloadableArtifacts,
    };
  }, [events, artifacts, selectedJob?.status]);

  const bump = useCallback(() => setStreamVersion((v) => v + 1), []);

  return {
    jobs,
    selectedId,
    setSelectedId,
    selectedJob,
    isRunning,
    events,
    messages,
    artifacts,
    message,
    setMessage,
    files,
    setFiles,
    busy,
    setBusy,
    error,
    setError,
    now,
    refreshJob,
    bump,
    setJobs,
    ...derived,
  };
}

export type WorkspaceState = ReturnType<typeof useWorkspace>;
export type { AssetRole };
