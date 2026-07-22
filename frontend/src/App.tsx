import {
  AlertCircle,
  BookOpen,
  Check,
  ChevronLeft,
  ChevronRight,
  CircleCheck,
  Copy,
  Download,
  FileText,
  Maximize2,
  KeyRound,
  LoaderCircle,
  LogIn,
  LogOut,
  Menu,
  MessageSquare,
  Minimize2,
  Paperclip,
  Palette,
  PanelRight,
  Plus,
  Presentation,
  Send,
  Square,
  Trash2,
  UserRound,
  X,
} from "lucide-react";
import {
  type ChangeEvent,
  type FormEvent,
  type KeyboardEvent,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import ReactMarkdown from "react-markdown";

import { ApiClient, ApiError } from "./api";
import type {
  ApiKey,
  Artifact,
  AssetRole,
  CreatedApiKey,
  Job,
  JobEvent,
  JobMessage,
  JobStatus,
  PendingFile,
  User,
} from "./types";
import { terminalStatuses } from "./types";

const THEME_STORAGE = "ppt-master-theme";
const initialOrgTicket = (() => {
  const url = new URL(window.location.href);
  const fragment = new URLSearchParams(url.hash.slice(1));
  const ticket =
    fragment.get("sso_ticket") || url.searchParams.get("sso_ticket");
  if (ticket) {
    fragment.delete("sso_ticket");
    url.searchParams.delete("sso_ticket");
    url.hash = fragment.toString();
    window.history.replaceState(
      {},
      "",
      `${url.pathname}${url.search}${url.hash}`,
    );
  }
  return ticket;
})();

type AppTheme = "mint" | "sakura" | "sky" | "dark";

const themeOptions: Array<{ key: AppTheme; label: string; color: string }> = [
  { key: "mint", label: "薄荷", color: "#4f9e8c" },
  { key: "sakura", label: "樱花", color: "#c76b85" },
  { key: "sky", label: "天空", color: "#4f8ab0" },
  { key: "dark", label: "深色", color: "#59534e" },
];

const statusLabels: Record<JobStatus, string> = {
  queued: "已排队",
  intake: "分析材料",
  awaiting_confirmation: "等待确认",
  planning: "规划中",
  acquiring: "准备素材",
  awaiting_asset: "等待素材",
  executing: "生成页面",
  validating: "检查中",
  exporting: "导出中",
  succeeded: "已完成",
  failed: "失败",
  cancelled: "已取消",
};

const eventMessageLabels: Record<string, string> = {
  "Task accepted": "任务已接收",
  "Analyzing source material": "正在分析需求与素材",
  "Response received": "已收到方案反馈",
  "Collecting outputs": "正在整理导出文件",
  "Task cancelled": "任务已取消",
  "Task execution failed": "任务执行失败",
};

function jobTitle(job: Job): string {
  return job.title?.trim() || job.prompt.trim().slice(0, 28) || "未命名演示";
}

function formatBytes(value: number): string {
  if (value < 1024 * 1024) return `${Math.max(1, Math.round(value / 1024))} KB`;
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
}

function statusTone(status: JobStatus): string {
  if (status === "succeeded") return "success";
  if (status === "failed" || status === "cancelled") return "danger";
  if (status === "awaiting_confirmation" || status === "awaiting_asset")
    return "waiting";
  return "active";
}

function statusLabel(status: JobStatus, running: boolean): string {
  return running ? "处理中" : statusLabels[status];
}

function eventMessage(event: JobEvent | null): string {
  if (!event) return "正在准备任务";
  return eventMessageLabels[event.message] || event.message;
}

function formatElapsed(createdAt: string, now: number): string {
  const seconds = Math.max(0, Math.floor((now - Date.parse(createdAt)) / 1000));
  if (seconds < 60) return `已运行 ${seconds} 秒`;
  const minutes = Math.floor(seconds / 60);
  const remainingSeconds = seconds % 60;
  return `已运行 ${minutes} 分 ${remainingSeconds} 秒`;
}

function previewStatusMessage(
  job: Job | null,
  running: boolean,
  latestEvent: JobEvent | null,
  previewCount: number,
): string {
  if (!job) return "等待新任务";
  if (job.status === "executing" && previewCount > 0)
    return `已完成 ${previewCount} 页`;
  if (running) return eventMessage(latestEvent);
  if (job.status === "awaiting_confirmation") return "方案已就绪，等待确认";
  if (job.status === "awaiting_asset") return "等待补充素材";
  if (job.status === "failed") return "任务未完成";
  if (job.status === "cancelled") return "任务已取消";
  return "等待页面产出";
}

export default function App() {
  const [theme, setTheme] = useState<AppTheme>(() => {
    const saved = localStorage.getItem(THEME_STORAGE) as AppTheme | null;
    return saved && themeOptions.some((option) => option.key === saved)
      ? saved
      : "mint";
  });
  const [currentUser, setCurrentUser] = useState<User | null>(null);
  const [authChecking, setAuthChecking] = useState(true);
  const [usernameDraft, setUsernameDraft] = useState("");
  const [passwordDraft, setPasswordDraft] = useState("");
  const [authError, setAuthError] = useState("");
  const [apiKeyDialogOpen, setApiKeyDialogOpen] = useState(false);
  const [apiKeys, setApiKeys] = useState<ApiKey[]>([]);
  const [apiKeyName, setApiKeyName] = useState("第三方调用");
  const [createdApiKey, setCreatedApiKey] = useState<CreatedApiKey | null>(
    null,
  );
  const [apiKeyBusy, setApiKeyBusy] = useState(false);
  const [apiKeyError, setApiKeyError] = useState("");
  const [jobs, setJobs] = useState<Job[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [events, setEvents] = useState<JobEvent[]>([]);
  const [messages, setMessages] = useState<JobMessage[]>([]);
  const [artifacts, setArtifacts] = useState<Artifact[]>([]);
  const [previewUrls, setPreviewUrls] = useState<Record<string, string>>({});
  const [selectedPreviewId, setSelectedPreviewId] = useState<string | null>(
    null,
  );
  const [message, setMessage] = useState("");
  const [files, setFiles] = useState<PendingFile[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [mobileView, setMobileView] = useState<"chat" | "preview">("chat");
  const [streamVersion, setStreamVersion] = useState(0);
  const [now, setNow] = useState(() => Date.now());
  const fileInputRef = useRef<HTMLInputElement>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const previewPaneRef = useRef<HTMLElement>(null);
  const authRequestRef = useRef<Promise<User> | null>(null);
  const [previewFullscreen, setPreviewFullscreen] = useState(false);

  const apiClient = useMemo(() => new ApiClient(), []);
  const client = currentUser ? apiClient : null;
  const selectedJob = jobs.find((job) => job.id === selectedId) || null;
  const isRunning = Boolean(
    selectedJob &&
    !terminalStatuses.has(selectedJob.status) &&
    !["awaiting_confirmation", "awaiting_asset"].includes(selectedJob.status),
  );
  const latestEvent = events.length > 0 ? events[events.length - 1] : null;
  const referenceEvent = [...events]
    .reverse()
    .find((event) => event.event_type === "references");
  const latestPageEvent = [...events]
    .reverse()
    .find((event) => typeof event.data.page_count === "number");
  const displayedActivity =
    selectedJob?.status === "executing" && latestPageEvent
      ? latestPageEvent
      : latestEvent;
  const runStartedEvent = [...events]
    .reverse()
    .find(
      (event) =>
        event.event_type === "status" && event.stage === selectedJob?.status,
    );
  const timelineEvents = events.filter(
    (event) =>
      event.event_type === "activity" ||
      Object.hasOwn(eventMessageLabels, event.message),
  );
  const visibleEvents = (
    isRunning ? timelineEvents.slice(0, -1) : timelineEvents
  ).slice(-6);
  const previewArtifacts = artifacts.filter(
    (artifact) => artifact.kind === "preview",
  );
  const displayedActivityMessage =
    selectedJob?.status === "executing" && previewArtifacts.length > 0
      ? `正在生成页面，已完成 ${previewArtifacts.length} 页`
      : eventMessage(displayedActivity);
  const downloadableArtifacts = artifacts.filter(
    (artifact) => artifact.kind !== "preview",
  );
  const selectedPreviewIndex = previewArtifacts.findIndex(
    (artifact) => artifact.id === selectedPreviewId,
  );

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem(THEME_STORAGE, theme);
  }, [theme]);

  useEffect(() => {
    let active = true;
    if (!authRequestRef.current) {
      authRequestRef.current = initialOrgTicket
        ? apiClient.consumeOrgTicket(initialOrgTicket)
        : apiClient.me();
    }
    authRequestRef.current
      .then((user) => {
        if (active) setCurrentUser(user);
      })
      .catch((reason: unknown) => {
        if (!active) return;
        if (
          !initialOrgTicket &&
          reason instanceof ApiError &&
          reason.status === 401
        )
          return;
        setAuthError(
          initialOrgTicket ? "工作台登录链接无效或已过期" : "认证服务不可用",
        );
      })
      .finally(() => {
        if (active) setAuthChecking(false);
      });
    return () => {
      active = false;
    };
  }, [apiClient]);

  useEffect(() => {
    if (!isRunning) return;
    setNow(Date.now());
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [isRunning, selectedJob?.id]);

  const refreshJob = useCallback(
    async (jobId: string) => {
      if (!client) return;
      const [job, nextArtifacts, nextMessages] = await Promise.all([
        client.getJob(jobId),
        client.listArtifacts(jobId),
        client.listMessages(jobId),
      ]);
      setJobs((current) => {
        const others = current.filter((item) => item.id !== job.id);
        return [job, ...others].sort(
          (left, right) =>
            Date.parse(right.updated_at) - Date.parse(left.updated_at),
        );
      });
      setArtifacts(nextArtifacts);
      setMessages(nextMessages);
    },
    [client],
  );

  useEffect(() => {
    if (!client) return;
    let active = true;
    client
      .listJobs()
      .then((nextJobs) => {
        if (!active) return;
        setJobs(nextJobs);
        setSelectedId((current) => current || nextJobs[0]?.id || null);
      })
      .catch((reason: unknown) => {
        if (active)
          setError(reason instanceof Error ? reason.message : "任务读取失败");
      });
    return () => {
      active = false;
    };
  }, [client]);

  useEffect(() => {
    if (!client || !selectedId) {
      setEvents([]);
      setArtifacts([]);
      setMessages([]);
      return;
    }
    const controller = new AbortController();
    setEvents([]);
    setArtifacts([]);
    setMessages([]);
    refreshJob(selectedId).catch((reason: unknown) => {
      setError(reason instanceof Error ? reason.message : "任务读取失败");
    });
    client
      .streamEvents(
        selectedId,
        (event) => {
          setEvents((current) =>
            current.some((item) => item.id === event.id)
              ? current
              : [...current, event],
          );
          if (event.event_type === "status") {
            const progress = Number(event.data.progress ?? 0);
            setJobs((current) =>
              current.map((job) => {
                if (job.id !== selectedId) return job;
                if (Date.parse(event.created_at) < Date.parse(job.updated_at)) {
                  return job;
                }
                return {
                  ...job,
                  status: event.stage as JobStatus,
                  stage: event.stage,
                  progress,
                  updated_at: event.created_at,
                };
              }),
            );
            if (
              [
                "awaiting_confirmation",
                "awaiting_asset",
                "succeeded",
                "failed",
                "cancelled",
              ].includes(event.stage)
            ) {
              refreshJob(selectedId).catch(() => undefined);
            }
          }
        },
        controller.signal,
      )
      .catch((reason: unknown) => {
        if (!(reason instanceof DOMException && reason.name === "AbortError")) {
          setError(reason instanceof Error ? reason.message : "进度连接失败");
        }
      });
    return () => controller.abort();
  }, [client, refreshJob, selectedId, streamVersion]);

  useEffect(() => {
    if (!client || !selectedId) return;
    const timer = window.setInterval(() => {
      refreshJob(selectedId).catch(() => undefined);
    }, 4000);
    return () => window.clearInterval(timer);
  }, [client, refreshJob, selectedId]);

  useEffect(() => {
    if (!client || !selectedId || previewArtifacts.length === 0) {
      setPreviewUrls({});
      setSelectedPreviewId(null);
      return;
    }
    let active = true;
    const objectUrls: string[] = [];
    Promise.all(
      previewArtifacts.map(async (artifact) => {
        const blob = await client.artifactBlob(selectedId, artifact.id, true);
        const url = URL.createObjectURL(blob);
        objectUrls.push(url);
        return [artifact.id, url] as const;
      }),
    )
      .then((entries) => {
        if (!active) return;
        setPreviewUrls(Object.fromEntries(entries));
        setSelectedPreviewId((current) =>
          current && entries.some(([id]) => id === current)
            ? current
            : entries[0]?.[0] || null,
        );
      })
      .catch((reason: unknown) => {
        if (active)
          setError(reason instanceof Error ? reason.message : "预览读取失败");
      });
    return () => {
      active = false;
      objectUrls.forEach((url) => URL.revokeObjectURL(url));
    };
  }, [
    client,
    selectedId,
    previewArtifacts.map((item) => `${item.id}:${item.sha256}`).join(","),
  ]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({
      behavior: "smooth",
      block: "end",
    });
  }, [events, messages]);

  useEffect(() => {
    const handleFullscreenChange = () => {
      setPreviewFullscreen(
        document.fullscreenElement === previewPaneRef.current,
      );
    };
    document.addEventListener("fullscreenchange", handleFullscreenChange);
    return () =>
      document.removeEventListener("fullscreenchange", handleFullscreenChange);
  }, []);

  useEffect(() => {
    if (!previewFullscreen) return;
    const handleFullscreenKeyDown = (event: globalThis.KeyboardEvent) => {
      if (event.key === "ArrowLeft" && selectedPreviewIndex > 0) {
        setSelectedPreviewId(
          previewArtifacts[selectedPreviewIndex - 1]?.id || null,
        );
      }
      if (
        event.key === "ArrowRight" &&
        selectedPreviewIndex >= 0 &&
        selectedPreviewIndex < previewArtifacts.length - 1
      ) {
        setSelectedPreviewId(
          previewArtifacts[selectedPreviewIndex + 1]?.id || null,
        );
      }
    };
    window.addEventListener("keydown", handleFullscreenKeyDown);
    return () => window.removeEventListener("keydown", handleFullscreenKeyDown);
  }, [previewArtifacts, previewFullscreen, selectedPreviewIndex]);

  async function unlock(event: FormEvent) {
    event.preventDefault();
    const username = usernameDraft.trim();
    if (!username || !passwordDraft) return;
    setBusy(true);
    setAuthError("");
    try {
      const user = await apiClient.login(username, passwordDraft);
      const nextJobs = await apiClient.listJobs();
      setCurrentUser(user);
      setPasswordDraft("");
      setJobs(nextJobs);
      setSelectedId(nextJobs[0]?.id || null);
    } catch (reason) {
      setAuthError(
        reason instanceof ApiError && reason.status === 401
          ? "用户名或密码错误"
          : "服务不可用",
      );
    } finally {
      setBusy(false);
    }
  }

  async function logout() {
    try {
      await apiClient.logout();
    } finally {
      setCurrentUser(null);
      setPasswordDraft("");
      setJobs([]);
      setSelectedId(null);
      setMessages([]);
      setApiKeyDialogOpen(false);
    }
  }

  async function openApiKeyDialog() {
    setApiKeyDialogOpen(true);
    setCreatedApiKey(null);
    setApiKeyError("");
    setApiKeyBusy(true);
    try {
      setApiKeys(await apiClient.listApiKeys());
    } catch (reason) {
      setApiKeyError(reason instanceof Error ? reason.message : "密钥读取失败");
    } finally {
      setApiKeyBusy(false);
    }
  }

  async function createUserApiKey(event: FormEvent) {
    event.preventDefault();
    const name = apiKeyName.trim();
    if (!name) return;
    setApiKeyBusy(true);
    setApiKeyError("");
    try {
      const created = await apiClient.createApiKey(name);
      setCreatedApiKey(created);
      setApiKeys((current) => [created, ...current]);
    } catch (reason) {
      setApiKeyError(reason instanceof Error ? reason.message : "密钥创建失败");
    } finally {
      setApiKeyBusy(false);
    }
  }

  async function revokeUserApiKey(keyId: string) {
    setApiKeyBusy(true);
    setApiKeyError("");
    try {
      await apiClient.revokeApiKey(keyId);
      setApiKeys((current) =>
        current.map((key) =>
          key.id === keyId
            ? { ...key, revoked_at: new Date().toISOString() }
            : key,
        ),
      );
    } catch (reason) {
      setApiKeyError(reason instanceof Error ? reason.message : "密钥撤销失败");
    } finally {
      setApiKeyBusy(false);
    }
  }

  function startNewJob() {
    setSelectedId(null);
    setEvents([]);
    setArtifacts([]);
    setMessages([]);
    setMessage("");
    setFiles([]);
    setSidebarOpen(false);
    setMobileView("chat");
  }

  function selectJob(jobId: string) {
    setSelectedId(jobId);
    setMessage("");
    setFiles([]);
    setSidebarOpen(false);
  }

  function addFiles(event: ChangeEvent<HTMLInputElement>) {
    const incoming = Array.from(event.target.files || []);
    setFiles((current) =>
      [
        ...current,
        ...incoming.map((file) => ({ file, role: "source" as AssetRole })),
      ].slice(0, 20),
    );
    event.target.value = "";
  }

  function setFileRole(index: number, role: AssetRole) {
    setFiles((current) =>
      current.map((item, itemIndex) =>
        itemIndex === index ? { ...item, role } : item,
      ),
    );
  }

  async function sendMessage() {
    if (!client || busy) return;
    const trimmed = message.trim();
    if (!trimmed) return;
    setBusy(true);
    setError("");
    try {
      if (!selectedJob || selectedJob.status === "cancelled") {
        const job = await client.createJob(trimmed, files);
        setJobs((current) => [job, ...current]);
        setSelectedId(job.id);
      } else if (selectedJob.status === "awaiting_confirmation") {
        await client.submitConfirmation(selectedJob.id, false, trimmed);
        await refreshJob(selectedJob.id);
        setStreamVersion((current) => current + 1);
      } else if (
        ["awaiting_asset", "succeeded", "failed"].includes(selectedJob.status)
      ) {
        if (files.length > 0) await client.uploadAssets(selectedJob.id, files);
        await client.resumeJob(selectedJob.id, trimmed);
        await refreshJob(selectedJob.id);
        setStreamVersion((current) => current + 1);
      }
      setMessage("");
      setFiles([]);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "操作失败");
    } finally {
      setBusy(false);
    }
  }

  async function approveConfirmation() {
    if (!client || !selectedJob || busy) return;
    setBusy(true);
    setError("");
    try {
      await client.submitConfirmation(selectedJob.id, true, message.trim());
      setMessage("");
      await refreshJob(selectedJob.id);
      setStreamVersion((current) => current + 1);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "确认失败");
    } finally {
      setBusy(false);
    }
  }

  async function cancelJob() {
    if (!client || !selectedJob || busy) return;
    setBusy(true);
    try {
      await client.cancelJob(selectedJob.id);
      await refreshJob(selectedJob.id);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "取消失败");
    } finally {
      setBusy(false);
    }
  }

  async function retryJob() {
    if (!client || !selectedJob || busy) return;
    setBusy(true);
    setError("");
    try {
      await client.resumeJob(selectedJob.id, "继续执行当前任务");
      await refreshJob(selectedJob.id);
      setStreamVersion((current) => current + 1);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "重新执行失败");
    } finally {
      setBusy(false);
    }
  }

  async function downloadArtifact(artifact: Artifact) {
    if (!client || !selectedJob) return;
    try {
      const blob = await client.artifactBlob(selectedJob.id, artifact.id);
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = artifact.filename;
      anchor.click();
      URL.revokeObjectURL(url);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "下载失败");
    }
  }

  async function togglePreviewFullscreen() {
    try {
      if (document.fullscreenElement) {
        await document.exitFullscreen();
      } else {
        await previewPaneRef.current?.requestFullscreen();
      }
    } catch {
      setError("浏览器未能进入全屏预览");
    }
  }

  function handleComposerKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      void sendMessage();
    }
  }

  const canSend = message.trim().length > 0 && !busy && !isRunning;

  return (
    <div className="app-shell">
      <aside className={`sidebar ${sidebarOpen ? "sidebar-open" : ""}`}>
        <div className="brand-row">
          <div className="brand-mark">
            <Presentation size={18} />
          </div>
          <strong>PPT Master</strong>
          <button
            className="icon-button sidebar-close"
            onClick={() => setSidebarOpen(false)}
            aria-label="关闭任务栏"
            title="关闭任务栏"
          >
            <X size={18} />
          </button>
        </div>
        <button className="new-job-button" onClick={startNewJob}>
          <Plus size={17} />
          <span>新建演示</span>
        </button>
        <div className="sidebar-label">最近任务</div>
        <nav className="job-list" aria-label="最近任务">
          {jobs.map((job) => (
            <button
              key={job.id}
              className={`job-item ${selectedId === job.id ? "selected" : ""}`}
              onClick={() => selectJob(job.id)}
            >
              <span className={`status-dot ${statusTone(job.status)}`} />
              <span className="job-copy">
                <strong>{jobTitle(job)}</strong>
                <small>{statusLabels[job.status]}</small>
              </span>
            </button>
          ))}
          {jobs.length === 0 && <div className="empty-list">暂无任务</div>}
        </nav>
        <div className="sidebar-footer">
          <div className="theme-row">
            <Palette size={16} />
            <div className="theme-swatches" role="group" aria-label="界面主题">
              {themeOptions.map((option) => (
                <button
                  key={option.key}
                  className={theme === option.key ? "active" : ""}
                  style={{ backgroundColor: option.color }}
                  onClick={() => setTheme(option.key)}
                  aria-label={option.label}
                  aria-pressed={theme === option.key}
                  title={option.label}
                />
              ))}
            </div>
          </div>
          <div className="account-row">
            <UserRound size={16} />
            <span>{currentUser?.username || "账户"}</span>
            {!currentUser?.org_id && (
              <button
                type="button"
                onClick={openApiKeyDialog}
                aria-label="管理 API 密钥"
                title="管理 API 密钥"
              >
                <KeyRound size={15} />
              </button>
            )}
            <button
              type="button"
              onClick={logout}
              aria-label="退出登录"
              title="退出登录"
            >
              <LogOut size={15} />
            </button>
          </div>
        </div>
      </aside>

      {sidebarOpen && (
        <button
          className="sidebar-scrim"
          onClick={() => setSidebarOpen(false)}
          aria-label="关闭任务栏"
        />
      )}

      <section
        className={`chat-pane ${mobileView === "preview" ? "mobile-hidden" : ""}`}
      >
        <header className="pane-header">
          <button
            className="icon-button mobile-only"
            onClick={() => setSidebarOpen(true)}
            aria-label="打开任务栏"
            title="打开任务栏"
          >
            <Menu size={19} />
          </button>
          <div className="header-title">
            <strong>
              {selectedJob ? jobTitle(selectedJob) : "新建演示文稿"}
            </strong>
            {selectedJob && (
              <span
                className={`status-label ${statusTone(selectedJob.status)}`}
              >
                {statusLabel(selectedJob.status, isRunning)}
              </span>
            )}
          </div>
          <div
            className="mobile-view-switch"
            role="tablist"
            aria-label="工作区视图"
          >
            <button
              className={mobileView === "chat" ? "active" : ""}
              onClick={() => setMobileView("chat")}
              aria-label="聊天"
              title="聊天"
            >
              <MessageSquare size={17} />
            </button>
            <button
              className={mobileView === "preview" ? "active" : ""}
              onClick={() => setMobileView("preview")}
              aria-label="预览"
              title="预览"
            >
              <PanelRight size={17} />
            </button>
          </div>
        </header>

        <div className="messages" aria-live="polite">
          {!selectedJob && (
            <div className="new-job-empty">
              <div className="empty-icon">
                <Presentation size={28} />
              </div>
              <h1>新建演示文稿</h1>
            </div>
          )}
          {selectedJob && (
            <>
              {messages.map((item) => (
                <div
                  className={`message-row ${
                    item.role === "user" ? "user-message" : "assistant-message"
                  }`}
                  key={item.id}
                >
                  {item.role === "user" ? (
                    <div className="message-bubble">{item.content}</div>
                  ) : (
                    <div className="message-bubble markdown-body">
                      <ReactMarkdown>{item.content}</ReactMarkdown>
                    </div>
                  )}
                </div>
              ))}
              {selectedJob.status === "failed" && (
                <div className="failure-status" role="alert">
                  <div className="failure-status-icon">
                    <AlertCircle size={20} />
                  </div>
                  <div className="failure-status-copy">
                    <strong>任务未完成</strong>
                    <span>
                      {selectedJob.error?.message || "执行过程中出现错误"}
                    </span>
                  </div>
                  <button
                    className="secondary-command"
                    onClick={retryJob}
                    disabled={busy}
                  >
                    {busy ? <LoaderCircle className="spin" size={16} /> : null}
                    <span>重新执行</span>
                  </button>
                </div>
              )}
              {isRunning && (
                <div className="run-status">
                  <div className="run-status-icon">
                    <LoaderCircle className="spin" size={20} />
                  </div>
                  <div className="run-status-copy">
                    <strong>{displayedActivityMessage}</strong>
                    <span>
                      {statusLabels[selectedJob.status]} ·{" "}
                      {formatElapsed(
                        runStartedEvent?.created_at || selectedJob.updated_at,
                        now,
                      )}
                    </span>
                  </div>
                </div>
              )}
              {visibleEvents.length > 0 && (
                <div className="event-timeline">
                  {visibleEvents.map((event) => (
                    <div className="event-row" key={event.id}>
                      {event.stage === "failed" ? (
                        <AlertCircle size={15} />
                      ) : event.stage === "succeeded" ? (
                        <CircleCheck size={15} />
                      ) : (
                        <CircleCheck size={15} />
                      )}
                      <span>{eventMessage(event)}</span>
                      <time>
                        {new Date(event.created_at).toLocaleTimeString(
                          "zh-CN",
                          {
                            hour: "2-digit",
                            minute: "2-digit",
                          },
                        )}
                      </time>
                    </div>
                  ))}
                </div>
              )}
              {referenceEvent && (
                <div className="reference-status">
                  <BookOpen size={16} />
                  <span>{referenceEvent.message}</span>
                </div>
              )}
            </>
          )}
          <div ref={messagesEndRef} />
        </div>

        <div className="composer-wrap">
          {error && (
            <div className="composer-error">
              <AlertCircle size={15} />
              <span>{error}</span>
              <button
                onClick={() => setError("")}
                aria-label="关闭错误"
                title="关闭"
              >
                <X size={14} />
              </button>
            </div>
          )}
          {files.length > 0 && (
            <div className="file-chips">
              {files.map(({ file, role }, index) => (
                <span className="file-chip" key={`${file.name}-${index}`}>
                  {role === "reference" ? (
                    <BookOpen size={14} />
                  ) : (
                    <FileText size={14} />
                  )}
                  <span className="file-name">{file.name}</span>
                  <select
                    className="file-role-select"
                    value={role}
                    onChange={(event) =>
                      setFileRole(index, event.target.value as AssetRole)
                    }
                    aria-label={`${file.name} 的用途`}
                    title="文件用途"
                  >
                    <option value="source">内容资料</option>
                    <option value="reference">参考案例</option>
                  </select>
                  <button
                    onClick={() =>
                      setFiles((current) =>
                        current.filter((_, itemIndex) => itemIndex !== index),
                      )
                    }
                    aria-label={`移除 ${file.name}`}
                    title="移除文件"
                  >
                    <X size={13} />
                  </button>
                </span>
              ))}
            </div>
          )}
          <div className="composer">
            <textarea
              value={message}
              onChange={(event) => setMessage(event.target.value)}
              onKeyDown={handleComposerKeyDown}
              placeholder={
                isRunning
                  ? `${statusLabel(selectedJob?.status ?? "queued", true)}，请稍候`
                  : selectedJob?.status === "awaiting_confirmation"
                    ? "写下修改意见"
                    : selectedJob?.status === "awaiting_asset"
                      ? "补充素材说明"
                      : selectedJob?.status === "succeeded"
                        ? "继续修改这份演示"
                        : "描述你要制作的演示"
              }
              rows={3}
              disabled={Boolean(isRunning)}
            />
            <div className="composer-actions">
              <div className="composer-tools">
                <input
                  ref={fileInputRef}
                  type="file"
                  multiple
                  onChange={addFiles}
                  hidden
                />
                <button
                  className="icon-button"
                  onClick={() => fileInputRef.current?.click()}
                  disabled={Boolean(isRunning)}
                  aria-label="添加文件"
                  title="添加文件"
                >
                  <Paperclip size={18} />
                </button>
                {isRunning && (
                  <button
                    className="icon-button danger-button"
                    onClick={cancelJob}
                    disabled={busy}
                    aria-label="取消任务"
                    title="取消任务"
                  >
                    <Square size={16} />
                  </button>
                )}
              </div>
              {selectedJob?.status === "awaiting_confirmation" ? (
                <div className="confirmation-actions">
                  <button
                    className="secondary-command"
                    onClick={sendMessage}
                    disabled={!canSend}
                  >
                    提出修改
                  </button>
                  <button
                    className="primary-command"
                    onClick={approveConfirmation}
                    disabled={busy}
                  >
                    <Check size={17} />
                    <span>确认方案</span>
                  </button>
                </div>
              ) : (
                <button
                  className="send-button"
                  onClick={sendMessage}
                  disabled={!canSend}
                  aria-label="发送"
                  title="发送"
                >
                  {busy ? (
                    <LoaderCircle className="spin" size={18} />
                  ) : (
                    <Send size={18} />
                  )}
                </button>
              )}
            </div>
          </div>
        </div>
      </section>

      <section
        ref={previewPaneRef}
        className={`preview-pane ${mobileView === "chat" ? "mobile-hidden-preview" : ""}`}
      >
        <header className="pane-header preview-header">
          <div>
            <strong>演示预览</strong>
            <span>
              {previewArtifacts.length > 0
                ? `${previewArtifacts.length} 页`
                : selectedJob
                  ? statusLabel(selectedJob.status, isRunning)
                  : "尚未开始"}
            </span>
          </div>
          <div className="preview-header-actions">
            <button
              className="icon-button fullscreen-button"
              disabled={!selectedPreviewId}
              onClick={() => void togglePreviewFullscreen()}
              aria-label={previewFullscreen ? "退出全屏" : "大屏预览"}
              title={previewFullscreen ? "退出全屏" : "大屏预览"}
            >
              {previewFullscreen ? (
                <Minimize2 size={18} />
              ) : (
                <Maximize2 size={18} />
              )}
            </button>
            <div
              className="mobile-view-switch"
              role="tablist"
              aria-label="工作区视图"
            >
              <button
                className={mobileView === "chat" ? "active" : ""}
                onClick={() => setMobileView("chat")}
                aria-label="聊天"
                title="聊天"
              >
                <MessageSquare size={17} />
              </button>
              <button
                className={mobileView === "preview" ? "active" : ""}
                onClick={() => setMobileView("preview")}
                aria-label="预览"
                title="预览"
              >
                <PanelRight size={17} />
              </button>
            </div>
            <div className="preview-nav">
              <button
                className="icon-button"
                disabled={selectedPreviewIndex <= 0}
                onClick={() =>
                  setSelectedPreviewId(
                    previewArtifacts[selectedPreviewIndex - 1]?.id || null,
                  )
                }
                aria-label="上一页"
                title="上一页"
              >
                <ChevronLeft size={18} />
              </button>
              <button
                className="icon-button"
                disabled={
                  selectedPreviewIndex < 0 ||
                  selectedPreviewIndex >= previewArtifacts.length - 1
                }
                onClick={() =>
                  setSelectedPreviewId(
                    previewArtifacts[selectedPreviewIndex + 1]?.id || null,
                  )
                }
                aria-label="下一页"
                title="下一页"
              >
                <ChevronRight size={18} />
              </button>
            </div>
          </div>
        </header>
        <div className="preview-content">
          <div className={`slide-stage ${selectedPreviewId ? "" : "empty"}`}>
            {selectedPreviewId && previewUrls[selectedPreviewId] ? (
              <img
                src={previewUrls[selectedPreviewId]}
                alt={`第 ${selectedPreviewIndex + 1} 页预览`}
              />
            ) : (
              <div className={`preview-empty ${isRunning ? "working" : ""}`}>
                <div className="preview-empty-mark">
                  {isRunning ? (
                    <LoaderCircle className="spin" size={24} />
                  ) : (
                    <Presentation size={24} />
                  )}
                </div>
                <strong>
                  {selectedJob
                    ? statusLabel(selectedJob.status, isRunning)
                    : "尚未生成"}
                </strong>
                <span>
                  {previewStatusMessage(
                    selectedJob,
                    isRunning,
                    displayedActivity,
                    previewArtifacts.length,
                  )}
                </span>
              </div>
            )}
          </div>
          {previewArtifacts.length > 0 && (
            <div className="thumbnail-grid">
              {previewArtifacts.map((artifact, index) => (
                <button
                  key={artifact.id}
                  className={
                    selectedPreviewId === artifact.id ? "selected" : ""
                  }
                  onClick={() => setSelectedPreviewId(artifact.id)}
                  aria-label={`查看第 ${index + 1} 页`}
                >
                  {previewUrls[artifact.id] ? (
                    <img src={previewUrls[artifact.id]} alt="" />
                  ) : (
                    <LoaderCircle className="spin" size={18} />
                  )}
                  <span>{index + 1}</span>
                </button>
              ))}
            </div>
          )}
          {downloadableArtifacts.length > 0 && (
            <div className="artifact-list">
              <div className="sidebar-label">导出文件</div>
              {downloadableArtifacts.map((artifact) => (
                <button
                  key={artifact.id}
                  onClick={() => downloadArtifact(artifact)}
                >
                  <FileText size={17} />
                  <span>
                    <strong>{artifact.filename}</strong>
                    <small>{formatBytes(artifact.size_bytes)}</small>
                  </span>
                  <Download size={17} />
                </button>
              ))}
            </div>
          )}
        </div>
      </section>

      {apiKeyDialogOpen && currentUser && !currentUser.org_id && (
        <div className="auth-overlay">
          <section className="auth-dialog api-key-dialog" aria-modal="true">
            <div className="dialog-heading">
              <div>
                <div className="auth-mark">
                  <KeyRound size={22} />
                </div>
                <h1>API 密钥</h1>
              </div>
              <button
                className="icon-button"
                type="button"
                onClick={() => setApiKeyDialogOpen(false)}
                aria-label="关闭"
                title="关闭"
              >
                <X size={18} />
              </button>
            </div>
            <form className="api-key-create" onSubmit={createUserApiKey}>
              <label htmlFor="api-key-name">密钥名称</label>
              <div>
                <input
                  id="api-key-name"
                  value={apiKeyName}
                  maxLength={100}
                  onChange={(event) => setApiKeyName(event.target.value)}
                />
                <button
                  className="primary-command"
                  type="submit"
                  disabled={apiKeyBusy || !apiKeyName.trim()}
                >
                  <Plus size={17} />
                  创建
                </button>
              </div>
            </form>
            {createdApiKey && (
              <div className="created-api-key">
                <span>请立即保存，此密钥只显示一次</span>
                <div>
                  <code>{createdApiKey.key}</code>
                  <button
                    className="icon-button"
                    type="button"
                    onClick={() =>
                      navigator.clipboard.writeText(createdApiKey.key)
                    }
                    aria-label="复制密钥"
                    title="复制密钥"
                  >
                    <Copy size={16} />
                  </button>
                </div>
              </div>
            )}
            {apiKeyError && (
              <div className="auth-error">
                <AlertCircle size={15} />
                {apiKeyError}
              </div>
            )}
            <div className="api-key-list">
              {apiKeyBusy && apiKeys.length === 0 && (
                <LoaderCircle className="spin" size={20} />
              )}
              {apiKeys.map((key) => (
                <div key={key.id}>
                  <span>
                    <strong>{key.name}</strong>
                    <small>
                      {key.key_prefix}… · {key.revoked_at ? "已撤销" : "有效"}
                    </small>
                  </span>
                  {!key.revoked_at && (
                    <button
                      className="icon-button"
                      type="button"
                      onClick={() => revokeUserApiKey(key.id)}
                      disabled={apiKeyBusy}
                      aria-label={`撤销 ${key.name}`}
                      title="撤销密钥"
                    >
                      <Trash2 size={16} />
                    </button>
                  )}
                </div>
              ))}
              {!apiKeyBusy && apiKeys.length === 0 && <p>尚未创建 API 密钥</p>}
            </div>
          </section>
        </div>
      )}

      {authChecking && (
        <div className="auth-overlay">
          <LoaderCircle className="spin" size={26} />
        </div>
      )}

      {!authChecking && !currentUser && (
        <div className="auth-overlay">
          <form className="auth-dialog" onSubmit={unlock}>
            <div className="auth-mark">
              <Presentation size={22} />
            </div>
            <h1>PPT Master</h1>
            <label htmlFor="username">用户名</label>
            <input
              id="username"
              value={usernameDraft}
              onChange={(event) => setUsernameDraft(event.target.value)}
              autoFocus
              autoComplete="username"
            />
            <label htmlFor="password">密码</label>
            <input
              id="password"
              type="password"
              value={passwordDraft}
              onChange={(event) => setPasswordDraft(event.target.value)}
              autoComplete="current-password"
            />
            {authError && (
              <div className="auth-error">
                <AlertCircle size={15} />
                {authError}
              </div>
            )}
            <button
              className="primary-command auth-submit"
              type="submit"
              disabled={busy || !usernameDraft.trim() || !passwordDraft}
            >
              {busy ? (
                <LoaderCircle className="spin" size={18} />
              ) : (
                <LogIn size={18} />
              )}
              <span>登录</span>
            </button>
          </form>
        </div>
      )}
    </div>
  );
}
