import { type FormEvent, useCallback, useEffect, useState } from "react";

import type { ApiClient } from "../api";
import type {
  CreatedOrgApiKey,
  Organization,
  OrgApiKey,
  OrgUsageRow,
} from "../types";

/** Admin organization management: list, create, top-up credits, keys, usage. */
export function useOrgs(apiClient: ApiClient) {
  const [orgs, setOrgs] = useState<Organization[]>([]);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  // Create-org form
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");

  // Selected org drill-down
  const [selected, setSelected] = useState<Organization | null>(null);
  const [topupAmount, setTopupAmount] = useState("");
  const [keys, setKeys] = useState<OrgApiKey[]>([]);
  const [createdKey, setCreatedKey] = useState<CreatedOrgApiKey | null>(null);
  const [usage, setUsage] = useState<OrgUsageRow[]>([]);

  const load = useCallback(async () => {
    setBusy(true);
    setError("");
    try {
      setOrgs(await apiClient.listOrgs());
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "组织读取失败");
    } finally {
      setBusy(false);
    }
  }, [apiClient]);

  useEffect(() => {
    void load();
  }, [load]);

  const createOrg = useCallback(
    async (event: FormEvent) => {
      event.preventDefault();
      if (!name.trim() || !slug.trim() || busy) return;
      setBusy(true);
      setError("");
      setSuccess("");
      try {
        const org = await apiClient.createOrg(name.trim(), slug.trim());
        setOrgs((current) => [org, ...current]);
        setName("");
        setSlug("");
        setSuccess(`组织 ${org.name} 已创建`);
      } catch (reason) {
        setError(reason instanceof Error ? reason.message : "组织创建失败");
      } finally {
        setBusy(false);
      }
    },
    [apiClient, busy, name, slug],
  );

  const openOrg = useCallback(
    async (org: Organization) => {
      if (selected?.id === org.id) {
        setSelected(null);
        return;
      }
      setSelected(org);
      setCreatedKey(null);
      setTopupAmount("");
      setError("");
      setBusy(true);
      try {
        const [orgKeys, report] = await Promise.all([
          apiClient.listOrgKeys(org.id),
          apiClient.orgUsage(org.id),
        ]);
        setKeys(orgKeys);
        setUsage(report.end_users);
      } catch (reason) {
        setError(reason instanceof Error ? reason.message : "组织详情读取失败");
      } finally {
        setBusy(false);
      }
    },
    [apiClient, selected],
  );

  const topup = useCallback(
    async (event: FormEvent) => {
      event.preventDefault();
      const amount = Number(topupAmount);
      if (!selected || !(amount > 0) || busy) return;
      setBusy(true);
      setError("");
      setSuccess("");
      try {
        const result = await apiClient.topupOrg(selected.id, amount);
        setOrgs((current) =>
          current.map((org) =>
            org.id === selected.id
              ? { ...org, credit_balance: result.credit_balance }
              : org,
          ),
        );
        setSelected((current) =>
          current
            ? { ...current, credit_balance: result.credit_balance }
            : current,
        );
        setTopupAmount("");
        setSuccess(`已充值 ${amount}，当前余额 ${result.credit_balance}`);
      } catch (reason) {
        setError(reason instanceof Error ? reason.message : "充值失败");
      } finally {
        setBusy(false);
      }
    },
    [apiClient, busy, selected, topupAmount],
  );

  const createKey = useCallback(async () => {
    if (!selected || busy) return;
    setBusy(true);
    setError("");
    try {
      const key = await apiClient.createOrgKey(selected.id, "组织服务密钥");
      setCreatedKey(key);
      setKeys((current) => [key, ...current]);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "组织密钥创建失败");
    } finally {
      setBusy(false);
    }
  }, [apiClient, busy, selected]);

  const revokeKey = useCallback(
    async (keyId: string) => {
      if (!selected || busy) return;
      setBusy(true);
      setError("");
      try {
        await apiClient.revokeOrgKey(selected.id, keyId);
        setKeys((current) =>
          current.map((key) =>
            key.id === keyId
              ? { ...key, revoked_at: new Date().toISOString() }
              : key,
          ),
        );
      } catch (reason) {
        setError(reason instanceof Error ? reason.message : "组织密钥撤销失败");
      } finally {
        setBusy(false);
      }
    },
    [apiClient, busy, selected],
  );

  return {
    orgs,
    busy,
    error,
    success,
    name,
    setName,
    slug,
    setSlug,
    selected,
    topupAmount,
    setTopupAmount,
    keys,
    createdKey,
    usage,
    load,
    createOrg,
    openOrg,
    topup,
    createKey,
    revokeKey,
  };
}
