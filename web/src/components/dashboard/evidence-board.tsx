import { useMemo, useState, type ReactNode } from "react";
import {
  Activity,
  BookOpen,
  ChevronRight,
  ScrollText,
  Search,
  TrendingUp,
  Wrench,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";

import { EmptyState } from "@/components/common/empty-state";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { evidenceKindCounts } from "@/lib/decision-utils";
import { fmtMetricValue, truncateMiddle } from "@/lib/format";
import { evidenceKindMeta } from "@/lib/labels";
import type { Evidence } from "@/lib/types";
import { cn } from "@/lib/utils";

const KIND_ICONS: Record<string, LucideIcon> = {
  signal: Activity,
  tool: Wrench,
  kb: BookOpen,
  market: TrendingUp,
  policy: ScrollText,
};

function FilterChip({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className={cn(
        "inline-flex h-6 items-center gap-1 rounded-full border px-2 text-caption transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        active
          ? "border-foreground/30 bg-surface-2 text-foreground"
          : "border-border text-muted-foreground hover:text-foreground",
      )}
    >
      {children}
    </button>
  );
}

interface EvidenceBoardProps {
  evidences: Evidence[];
  missingIds: string[];
  onOpenEvidence: (evidenceId: string) => void;
}

export function EvidenceBoard({ evidences, missingIds, onOpenEvidence }: EvidenceBoardProps) {
  const [kind, setKind] = useState<string>("all");
  const [query, setQuery] = useState("");

  const kinds = useMemo(() => evidenceKindCounts(evidences), [evidences]);
  const normalizedQuery = query.trim().toLowerCase();

  const filtered = useMemo(
    () =>
      evidences.filter((item) => {
        if (kind !== "all" && item.kind !== kind) return false;
        if (!normalizedQuery) return true;
        const haystack = [
          item.title,
          item.summary,
          item.evidence_id,
          item.source?.name,
          item.tool?.name,
        ]
          .filter(Boolean)
          .join(" ")
          .toLowerCase();
        return haystack.includes(normalizedQuery);
      }),
    [evidences, kind, normalizedQuery],
  );

  return (
    <div className="flex min-h-0 min-w-0 flex-col min-[1180px]:h-full">
      <div className="shrink-0">
        <div className="flex flex-wrap items-center gap-1.5">
        <FilterChip active={kind === "all"} onClick={() => setKind("all")}>
          全部 <span className="metric-value text-muted-foreground">{evidences.length}</span>
        </FilterChip>
        {kinds.map((item) => (
          <FilterChip
            key={item.kind}
            active={kind === item.kind}
            onClick={() => setKind(item.kind)}
          >
            {evidenceKindMeta(item.kind).short}
            <span className="metric-value text-muted-foreground">{item.count}</span>
          </FilterChip>
        ))}
      </div>

      <div className="relative mt-2">
        <Search
          className="pointer-events-none absolute left-2 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground"
          aria-hidden="true"
        />
        <Input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="搜索标题 / 来源 / 证据 ID"
          aria-label="搜索证据"
          className="pl-7"
        />
      </div>

      <div className="mt-2 flex flex-wrap items-center justify-between gap-2 text-caption text-muted-foreground">
        <span>
          共 {evidences.length} 条，当前展示 {filtered.length} 条
        </span>
        {missingIds.length ? (
          <span className="text-warning-ink">{missingIds.length} 条引用未解析</span>
        ) : null}
      </div>
      </div>

      {evidences.length === 0 ? (
        <EmptyState
          className="mt-3"
          title="本次决策未引用证据"
          description="决策卡 evidence 为空：编排层尚未把证据写入黑板快照。"
        />
      ) : (
        <>
          <div className="mt-2 h-[380px] min-h-0 min-[1180px]:h-auto min-[1180px]:flex-1">
            <ScrollArea className="h-full pr-1">
            {filtered.length === 0 ? (
              <EmptyState
                title="没有匹配的证据"
                description="调整类型过滤或搜索关键词后重试。"
                className="mr-2 mt-2"
              />
            ) : (
              <ul className="divide-y divide-border">
                {filtered.map((item) => {
                  const kindMeta = evidenceKindMeta(item.kind);
                  const Icon = KIND_ICONS[item.kind] ?? BookOpen;
                  return (
                    <li key={item.evidence_id}>
                      <button
                        type="button"
                        onClick={() => onOpenEvidence(item.evidence_id)}
                        className="flex w-full items-start gap-2.5 px-1 py-2.5 text-left transition-colors duration-150 hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"
                      >
                        <span className="mt-0.5 grid size-7 shrink-0 place-items-center rounded-md border border-border bg-surface-2 text-muted-foreground">
                          <Icon className="size-3.5" aria-hidden="true" />
                        </span>
                        <span className="min-w-0 flex-1">
                          <span className="flex items-center gap-1.5">
                            <span className="truncate text-body font-medium text-foreground">
                              {item.title || item.evidence_id}
                            </span>
                            {item.verified === true ? (
                              <Badge variant="success" className="shrink-0 text-tiny">
                                已核验
                              </Badge>
                            ) : null}
                          </span>
                          <span className="mt-0.5 block truncate text-caption text-muted-foreground">
                            {kindMeta.label} · as_of {item.as_of} ·{" "}
                            {item.source?.name || "未知来源"} · {item.evidence_id}
                          </span>
                          {item.summary ? (
                            <span className="mt-0.5 line-clamp-1 block text-tiny text-muted-foreground">
                              {item.summary}
                            </span>
                          ) : null}
                        </span>
                        <span className="metric-value mt-0.5 shrink-0 text-caption text-muted-foreground">
                          {item.value !== null && item.value !== undefined ? (
                            fmtMetricValue(item.value, item.unit)
                          ) : (
                            <ChevronRight className="size-3.5" aria-hidden="true" />
                          )}
                        </span>
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
          </ScrollArea>
          </div>

          {missingIds.length ? (
            <details className="scrollbar-thin mt-3 max-h-40 shrink-0 overflow-y-auto rounded-lg border border-warning/30 bg-warning/10 p-2.5">
              <summary className="cursor-pointer text-caption font-medium text-warning-ink">
                {missingIds.length} 条引用证据未在黑板快照中（点击展开）
              </summary>
              <p className="mt-1 text-caption leading-relaxed text-muted-foreground">
                以下 evidence_id 被决策卡引用，但本次黑板快照未包含；点击可尝试通过
                GET /api/evidence/&lt;id&gt; 读取。通常意味着证据检索接口待核心补齐，不是界面错误。
              </p>
              <div className="mt-1.5 flex flex-wrap gap-1">
                {missingIds.map((id) => (
                  <button
                    key={id}
                    type="button"
                    onClick={() => onOpenEvidence(id)}
                    title={id}
                    className="rounded border border-border bg-surface-1 px-1.5 py-0.5 font-mono text-tiny text-muted-foreground transition-colors duration-150 hover:border-foreground/30 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  >
                    {truncateMiddle(id, 20, 8)}
                  </button>
                ))}
              </div>
            </details>
          ) : null}
        </>
      )}
    </div>
  );
}
