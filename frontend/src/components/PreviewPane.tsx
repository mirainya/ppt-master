import { type RefObject } from "react";
import {
  ChevronLeft,
  ChevronRight,
  Download,
  FileText,
  LoaderCircle,
  Maximize2,
  Minimize2,
  Presentation,
} from "lucide-react";

import { MobileViewSwitch, type MobileView } from "./MobileViewSwitch";
import { formatBytes, statusLabel } from "../lib/jobDisplay";
import type { Artifact, Job, JobEvent } from "../types";

function previewStatusMessage(
  job: Job | null,
  running: boolean,
  latestEvent: JobEvent | null,
  previewCount: number,
): string {
  if (!job) return "等待新任务";
  if (job.status === "executing" && previewCount > 0)
    return `已完成 ${previewCount} 页`;
  if (running) return latestEvent?.message ?? "正在准备任务";
  if (job.status === "awaiting_confirmation") return "方案已就绪，等待确认";
  if (job.status === "awaiting_asset") return "等待补充素材";
  if (job.status === "failed") return "任务未完成";
  if (job.status === "cancelled") return "任务已取消";
  if (job.status === "succeeded") return "生成完成，可下载导出文件";
  return "等待页面产出";
}

interface PreviewPaneProps {
  hidden: boolean;
  paneRef: RefObject<HTMLElement | null>;
  selectedJob: Job | null;
  isRunning: boolean;
  previewArtifacts: Artifact[];
  downloadableArtifacts: Artifact[];
  previewUrls: Record<string, string>;
  selectedPreviewId: string | null;
  selectedIndex: number;
  onSelectPreview: (id: string) => void;
  onGoTo: (index: number) => void;
  fullscreen: boolean;
  onToggleFullscreen: () => void;
  onDownload: (artifact: Artifact) => void;
  latestActivity: JobEvent | null;
  mobileView: MobileView;
  onMobileView: (view: MobileView) => void;
}

/** Right column: current slide, thumbnail strip, fullscreen, export downloads. */
export function PreviewPane({
  hidden,
  paneRef,
  selectedJob,
  isRunning,
  previewArtifacts,
  downloadableArtifacts,
  previewUrls,
  selectedPreviewId,
  selectedIndex,
  onSelectPreview,
  onGoTo,
  fullscreen,
  onToggleFullscreen,
  onDownload,
  latestActivity,
  mobileView,
  onMobileView,
}: PreviewPaneProps) {
  return (
    <section
      ref={paneRef}
      className={`preview-pane ${hidden ? "mobile-hidden-preview" : ""}`}
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
            onClick={onToggleFullscreen}
            aria-label={fullscreen ? "退出全屏" : "大屏预览"}
            title={fullscreen ? "退出全屏" : "大屏预览"}
          >
            {fullscreen ? <Minimize2 size={18} /> : <Maximize2 size={18} />}
          </button>
          <MobileViewSwitch view={mobileView} onChange={onMobileView} />
          <div className="preview-nav">
            <button
              className="icon-button"
              disabled={selectedIndex <= 0}
              onClick={() => onGoTo(selectedIndex - 1)}
              aria-label="上一页"
              title="上一页"
            >
              <ChevronLeft size={18} />
            </button>
            <button
              className="icon-button"
              disabled={
                selectedIndex < 0 ||
                selectedIndex >= previewArtifacts.length - 1
              }
              onClick={() => onGoTo(selectedIndex + 1)}
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
              alt={`第 ${selectedIndex + 1} 页预览`}
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
                  latestActivity,
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
                className={selectedPreviewId === artifact.id ? "selected" : ""}
                onClick={() => onSelectPreview(artifact.id)}
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
              <button key={artifact.id} onClick={() => onDownload(artifact)}>
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
  );
}
