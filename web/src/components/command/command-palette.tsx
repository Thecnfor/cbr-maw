import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
  type ReactNode,
} from "react";
import type { LucideIcon } from "lucide-react";
import {
  BookOpen,
  Copy,
  Download,
  LayoutDashboard,
  Layers,
  MessageSquare,
  Moon,
  RefreshCw,
  Search,
  SearchX,
  SlidersHorizontal,
  Sparkles,
  Sun,
} from "lucide-react";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { copyText } from "@/lib/clipboard";
import { decisionKey, getCachedDecision, useCachedDecision } from "@/lib/decision";
import { briefingFileSlug, buildMarkdownBriefing, downloadText } from "@/lib/export";
import { loadTrace } from "@/lib/api";
import { fmtDate } from "@/lib/format";
import { MODE_META, MODE_OPTIONS, riskMeta } from "@/lib/labels";
import { navigate, paramsToRecord, useRoute } from "@/lib/router";
import { requestRefresh } from "@/lib/refresh-bus";
import { useRun } from "@/lib/run-context";
import { useTheme } from "@/lib/theme";
import { useToast } from "@/lib/toast";
import { queuePrompt } from "@/lib/ai-actions";
import type { TraceEvent } from "@/lib/types";
import { cn } from "@/lib/utils";

const GROUP_ORDER = ["导航", "场景", "模式", "操作", "AI 快捷问"] as const;
type GroupName = (typeof GROUP_ORDER)[number];

interface CommandItem {
  id: string;
  group: GroupName;
  label: string;
  hint?: string;
  keywords?: string;
  icon: LucideIcon;
  run: () => void;
}

function Kbd({ children }: { children: ReactNode }) {
  return (
    <kbd className="rounded border border-border bg-surface-2 px-1 py-0.5 font-mono text-tiny text-muted-foreground">
      {children}
    </kbd>
  );
}

/**
 * ⌘K / Ctrl+K 命令面板：Radix Dialog + 自写列表（不引入 cmdk 等新依赖）。
 * 支持 URL `?cmd=1` 自动打开（截图验收），关闭时移除该参数以免刷新重复弹出。
 */
export function CommandPalette({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const run = useRun();
  const route = useRoute();
  const { theme, toggle: toggleTheme } = useTheme();
  const { toast } = useToast();
  const [query, setQuery] = useState("");
  const [activeIndex, setActiveIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const consumedUrlRef = useRef(false);

  const currentDecision = useCachedDecision({
    asOf: run.asOf,
    scenario: run.scenarioId,
    mode: run.mode,
  });
  const regulatorLevel = currentDecision?.cards?.regulator?.risk_level;
  const regulatorLabel = regulatorLevel ? riskMeta(regulatorLevel).label : null;

  useEffect(() => {
    if (consumedUrlRef.current) return;
    consumedUrlRef.current = true;
    try {
      const url = new URL(window.location.href);
      if (url.searchParams.get("cmd") !== "1") return;
      url.searchParams.delete("cmd");
      window.history.replaceState(null, "", `${url.pathname}${url.search}${url.hash}`);
      onOpenChange(true);
    } catch {
      // 忽略 URL 解析失败
    }
  }, [onOpenChange]);

  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && !event.altKey && event.key.toLowerCase() === "k") {
        event.preventDefault();
        onOpenChange(!open);
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [open, onOpenChange]);

  useEffect(() => {
    if (open) {
      setQuery("");
      setActiveIndex(0);
    }
  }, [open]);

  const items = useMemo<CommandItem[]>(() => {
    const contextParams = () => {
      const params = paramsToRecord(route.params);
      params.as_of = run.asOf;
      if (run.scenarioId) params.scenario = run.scenarioId;
      params.mode = run.mode;
      return params;
    };
    const go = (path: string) => {
      navigate(path, contextParams());
    };
    const ask = (prompt: string) => {
      queuePrompt(prompt, "command-palette");
      const params = contextParams();
      delete params.tab;
      navigate("/chat", params);
    };

    const list: CommandItem[] = [
      {
        id: "nav-dashboard",
        group: "导航",
        label: "打开驾驶台",
        hint: "风险信号 / 证据 / 协同过程",
        keywords: "dashboard 驾驶台 首页",
        icon: LayoutDashboard,
        run: () => go("/dashboard"),
      },
      {
        id: "nav-chat",
        group: "导航",
        label: "打开对话",
        hint: "追问共享信号与分歧",
        keywords: "chat 对话 追问",
        icon: MessageSquare,
        run: () => go("/chat"),
      },
    ];

    for (const scenario of run.scenarios) {
      list.push({
        id: `scenario-${scenario.scenario_id}`,
        group: "场景",
        label: `切换到场景：${scenario.name}`,
        hint: `${fmtDate(scenario.as_of)} · ${scenario.scenario_id}`,
        keywords: `${scenario.scenario_id} ${scenario.description ?? ""} ${(scenario.tags ?? []).join(" ")}`,
        icon: Layers,
        run: () => run.setScenarioId(scenario.scenario_id),
      });
    }

    for (const mode of MODE_OPTIONS) {
      list.push({
        id: `mode-${mode}`,
        group: "模式",
        label: `切换为${MODE_META[mode].label}`,
        hint: mode === "collaborative" ? "三主体共享黑板并协调" : mode === "independent" ? "三主体独立推理" : "仅单智能体",
        keywords: `mode ${mode} 模式`,
        icon: SlidersHorizontal,
        run: () => run.setMode(mode),
      });
    }

    list.push(
      {
        id: "action-refresh",
        group: "操作",
        label: "重新生成决策卡",
        hint: "走流式接口；约 12–18 秒",
        keywords: "refresh regenerate 重新生成 刷新",
        icon: RefreshCw,
        run: () => {
          go("/dashboard");
          requestRefresh();
        },
      },
      {
        id: "action-theme",
        group: "操作",
        label: theme === "dark" ? "切换为浅色主题" : "切换为深色主题",
        hint: `当前：${theme === "dark" ? "深色" : "浅色"}`,
        keywords: "theme dark light 主题 夜间",
        icon: theme === "dark" ? Sun : Moon,
        run: () => toggleTheme(),
      },
      {
        id: "action-export",
        group: "操作",
        label: "导出 Markdown 简报",
        hint: "浏览器本地下载",
        keywords: "export download 导出 简报 markdown",
        icon: Download,
        run: () => {
          void (async () => {
            const entry = getCachedDecision(
              decisionKey({ asOf: run.asOf, scenario: run.scenarioId, mode: run.mode }),
            );
            if (!entry) {
              toast({
                title: "尚未生成决策卡",
                description: "已在驾驶台发起生成，完成后可再次导出。",
                tone: "default",
              });
              go("/dashboard");
              return;
            }
            let traceEvents: TraceEvent[] = [];
            try {
              traceEvents = await loadTrace(entry.decision.run_id);
            } catch {
              traceEvents = [];
            }
            const markdown = buildMarkdownBriefing(
              entry.decision,
              entry.decision.evidence ?? [],
              traceEvents,
              run.scenario?.name ?? entry.decision.scenario ?? null,
            );
            downloadText(
              `${briefingFileSlug(entry.decision)}.md`,
              markdown,
              "text/markdown;charset=utf-8",
            );
            toast({
              title: "简报已导出",
              description: `${entry.decision.run_id} · Markdown`,
              tone: "success",
            });
          })();
        },
      },
      {
        id: "action-copy-run",
        group: "操作",
        label: "复制当前 run_id",
        hint: currentDecision?.run_id ?? "尚无决策卡",
        keywords: "copy run_id 复制 运行 id",
        icon: Copy,
        run: () => {
          void (async () => {
            const entry = getCachedDecision(
              decisionKey({ asOf: run.asOf, scenario: run.scenarioId, mode: run.mode }),
            );
            if (!entry) {
              toast({
                title: "尚无 run_id",
                description: "请先生成一次预警决策。",
                tone: "default",
              });
              return;
            }
            const ok = await copyText(entry.decision.run_id);
            toast(
              ok
                ? {
                    title: "已复制 run_id",
                    description: entry.decision.run_id,
                    tone: "success",
                  }
                : {
                    title: "复制失败",
                    description: "当前环境不允许访问剪贴板，请手动选择文本。",
                    tone: "error",
                  },
            );
          })();
        },
      },
      {
        id: "action-docs",
        group: "操作",
        label: "打开 API 文档",
        hint: "/docs",
        keywords: "api docs openapi 文档 接口",
        icon: BookOpen,
        run: () => {
          window.open("/docs", "_blank", "noopener,noreferrer");
        },
      },
    );

    list.push(
      {
        id: "ai-summary",
        group: "AI 快捷问",
        label: "总结当前预警",
        hint: "跳转对话并预填",
        keywords: "ai 总结 summary 预警",
        icon: Sparkles,
        run: () =>
          ask(
            `请用 3–5 句话总结当前 as_of ${run.asOf} 的预警结论：风险等级、主要驱动因子，以及三个主体的分歧。`,
          ),
      },
      {
        id: "ai-regulator",
        group: "AI 快捷问",
        label: regulatorLabel
          ? `为什么监管判定为「${regulatorLabel}」？`
          : "为什么监管判定为极高？",
        hint: "监管主体 · 关键证据",
        keywords: "ai 监管 regulator 为什么 判定 极高",
        icon: Sparkles,
        run: () =>
          ask(
            regulatorLabel
              ? `为什么监管主体给出「${regulatorLabel}」判断？请列出关键证据与局限。`
              : "为什么监管主体给出「极高」判断？请列出关键证据与局限。",
          ),
      },
      {
        id: "ai-evidence",
        group: "AI 快捷问",
        label: "三条关键证据是什么？",
        hint: "引用来源与影响",
        keywords: "ai 证据 evidence 关键 引用",
        icon: Sparkles,
        run: () =>
          ask(
            "本次判断最关键的 3 条证据分别是什么？请说明它们的来源、可靠性以及对结论的影响。",
          ),
      },
      {
        id: "ai-conflict",
        group: "AI 快捷问",
        label: "当前分歧如何协调？",
        hint: "三主体不一致时",
        keywords: "ai 分歧 conflict 协调",
        icon: Sparkles,
        run: () =>
          ask("当前三个主体存在哪些分歧？协调者与核验者是如何处理的，哪些仍未收敛？"),
      },
    );

    return list;
  }, [currentDecision?.run_id, regulatorLevel, route.params, run, theme, toast, toggleTheme]);

  const filtered = useMemo(() => {
    const value = query.trim().toLowerCase();
    if (!value) return items;
    return items.filter((item) =>
      [item.label, item.hint, item.keywords, item.group]
        .filter(Boolean)
        .join(" ")
        .toLowerCase()
        .includes(value),
    );
  }, [items, query]);

  const grouped = useMemo(
    () =>
      GROUP_ORDER.map((group) => ({
        group,
        items: filtered.filter((item) => item.group === group),
      })).filter((entry) => entry.items.length > 0),
    [filtered],
  );

  const flat = useMemo(() => grouped.flatMap((entry) => entry.items), [grouped]);
  const activeItem = flat[activeIndex] ?? null;

  useEffect(() => {
    setActiveIndex(0);
  }, [query]);

  useEffect(() => {
    if (activeIndex < flat.length) return;
    setActiveIndex(flat.length ? flat.length - 1 : 0);
  }, [activeIndex, flat.length]);

  useEffect(() => {
    if (!open || !activeItem) return;
    const element = document.getElementById(`command-item-${activeItem.id}`);
    element?.scrollIntoView({ block: "nearest" });
  }, [activeItem, open]);

  const execute = (item: CommandItem | null) => {
    if (!item) return;
    onOpenChange(false);
    window.setTimeout(() => item.run(), 0);
  };

  const onKeyDown = (event: ReactKeyboardEvent<HTMLInputElement>) => {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      if (!flat.length) return;
      setActiveIndex((current) => (current + 1) % flat.length);
      return;
    }
    if (event.key === "ArrowUp") {
      event.preventDefault();
      if (!flat.length) return;
      setActiveIndex((current) => (current - 1 + flat.length) % flat.length);
      return;
    }
    if (event.key === "Home") {
      event.preventDefault();
      setActiveIndex(0);
      return;
    }
    if (event.key === "End") {
      event.preventDefault();
      setActiveIndex(Math.max(0, flat.length - 1));
      return;
    }
    if (event.key === "Enter") {
      event.preventDefault();
      execute(activeItem);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className="top-[12vh] max-w-xl translate-y-0 overflow-hidden p-0"
        onOpenAutoFocus={(event) => {
          event.preventDefault();
          inputRef.current?.focus();
        }}
      >
        <DialogTitle className="sr-only">命令面板</DialogTitle>
        <DialogDescription className="sr-only">
          搜索并执行导航、场景、模式、操作或 AI 快捷问；↑↓ 选择，Enter 执行，Esc 关闭。
        </DialogDescription>

        <div className="border-b border-border p-3 pr-12">
          <div className="relative">
            <Search
              className="pointer-events-none absolute left-2 top-1/2 size-4 -translate-y-1/2 text-muted-foreground"
              aria-hidden="true"
            />
            <Input
              ref={inputRef}
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              onKeyDown={onKeyDown}
              placeholder="搜索或输入命令…"
              aria-label="搜索命令"
              role="combobox"
              aria-expanded={open}
              aria-controls="command-listbox"
              aria-autocomplete="list"
              aria-activedescendant={
                activeItem ? `command-item-${activeItem.id}` : undefined
              }
              className="h-9 border-0 bg-transparent pl-8 pr-2 text-body focus-visible:ring-0"
            />
          </div>
        </div>

        <div
          id="command-listbox"
          role="listbox"
          aria-label="命令与操作"
          className="scrollbar-thin max-h-[60vh] overflow-y-auto p-1.5"
        >
          {flat.length === 0 ? (
            <div className="flex flex-col items-center gap-1.5 px-4 py-10 text-center">
              <SearchX className="size-6 text-muted-foreground" aria-hidden="true" />
              <p className="text-body font-medium text-foreground">没有匹配的命令</p>
              <p className="text-caption text-muted-foreground">
                试试「重新生成」「总结当前预警」或场景名称。
              </p>
            </div>
          ) : (
            grouped.map((entry) => {
              const headingId = `command-group-${entry.group}`;
              return (
                <div key={entry.group} role="group" aria-labelledby={headingId} className="mb-1">
                  <div
                    id={headingId}
                    className="px-2 pb-0.5 pt-1.5 text-tiny font-medium text-muted-foreground"
                  >
                    {entry.group}
                  </div>
                  <div className="space-y-0.5">
                    {entry.items.map((item) => {
                      const index = flat.findIndex((entryItem) => entryItem.id === item.id);
                      const active = index === activeIndex;
                      const Icon = item.icon;
                      return (
                        <div
                          key={item.id}
                          id={`command-item-${item.id}`}
                          role="option"
                          aria-selected={active}
                          onMouseMove={() => setActiveIndex(index)}
                          onClick={() => execute(item)}
                          className={cn(
                            "flex cursor-pointer items-center gap-2 rounded-md px-2 py-1 text-left transition-colors duration-150",
                            active
                              ? "bg-accent text-foreground"
                              : "text-foreground/85 hover:bg-accent/60",
                          )}
                        >
                          <Icon
                            className={cn(
                              "size-4 shrink-0",
                              active ? "text-foreground" : "text-muted-foreground",
                            )}
                            aria-hidden="true"
                          />
                          <span className="min-w-0 flex-1 truncate text-body">
                            {item.label}
                          </span>
                          {item.hint ? (
                            <span className="max-w-[48%] shrink-0 truncate text-tiny text-muted-foreground">
                              {item.hint}
                            </span>
                          ) : null}
                        </div>
                      );
                    })}
                  </div>
                </div>
              );
            })
          )}
        </div>

        <div className="flex flex-wrap items-center justify-between gap-2 border-t border-border px-3 py-2 text-tiny text-muted-foreground">
          <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <Kbd>↑</Kbd>
            <Kbd>↓</Kbd>
            选择
            <Kbd>Enter</Kbd>
            执行
            <Kbd>Esc</Kbd>
            关闭
          </span>
          <span className="flex items-center gap-2">
            <span className="metric-value">
              {flat.length} / {items.length}
            </span>
            <span>条命令</span>
          </span>
        </div>
      </DialogContent>
    </Dialog>
  );
}
