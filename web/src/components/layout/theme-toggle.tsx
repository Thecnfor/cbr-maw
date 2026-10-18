import { Moon, Sun } from "lucide-react";

import { IconButton } from "@/components/common/icon-button";
import { useTheme } from "@/lib/theme";

export function ThemeToggle({ className }: { className?: string }) {
  const { theme, toggle } = useTheme();
  const isDark = theme === "dark";
  const label = isDark ? "切换为浅色主题" : "切换为深色主题";
  return (
    <IconButton
      label={label}
      onClick={toggle}
      variant="ghost"
      size="icon-sm"
      className={className}
    >
      {isDark ? <Sun aria-hidden="true" /> : <Moon aria-hidden="true" />}
    </IconButton>
  );
}
