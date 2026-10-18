import { useEffect, useState, type ReactNode } from "react";

import { CommandPalette } from "@/components/command/command-palette";
import { SidebarContent } from "@/components/layout/sidebar";
import { Topbar } from "@/components/layout/topbar";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
} from "@/components/ui/dialog";
import { useRoute } from "@/lib/router";

interface AppShellProps {
  page: "dashboard" | "chat";
  children: ReactNode;
}

export function AppShell({ page, children }: AppShellProps) {
  const [mobileOpen, setMobileOpen] = useState(false);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const route = useRoute();

  // 页面切换（驾驶台 ↔ 对话）时回到内容顶部，避免沿用上一页滚动位置
  useEffect(() => {
    const main = document.getElementById("main-content");
    if (main) main.scrollTop = 0;
    window.scrollTo(0, 0);
  }, [route.path]);

  return (
    <div className="flex h-dvh overflow-hidden bg-surface-0 text-foreground">
      <button
        type="button"
        onClick={() => document.getElementById("main-content")?.focus()}
        className="sr-only focus:not-sr-only focus:absolute focus:left-3 focus:top-3 focus:z-50 focus:rounded-lg focus:bg-primary focus:px-3 focus:py-2 focus:text-body focus:text-primary-foreground focus:outline-none focus:ring-2 focus:ring-ring"
      >
        跳到主要内容
      </button>

      <aside className="hidden w-[248px] shrink-0 border-r border-border lg:block">
        <SidebarContent />
      </aside>

      <div className="flex min-h-0 min-w-0 flex-1 flex-col">
        <Topbar
          page={page}
          onOpenSidebar={() => setMobileOpen(true)}
          onOpenPalette={() => setPaletteOpen(true)}
        />
        <main
          id="main-content"
          tabIndex={-1}
          className="scrollbar-thin min-h-0 flex-1 overflow-y-auto focus:outline-none"
        >
          {children}
        </main>
      </div>

      <Dialog open={mobileOpen} onOpenChange={setMobileOpen}>
        <DialogContent className="left-0 top-0 h-dvh max-h-dvh w-[280px] max-w-[calc(100vw-2rem)] translate-x-0 translate-y-0 rounded-none border-y-0 border-l-0 p-0">
          <DialogTitle className="sr-only">导航与场景</DialogTitle>
          <DialogDescription className="sr-only">
            选择功能页面、演示场景，并查看系统状态与 Streamlit 回退入口。
          </DialogDescription>
          <SidebarContent onNavigate={() => setMobileOpen(false)} />
        </DialogContent>
      </Dialog>

      <CommandPalette open={paletteOpen} onOpenChange={setPaletteOpen} />
    </div>
  );
}
