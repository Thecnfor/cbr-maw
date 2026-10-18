import { ArrowDownRight, ArrowUpRight, BarChart3, Layers } from "lucide-react";

import { EmptyState } from "@/components/common/empty-state";
import { Panel } from "@/components/common/panel";
import { fmtNum, fmtPct } from "@/lib/format";
import { sortedDrivers } from "@/lib/decision-utils";
import type { RiskSignal } from "@/lib/types";
import { cn } from "@/lib/utils";

const driversLegend = (
  <div className="hidden items-center gap-3 text-caption text-muted-foreground sm:flex">
    <span className="inline-flex items-center gap-1.5">
      <span className="size-2 rounded-sm bg-warning" aria-hidden="true" />
      推高风险
    </span>
    <span className="inline-flex items-center gap-1.5">
      <span className="size-2 rounded-sm bg-success" aria-hidden="true" />
      缓解风险
    </span>
  </div>
);

export function DriversPanel({ signal }: { signal: RiskSignal }) {
  const drivers = sortedDrivers(signal, 8);
  const maxAbs = Math.max(
    ...drivers.map((driver) => Math.abs(Number(driver.contribution) || 0)),
    0.000001,
  );

  return (
    <Panel
      title="驱动因子归因"
      icon={<BarChart3 />}
      meta={
        <>
          <span className="text-caption text-muted-foreground">Top {drivers.length}</span>
          {driversLegend}
        </>
      }
    >
      {drivers.length === 0 ? (
        <EmptyState
          title="未提供驱动因子"
          description="共享信号 signal.drivers 为空，无法给出归因排序。"
        />
      ) : (
        <ul className="space-y-0.5">
          {drivers.map((driver) => {
            const contribution = Number(driver.contribution) || 0;
            const up = driver.direction !== "down";
            const Icon = up ? ArrowUpRight : ArrowDownRight;
            const width = Math.max(2, (Math.abs(contribution) / maxAbs) * 100);
            return (
              <li key={driver.factor} className="py-1.5">
                <div className="flex items-center justify-between gap-2">
                  <span className="flex min-w-0 items-center gap-1">
                    <Icon
                      className={cn(
                        "size-3 shrink-0",
                        up ? "text-warning-ink" : "text-success-ink",
                      )}
                      aria-hidden="true"
                    />
                    <span className="truncate font-mono text-caption text-foreground">
                      {driver.factor}
                    </span>
                  </span>
                  <span className="metric-value shrink-0 text-caption text-muted-foreground">
                    {fmtNum(contribution, 3)}
                  </span>
                </div>
                <div className="mt-1 h-1.5 w-full overflow-hidden rounded-full bg-surface-2">
                  <div
                    className={cn("h-full rounded-full", up ? "bg-warning" : "bg-success")}
                    style={{ width: `${width}%` }}
                  />
                </div>
                {driver.description ? (
                  <p
                    className="mt-0.5 line-clamp-1 text-tiny text-muted-foreground"
                    title={driver.description}
                  >
                    {driver.description}
                  </p>
                ) : null}
              </li>
            );
          })}
        </ul>
      )}
    </Panel>
  );
}

const MODALITY_META: Record<string, { label: string; bar: string; dot: string }> = {
  numeric: { label: "数值模态", bar: "bg-viz-1", dot: "bg-viz-1" },
  text: { label: "文本模态", bar: "bg-viz-2", dot: "bg-viz-2" },
};

const FALLBACK_BARS = ["bg-viz-3", "bg-viz-4", "bg-viz-5", "bg-viz-6"];
const FALLBACK_DOTS = ["bg-viz-3", "bg-viz-4", "bg-viz-5", "bg-viz-6"];

export function ModalityPanel({ signal }: { signal: RiskSignal }) {
  const entries = Object.entries(signal.modality_contrib ?? {}).filter(
    ([, value]) => Number.isFinite(Number(value)) && Number(value) > 0,
  );
  const total = entries.reduce((sum, [, value]) => sum + Number(value), 0);

  return (
    <Panel
      title="模态贡献"
      icon={<Layers />}
      meta={<span className="text-caption text-muted-foreground">数值 vs 文本</span>}
    >
      {entries.length === 0 || total <= 0 ? (
        <EmptyState
          title="无模态贡献数据"
          description="signal.modality_contrib 为空或全为 0。"
        />
      ) : (
        <>
          <div
            className="flex h-2 w-full overflow-hidden rounded-full bg-surface-2"
            role="img"
            aria-label="数值与文本模态贡献占比"
          >
            {entries.map(([key, value], index) => {
              const meta = MODALITY_META[key];
              return (
                <div
                  key={key}
                  className={cn(meta?.bar ?? FALLBACK_BARS[index % FALLBACK_BARS.length])}
                  style={{ width: `${(Number(value) / total) * 100}%` }}
                  aria-hidden="true"
                />
              );
            })}
          </div>
          <ul className="mt-3 space-y-2">
            {entries.map(([key, value], index) => {
              const meta = MODALITY_META[key];
              return (
                <li key={key} className="flex items-center gap-2 text-caption">
                  <span
                    className={cn(
                      "size-2 shrink-0 rounded-sm",
                      meta?.dot ?? FALLBACK_DOTS[index % FALLBACK_DOTS.length],
                    )}
                    aria-hidden="true"
                  />
                  <span className="min-w-0 truncate text-foreground">
                    {meta?.label ?? key}
                  </span>
                  <span className="metric-value ml-auto text-muted-foreground">
                    {fmtPct(Number(value))}
                  </span>
                </li>
              );
            })}
          </ul>
          <p className="mt-3 border-t border-border pt-2 text-caption leading-relaxed text-muted-foreground">
            融合模型输出的相对贡献，非人工标注；数值与文本共享同一 as_of 时点。
          </p>
        </>
      )}
    </Panel>
  );
}
