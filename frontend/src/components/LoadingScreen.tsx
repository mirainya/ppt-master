import { LoaderCircle, Presentation } from "lucide-react";

/** Full-screen splash shown while the initial session probe is still running. */
export function LoadingScreen() {
  return (
    <div className="boot-screen">
      <div className="boot-mark">
        <Presentation size={26} />
      </div>
      <LoaderCircle className="spin" size={22} />
      <span>正在连接工作台…</span>
    </div>
  );
}
