import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

type Theme = "light" | "dark";

interface ThemeContextValue {
  theme: Theme;
  toggle: () => void;
}

const ThemeContext = createContext<ThemeContextValue | null>(null);

const STORAGE_KEY = "cbr-theme";

/** URL 查询参数 ?theme=light|dark 优先（验收/截图/分享场景），其次 localStorage/首屏内联脚本。 */
function forcedTheme(): Theme | null {
  if (typeof window === "undefined") return null;
  try {
    const value = new URLSearchParams(window.location.search).get("theme");
    return value === "dark" || value === "light" ? value : null;
  } catch {
    return null;
  }
}

function readInitialTheme(): Theme {
  if (typeof document === "undefined") return "light";
  const forced = forcedTheme();
  if (forced) return forced;
  return document.documentElement.classList.contains("dark") ? "dark" : "light";
}

/**
 * 双主题 Provider：默认 light，切换结果写入 localStorage。
 * 首屏由 index.html 的内联脚本预置 .dark，避免刷新闪烁；URL ?theme= 可强制覆盖且不写回偏好。
 */
export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setTheme] = useState<Theme>(readInitialTheme);

  useEffect(() => {
    const root = document.documentElement;
    root.classList.toggle("dark", theme === "dark");
    root.style.background = "var(--surface-0)";
    root.dataset.theme = theme;
    if (forcedTheme()) return; // 验收/分享场景不污染用户偏好
    try {
      window.localStorage.setItem(STORAGE_KEY, theme);
    } catch {
      // localStorage 不可用（隐私模式）时静默降级，仅影响持久化
    }
  }, [theme]);

  const toggle = useCallback(() => {
    setTheme((previous) => (previous === "dark" ? "light" : "dark"));
  }, []);

  const value = useMemo(() => ({ theme, toggle }), [theme, toggle]);

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme(): ThemeContextValue {
  const context = useContext(ThemeContext);
  if (!context) throw new Error("useTheme 必须在 ThemeProvider 内使用");
  return context;
}
