import {
  evidenceKindMeta,
  conflictTypeLabel,
  issueTypeLabel,
  modeMeta,
  resolvedByLabel,
  riskMeta,
  ROLE_ORDER,
  roleMeta,
} from "@/lib/labels";
import {
  fmtDate,
  fmtDateTime,
  fmtMetricValue,
  fmtNum,
  fmtPct,
  fmtDuration,
  fmtTokens,
  fmtCostUnits,
  horizonsOf,
  toNumber,
} from "@/lib/format";
import type { DecisionCard, Evidence, TraceEvent } from "@/lib/types";

/**
 * 与 Streamlit `build_markdown_briefing` 对齐的可复核简报。
 * 纯函数：只依赖 decision / evidence / trace，不读取组件状态。
 */
export function buildMarkdownBriefing(
  decision: DecisionCard,
  evidences: Evidence[] = [],
  traceEvents: TraceEvent[] | null = null,
  scenarioName?: string | null,
): string {
  const signal = decision.signal;
  const lines: string[] = [];
  const push = (...items: string[]) => lines.push(...items);

  push(
    "# CBR-MAW 跨境金融风险预警简报",
    "",
    `- **场景**：${scenarioName || decision.scenario || "—"}`,
    `- **分析时点（as_of）**：${fmtDate(decision.as_of)}`,
    `- **实验模式**：${modeMeta(decision.mode).label}`,
    `- **运行 ID**：\`${decision.run_id || "—"}\``,
    `- **生成时间**：${fmtDateTime(decision.created_at)}`,
    "",
    "## 一、共享风险信号",
    "",
    `- 综合风险等级：**${riskMeta(signal.level).label}**`,
    `- 模型版本：${signal.model_version || "—"}（标签版本 ${signal.label_version || "—"}）`,
  );

  for (const point of horizonsOf(signal)) {
    push(`- ${point.horizon} 日高压力概率：${fmtPct(point.value)}`);
  }
  push(`- 历史分位：${fmtPct(signal.percentile)}`);

  const drivers = [...(signal.drivers ?? [])]
    .filter((driver) => toNumber(driver.contribution) !== null)
    .sort(
      (left, right) =>
        Math.abs(toNumber(right.contribution) ?? 0) -
        Math.abs(toNumber(left.contribution) ?? 0),
    )
    .slice(0, 5);
  if (drivers.length) {
    push("- 主要驱动因子：");
    for (const driver of drivers) {
      const direction = driver.direction === "down" ? "缓解" : "推高";
      const description = driver.description ? `：${driver.description}` : "";
      push(
        `  - \`${driver.factor}\`（贡献 ${fmtNum(driver.contribution, 3)}，${direction}风险）${description}`,
      );
    }
  }

  const modality = signal.modality_contrib ?? {};
  if (Object.keys(modality).length) {
    push(
      "- 模态贡献：" +
        Object.entries(modality)
          .map(([key, value]) => `${key} ${fmtPct(value)}`)
          .join("、"),
    );
  }
  push("");

  push("## 二、三主体判断与建议", "");
  const cards = decision.cards ?? {};
  const roles = ROLE_ORDER.filter((role) => cards[role]);
  if (!roles.length) {
    push("（本次运行未包含三主体结果，可能处于单智能体模式。）", "");
  }
  for (const role of roles) {
    const card = cards[role];
    const meta = roleMeta(role);
    push(
      `### ${meta.label} · 风险等级：${riskMeta(card.risk_level).label}`,
      "",
      `- 核心结论：${card.headline || "—"}`,
    );
    const metrics = (card.key_metrics ?? []).slice(0, 4);
    if (metrics.length) {
      push(
        "- 关键指标：" +
          metrics
            .map(
              (metric) =>
                `${metric.label || metric.name} = ${fmtMetricValue(metric.value, metric.unit)}`,
            )
            .join("；"),
      );
    }
    push(`- 建议：${card.recommendation || "—"}`);
    const confidences = (card.claims ?? [])
      .map((claim) => claim.confidence)
      .filter((value): value is number => typeof value === "number");
    if (confidences.length) {
      const average =
        confidences.reduce((sum, value) => sum + value, 0) / confidences.length;
      push(`- 置信度（主张均值）：${fmtPct(average)}`);
    }
    const limitations = (card.limitations ?? []).filter(Boolean);
    if (limitations.length) push(`- 局限：${limitations.join("；")}`);
    push("");
  }

  push("## 三、分歧与协调", "");
  const conflicts = decision.conflicts ?? [];
  if (!conflicts.length) {
    push("本轮未检测到智能体间冲突。", "");
  } else {
    for (const conflict of conflicts) {
      const status = conflict.resolved ? "已解决" : "未解决";
      push(
        `- **${conflict.subject || "未命名冲突"}**（${conflictTypeLabel(conflict.type)} · ${status}）：${conflict.description || "—"}`,
      );
      if (conflict.resolved) {
        push(
          `  - 协调结果（${resolvedByLabel(conflict.resolved_by)}）：${conflict.resolution || "—"}`,
        );
      }
    }
    push("");
  }

  push("## 四、核验与审计", "");
  const report = decision.verification ?? {};
  const numericTotal = toNumber(report.numeric_checks_total) ?? 0;
  const numericPassed = toNumber(report.numeric_checks_passed) ?? 0;
  const citationTotal = toNumber(report.citation_checks_total) ?? 0;
  const citationPassed = toNumber(report.citation_checks_passed) ?? 0;
  push(
    `- 核验结论：${report.passed === true ? "通过" : report.passed === false ? "存在异常" : "—"}`,
    `- 数值核验：${numericPassed} / ${numericTotal}（错误率 ${fmtPct(report.numeric_error_rate)}）`,
    `- 引文核验：${citationPassed} / ${citationTotal}（证据准确率 ${fmtPct(report.evidence_accuracy)}）`,
    `- 越权拦截：${toNumber(report.permission_violations) ?? 0} 次；时点泄漏：${
      toNumber(report.leakage_events) ?? 0
    } 次；Schema 错误：${toNumber(report.schema_errors) ?? 0} 次`,
    `- 审计轨迹：\`${decision.trace_ref || "—"}\`，事件 ${traceEvents?.length ?? 0} 条`,
  );
  const issues = report.issues ?? [];
  if (issues.length) {
    push("- 核验问题：");
    for (const issue of issues) {
      push(`  - [${issueTypeLabel(issue.issue_type)}] ${issue.detail || "—"}`);
    }
  }
  push("");

  push("## 五、证据清单（可复核）", "");
  if (!evidences.length) {
    push("（本次运行未获取到证据对象，证据以 evidence_id 引用形式保留。）");
  }
  for (const item of evidences) {
    const kind = evidenceKindMeta(item.kind);
    const source = item.source?.name ? ` · 来源 ${item.source.name}` : "";
    const tool = item.tool ? ` · 工具 ${item.tool.name} v${item.tool.version}` : "";
    push(
      `- \`${item.evidence_id}\` · ${kind.label} · ${item.title || "—"} · as_of ${fmtDate(
        item.as_of,
      )}${source}${tool}`,
    );
  }
  push("");

  const coordination = decision.coordination ?? {};
  push(
    "## 六、说明与免责声明",
    "",
    "- 本简报由 CBR-MAW 多智能体协同系统在指定 `as_of` 时点、仅使用当日可得信息生成，用于研究与演示。",
    "- 数值与结论均经过数值核验 / 引文溯源 / 时点核验流程；仍存在模型与数据局限，不构成投资建议。",
    `- 协同开销：tokens ${toNumber(coordination.tokens) ?? 0}，工具调用 ${
      toNumber(coordination.tool_calls) ?? 0
    } 次，端到端 ${fmtDuration(coordination.latency_ms ?? 0)}（折算成本 C=${fmtCostUnits(
      coordination.cost_usd,
    )}，tokens ${fmtTokens(coordination.tokens)}）。`,
    "",
  );

  return lines.join("\n");
}

export function buildJsonBriefing(
  decision: DecisionCard,
  evidences: Evidence[] = [],
  traceEvents: TraceEvent[] | null = null,
  scenarioName?: string | null,
): string {
  return JSON.stringify(
    {
      brief_version: "1.0",
      generated_at: new Date().toISOString(),
      scenario_name: scenarioName ?? decision.scenario ?? null,
      decision,
      evidence: evidences,
      trace: traceEvents ?? [],
    },
    null,
    2,
  );
}

export function buildTraceJsonl(traceEvents: TraceEvent[]): string {
  return traceEvents.map((event) => JSON.stringify(event)).join("\n");
}

export function briefingFileSlug(decision: DecisionCard): string {
  const asOf = fmtDate(decision.as_of).replaceAll("-", "");
  const runId = (decision.run_id || "run").replaceAll("/", "_").slice(0, 32);
  return `CBR-MAW_预警简报_${asOf}_${runId}`;
}

/** 触发浏览器下载（Blob + a[download]），不产生后端写入。 */
export function downloadText(filename: string, text: string, mime: string): void {
  const blob = new Blob([text], { type: mime });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.rel = "noopener";
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}
