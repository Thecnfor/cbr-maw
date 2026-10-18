import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import App from "@/App";
import { TooltipProvider } from "@/components/ui/tooltip";
import { ChatProvider } from "@/lib/chat-context";
import { RunProvider } from "@/lib/run-context";
import { ThemeProvider } from "@/lib/theme";
import { ToastProvider } from "@/lib/toast";
import "@/styles/index.css";

const rootElement = document.getElementById("root");
if (!rootElement) {
  throw new Error("缺少 #root 挂载点，无法启动 CBR-MAW Web 前端。");
}

createRoot(rootElement).render(
  <StrictMode>
    <ThemeProvider>
      <RunProvider>
        <ChatProvider>
          <TooltipProvider delayDuration={200}>
            <ToastProvider>
              <App />
            </ToastProvider>
          </TooltipProvider>
        </ChatProvider>
      </RunProvider>
    </ThemeProvider>
  </StrictMode>,
);
