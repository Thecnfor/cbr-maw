import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";

import { Callout } from "@/components/common/callout";
import { EmptyState } from "@/components/common/empty-state";
import { ErrorState } from "@/components/common/error-state";
import { PageHeader } from "@/components/common/page-header";
import { RiskBadge } from "@/components/common/risk-badge";
import { TopProgress } from "@/components/common/top-progress";
import { AgentCards } from "@/components/dashboard/agent-cards";
import { DriversPanel, ModalityPanel } from "@/components/dashboard/attribution";
import { DashboardSkeleton } from "@/components/dashboard/dashboard-skeleton";
import { EvidenceDialog } from "@/components/dashboard/evidence-dialog";
import { KpiRow } from "@/components/dashboard/kpi-row";
import {
  isDashboardTab,
  RightPanel,
  type DashboardTab,
} from "@/components/dashboard/right-panel";
import { RunProgress } from "@/components/dashboard/run-progress";
import { RunControls } from "@/components/layout/run-controls";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { queuePrompt } from "@/lib/ai-actions";
import { errorMessage } from "@/lib/api";
import { collectMissingEvidenceIds } from "@/lib/decision-utils";
import { useDecision } from "@/lib/decision";
import { fmtClock, fmtDateTime, truncateMiddle } from "@/lib/format";
import { modeMeta } from "@/lib/labels";
import { fmtElapsed } from "@/lib/motion";
import { subscribeRefreshRequest } from "@/lib/refresh-bus";
import { useDataCardsResource, useTraceResource } from "@/lib/resources";
import { navigate, paramsToRecord, useRoute } from "@/lib/router";
import { useRun } from "@/lib/run-context";
import { useToast } from "@/lib/toast";

/** recharts 体积较大：按需加载图表区块，首屏壳与决策数据不被图表阻塞。 */
const SignalPanel = lazy(() =>
  import("@/components/dashboard/signal-panel").then((module) => ({
    default: module.SignalPanel,
  })),
);

export function DashboardPage() {
  const run = useRun();
  const route = useRoute();
  const requestedTab = route.params.get("tab");
  const tab: DashboardTab = isDashboardTab(requestedTab) ? requestedTab : "evidence";

  const setTab = useCallback(
    (next: DashboardTab) => {
      const record = paramsToRecord(route.params);
      record.tab = next;
      navigate(route.path, record, { replace: true });
    },
    [route.path, route.params],
  );

  const decisionState = useDecision(
    { asOf: run.asOf, scenario: run.scenarioId, mode: run.mode },
    !run.scenariosLoading,
  );
  const decision = decisionState.decision;
  const trace = useTraceResource(decision?.run_id ?? null);
  const dataCards = useDataCardsResource(Boolean(decision));
  const { toast } = useToast();

  const handleAskAI = useCallback(
    (prompt: string) => {
      queuePrompt(prompt, "dashboard");
      const params = paramsToRecord(route.params);
      params.as_of = run.asOf;
      if (run.scenarioId) params.scenario = run.scenarioId;
      params.mode = run.mode;
      delete params.tab;
      navigate("/chat", params);
    },
    [route.params, run.asOf, run.mode, run.scenarioId],
  );

  const completionRef = useRef(0);
  useEffect(() => {
    const completion = decisionState.lastCompleted;
    if (!completion || completion.at <= completionRef.current) return;
    completionRef.current = completion.at;
    // 后端 30 分钟缓存命中时前端几乎瞬时完成，不弹「0s 完成」噪音 toast。
    if (completion.elapsedMs < 600) return;
    toast({
      title: "协同分析完成",
      description: `${completion.runId} · ${fmtElapsed(completion.elapsedMs / 1000)} · ${
        completion.usedFallback ? "同步回退" : "SSE 流式"
      }`,
      tone: "success",
    });
  }, [decisionState.lastCompleted, toast]);

  const failureRef = useRef(0);
  useEffect(() => {
    const failure = decisionState.lastFailed;
    if (!failure || failure.at <= failureRef.current) return;
    failureRef.current = failure.at;
    toast({
      title: "生成预警失败",
      description: failure.message,
      tone: "error",
    });
  }, [decisionState.lastFailed, toast]);

  const refreshRef = useRef(decisionState.refresh);
  useEffect(() => {
    refreshRef.current = decisionState.refresh;
  }, [decisionState.refresh]);
  useEffect(() => subscribeRefreshRequest(() => refreshRef.current()), []);

  useEffect(() => {
    document.title = decision
      ? `${decision.as_of} · 跨境风险协同预警驾驶台 · CBR-MAW`
      : "跨境风险协同预警驾驶台 · CBR-MAW";
  }, [decision]);

  const [evidenceId, setEvidenceId] = useState<string | null>(null);
  const evidenceList = useMemo(() => decision?.evidence ?? [], [decision]);
  const missingEvidenceIds = useMemo(
    () => (decision ? collectMissingEvidenceIds(decision) : []),
    [decision],
  );

  const error = decisionState.error;
  const showSkeleton = !decision && !error && !decisionState.cancelled;
  const retry = () => {
    decisionState.refresh();
    run.reload();
  };
  const cancel = () => {
    decisionState.cancel();
    toast({ title: "已取消本次生成", description: "保留上一次结果与缓存。", tone: "default" });
  };

  return (
    <>
      <TopProgress active={decisionState.loading} label="协同分析进行中" />
      <div className="page-container animate-rise">
      <PageHeader
        title="跨境风险协同预警驾驶台"
        description="时点回放：共享多模态信号 → 监管 / 投资 / 融资协同推理 → 证据共享与冲突协调 → 数值 / 引文 / 时点核验 → 可复核简报。系统仅使用 as_of 当日可得信息。"
        actions={
          <div className="flex flex-wrap items-center gap-2">
            {decision ? <RiskBadge level={decision.signal.level} /> : null}
            {decision ? (
              <Badge
                variant="outline"
                className="font-mono text-tiny"
                title={decision.run_id}
              >
                {truncateMiddle(decision.run_id, 18, 8)}
              </Badge>
            ) : null}
            {decisionState.fetchedAt ? (
              <span className="metric-value text-caption text-muted-foreground">
                {decisionState.fromCache ? "本地缓存" : "获取于"} ·{" "}
                {fmtClock(decisionState.fetchedAt)}
              </span>
            ) : null}
          </div>
        }
      >
        <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-caption text-muted-foreground">
          <span>
            场景：
            <span className="text-foreground">{run.scenario?.name ?? "—"}</span>
          </span>
          <span>
            模式：
            <span className="text-foreground">
              {modeMeta(decision?.mode ?? run.mode).label}
            </span>
          </span>
          {decision ? (
            <span className="hidden sm:inline">
              生成于 {fmtDateTime(decision.created_at)}
            </span>
          ) : null}
        </div>
      </PageHeader>

      <div className="mt-4 xl:hidden">
        <Card className="p-4">
          <RunControls variant="page" />
        </Card>
      </div>

      {run.scenariosError ? (
        <Callout
          tone="warning"
          className="mt-4"
          title="演示场景配置读取失败"
        >
          {run.scenariosError}；仍可使用默认时点生成决策，或在页面控件中手动选择日期。
        </Callout>
      ) : null}

      {decisionState.loading ? (
        <div className="mt-4">
          <RunProgress
            startedAt={decisionState.startedAt}
            active={decisionState.run.active}
            runId={decisionState.run.runId}
            stageEvents={decisionState.run.stageEvents}
            activities={decisionState.run.activities}
            usedFallback={decisionState.run.usedFallback}
            onCancel={cancel}
          />
        </div>
      ) : null}

      {error && decision ? (
        <ErrorState
          className="mt-4"
          title="刷新失败，仍展示上一次结果"
          message={errorMessage(error)}
          onRetry={retry}
          retrying={decisionState.loading}
        />
      ) : null}

      {showSkeleton ? (
        <DashboardSkeleton />
      ) : !decision ? (
        <div className="mt-4 space-y-3">
          {error ? (
            <ErrorState
              title="生成预警决策失败"
              message={errorMessage(error)}
              onRetry={retry}
              retrying={decisionState.loading}
              hint="已尝试流式接口 /api/decision/stream，并自动回退同步 /api/decision。若返回 503，说明核心模块尚未装配完成。可先访问 /api/health 查看待就绪模块，或启动 FastAPI 后重试。"
              details={run.health?.service_error ?? null}
            />
          ) : decisionState.cancelled ? (
            <EmptyState
              title="已取消本次生成"
              description="本次流式请求已中止，令牌与算力不会继续消耗；上一次结果或本地缓存仍可继续使用。"
              action={
                <Button size="sm" onClick={() => decisionState.refresh()}>
                  重新生成
                </Button>
              }
            />
          ) : (
            <EmptyState
              title="尚未生成决策卡"
              description="选择演示场景与 as_of 时点后，点击顶栏「重新生成」开始协同推理。"
              action={
                <Button size="sm" onClick={() => decisionState.refresh()}>
                  生成预警
                </Button>
              }
            />
          )}
        </div>
      ) : (
        <div key={decision.run_id} className="mt-4 space-y-4 animate-rise">
          <KpiRow decision={decision} />

          <div className="grid gap-4 min-[1180px]:grid-cols-[3fr_2fr]">
            <div className="min-w-0 space-y-4">
              <Suspense fallback={<div className="skeleton h-[336px] rounded-card" />}>
                <SignalPanel signal={decision.signal} />
              </Suspense>
              <div className="grid gap-4 md:grid-cols-[3fr_2fr]">
                <DriversPanel signal={decision.signal} />
                <ModalityPanel signal={decision.signal} />
              </div>
              <AgentCards
                decision={decision}
                onOpenEvidence={setEvidenceId}
                onAskAI={handleAskAI}
              />
            </div>

            <div className="min-w-0">
              <RightPanel
                decision={decision}
                tab={tab}
                onTabChange={setTab}
                onOpenEvidence={setEvidenceId}
                missingEvidenceIds={missingEvidenceIds}
                trace={trace}
                dataCards={dataCards}
                scenarioName={run.scenario?.name ?? decision.scenario ?? "—"}
                onAskAI={handleAskAI}
              />
            </div>
          </div>

          <footer className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 border-t border-border pt-3 text-caption text-muted-foreground">
            <span>CBR-MAW · 决策支持与演示层（L6）· 仅使用 as_of 当日可得信息</span>
            <span className="metric-value max-w-full truncate">run_id {decision.run_id}</span>
            <span>研究演示用途，不构成投资建议</span>
          </footer>
        </div>
      )}

      <EvidenceDialog
        evidenceId={evidenceId}
        evidenceList={evidenceList}
        onOpenChange={(open) => {
          if (!open) setEvidenceId(null);
        }}
        onAskAI={handleAskAI}
      />
      </div>
    </>
  );
}
