import { Database, RefreshCw } from "lucide-react";

import { EmptyState } from "@/components/common/empty-state";
import { ErrorState } from "@/components/common/error-state";
import { IconButton } from "@/components/common/icon-button";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { errorMessage } from "@/lib/api";
import { fmtDate } from "@/lib/format";
import { frequencyLabel, pitLabel } from "@/lib/labels";
import type { DataCardsResource } from "@/lib/resources";
import { cn } from "@/lib/utils";

function pitVariant(grade: string | undefined): "success" | "warning" | "muted" {
  if (grade === "strict") return "success";
  if (grade === "approximate") return "warning";
  return "muted";
}

const HEADERS = [
  "序列 ID",
  "名称",
  "来源",
  "频率",
  "覆盖期",
  "发布滞后",
  "时点评级",
  "单位",
];

export function DataCardsPanel({ resource }: { resource: DataCardsResource }) {
  const { cards, loading, error, reload } = resource;

  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-1.5 text-caption text-muted-foreground">
          <Database className="size-3.5" aria-hidden="true" />
          {cards.length} 条序列 · 数据口径与时点可得性
        </div>
        <IconButton
          label="刷新数据卡"
          size="icon-sm"
          onClick={reload}
          disabled={loading}
        >
          <RefreshCw className={cn(loading && "animate-spin")} aria-hidden="true" />
        </IconButton>
      </div>

      {loading ? (
        <div className="mt-2 space-y-2" aria-busy="true" aria-label="数据卡加载中">
          {Array.from({ length: 5 }).map((_, index) => (
            <Skeleton key={index} className="h-10 rounded-lg" />
          ))}
        </div>
      ) : error ? (
        <ErrorState
          className="mt-2"
          title="数据卡读取失败"
          message={errorMessage(error)}
          hint="GET /api/data-cards 在核心数据层未就绪时返回 503；这不影响本次决策卡的展示。"
          onRetry={reload}
        />
      ) : cards.length === 0 ? (
        <EmptyState
          className="mt-2"
          title="数据层未返回数据卡"
          description="DataProvider.data_cards() 为空或尚未实现；序列口径与时点评级暂不可见。"
        />
      ) : (
        <>
          <div className="mt-2 overflow-x-auto rounded-lg border border-border">
            <table className="w-full min-w-[760px] border-collapse text-caption">
              <caption className="sr-only">
                数据卡列表：序列口径、覆盖期、发布滞后与时点可得性评级
              </caption>
              <thead>
                <tr className="bg-surface-2 text-muted-foreground">
                  {HEADERS.map((header) => (
                    <th
                      key={header}
                      scope="col"
                      className="whitespace-nowrap border-b border-border px-2.5 py-2 text-left font-medium"
                    >
                      {header}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {cards.map((card) => {
                  const coverage =
                    card.coverage_start || card.coverage_end
                      ? `${fmtDate(card.coverage_start)} ~ ${fmtDate(card.coverage_end)}`
                      : "—";
                  return (
                    <tr
                      key={card.series_id}
                      className="border-b border-border transition-colors duration-150 last:border-b-0 hover:bg-accent/50"
                    >
                      <td className="whitespace-nowrap px-2.5 py-2 font-mono text-foreground">
                        {card.series_id}
                      </td>
                      <td className="px-2.5 py-2 text-foreground">
                        <span
                          className="block max-w-[180px] truncate"
                          title={card.notes || card.name}
                        >
                          {card.name}
                        </span>
                      </td>
                      <td className="px-2.5 py-2 text-foreground/85">{card.source}</td>
                      <td className="whitespace-nowrap px-2.5 py-2 text-foreground/85">
                        {frequencyLabel(card.frequency)}
                      </td>
                      <td className="whitespace-nowrap px-2.5 py-2 font-mono text-muted-foreground">
                        {coverage}
                      </td>
                      <td className="whitespace-nowrap px-2.5 py-2 font-mono text-muted-foreground">
                        {card.release_lag_days ?? 0} 天
                      </td>
                      <td className="px-2.5 py-2">
                        <Badge variant={pitVariant(card.pit_grade)}>
                          {pitLabel(card.pit_grade)}
                        </Badge>
                      </td>
                      <td className="whitespace-nowrap px-2.5 py-2 text-foreground/85">
                        {card.unit || "—"}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {cards.some((card) => card.notes) ? (
            <details className="mt-2 rounded-lg border border-border bg-surface-2 p-2.5">
              <summary className="cursor-pointer text-caption text-muted-foreground">
                数据口径备注（{cards.filter((card) => card.notes).length}）
              </summary>
              <ul className="mt-1 space-y-1 text-caption leading-relaxed text-foreground/80">
                {cards
                  .filter((card) => card.notes)
                  .map((card) => (
                    <li key={card.series_id}>
                      <span className="font-mono text-foreground">{card.series_id}</span>：
                      {card.notes}
                    </li>
                  ))}
              </ul>
            </details>
          ) : null}

          <p className="mt-2 text-caption leading-relaxed text-muted-foreground">
            时点评级：严格 = release_time 精确可得；近似 = 用交易日近似；不可得 = 仅用于事后评估。
          </p>
        </>
      )}
    </div>
  );
}
