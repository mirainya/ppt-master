import { Component, type ErrorInfo, type ReactNode } from "react";
import { RotateCcw } from "lucide-react";

interface ErrorBoundaryProps {
  children: ReactNode;
}

interface ErrorBoundaryState {
  error: Error | null;
}

/** Last-resort guard so a render-time crash shows a recovery card, not a blank page. */
export class ErrorBoundary extends Component<
  ErrorBoundaryProps,
  ErrorBoundaryState
> {
  state: ErrorBoundaryState = { error: null };

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("界面渲染出错：", error, info.componentStack);
  }

  render() {
    if (this.state.error) {
      return (
        <div className="crash-screen" role="alert">
          <div className="crash-card">
            <h1>界面出错了</h1>
            <p>页面遇到了预期外的问题，刷新通常可以恢复。</p>
            <button
              type="button"
              className="primary-command"
              onClick={() => window.location.reload()}
            >
              <RotateCcw size={17} />
              <span>刷新页面</span>
            </button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}
