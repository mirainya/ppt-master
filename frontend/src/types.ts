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
  files_purged_at: string | null;
}

export interface AdminJob extends Job {
  owner_username: string | null;
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

export type MessageRole = "user" | "assistant" | "system";

export interface JobMessage {
  id: number;
  job_id: string;
  role: MessageRole;
  content: string;
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

export type ArtifactKind = "pptx" | "preview" | "document";

export interface Artifact {
  id: string;
  job_id: string;
  kind: ArtifactKind;
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
  org_id: string | null;
}

export interface AdminUser {
  id: string;
  username: string;
  is_admin: boolean;
  disabled: boolean;
  active_api_key_count: number;
  created_at: string;
  updated_at: string;
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

export interface RuntimeConfig {
  codex_base_url: string;
  codex_api_key_configured: boolean;
  codex_model: string;
  image_base_url: string;
  image_api_key_configured: boolean;
  image_model: string;
  image_size: string;
  image_concurrency: number | null;
  updated_at: string | null;
}

export interface RuntimeConfigUpdate {
  codex_base_url: string;
  codex_api_key?: string;
  clear_codex_api_key: boolean;
  codex_model: string;
  image_base_url: string;
  image_api_key?: string;
  clear_image_api_key: boolean;
  image_model: string;
  image_size: string;
  image_concurrency: number | null;
}

export const terminalStatuses = new Set<JobStatus>([
  "succeeded",
  "failed",
  "cancelled",
]);

export interface Pricing {
  price_input_token: number;
  price_output_token: number;
  price_image: number;
  hold_amount: number;
}

export interface Organization {
  id: string;
  name: string;
  slug: string;
  credit_balance: number;
  daily_job_limit: number;
  max_active_jobs: number;
  created_at: string;
}

export interface OrgApiKey {
  id: string;
  name: string;
  key_prefix: string;
  last_used_at: string | null;
  revoked_at: string | null;
  created_at: string;
}

export interface CreatedOrgApiKey extends OrgApiKey {
  key: string;
}

export interface OrgUsageRow {
  end_user_id: string | null;
  input_tokens: number;
  output_tokens: number;
  images: number;
  pages: number;
  our_charge: number;
  jobs: number;
}

export type AppTheme = "mint" | "sakura" | "sky" | "dark";

export interface ThemeOption {
  key: AppTheme;
  label: string;
  color: string;
}

export const themeOptions: ThemeOption[] = [
  { key: "mint", label: "薄荷", color: "#4f9e8c" },
  { key: "sakura", label: "樱花", color: "#c76b85" },
  { key: "sky", label: "天空", color: "#4f8ab0" },
  { key: "dark", label: "深色", color: "#59534e" },
];
