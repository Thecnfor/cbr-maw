import { Activity, Coins, Gauge, Percent } from "lucide-react";

import { MicroLabel } from "@/components/common/detail-row";
import { LevelText, RiskBadge } from "@/components/common/risk-badge";
import { Meter } from "@/components/common/meter";
import { Sparkline } from "@/components/dashboard/sparkline";
import { Card } from "@/components/ui/card";
import {
  fmtCostUnits,
  fmtDuration,
  fmtNum,
  fmtPct,
  fmtTokens,
  horizonsOf,
  percentilePercent,
} from "@/lib/format";
import type { DecisionCard } from "@/lib/types";
import { cn } from "@/lib/utils";

const THRESHOLD = 0.6;

export function KpiRow({ decision }: { decision: DecisionCard }) {
  const { signal } = decision;
  const coordination = decision.coordination ?? {};
  const horizons = horizonsOf(signal);
  const fiveDay = horizons.find((point) => point.horizon === 5)?.value ?? null;
  const percentile = percentilePercent(signal.percentile);
  const gap = fiveDay === null ? null : fiveDay * 100 - THRESHOLD * 100;

  return (
    <div className="grid gap-3 min-[1180px]:grid-cols-[2fr_1fr_1fr] min-[1180px]:grid-rows-[auto_auto]">
      <Card className="flex flex-col p-4 min-[1180px]:row-span-2">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div className="min-w-0">
            <div className="flex items-center gap-1.5 text-caption text-muted-foreground">
              <Activity className="size-3.5" aria-hidden="true" />
              5 日高压力概率
            </div>
            <div className="mt-1.5 flex flex-wrap items-end gap-2">
              <span className="metric-value text-metric font-semibold text-foreground">
                {fmtPct(fiveDay)}
              </span>
              <RiskBadge level={signal.level} className="mb-1" />
            </div>
            <p className="mt-1 text-caption text-muted-foreground">
              预警阈值 {THRESHOLD * 100}%
              {gap !== null
                ? ` · 当前${gap >= 0 ? "高于" : "低于"}阈值 ${fmtNum(Math.abs(gap), 1)} 个百分点`
                : ""}
            </p>
          </div>
          <span
            className="font-mono text-tiny text-muted-foreground"
            title="共享信号标签版本"
          >
            标签 {signal.label_version || "stress_pca_q90"}
          </span>
        </div>

        <div className="mt-4">
          <Sparkline values={horizons.map((point) => point.value)} />
          <div className="mt-1 grid grid-cols-3 gap-2">
            {horizons.map((point) => (
              <div key={point.horizon} className="min-w-0">
                <div className="text-tiny text-muted-foreground">{point.horizon} 日</div>
                <div className="metric-value truncate text-caption font-medium text-foreground">
                  {fmtPct(point.value)}
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="mt-auto flex flex-wrap items-center justify-between gap-2 border-t border-border pt-3 text-caption text-muted-foreground">
          <span className="min-w-0 truncate" title={signal.model_version}>
            模型 {signal.model_version || "—"}
          </span>
          <span className="metric-value shrink-0">as_of {decision.as_of}</span>
        </div>
      </Card>

      <Card className="p-4">
        <div className="flex items-center justify-between gap-2">
          <MicroLabel>风险等级</MicroLabel>
          <Gauge className="size-4 text-muted-foreground" aria-hidden="true" />
        </div>
        <div className="mt-1.5 flex items-baseline gap-2">
          <LevelText level={signal.level} className="text-h1 leading-none" />
          <span className="text-caption text-muted-foreground">模型判定</span>
        </div>
        <p className="mt-2 text-caption text-muted-foreground">
          共享信号等级 · 标签版本 {signal.label_version || "—"}
        </p>
      </Card>

      <Card className="p-4">
        <div className="flex items-center justify-between gap-2">
          <MicroLabel>历史分位</MicroLabel>
          <Percent className="size-4 text-muted-foreground" aria-hidden="true" />
        </div>
        <div className="mt-1.5 flex items-baseline gap-2">
          <span className="metric-value text-h1 font-semibold leading-none text-foreground">
            {fmtPct(signal.percentile)}
          </span>
          <span className="text-caption text-muted-foreground">阈值 90%</span>
        </div>
        <Meter
          value={percentile}
          tone={percentile !== null && percentile >= 90 ? "danger" : "neutral"}
          label="历史分位"
          className="mt-3"
        />
        <p className="mt-1.5 text-caption text-muted-foreground">
          {percentile === null
            ? "未提供历史分位"
            : percentile >= 90
              ? "处于历史高位区间"
              : "低于 90% 预警分位"}
        </p>
      </Card>

      <Card className="p-4 min-[1180px]:col-span-2">
        <div className="flex items-center justify-between gap-2">
          <MicroLabel>协同成本 C</MicroLabel>
          <Coins className="size-4 text-muted-foreground" aria-hidden="true" />
        </div>
        <div className="mt-1.5 flex flex-wrap items-end justify-between gap-x-4 gap-y-2">
          <span className="metric-value text-h1 font-semibold leading-none text-foreground">
            {fmtCostUnits(coordination.cost_usd)}
          </span>
          <div className="grid grid-cols-3 gap-x-4 gap-y-1 text-caption">
            <div>
              <div className="text-muted-foreground">工具调用</div>
              <div className="metric-value text-foreground">{coordination.tool_calls ?? 0}</div>
            </div>
            <div>
              <div className="text-muted-foreground">tokens</div>
              <div className="metric-value text-foreground">
                {fmtTokens(coordination.tokens)}
              </div>
            </div>
            <div>
              <div className="text-muted-foreground">端到端</div>
              <div className="metric-value text-foreground">
                {fmtDuration(coordination.latency_ms ?? 0)}
              </div>
            </div>
          </div>
        </div>
        <p className={cn("mt-2 text-caption text-muted-foreground")}>
          证据 {coordination.evidence_shared ?? 0} 条
          {coordination.duplicate_evidence
            ? `（去重 ${coordination.duplicate_evidence}）`
            : ""}
          {" · "}冲突 {coordination.conflicts_resolved ?? 0}/{coordination.conflicts_total ?? 0} 已解决
          {" · "}协调轮次 {coordination.rounds ?? 0}
        </p>
      </Card>
    </div>
  );
}
