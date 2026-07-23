import { type DependencyList, type RefObject, useEffect, useRef } from "react";

/**
 * Scrolls the referenced sentinel into view when deps change, but only when the
 * user is already near the bottom of the scroll container. If the user has
 * scrolled up to read history, auto-scroll is suppressed so the view stays put.
 */
export function useAutoScroll(
  ref: RefObject<HTMLElement | null>,
  deps: DependencyList,
) {
  // Whether the user is currently pinned near the bottom.
  const stickToBottom = useRef(true);

  // Track the user's scroll position on the sentinel's scroll container.
  useEffect(() => {
    const sentinel = ref.current;
    const container = sentinel?.parentElement;
    if (!container) return;

    const THRESHOLD = 80; // px from bottom still counts as "at bottom"
    const onScroll = () => {
      const distance =
        container.scrollHeight - container.scrollTop - container.clientHeight;
      stickToBottom.current = distance <= THRESHOLD;
    };

    onScroll(); // initialize
    container.addEventListener("scroll", onScroll, { passive: true });
    return () => container.removeEventListener("scroll", onScroll);
  }, [ref]);

  useEffect(() => {
    if (!stickToBottom.current) return;
    ref.current?.scrollIntoView({ behavior: "smooth", block: "end" });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
}
