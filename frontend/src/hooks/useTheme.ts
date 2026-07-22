import { useCallback, useEffect, useState } from "react";

import { type AppTheme, themeOptions } from "../types";

const THEME_STORAGE = "ppt-master-theme";

function readInitialTheme(): AppTheme {
  const saved = localStorage.getItem(THEME_STORAGE) as AppTheme | null;
  return saved && themeOptions.some((option) => option.key === saved)
    ? saved
    : "mint";
}

/**
 * Owns the active color theme, persists it to localStorage, and mirrors it onto
 * the document root so every route (login / workspace / admin) stays in sync.
 */
export function useTheme() {
  const [theme, setTheme] = useState<AppTheme>(readInitialTheme);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem(THEME_STORAGE, theme);
  }, [theme]);

  const cycleTheme = useCallback((next: AppTheme) => setTheme(next), []);

  return { theme, setTheme: cycleTheme };
}
