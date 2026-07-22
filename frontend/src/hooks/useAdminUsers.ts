import { type FormEvent, useCallback, useEffect, useState } from "react";

import type { ApiClient } from "../api";
import type { AdminUser, ApiKey, CreatedApiKey } from "../types";

/** Admin account management: list, create, disable, reset password, per-user keys. */
export function useAdminUsers(apiClient: ApiClient, currentUserId: string) {
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [createAdmin, setCreateAdmin] = useState(false);
  const [passwordUser, setPasswordUser] = useState<AdminUser | null>(null);
  const [newPassword, setNewPassword] = useState("");
  const [keyUser, setKeyUser] = useState<AdminUser | null>(null);
  const [keys, setKeys] = useState<ApiKey[]>([]);
  const [createdKey, setCreatedKey] = useState<CreatedApiKey | null>(null);

  const loadUsers = useCallback(async () => {
    setBusy(true);
    setError("");
    try {
      setUsers(await apiClient.listAdminUsers());
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "账号读取失败");
    } finally {
      setBusy(false);
    }
  }, [apiClient]);

  useEffect(() => {
    void loadUsers();
  }, [loadUsers]);

  const createUser = useCallback(
    async (event: FormEvent) => {
      event.preventDefault();
      if (!username.trim() || password.length < 12 || busy) return;
      setBusy(true);
      setError("");
      setSuccess("");
      try {
        const created = await apiClient.createAdminUser(
          username.trim(),
          password,
          createAdmin,
        );
        setUsers((current) => [...current, created]);
        setUsername("");
        setPassword("");
        setCreateAdmin(false);
        setSuccess(`账号 ${created.username} 已创建`);
      } catch (reason) {
        setError(reason instanceof Error ? reason.message : "账号创建失败");
      } finally {
        setBusy(false);
      }
    },
    [apiClient, busy, createAdmin, password, username],
  );

  const toggleDisabled = useCallback(
    async (user: AdminUser) => {
      setBusy(true);
      setError("");
      setSuccess("");
      try {
        const updated = await apiClient.setAdminUserDisabled(
          user.id,
          !user.disabled,
        );
        setUsers((current) =>
          current.map((item) => (item.id === updated.id ? updated : item)),
        );
        setSuccess(
          `${updated.username} 已${updated.disabled ? "禁用" : "启用"}`,
        );
      } catch (reason) {
        setError(reason instanceof Error ? reason.message : "账号状态更新失败");
      } finally {
        setBusy(false);
      }
    },
    [apiClient],
  );

  const resetPassword = useCallback(
    async (event: FormEvent) => {
      event.preventDefault();
      if (!passwordUser || newPassword.length < 12 || busy) return;
      setBusy(true);
      setError("");
      setSuccess("");
      try {
        await apiClient.resetAdminUserPassword(passwordUser.id, newPassword);
        setSuccess(`${passwordUser.username} 的密码已重置，现有会话已失效`);
        const resetSelf = passwordUser.id === currentUserId;
        setPasswordUser(null);
        setNewPassword("");
        if (resetSelf) window.setTimeout(() => window.location.reload(), 900);
      } catch (reason) {
        setError(reason instanceof Error ? reason.message : "密码重置失败");
      } finally {
        setBusy(false);
      }
    },
    [apiClient, busy, currentUserId, newPassword, passwordUser],
  );

  const openKeys = useCallback(
    async (user: AdminUser) => {
      if (keyUser?.id === user.id) {
        setKeyUser(null);
        setKeys([]);
        setCreatedKey(null);
        return;
      }
      setBusy(true);
      setError("");
      setCreatedKey(null);
      try {
        setKeys(await apiClient.listAdminUserApiKeys(user.id));
        setKeyUser(user);
      } catch (reason) {
        setError(reason instanceof Error ? reason.message : "API Key 读取失败");
      } finally {
        setBusy(false);
      }
    },
    [apiClient, keyUser],
  );

  const createKey = useCallback(async () => {
    if (!keyUser || busy) return;
    setBusy(true);
    setError("");
    setSuccess("");
    try {
      const created = await apiClient.createAdminUserApiKey(
        keyUser.id,
        "管理员签发",
      );
      setCreatedKey(created);
      setKeys((current) => [created, ...current]);
      setUsers((current) =>
        current.map((user) =>
          user.id === keyUser.id
            ? { ...user, active_api_key_count: user.active_api_key_count + 1 }
            : user,
        ),
      );
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "API Key 创建失败");
    } finally {
      setBusy(false);
    }
  }, [apiClient, busy, keyUser]);

  const revokeKey = useCallback(
    async (keyId: string) => {
      if (!keyUser || busy) return;
      setBusy(true);
      setError("");
      try {
        await apiClient.revokeAdminUserApiKey(keyUser.id, keyId);
        setKeys((current) =>
          current.map((key) =>
            key.id === keyId
              ? { ...key, revoked_at: new Date().toISOString() }
              : key,
          ),
        );
        setUsers((current) =>
          current.map((user) =>
            user.id === keyUser.id
              ? {
                  ...user,
                  active_api_key_count: Math.max(
                    0,
                    user.active_api_key_count - 1,
                  ),
                }
              : user,
          ),
        );
      } catch (reason) {
        setError(reason instanceof Error ? reason.message : "API Key 撤销失败");
      } finally {
        setBusy(false);
      }
    },
    [apiClient, busy, keyUser],
  );

  return {
    users,
    busy,
    error,
    success,
    username,
    setUsername,
    password,
    setPassword,
    createAdmin,
    setCreateAdmin,
    passwordUser,
    setPasswordUser,
    newPassword,
    setNewPassword,
    keyUser,
    keys,
    createdKey,
    loadUsers,
    createUser,
    toggleDisabled,
    resetPassword,
    openKeys,
    createKey,
    revokeKey,
  };
}
