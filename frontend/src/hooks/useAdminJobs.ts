import { useCallback, useEffect, useState } from "react";

import type { ApiClient } from "../api";
import type { AdminJob } from "../types";

/** Admin task console: list every task and purge one task's files. */
export function useAdminJobs(apiClient: ApiClient) {
  const [jobs, setJobs] = useState<AdminJob[]>([]);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setBusy(true);
    setError("");
    try {
      setJobs(await apiClient.listAllJobs(100));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "任务读取失败");
    } finally {
      setBusy(false);
    }
  }, [apiClient]);

  useEffect(() => {
    void load();
  }, [load]);

  const purge = useCallback(
    async (jobId: string) => {
      setError("");
      try {
        const updated = await apiClient.purgeJob(jobId);
        setJobs((current) =>
          current.map((job) => (job.id === jobId ? updated : job)),
        );
      } catch (reason) {
        setError(reason instanceof Error ? reason.message : "清理失败");
      }
    },
    [apiClient],
  );

  return { jobs, busy, error, load, purge };
}
