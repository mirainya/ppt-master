import { useCallback, useRef, useState } from "react";

import { ApiKeyDialog } from "../components/ApiKeyDialog";
import { ChatPanel } from "../components/ChatPanel";
import { Composer } from "../components/Composer";
import type { MobileView } from "../components/MobileViewSwitch";
import { PreviewPane } from "../components/PreviewPane";
import { WorkspaceSidebar } from "../components/WorkspaceSidebar";
import { useApiKeys } from "../hooks/useApiKeys";
import { useAuth } from "../hooks/authContext";
import { usePreview } from "../hooks/usePreview";
import { useWorkspace } from "../hooks/useWorkspace";
import { useAutoScroll } from "../hooks/useAutoScroll";
import type { AppTheme, Artifact } from "../types";

interface WorkspacePageProps {
  theme: AppTheme;
  onTheme: (theme: AppTheme) => void;
}

/** The signed-in user workspace: chat, live preview, and personal API keys. */
export function WorkspacePage({ theme, onTheme }: WorkspacePageProps) {
  const { user, apiClient, logout } = useAuth();
  const client = user ? apiClient : null;
  const ws = useWorkspace(client);
  const apiKeys = useApiKeys(apiClient);

  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [mobileView, setMobileView] = useState<MobileView>("chat");
  const previewPaneRef = useRef<HTMLElement>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const preview = usePreview(
    client,
    ws.selectedId,
    ws.previewArtifacts,
    previewPaneRef,
    ws.setError,
  );
  useAutoScroll(messagesEndRef, [ws.events, ws.messages]);

  const { selectedJob, refreshJob, bump, setBusy, setError } = ws;

  function startNewJob() {
    ws.setSelectedId(null);
    ws.setMessage("");
    ws.setFiles(() => []);
    setSidebarOpen(false);
    setMobileView("chat");
  }

  function selectJob(jobId: string) {
    ws.setSelectedId(jobId);
    ws.setMessage("");
    ws.setFiles(() => []);
    setSidebarOpen(false);
  }

  async function sendMessage() {
    if (!client || ws.busy) return;
    const trimmed = ws.message.trim();
    if (!trimmed) return;
    setBusy(true);
    setError("");
    try {
      if (!selectedJob || selectedJob.status === "cancelled") {
        const job = await client.createJob(trimmed, ws.files);
        ws.setJobs((current) => [job, ...current]);
        ws.setSelectedId(job.id);
      } else if (selectedJob.status === "awaiting_confirmation") {
        await client.submitConfirmation(selectedJob.id, false, trimmed);
        await refreshJob(selectedJob.id);
        bump();
      } else if (
        ["awaiting_asset", "succeeded", "failed"].includes(selectedJob.status)
      ) {
        if (ws.files.length > 0)
          await client.uploadAssets(selectedJob.id, ws.files);
        await client.resumeJob(selectedJob.id, trimmed);
        await refreshJob(selectedJob.id);
        bump();
      }
      ws.setMessage("");
      ws.setFiles(() => []);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "操作失败");
    } finally {
      setBusy(false);
    }
  }

  async function approveConfirmation() {
    if (!client || !selectedJob || ws.busy) return;
    setBusy(true);
    setError("");
    try {
      await client.submitConfirmation(selectedJob.id, true, ws.message.trim());
      ws.setMessage("");
      await refreshJob(selectedJob.id);
      bump();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "确认失败");
    } finally {
      setBusy(false);
    }
  }

  async function cancelJob() {
    if (!client || !selectedJob || ws.busy) return;
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
    if (!client || !selectedJob || ws.busy) return;
    setBusy(true);
    setError("");
    try {
      await client.resumeJob(selectedJob.id, "继续执行当前任务");
      await refreshJob(selectedJob.id);
      bump();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "重新执行失败");
    } finally {
      setBusy(false);
    }
  }

  const downloadArtifact = useCallback(
    async (artifact: Artifact) => {
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
    },
    [client, selectedJob, setError],
  );

  return (
    <div className="app-shell">
      <WorkspaceSidebar
        open={sidebarOpen}
        onClose={() => setSidebarOpen(false)}
        jobs={ws.jobs}
        selectedId={ws.selectedId}
        onSelect={selectJob}
        onNewJob={startNewJob}
        user={user}
        theme={theme}
        onTheme={onTheme}
        onOpenApiKeys={apiKeys.openDialog}
        onLogout={() => void logout()}
      />

      {sidebarOpen && (
        <button
          className="sidebar-scrim"
          onClick={() => setSidebarOpen(false)}
          aria-label="关闭任务栏"
        />
      )}

      <ChatPanel
        hidden={mobileView === "preview"}
        selectedJob={selectedJob}
        isRunning={ws.isRunning}
        messages={ws.messages}
        timelineEvents={ws.timelineEvents}
        latestEvent={ws.latestEvent}
        latestPageEvent={ws.latestPageEvent ?? null}
        runStartedEvent={ws.runStartedEvent ?? null}
        referenceEvent={ws.referenceEvent ?? null}
        previewCount={ws.previewArtifacts.length}
        now={ws.now}
        busy={ws.busy}
        onRetry={retryJob}
        mobileView={mobileView}
        onMobileView={setMobileView}
        onOpenSidebar={() => setSidebarOpen(true)}
        messagesEndRef={messagesEndRef}
      >
        <Composer
          message={ws.message}
          onMessage={ws.setMessage}
          files={ws.files}
          onFiles={ws.setFiles}
          selectedJob={selectedJob}
          isRunning={ws.isRunning}
          busy={ws.busy}
          error={ws.error}
          onClearError={() => setError("")}
          onSend={sendMessage}
          onApprove={approveConfirmation}
          onCancel={cancelJob}
        />
      </ChatPanel>

      <PreviewPane
        hidden={mobileView === "chat"}
        paneRef={previewPaneRef}
        selectedJob={selectedJob}
        isRunning={ws.isRunning}
        previewArtifacts={ws.previewArtifacts}
        downloadableArtifacts={ws.downloadableArtifacts}
        previewUrls={preview.previewUrls}
        selectedPreviewId={preview.selectedPreviewId}
        selectedIndex={preview.selectedIndex}
        onSelectPreview={preview.setSelectedPreviewId}
        onGoTo={preview.goTo}
        fullscreen={preview.fullscreen}
        onToggleFullscreen={() => void preview.toggleFullscreen()}
        onDownload={downloadArtifact}
        latestActivity={
          selectedJob?.status === "executing" && ws.latestPageEvent
            ? ws.latestPageEvent
            : ws.latestEvent
        }
        mobileView={mobileView}
        onMobileView={setMobileView}
      />

      {apiKeys.open && (
        <ApiKeyDialog
          keys={apiKeys.keys}
          name={apiKeys.name}
          onName={apiKeys.setName}
          created={apiKeys.created}
          busy={apiKeys.busy}
          error={apiKeys.error}
          onCreate={apiKeys.create}
          onRevoke={apiKeys.revoke}
          onClose={apiKeys.closeDialog}
        />
      )}
    </div>
  );
}
