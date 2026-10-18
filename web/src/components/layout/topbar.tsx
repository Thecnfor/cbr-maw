import { Menu, Radar, RefreshCw, Search } from "lucide-react";

import { ThemeToggle } from "@/components/layout/theme-toggle";
import { RunControls } from "@/components/layout/run-controls";
import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { requestRefresh } from "@/lib/refresh-bus";

interface TopbarProps {
  page: "dashboard" | "chat";
  onOpenSidebar: () => void;
  onOpenPalette: () => void;
}

/** 顶栏 52px：面包屑 / 命令面板 / 运行条件（xl+）/ 主行动 / 主题切换。 */
export function Topbar({ page, onOpenSidebar, onOpenPalette }: TopbarProps) {
  return (
    <header className="flex h-[52px] shrink-0 items-center gap-2 border-b border-border bg-surface-1 px-3 sm:px-4">
      <div className="flex min-w-0 items-center gap-2">
        <Button
          variant="ghost"
          size="icon-sm"
          className="size-10 lg:hidden"
          onClick={onOpenSidebar}
          aria-label="打开导航与场景"
        >
          <Menu aria-hidden="true" />
        </Button>
        <div className="flex items-center gap-2 sm:hidden">
          <Radar className="size-4 text-foreground" aria-hidden="true" />
          <span className="text-body font-semibold text-foreground">CBR-MAW</span>
        </div>
        <span className="dash-crumbs hidden min-w-0 truncate sm:inline">
          风险监测 / <b>{page === "chat" ? "智能对话" : "协同预警"}</b>
        </span>
      </div>

      <div className="ml-auto flex shrink-0 items-center gap-2">
        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              variant="outline"
              size="sm"
              onClick={onOpenPalette}
              aria-label="打开命令面板（Ctrl+K）"
              className="h-10 w-10 px-0 sm:h-8 sm:w-auto sm:px-2.5"
            >
              <Search aria-hidden="true" />
              <span className="hidden sm:inline">命令</span>
              <kbd className="hidden rounded border border-border bg-surface-2 px-1 py-0.5 font-mono text-tiny text-muted-foreground md:inline">
                ⌘K
              </kbd>
            </Button>
          </TooltipTrigger>
          <TooltipContent side="bottom">
            命令面板：⌘K / Ctrl+K（导航、场景、模式、操作与 AI 快捷问）
          </TooltipContent>
        </Tooltip>
        <RunControls className="hidden xl:flex" />
        {page === "dashboard" ? (
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                size="sm"
                onClick={requestRefresh}
                aria-label="重新生成预警决策卡"
                className="h-10 w-10 px-0 sm:h-8 sm:w-auto sm:px-2.5"
              >
                <RefreshCw aria-hidden="true" />
                <span className="hidden sm:inline">重新生成</span>
              </Button>
            </TooltipTrigger>
            <TooltipContent side="bottom">
              按当前场景 / 时点 / 模式重新生成（真实 LLM 约 12 秒）
            </TooltipContent>
          </Tooltip>
        ) : null}
        <ThemeToggle className="size-10 sm:size-8" />
      </div>
    </header>
  );
}
