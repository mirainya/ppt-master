import { Palette } from "lucide-react";

import { type AppTheme, themeOptions } from "../types";

interface ThemeSwitcherProps {
  theme: AppTheme;
  onChange: (theme: AppTheme) => void;
  showIcon?: boolean;
}

/** Four-swatch color-theme picker, shared by the login page, workspace and admin. */
export function ThemeSwitcher({
  theme,
  onChange,
  showIcon = true,
}: ThemeSwitcherProps) {
  return (
    <div className="theme-row">
      {showIcon && <Palette size={16} />}
      <div className="theme-swatches" role="group" aria-label="界面主题">
        {themeOptions.map((option) => (
          <button
            key={option.key}
            type="button"
            className={theme === option.key ? "active" : ""}
            style={{ backgroundColor: option.color }}
            onClick={() => onChange(option.key)}
            aria-label={option.label}
            aria-pressed={theme === option.key}
            title={option.label}
          />
        ))}
      </div>
    </div>
  );
}
