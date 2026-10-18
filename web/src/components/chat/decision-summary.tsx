import { useState } from "react";
import { Download, ExternalLink, Link2, Loader2 } from "lucide-react";

import { LevelText, RiskBadge } from "@/components/common/risk-badge";
import { Button } from "@/components/ui/button";
import { loadTrace } from "@/lib/api";
import {
  briefingFileSlug,
  buildMarkdownBriefing,
  downloadText,
} from "@/lib/export";
import { truncateMiddle } from "@/lib/format";
import { modeMeta, roleMeta, ROLE_ORDER } from "@/lib/labels";
import { navigate } from "@/lib/router";
import { useRun } from "@/lib/run-context";
import type { DecisionCard, TraceEvent } from "@/lib/types";
import { cn } from "@/lib/utils";

const RISK_TONE = {
  low: "text-success-ink",
  medium: "text-warning-ink",
  high: "text-destructive-ink",
  critical: "text-destructive-ink",
} as const;

/** 对话中的关联决策卡摘要：跳转驾驶台 / 下载简报（trace 缺失时降级为空）。 */
export function DecisionSummary({ decision }: { decision: DecisionCard }) {
  const run = useRun();
  const [downloading, setDownloading] = useState(false);
  const [expanded, setExpanded] = useState(false);

  const roles = ROLE_ORDER.filter((role) => decision.cards?.[role]);
  const advice = decision.final_advice || "无综合建议";
  const canExpand = advice.length > 110;

  const openDashboard = () => {
    navigate("/dashboard", {
      as_of: decision.as_of,
      mode: decision.mode,
      scenario: decision.scenario ?? run.scenarioId,
      tab: "evidence",
    });
  };

  const downloadBriefing = async () => {
    setDownloading(true);
    let traceEvents: TraceEvent[] = [];
    try {
      traceEvents = await loadTrace(decision.run_id);
    } catch {
      traceEvents = [];
    }
    const markdown = buildMarkdownBriefing(
      decision,
      decision.evidence ?? [],
      traceEvents,
      run.scenario?.name ?? decision.scenario ?? null,
    );
    downloadText(
      `${briefingFileSlug(decision)}.md`,
      markdown,
      "text/markdown;charset=utf-8",
    );
    setDownloading(false);
  };

  return (
    <div className="mt-2.5 rounded-lg border border-border bg-surface-2 p-2.5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-1.5 text-caption font-medium text-foreground">
          <Link2 className="size-3.5 text-muted-foreground" aria-hidden="true" />
          关联决策卡
        </div>
        <RiskBadge level={decision.signal.level} />
      </div>

      <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-tiny text-muted-foreground">
        <span className="metric-value" title={decision.run_id}>
          {truncateMiddle(decision.run_id, 18, 8)}
        </span>
        <span>as_of {decision.as_of}</span>
        <span>{modeMeta(decision.mode).label}</span>
        <span>证据 {decision.evidence?.length ?? 0} 条</span>
        <span>冲突 {decision.conflicts?.length ?? 0} 项</span>
      </div>

      {roles.length ? (
        <div className="mt-1.5 flex flex-wrap gap-1.5">
          {roles.map((role) => (
            <span
              key={role}
              className="inline-flex items-center gap-1 rounded-md border border-border bg-surface-1 px-1.5 py-0.5 text-tiny"
            >
              <span className="text-muted-foreground">{roleMeta(role).label}</span>
              <LevelText
                level={decision.cards[role]?.risk_level}
                className={cn("text-tiny", RISK_TONE[decision.cards[role]?.risk_level ?? "low"])}
              />
            </span>
          ))}
        </div>
      ) : null}

      <p
        className={cn(
          "mt-1.5 whitespace-pre-line text-caption leading-relaxed text-foreground/80",
          !expanded && canExpand && "line-clamp-2",
        )}
      >
        {advice}
      </p>
      {canExpand ? (
        <button
          type="button"
          onClick={() => setExpanded((value) => !value)}
          aria-expanded={expanded}
          className="mt-0.5 text-caption text-muted-foreground underline-offset-2 hover:text-foreground hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          {expanded ? "收起建议" : "展开建议"}
        </button>
      ) : null}

      <div className="mt-2 flex flex-wrap gap-2">
        <Button variant="outline" size="sm" onClick={openDashboard}>
          <ExternalLink aria-hidden="true" />
          在驾驶台打开
        </Button>
        <Button variant="ghost" size="sm" onClick={downloadBriefing} disabled={downloading}>
          {downloading ? (
            <Loader2 className="animate-spin" aria-hidden="true" />
          ) : (
            <Download aria-hidden="true" />
          )}
          {downloading ? "准备简报" : "下载简报"}
        </Button>
      </div>
    </div>
  );
}
