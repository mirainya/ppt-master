import { type FormEvent, useCallback, useState } from "react";

import type { ApiClient } from "../api";
import type { Pricing } from "../types";

/** Loads and saves layer-1 pricing (per-token / per-image) and per-job hold. */
export function usePricing(apiClient: ApiClient) {
  const [pricing, setPricing] = useState<Pricing | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);

  const load = useCallback(async () => {
    setBusy(true);
    setError("");
    setSaved(false);
    try {
      setPricing(await apiClient.getPricing());
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "计价配置读取失败");
    } finally {
      setBusy(false);
    }
  }, [apiClient]);

  const save = useCallback(
    async (event: FormEvent) => {
      event.preventDefault();
      if (!pricing || busy) return;
      setBusy(true);
      setError("");
      setSaved(false);
      try {
        setPricing(await apiClient.updatePricing(pricing));
        setSaved(true);
      } catch (reason) {
        setError(reason instanceof Error ? reason.message : "计价配置保存失败");
      } finally {
        setBusy(false);
      }
    },
    [apiClient, busy, pricing],
  );

  const setField = useCallback((key: keyof Pricing, value: number) => {
    setPricing((current) => (current ? { ...current, [key]: value } : current));
    setSaved(false);
  }, []);

  return { pricing, busy, error, saved, load, save, setField };
}
