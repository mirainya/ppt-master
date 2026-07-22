import { type RefObject } from "react";
import {
  AlertCircle,
  BookOpen,
  CircleCheck,
  LoaderCircle,
  Menu,
} from "lucide-react";
import ReactMarkdown from "react-markdown";

import { MobileViewSwitch, type MobileView } from "./MobileViewSwitch";
import {
  eventMessageLabels,
  formatElapsed,
  jobTitle,
  statusLabel,
  statusLabels,
  statusTone,
} from "../lib/jobDisplay";
import type { Job, JobEvent, JobMessage } from "../types";

function eventMessage(event: JobEvent | null): string {
  if (!event) return "正在准备任务";
  return eventMessageLabels[event.message] || event.message;
}

interface ChatPanelProps {
  hidden: boolean;
  selectedJob: Job | null;
  isRunning: boolean;
  messages: JobMessage[];
  timelineEvents: JobEvent[];
  latestEvent: JobEvent | null;
  latestPageEvent: JobEvent | null;
  runStartedEvent: JobEvent | null;
  referenceEvent: JobEvent | null;
  previewCount: number;
  now: number;
  busy: boolean;
  onRetry: () => void;
  mobileView: MobileView;
  onMobileView: (view: MobileView) => void;
  onOpenSidebar: () => void;
  messagesEndRef: RefObject<HTMLDivElement | null>;
  children: React.ReactNode;
}

/** Center column: header, message stream, live status, event timeline, composer. */
export function ChatPanel({
  hidden,
  selectedJob,
  isRunning,
  messages,
  timelineEvents,
  latestEvent,
  latestPageEvent,
  runStartedEvent,
  referenceEvent,
  previewCount,
  now,
  busy,
  onRetry,
  mobileView,
  onMobileView,
  onOpenSidebar,
  messagesEndRef,
  children,
}: ChatPanelProps) {
  const displayedActivity =
    selectedJob?.status === "executing" && latestPageEvent
      ? latestPageEvent
      : latestEvent;
  const displayedActivityMessage =
    selectedJob?.status === "executing" && previewCount > 0
      ? `正在生成页面，已完成 ${previewCount} 页`
      : eventMessage(displayedActivity);
  const visibleEvents = (
    isRunning ? timelineEvents.slice(0, -1) : timelineEvents
  ).slice(-6);

  return (
    <section className={`chat-pane ${hidden ? "mobile-hidden" : ""}`}>
      <header className="pane-header">
        <button
          className="icon-button mobile-only"
          onClick={onOpenSidebar}
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
            <span className={`status-label ${statusTone(selectedJob.status)}`}>
              {statusLabel(selectedJob.status, isRunning)}
            </span>
          )}
        </div>
        <MobileViewSwitch view={mobileView} onChange={onMobileView} />
      </header>

      <div className="messages" aria-live="polite">
        {!selectedJob && (
          <div className="new-job-empty">
            <div className="empty-icon">
              <CircleCheck size={28} />
            </div>
            <h1>新建演示文稿</h1>
            <p>描述主题或上传资料，AI 会先给出方案，确认后开始生成。</p>
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
                  onClick={onRetry}
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
                    ) : (
                      <CircleCheck size={15} />
                    )}
                    <span>{eventMessage(event)}</span>
                    <time>
                      {new Date(event.created_at).toLocaleTimeString("zh-CN", {
                        hour: "2-digit",
                        minute: "2-digit",
                      })}
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

      {children}
    </section>
  );
}
