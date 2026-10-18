import { Activity } from "lucide-react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  LabelList,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip as RechartsTooltip,
  XAxis,
  YAxis,
} from "recharts";

import { EmptyState } from "@/components/common/empty-state";
import { Panel } from "@/components/common/panel";
import { fmtPct, horizonsOf } from "@/lib/format";
import type { RiskSignal } from "@/lib/types";

const THRESHOLD_PERCENT = 60;

interface HorizonDatum {
  label: string;
  display: string;
  percent: number;
  threshold: string;
}

interface SignalTooltipProps {
  active?: boolean;
  payload?: ReadonlyArray<{ payload?: HorizonDatum }>;
}

function SignalTooltip({ active, payload }: SignalTooltipProps) {
  const datum = payload?.[0]?.payload;
  if (!active || !datum) return null;
  return (
    <div className="rounded-md border border-border bg-surface-1 px-2.5 py-1.5 shadow-raised">
      <div className="text-caption font-medium text-foreground">{datum.label}</div>
      <div className="metric-value text-caption text-muted-foreground">
        高压力概率 {datum.display}
      </div>
      <div className="text-tiny text-muted-foreground">{datum.threshold}</div>
    </div>
  );
}

const legend = (
  <div className="hidden items-center gap-3 text-caption text-muted-foreground sm:flex">
    <span className="inline-flex items-center gap-1.5">
      <span className="size-2 rounded-sm bg-viz-1" aria-hidden="true" />
      高压力概率
    </span>
    <span className="inline-flex items-center gap-1.5">
      <span className="w-3 border-t border-dashed border-destructive" aria-hidden="true" />
      阈值 60%
    </span>
  </div>
);

export function SignalPanel({ signal }: { signal: RiskSignal }) {
  const horizons = horizonsOf(signal);
  const data: HorizonDatum[] = horizons.map((point) => {
    const percent = point.value === null ? 0 : Math.round(point.value * 1000) / 10;
    return {
      label: `${point.horizon} 日`,
      display: fmtPct(point.value),
      percent,
      threshold:
        percent >= THRESHOLD_PERCENT
          ? `高于阈值 ${(percent - THRESHOLD_PERCENT).toFixed(1)}pp`
          : `低于阈值 ${(THRESHOLD_PERCENT - percent).toFixed(1)}pp`,
    };
  });

  return (
    <Panel title="风险信号 · 5 / 10 / 20 日" icon={<Activity />} meta={legend}>
      {data.length === 0 ? (
        <EmptyState
          title="决策卡未包含期限概率"
          description="共享信号 signal.horizons 为空，无法绘制 5 / 10 / 20 日高压力概率。"
        />
      ) : (
        <>
          <div className="h-[216px] w-full" aria-label="未来 5 / 10 / 20 日高压力概率柱状图">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={data} margin={{ top: 26, right: 8, bottom: 0, left: 0 }}>
                <CartesianGrid vertical={false} stroke="var(--border)" />
                <XAxis
                  dataKey="label"
                  axisLine={false}
                  tickLine={false}
                  tickMargin={8}
                  tick={{ fill: "var(--muted-foreground)", fontSize: 11 }}
                />
                <YAxis
                  width={42}
                  domain={[0, 100]}
                  ticks={[0, 25, 50, 75, 100]}
                  axisLine={false}
                  tickLine={false}
                  tick={{ fill: "var(--muted-foreground)", fontSize: 10 }}
                  tickFormatter={(value) => `${value}%`}
                />
                <RechartsTooltip
                  content={<SignalTooltip />}
                  cursor={{ fill: "var(--accent)" }}
                />
                <ReferenceLine
                  y={THRESHOLD_PERCENT}
                  stroke="var(--destructive)"
                  strokeWidth={1}
                  strokeDasharray="4 4"
                  label={{
                    value: "阈值 60%",
                    position: "insideTopRight",
                    fill: "var(--destructive-ink)",
                    fontSize: 10,
                  }}
                />
                <Bar
                  dataKey="percent"
                  name="高压力概率"
                  fill="var(--viz-1)"
                  radius={[4, 4, 0, 0]}
                  maxBarSize={56}
                  isAnimationActive={false}
                >
                  <LabelList
                    dataKey="display"
                    position="top"
                    offset={6}
                    fill="var(--foreground)"
                    fontSize={11}
                    fontFamily="var(--font-mono)"
                  />
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>

          <div className="mt-2 flex flex-wrap items-center justify-between gap-2 border-t border-border pt-2 text-caption text-muted-foreground">
            <span>
              历史分位 {fmtPct(signal.percentile)} · 标签版本 {signal.label_version || "—"}
            </span>
            <span
              className="metric-value max-w-full truncate"
              title={signal.evidence_id ?? undefined}
            >
              共享信号 {signal.evidence_id || "—"}
            </span>
          </div>
        </>
      )}
    </Panel>
  );
}
