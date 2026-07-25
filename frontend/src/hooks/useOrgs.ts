import { type FormEvent, useCallback, useEffect, useState } from "react";

import type { ApiClient } from "../api";
import type {
  CreatedOrgApiKey,
  Organization,
  OrgApiKey,
  OrgUsageRow,
  OrgWebhook,
  OrgWebhookTestResult,
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

  // Usage callback (webhook). `webhook` is null until one is configured.
  const [webhook, setWebhook] = useState<OrgWebhook | null>(null);
  const [webhookUrl, setWebhookUrl] = useState("");
  const [webhookEnabled, setWebhookEnabled] = useState(true);
  const [webhookSecret, setWebhookSecret] = useState("");
  const [webhookTest, setWebhookTest] = useState<OrgWebhookTestResult | null>(
    null,
  );

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
      setWebhookSecret("");
      setWebhookTest(null);
      setError("");
      setBusy(true);
      try {
        const [orgKeys, report, hook] = await Promise.all([
          apiClient.listOrgKeys(org.id),
          apiClient.orgUsage(org.id),
          apiClient.orgWebhook(org.id),
        ]);
        setKeys(orgKeys);
        setUsage(report.end_users);
        setWebhook(hook);
        setWebhookUrl(hook?.callback_url ?? "");
        setWebhookEnabled(hook?.enabled ?? true);
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

  const saveWebhook = useCallback(
    async (rotateSecret: boolean) => {
      if (!selected || busy || !webhookUrl.trim()) return;
      setBusy(true);
      setError("");
      setSuccess("");
      setWebhookTest(null);
      try {
        const saved = await apiClient.saveOrgWebhook(selected.id, {
          callback_url: webhookUrl.trim(),
          enabled: webhookEnabled,
          rotate_secret: rotateSecret,
        });
        setWebhook({
          org_id: saved.org_id,
          callback_url: saved.callback_url,
          enabled: saved.enabled,
          secret_configured: saved.secret_configured,
        });
        setWebhookUrl(saved.callback_url);
        // Plaintext comes back only on create/rotate; keep any earlier one shown.
        if (saved.secret) setWebhookSecret(saved.secret);
        setSuccess(rotateSecret ? "回调已保存，密钥已轮换" : "回调配置已保存");
      } catch (reason) {
        setError(reason instanceof Error ? reason.message : "回调保存失败");
      } finally {
        setBusy(false);
      }
    },
    [apiClient, busy, selected, webhookEnabled, webhookUrl],
  );

  const testWebhook = useCallback(async () => {
    if (!selected || busy) return;
    setBusy(true);
    setError("");
    setSuccess("");
    try {
      setWebhookTest(await apiClient.testOrgWebhook(selected.id));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "回调测试失败");
    } finally {
      setBusy(false);
    }
  }, [apiClient, busy, selected]);

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
    webhook,
    webhookUrl,
    setWebhookUrl,
    webhookEnabled,
    setWebhookEnabled,
    webhookSecret,
    webhookTest,
    load,
    createOrg,
    openOrg,
    topup,
    createKey,
    revokeKey,
    saveWebhook,
    testWebhook,
  };
}
