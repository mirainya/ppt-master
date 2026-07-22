import { MessageSquare, PanelRight } from "lucide-react";

export type MobileView = "chat" | "preview";

interface MobileViewSwitchProps {
  view: MobileView;
  onChange: (view: MobileView) => void;
}

/** Chat / preview toggle for narrow screens — was duplicated verbatim before. */
export function MobileViewSwitch({ view, onChange }: MobileViewSwitchProps) {
  return (
    <div className="mobile-view-switch" role="tablist" aria-label="工作区视图">
      <button
        className={view === "chat" ? "active" : ""}
        onClick={() => onChange("chat")}
        aria-label="聊天"
        title="聊天"
      >
        <MessageSquare size={17} />
      </button>
      <button
        className={view === "preview" ? "active" : ""}
        onClick={() => onChange("preview")}
        aria-label="预览"
        title="预览"
      >
        <PanelRight size={17} />
      </button>
    </div>
  );
}
