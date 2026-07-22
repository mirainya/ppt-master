import { type ChangeEvent, type KeyboardEvent, useRef } from "react";
import {
  AlertCircle,
  BookOpen,
  Check,
  FileText,
  LoaderCircle,
  Paperclip,
  Send,
  Square,
  X,
} from "lucide-react";

import { statusLabel } from "../lib/jobDisplay";
import type { AssetRole, Job, PendingFile } from "../types";

interface ComposerProps {
  message: string;
  onMessage: (value: string) => void;
  files: PendingFile[];
  onFiles: (updater: (current: PendingFile[]) => PendingFile[]) => void;
  selectedJob: Job | null;
  isRunning: boolean;
  busy: boolean;
  error: string;
  onClearError: () => void;
  onSend: () => void;
  onApprove: () => void;
  onCancel: () => void;
}

/** Message input, attachment chips, and the send / confirm action cluster. */
export function Composer({
  message,
  onMessage,
  files,
  onFiles,
  selectedJob,
  isRunning,
  busy,
  error,
  onClearError,
  onSend,
  onApprove,
  onCancel,
}: ComposerProps) {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const canSend = message.trim().length > 0 && !busy && !isRunning;

  function addFiles(event: ChangeEvent<HTMLInputElement>) {
    const incoming = Array.from(event.target.files || []);
    onFiles((current) =>
      [
        ...current,
        ...incoming.map((file) => ({ file, role: "source" as AssetRole })),
      ].slice(0, 20),
    );
    event.target.value = "";
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      onSend();
    }
  }

  const placeholder = isRunning
    ? `${statusLabel(selectedJob?.status ?? "queued", true)}，请稍候`
    : selectedJob?.status === "awaiting_confirmation"
      ? "写下修改意见"
      : selectedJob?.status === "awaiting_asset"
        ? "补充素材说明"
        : selectedJob?.status === "succeeded"
          ? "继续修改这份演示"
          : "描述你要制作的演示";

  return (
    <div className="composer-wrap">
      {error && (
        <div className="composer-error">
          <AlertCircle size={15} />
          <span>{error}</span>
          <button onClick={onClearError} aria-label="关闭错误" title="关闭">
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
                  onFiles((current) =>
                    current.map((item, itemIndex) =>
                      itemIndex === index
                        ? { ...item, role: event.target.value as AssetRole }
                        : item,
                    ),
                  )
                }
                aria-label={`${file.name} 的用途`}
                title="文件用途"
              >
                <option value="source">内容资料</option>
                <option value="reference">参考案例</option>
              </select>
              <button
                onClick={() =>
                  onFiles((current) =>
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
          onChange={(event) => onMessage(event.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={placeholder}
          aria-label="演示需求输入"
          rows={3}
          disabled={isRunning}
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
              disabled={isRunning}
              aria-label="添加文件"
              title="添加文件"
            >
              <Paperclip size={18} />
            </button>
            {isRunning && (
              <button
                className="icon-button danger-button"
                onClick={onCancel}
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
                onClick={onSend}
                disabled={!canSend}
              >
                提出修改
              </button>
              <button
                className="primary-command"
                onClick={onApprove}
                disabled={busy}
              >
                <Check size={17} />
                <span>确认方案</span>
              </button>
            </div>
          ) : (
            <button
              className="send-button"
              onClick={onSend}
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
  );
}
