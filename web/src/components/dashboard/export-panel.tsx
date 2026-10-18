import { useMemo, useState } from "react";
import { Download, FileJson, FileText, ScrollText } from "lucide-react";

import { MicroLabel } from "@/components/common/detail-row";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  briefingFileSlug,
  buildJsonBriefing,
  buildMarkdownBriefing,
  buildTraceJsonl,
  downloadText,
} from "@/lib/export";
import type { DecisionCard, Evidence, TraceEvent } from "@/lib/types";
import { cn } from "@/lib/utils";

interface ExportPanelProps {
  decision: DecisionCard;
  evidence: Evidence[];
  trace: TraceEvent[];
  scenarioName: string;
}

type PreviewMode = "markdown" | "json";

export function ExportPanel({
  decision,
  evidence,
  trace,
  scenarioName,
}: ExportPanelProps) {
  const [preview, setPreview] = useState<PreviewMode>("markdown");

  const markdown = useMemo(
    () => buildMarkdownBriefing(decision, evidence, trace, scenarioName),
    [decision, evidence, trace, scenarioName],
  );
  const json = useMemo(
    () => buildJsonBriefing(decision, evidence, trace, scenarioName),
    [decision, evidence, trace, scenarioName],
  );
  const jsonl = useMemo(() => buildTraceJsonl(trace), [trace]);
  const slug = briefingFileSlug(decision);

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-2">
        <Button
          variant="outline"
          size="sm"
          onClick={() => downloadText(`${slug}.md`, markdown, "text/markdown;charset=utf-8")}
        >
          <FileText aria-hidden="true" />
          Markdown 简报
        </Button>
        <Button
          variant="outline"
          size="sm"
          onClick={() => downloadText(`${slug}.json`, json, "application/json;charset=utf-8")}
        >
          <FileJson aria-hidden="true" />
          JSON 数据包
        </Button>
        <Button
          variant="outline"
          size="sm"
          disabled={!trace.length}
          onClick={() =>
            downloadText(`${slug}_trace.jsonl`, jsonl, "application/x-ndjson;charset=utf-8")
          }
        >
          <ScrollText aria-hidden="true" />
          审计 JSONL
        </Button>
      </div>

      <p className="text-caption leading-relaxed text-muted-foreground">
        简报固定包含 as_of、run_id、共享信号、三主体卡片、冲突协调、核验结果与证据清单
        （当前证据 {evidence.length} 条、trace {trace.length} 条）。
      </p>

      <div>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <MicroLabel>简报预览</MicroLabel>
          <div
            role="group"
            aria-label="预览格式"
            className="inline-flex items-center gap-0.5 rounded-md border border-border p-0.5"
          >
            {(["markdown", "json"] as const).map((mode) => (
              <button
                key={mode}
                type="button"
                aria-pressed={preview === mode}
                onClick={() => setPreview(mode)}
                className={cn(
                  "rounded px-2 py-0.5 text-caption transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                  preview === mode
                    ? "bg-surface-2 text-foreground"
                    : "text-muted-foreground hover:text-foreground",
                )}
              >
                {mode === "markdown" ? "Markdown" : "JSON"}
              </button>
            ))}
          </div>
        </div>

        <ScrollArea className="terminal mt-1.5 h-[360px] sm:h-[420px]">
          <pre className="whitespace-pre-wrap break-words p-2.5 font-mono text-caption leading-relaxed">
            {preview === "markdown" ? markdown : json}
          </pre>
        </ScrollArea>

        <p className="mt-1 break-all text-tiny text-muted-foreground">
          文件名：{slug}.md / {slug}.json
        </p>
      </div>

      <p className="flex items-center gap-1.5 border-t border-border pt-2 text-caption text-muted-foreground">
        <Download className="size-3.5" aria-hidden="true" />
        下载为浏览器本地文件，不写入服务端，也不影响本次决策结果。
      </p>
    </div>
  );
}
