import { type FormEvent, useCallback, useState } from "react";

import type { ApiClient } from "../api";
import type { ApiKey, CreatedApiKey } from "../types";

/** Self-service personal API key management for the current (non-org) user. */
export function useApiKeys(apiClient: ApiClient) {
  const [open, setOpen] = useState(false);
  const [keys, setKeys] = useState<ApiKey[]>([]);
  const [name, setName] = useState("第三方调用");
  const [created, setCreated] = useState<CreatedApiKey | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const openDialog = useCallback(async () => {
    setOpen(true);
    setCreated(null);
    setError("");
    setBusy(true);
    try {
      setKeys(await apiClient.listApiKeys());
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "密钥读取失败");
    } finally {
      setBusy(false);
    }
  }, [apiClient]);

  const closeDialog = useCallback(() => setOpen(false), []);

  const create = useCallback(
    async (event: FormEvent) => {
      event.preventDefault();
      const trimmed = name.trim();
      if (!trimmed) return;
      setBusy(true);
      setError("");
      try {
        const key = await apiClient.createApiKey(trimmed);
        setCreated(key);
        setKeys((current) => [key, ...current]);
      } catch (reason) {
        setError(reason instanceof Error ? reason.message : "密钥创建失败");
      } finally {
        setBusy(false);
      }
    },
    [apiClient, name],
  );

  const revoke = useCallback(
    async (keyId: string) => {
      setBusy(true);
      setError("");
      try {
        await apiClient.revokeApiKey(keyId);
        setKeys((current) =>
          current.map((key) =>
            key.id === keyId
              ? { ...key, revoked_at: new Date().toISOString() }
              : key,
          ),
        );
      } catch (reason) {
        setError(reason instanceof Error ? reason.message : "密钥撤销失败");
      } finally {
        setBusy(false);
      }
    },
    [apiClient],
  );

  return {
    open,
    keys,
    name,
    setName,
    created,
    busy,
    error,
    openDialog,
    closeDialog,
    create,
    revoke,
  };
}
