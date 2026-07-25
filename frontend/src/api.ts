import type {
  AdminJob,
  AdminUser,
  ApiKey,
  Artifact,
  Confirmation,
  CreatedApiKey,
  CreatedOrgApiKey,
  CreatedOrgWebhook,
  ImageCapabilitiesResponse,
  Job,
  JobEvent,
  JobMessage,
  Organization,
  OrgApiKey,
  OrgUsageRow,
  OrgWebhook,
  OrgWebhookTestResult,
  PendingFile,
  Pricing,
  RuntimeConfig,
  RuntimeConfigUpdate,
  User,
} from "./types";

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export class ApiClient {
  private async request<T>(path: string, init: RequestInit = {}): Promise<T> {
    const headers = new Headers(init.headers);
    if (init.body && !(init.body instanceof FormData)) {
      headers.set("Content-Type", "application/json");
    }
    const response = await fetch(path, {
      ...init,
      credentials: "same-origin",
      headers,
    });
    if (!response.ok) {
      let message = `请求失败 (${response.status})`;
      try {
        const payload = (await response.json()) as { detail?: string };
        message = payload.detail || message;
      } catch {
        // Keep the status-based message when the server does not return JSON.
      }
      throw new ApiError(response.status, message);
    }
    return (await response.json()) as T;
  }

  login(username: string, password: string): Promise<User> {
    return this.request<User>("/v1/auth/login", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    });
  }

  consumeOrgTicket(ticket: string): Promise<User> {
    return this.request<User>("/v1/auth/org-tickets/consume", {
      method: "POST",
      body: JSON.stringify({ ticket }),
    });
  }

  logout(): Promise<unknown> {
    return this.request("/v1/auth/logout", { method: "POST" });
  }

  me(): Promise<User> {
    return this.request<User>("/v1/auth/me");
  }

  listApiKeys(): Promise<ApiKey[]> {
    return this.request<ApiKey[]>("/v1/auth/api-keys");
  }

  createApiKey(name: string): Promise<CreatedApiKey> {
    return this.request<CreatedApiKey>("/v1/auth/api-keys", {
      method: "POST",
      body: JSON.stringify({ name }),
    });
  }

  revokeApiKey(keyId: string): Promise<unknown> {
    return this.request(`/v1/auth/api-keys/${keyId}`, { method: "DELETE" });
  }

  listAdminUsers(): Promise<AdminUser[]> {
    return this.request<AdminUser[]>("/v1/admin/users");
  }

  createAdminUser(
    username: string,
    password: string,
    isAdmin: boolean,
  ): Promise<AdminUser> {
    return this.request<AdminUser>("/v1/admin/users", {
      method: "POST",
      body: JSON.stringify({ username, password, is_admin: isAdmin }),
    });
  }

  setAdminUserDisabled(userId: string, disabled: boolean): Promise<AdminUser> {
    return this.request<AdminUser>(`/v1/admin/users/${userId}`, {
      method: "PATCH",
      body: JSON.stringify({ disabled }),
    });
  }

  resetAdminUserPassword(userId: string, password: string): Promise<unknown> {
    return this.request(`/v1/admin/users/${userId}/password`, {
      method: "PUT",
      body: JSON.stringify({ password }),
    });
  }

  listAdminUserApiKeys(userId: string): Promise<ApiKey[]> {
    return this.request<ApiKey[]>(`/v1/admin/users/${userId}/api-keys`);
  }

  createAdminUserApiKey(userId: string, name: string): Promise<CreatedApiKey> {
    return this.request<CreatedApiKey>(`/v1/admin/users/${userId}/api-keys`, {
      method: "POST",
      body: JSON.stringify({ name }),
    });
  }

  revokeAdminUserApiKey(userId: string, keyId: string): Promise<unknown> {
    return this.request(`/v1/admin/users/${userId}/api-keys/${keyId}`, {
      method: "DELETE",
    });
  }

  getRuntimeConfig(): Promise<RuntimeConfig> {
    return this.request<RuntimeConfig>("/v1/admin/runtime-config");
  }

  updateRuntimeConfig(config: RuntimeConfigUpdate): Promise<RuntimeConfig> {
    return this.request<RuntimeConfig>("/v1/admin/runtime-config", {
      method: "PUT",
      body: JSON.stringify(config),
    });
  }

  getImageCapabilities(): Promise<ImageCapabilitiesResponse> {
    return this.request<ImageCapabilitiesResponse>(
      "/v1/admin/image-capabilities",
    );
  }

  getPricing(): Promise<Pricing> {
    return this.request<Pricing>("/v1/admin/billing-config");
  }

  updatePricing(pricing: Pricing): Promise<Pricing> {
    return this.request<Pricing>("/v1/admin/billing-config", {
      method: "PUT",
      body: JSON.stringify(pricing),
    });
  }

  listOrgs(): Promise<Organization[]> {
    return this.request<Organization[]>("/v1/admin/orgs");
  }

  createOrg(name: string, slug: string): Promise<Organization> {
    return this.request<Organization>("/v1/admin/orgs", {
      method: "POST",
      body: JSON.stringify({ name, slug }),
    });
  }

  topupOrg(
    orgId: string,
    amount: number,
  ): Promise<{ org_id: string; credit_balance: number }> {
    return this.request(`/v1/admin/orgs/${orgId}/credits`, {
      method: "POST",
      body: JSON.stringify({ amount }),
    });
  }

  listOrgKeys(orgId: string): Promise<OrgApiKey[]> {
    return this.request<OrgApiKey[]>(`/v1/admin/orgs/${orgId}/keys`);
  }

  createOrgKey(orgId: string, name: string): Promise<CreatedOrgApiKey> {
    return this.request<CreatedOrgApiKey>(`/v1/admin/orgs/${orgId}/keys`, {
      method: "POST",
      body: JSON.stringify({ name }),
    });
  }

  revokeOrgKey(orgId: string, keyId: string): Promise<unknown> {
    return this.request(`/v1/admin/orgs/${orgId}/keys/${keyId}`, {
      method: "DELETE",
    });
  }

  orgUsage(
    orgId: string,
    params: { endUserId?: string; since?: string; until?: string } = {},
  ): Promise<{ org_id: string; end_users: OrgUsageRow[] }> {
    const query = new URLSearchParams();
    if (params.endUserId) query.set("end_user_id", params.endUserId);
    if (params.since) query.set("since", params.since);
    if (params.until) query.set("until", params.until);
    const suffix = query.toString() ? `?${query.toString()}` : "";
    return this.request(`/v1/admin/orgs/${orgId}/usage${suffix}`);
  }

  /** Returns null when the org has no callback configured yet (404). */
  async orgWebhook(orgId: string): Promise<OrgWebhook | null> {
    try {
      return await this.request<OrgWebhook>(
        `/v1/admin/orgs/${orgId}/webhook`,
      );
    } catch (reason) {
      if (reason instanceof ApiError && reason.status === 404) return null;
      throw reason;
    }
  }

  saveOrgWebhook(
    orgId: string,
    body: { callback_url: string; enabled: boolean; rotate_secret: boolean },
  ): Promise<CreatedOrgWebhook> {
    return this.request<CreatedOrgWebhook>(
      `/v1/admin/orgs/${orgId}/webhook`,
      { method: "PUT", body: JSON.stringify(body) },
    );
  }

  testOrgWebhook(orgId: string): Promise<OrgWebhookTestResult> {
    return this.request<OrgWebhookTestResult>(
      `/v1/admin/orgs/${orgId}/webhook/test`,
      { method: "POST" },
    );
  }

  listJobs(): Promise<Job[]> {
    return this.request<Job[]>("/v1/jobs?limit=50");
  }

  listAllJobs(limit = 50): Promise<AdminJob[]> {
    return this.request<AdminJob[]>(`/v1/admin/jobs?limit=${limit}`);
  }

  purgeJob(jobId: string): Promise<AdminJob> {
    return this.request<AdminJob>(`/v1/admin/jobs/${jobId}/purge`, {
      method: "POST",
    });
  }

  getJob(jobId: string): Promise<Job> {
    return this.request<Job>(`/v1/jobs/${jobId}`);
  }

  listMessages(jobId: string): Promise<JobMessage[]> {
    return this.request<JobMessage[]>(`/v1/jobs/${jobId}/messages`);
  }

  createJob(prompt: string, files: PendingFile[]): Promise<Job> {
    const form = new FormData();
    form.set("prompt", prompt);
    form.set("route", "generate_pptx");
    files.forEach(({ file, role }) =>
      form.append(role === "reference" ? "references" : "files", file),
    );
    return this.request<Job>("/v1/jobs", { method: "POST", body: form });
  }

  async getConfirmation(jobId: string): Promise<Confirmation | null> {
    try {
      return await this.request<Confirmation>(`/v1/jobs/${jobId}/confirmation`);
    } catch (error) {
      if (error instanceof ApiError && error.status === 404) {
        return null;
      }
      throw error;
    }
  }

  submitConfirmation(
    jobId: string,
    approved: boolean,
    message: string,
  ): Promise<Confirmation> {
    return this.request<Confirmation>(`/v1/jobs/${jobId}/confirmation`, {
      method: "POST",
      body: JSON.stringify({ approved, message }),
    });
  }

  uploadAssets(jobId: string, files: PendingFile[]): Promise<unknown> {
    const form = new FormData();
    files.forEach(({ file, role }) =>
      form.append(role === "reference" ? "references" : "files", file),
    );
    return this.request(`/v1/jobs/${jobId}/assets`, {
      method: "POST",
      body: form,
    });
  }

  resumeJob(jobId: string, message: string): Promise<unknown> {
    return this.request(`/v1/jobs/${jobId}/resume`, {
      method: "POST",
      body: JSON.stringify({ message }),
    });
  }

  cancelJob(jobId: string): Promise<unknown> {
    return this.request(`/v1/jobs/${jobId}/cancel`, { method: "POST" });
  }

  listArtifacts(jobId: string): Promise<Artifact[]> {
    return this.request<Artifact[]>(`/v1/jobs/${jobId}/artifacts`);
  }

  async artifactBlob(
    jobId: string,
    artifactId: string,
    view = false,
  ): Promise<Blob> {
    const action = view ? "view" : "download";
    const response = await fetch(
      `/v1/jobs/${jobId}/artifacts/${artifactId}/${action}`,
      { credentials: "same-origin" },
    );
    if (!response.ok) {
      throw new ApiError(response.status, "产物读取失败");
    }
    return response.blob();
  }

  async streamEvents(
    jobId: string,
    onEvent: (event: JobEvent) => void,
    signal: AbortSignal,
  ): Promise<void> {
    const response = await fetch(`/v1/jobs/${jobId}/events`, {
      headers: {
        Accept: "text/event-stream",
      },
      credentials: "same-origin",
      signal,
    });
    if (!response.ok || !response.body) {
      throw new ApiError(response.status, "进度连接失败");
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    while (true) {
      const { value, done } = await reader.read();
      buffer += decoder
        .decode(value, { stream: !done })
        .replaceAll("\r\n", "\n");
      let boundary = buffer.indexOf("\n\n");
      while (boundary >= 0) {
        const block = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        const data = block
          .split("\n")
          .filter((line) => line.startsWith("data:"))
          .map((line) => line.slice(5).trimStart())
          .join("\n");
        if (data) {
          try {
            onEvent(JSON.parse(data) as JobEvent);
          } catch {
            // A malformed SSE data line must not tear down the whole stream.
            console.warn("跳过无法解析的事件流数据行");
          }
        }
        boundary = buffer.indexOf("\n\n");
      }
      if (done) {
        break;
      }
    }
  }
}
