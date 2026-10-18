import type { ReactNode } from "react";
import {
  ExternalLink,
  LayoutDashboard,
  MessageSquare,
  Radar,
  RefreshCw,
} from "lucide-react";

import { IconButton } from "@/components/common/icon-button";
import { StatusDot, type StatusTone } from "@/components/ui/status-dot";
import { Skeleton } from "@/components/ui/skeleton";
import { navigate, paramsToRecord, useRoute } from "@/lib/router";
import { useRun } from "@/lib/run-context";
import { cn } from "@/lib/utils";

function NavItem({
  active,
  icon,
  label,
  onClick,
}: {
  active: boolean;
  icon: ReactNode;
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-current={active ? "page" : undefined}
      className={cn(
        "relative flex h-9 w-full items-center gap-2.5 rounded-lg px-2.5 text-body transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        active
          ? "bg-surface-2 font-medium text-foreground"
          : "text-muted-foreground hover:bg-accent hover:text-foreground",
      )}
    >
      {active ? (
        <span
          className="absolute left-0 top-2 h-5 w-0.5 rounded-full bg-foreground"
          aria-hidden="true"
        />
      ) : null}
      <span className="[&_svg]:size-4 [&_svg]:shrink-0" aria-hidden="true">
        {icon}
      </span>
      <span className="truncate">{label}</span>
    </button>
  );
}

function StatusRow({
  label,
  tone,
  value,
  pulse = false,
}: {
  label: string;
  tone: StatusTone;
  value: string;
  pulse?: boolean;
}) {
  return (
    <div className="flex items-center gap-2">
      <StatusDot status={tone} size="sm" pulse={pulse} />
      <span className="shrink-0 text-muted-foreground">{label}</span>
      <span
        className="metric-value ml-auto min-w-0 truncate text-right text-foreground"
        title={value}
      >
        {value}
      </span>
    </div>
  );
}

function ScenarioList({ onNavigate }: { onNavigate?: () => void }) {
  const { scenarios, scenariosLoading, scenariosError, scenarioId, setScenarioId } = useRun();

  return (
    <div className="mt-5">
      <div className="flex items-center justify-between px-2 pb-1">
        <span className="text-caption font-medium text-muted-foreground">演示场景</span>
        <span className="metric-value text-tiny text-muted-foreground">
          {scenarios.length}
        </span>
      </div>

      {scenariosLoading ? (
        <div className="space-y-1.5 px-2 py-1">
          {Array.from({ length: 3 }).map((_, index) => (
            <div key={index} className="space-y-1">
              <Skeleton className="h-3 w-4/5" />
              <Skeleton className="h-2.5 w-1/2" />
            </div>
          ))}
        </div>
      ) : scenariosError ? (
        <p className="px-2 py-1 text-caption leading-relaxed text-destructive-ink">
          场景读取失败：{scenariosError}
        </p>
      ) : scenarios.length === 0 ? (
        <p className="px-2 py-1 text-caption text-muted-foreground">
          暂无演示场景（configs/scenarios.yaml）。
        </p>
      ) : (
        <div className="space-y-0.5">
          {scenarios.map((scenario) => {
            const active = scenario.scenario_id === scenarioId;
            return (
              <button
                key={scenario.scenario_id}
                type="button"
                onClick={() => {
                  setScenarioId(scenario.scenario_id);
                  onNavigate?.();
                }}
                aria-current={active ? "true" : undefined}
                title={scenario.description || scenario.name}
                className={cn(
                  "flex w-full flex-col items-start gap-0.5 rounded-lg border px-2 py-1.5 text-left transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                  active
                    ? "border-border bg-surface-2"
                    : "border-transparent hover:bg-accent",
                )}
              >
                <span className="flex w-full min-w-0 items-center gap-1.5">
                  {active ? (
                    <span
                      className="size-1.5 shrink-0 rounded-full bg-foreground"
                      aria-hidden="true"
                    />
                  ) : null}
                  <span
                    className={cn(
                      "truncate text-body",
                      active ? "font-medium text-foreground" : "text-foreground/85",
                    )}
                  >
                    {scenario.name}
                  </span>
                </span>
                <span className="metric-value w-full truncate pl-3 text-tiny text-muted-foreground">
                  {scenario.as_of} · {scenario.scenario_id}
                </span>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

function SystemStatus({ onNavigate }: { onNavigate?: () => void }) {
  const { health, healthError, healthLoading, reload } = useRun();
  const llm = health?.llm;
  const dataSources = health?.data_sources;
  const pending = health?.pending_modules ?? [];
  const ready = health?.ready_modules ?? [];

  const serviceTone: StatusTone = healthLoading
    ? "info"
    : health?.service_ready
      ? "success"
      : "danger";
  const serviceText = healthLoading
    ? "检测中"
    : health?.service_ready
      ? "已就绪"
      : "未就绪";

  const llmText = healthLoading
    ? "检测中"
    : !llm
      ? "—"
      : `${llm.mock ? "mock" : "真实"} · ${llm.model || llm.provider || "—"}`;
  const llmTone: StatusTone = healthLoading
    ? "info"
    : !llm
      ? "idle"
      : llm.mock
        ? "warning"
        : "success";

  const dataText = healthLoading
    ? "检测中"
    : dataSources?.provider
      ? `${dataSources.provider}${typeof dataSources.data_cards === "number" ? ` · ${dataSources.data_cards} 卡片` : ""}`
      : "—";
  const dataTone: StatusTone = healthLoading
    ? "info"
    : dataSources?.ready
      ? "success"
      : "warning";

  const moduleText = healthLoading
    ? "检测中"
    : `${ready.length} 就绪${pending.length ? ` / ${pending.length} 待就绪` : ""}`;
  const moduleTone: StatusTone = healthLoading
    ? "info"
    : pending.length
      ? "warning"
      : health?.core_ready
        ? "success"
        : "idle";

  return (
    <div>
      <div className="flex items-center justify-between px-2">
        <span className="text-caption font-medium text-muted-foreground">系统状态</span>
        <IconButton
          label="重新检测核心模块"
          size="icon-sm"
          className="size-6 [&_svg]:size-3"
          onClick={() => {
            reload();
            onNavigate?.();
          }}
          disabled={healthLoading}
        >
          <RefreshCw aria-hidden="true" />
        </IconButton>
      </div>

      <dl className="mt-1 space-y-1.5 px-2 text-caption">
        <StatusRow label="核心服务" tone={serviceTone} value={serviceText} pulse={healthLoading} />
        <StatusRow label="LLM" tone={llmTone} value={llmText} />
        <StatusRow label="数据源" tone={dataTone} value={dataText} />
        <StatusRow label="模块" tone={moduleTone} value={moduleText} />
      </dl>

      {pending.length ? (
        <p
          className="mt-1.5 px-2 text-tiny leading-relaxed text-muted-foreground"
          title={pending.join("、")}
        >
          待就绪：
          {pending
            .map((item) => item.replace(/^cbr\./, ""))
            .slice(0, 3)
            .join("、")}
          {pending.length > 3 ? ` 等 ${pending.length} 项` : ""}
        </p>
      ) : null}

      {healthError ? (
        <p className="mt-1.5 px-2 text-tiny leading-relaxed text-destructive-ink" title={healthError}>
          健康检查失败：{healthError}
        </p>
      ) : null}

      <div className="mt-3 flex items-center justify-between gap-2 border-t border-border px-2 pt-2 text-caption text-muted-foreground">
        <span className="metric-value">v{health?.version || "—"}</span>
        <a
          href="http://127.0.0.1:8501"
          target="_blank"
          rel="noreferrer noopener"
          className="inline-flex items-center gap-1 transition-colors duration-150 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          Streamlit 回退
          <ExternalLink className="size-3" aria-hidden="true" />
        </a>
      </div>
    </div>
  );
}

export function SidebarContent({ onNavigate }: { onNavigate?: () => void }) {
  const route = useRoute();
  const page = route.path === "/chat" ? "chat" : "dashboard";
  const params = paramsToRecord(route.params);

  const go = (path: string) => {
    navigate(path, params);
    onNavigate?.();
  };

  return (
    <div className="flex h-full min-h-0 w-full flex-col bg-surface-1">
      <div className="flex h-[52px] shrink-0 items-center gap-2.5 border-b border-border px-4 pr-10">
        <div className="grid size-7 shrink-0 place-items-center rounded-md bg-primary text-primary-foreground">
          <Radar className="size-4" aria-hidden="true" />
        </div>
        <div className="min-w-0">
          <div className="truncate text-body font-semibold leading-tight text-foreground">
            CBR-MAW
          </div>
          <div className="truncate text-caption leading-tight text-muted-foreground">
            跨境风险协同预警
          </div>
        </div>
      </div>

      <div className="scrollbar-thin min-h-0 flex-1 overflow-y-auto px-2 py-3">
        <nav aria-label="主导航" className="space-y-0.5">
          <NavItem
            active={page === "dashboard"}
            icon={<LayoutDashboard />}
            label="驾驶台"
            onClick={() => go("/dashboard")}
          />
          <NavItem
            active={page === "chat"}
            icon={<MessageSquare />}
            label="对话"
            onClick={() => go("/chat")}
          />
        </nav>

        <ScenarioList onNavigate={onNavigate} />
      </div>

      <div className="scrollbar-thin max-h-[48%] shrink-0 overflow-y-auto border-t border-border py-3">
        <SystemStatus onNavigate={onNavigate} />
      </div>
    </div>
  );
}
