export type JobRoute =
  | "generate_pptx"
  | "create_template"
  | "fill_native_pptx"
  | "enhance_native_pptx";

export type JobStatus =
  | "queued"
  | "intake"
  | "awaiting_confirmation"
  | "planning"
  | "acquiring"
  | "awaiting_asset"
  | "executing"
  | "validating"
  | "exporting"
  | "succeeded"
  | "failed"
  | "cancelled";

export type AssetRole = "source" | "reference";

export interface PendingFile {
  file: File;
  role: AssetRole;
}

export interface Job {
  id: string;
  title: string | null;
  prompt: string;
  route: JobRoute;
  status: JobStatus;
  stage: string;
  progress: number;
  cancel_requested: boolean;
  error: { code?: string; message?: string } | null;
  created_at: string;
  updated_at: string;
}

export interface JobEvent {
  id: number;
  job_id: string;
  event_type: string;
  stage: string;
  message: string;
  data: Record<string, unknown>;
  created_at: string;
}

export interface Confirmation {
  job_id: string;
  proposal: { markdown?: string; [key: string]: unknown };
  response: { approved: boolean; message: string } | null;
  status: "pending" | "approved" | "revision_requested" | "consumed";
  created_at: string;
  updated_at: string;
}

export interface Artifact {
  id: string;
  job_id: string;
  kind: "pptx" | "preview" | "document" | string;
  filename: string;
  size_bytes: number;
  sha256: string;
  media_type: string | null;
  created_at: string;
}

export interface User {
  id: string;
  username: string;
  is_admin: boolean;
}

export interface ApiKey {
  id: string;
  name: string;
  key_prefix: string;
  last_used_at: string | null;
  revoked_at: string | null;
  created_at: string;
}

export interface CreatedApiKey extends ApiKey {
  key: string;
}

export const terminalStatuses = new Set<JobStatus>([
  "succeeded",
  "failed",
  "cancelled",
]);
