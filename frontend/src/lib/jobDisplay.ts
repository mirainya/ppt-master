import type { JobStatus } from "../types";

export const statusLabels: Record<JobStatus, string> = {
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

export const eventMessageLabels: Record<string, string> = {
  "Task accepted": "任务已接收",
  "Analyzing source material": "正在分析需求与素材",
  "Response received": "已收到方案反馈",
  "Collecting outputs": "正在整理导出文件",
  "Task cancelled": "任务已取消",
  "Task execution failed": "任务执行失败",
};

export function statusTone(status: JobStatus): string {
  if (status === "succeeded") return "success";
  if (status === "failed" || status === "cancelled") return "danger";
  if (status === "awaiting_confirmation" || status === "awaiting_asset")
    return "waiting";
  return "active";
}

export function statusLabel(status: JobStatus, running: boolean): string {
  return running ? "处理中" : statusLabels[status];
}

export function formatBytes(value: number): string {
  if (value < 1024 * 1024) return `${Math.max(1, Math.round(value / 1024))} KB`;
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
}

export function formatDate(value: string): string {
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date(value));
}

export function formatElapsed(createdAt: string, now: number): string {
  const seconds = Math.max(0, Math.floor((now - Date.parse(createdAt)) / 1000));
  if (seconds < 60) return `已运行 ${seconds} 秒`;
  const minutes = Math.floor(seconds / 60);
  const remainingSeconds = seconds % 60;
  return `已运行 ${minutes} 分 ${remainingSeconds} 秒`;
}

export function jobTitle(job: {
  title: string | null;
  prompt: string;
}): string {
  return job.title?.trim() || job.prompt.trim().slice(0, 28) || "未命名演示";
}
