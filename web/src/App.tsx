import { lazy, Suspense, useEffect } from "react";

import { DashboardPage } from "@/components/dashboard/dashboard-page";
import { AppShell } from "@/components/layout/app-shell";
import { navigate, paramsToRecord, useRoute } from "@/lib/router";

/** 对话页独立分块：驾驶台首屏不加载对话与引用 UI。 */
const ChatPage = lazy(() =>
  import("@/components/chat/chat-page").then((module) => ({ default: module.ChatPage })),
);

function ChatFallback() {
  return (
    <div className="mx-auto w-full max-w-4xl px-4 py-6 sm:px-6" aria-busy="true">
      <div className="skeleton h-8 w-40" />
      <div className="skeleton mt-2 h-3 w-3/4" />
      <div className="skeleton mt-4 h-10 w-full" />
      <div className="skeleton mt-3 h-10 w-full" />
      <div className="skeleton mt-5 h-64 rounded-card" />
    </div>
  );
}

export default function App() {
  const route = useRoute();
  const page = route.path === "/chat" ? "chat" : "dashboard";

  useEffect(() => {
    if (route.path === "/dashboard" || route.path === "/chat") return;
    navigate("/dashboard", paramsToRecord(route.params), { replace: true });
  }, [route.path, route.params]);

  return (
    <AppShell page={page}>
      {page === "chat" ? (
        <Suspense fallback={<ChatFallback />}>
          <ChatPage />
        </Suspense>
      ) : (
        <DashboardPage />
      )}
    </AppShell>
  );
}
