import type {
  ApiKey,
  Artifact,
  Confirmation,
  CreatedApiKey,
  Job,
  JobEvent,
  JobMessage,
  PendingFile,
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

  listJobs(): Promise<Job[]> {
    return this.request<Job[]>("/v1/jobs?limit=50");
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
          onEvent(JSON.parse(data) as JobEvent);
        }
        boundary = buffer.indexOf("\n\n");
      }
      if (done) {
        break;
      }
    }
  }
}
