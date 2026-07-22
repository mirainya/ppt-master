import { type DependencyList, type RefObject, useEffect } from "react";

/** Smoothly scrolls the referenced sentinel into view whenever deps change. */
export function useAutoScroll(
  ref: RefObject<HTMLElement | null>,
  deps: DependencyList,
) {
  useEffect(() => {
    ref.current?.scrollIntoView({ behavior: "smooth", block: "end" });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
}
