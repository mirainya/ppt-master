import { type FormEvent, useCallback, useState } from "react";

import type { ApiClient } from "../api";
import type { ImageCapability, RuntimeConfig, RuntimeConfigUpdate } from "../types";

/** Loads and saves service-wide runtime config (Codex + image provider). */
export function useRuntimeConfig(apiClient: ApiClient) {
  const [config, setConfig] = useState<RuntimeConfig | null>(null);
  const [codexKeyDraft, setCodexKeyDraft] = useState("");
  const [imageKeyDraft, setImageKeyDraft] = useState("");
  const [clearCodexKey, setClearCodexKey] = useState(false);
  const [clearImageKey, setClearImageKey] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);
  const [imageModels, setImageModels] = useState<ImageCapability[]>([]);

  const load = useCallback(async () => {
    setConfig(null);
    setBusy(true);
    setError("");
    setSaved(false);
    setCodexKeyDraft("");
    setImageKeyDraft("");
    setClearCodexKey(false);
    setClearImageKey(false);
    try {
      setConfig(await apiClient.getRuntimeConfig());
      try {
        const caps = await apiClient.getImageCapabilities();
        setImageModels(caps.available ? caps.models : []);
      } catch {
        setImageModels([]); // capabilities are optional; panel falls back to manual entry
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "配置读取失败");
    } finally {
      setBusy(false);
    }
  }, [apiClient]);

  const save = useCallback(
    async (event: FormEvent) => {
      event.preventDefault();
      if (!config || busy) return;
      setBusy(true);
      setError("");
      setSaved(false);
      const update: RuntimeConfigUpdate = {
        codex_base_url: config.codex_base_url.trim(),
        clear_codex_api_key: clearCodexKey,
        codex_model: config.codex_model.trim(),
        image_base_url: config.image_base_url.trim(),
        clear_image_api_key: clearImageKey,
        image_model: config.image_model.trim(),
        image_size: config.image_size.trim(),
        image_concurrency: config.image_concurrency,
      };
      if (codexKeyDraft.trim()) update.codex_api_key = codexKeyDraft.trim();
      if (imageKeyDraft.trim()) update.image_api_key = imageKeyDraft.trim();
      try {
        const next = await apiClient.updateRuntimeConfig(update);
        setConfig(next);
        setCodexKeyDraft("");
        setImageKeyDraft("");
        setClearCodexKey(false);
        setClearImageKey(false);
        setSaved(true);
      } catch (reason) {
        setError(reason instanceof Error ? reason.message : "配置保存失败");
      } finally {
        setBusy(false);
      }
    },
    [
      apiClient,
      busy,
      clearCodexKey,
      clearImageKey,
      codexKeyDraft,
      config,
      imageKeyDraft,
    ],
  );

  return {
    config,
    imageModels,
    setConfig,
    codexKeyDraft,
    setCodexKeyDraft,
    imageKeyDraft,
    setImageKeyDraft,
    clearCodexKey,
    setClearCodexKey,
    clearImageKey,
    setClearImageKey,
    busy,
    error,
    saved,
    load,
    save,
  };
}
