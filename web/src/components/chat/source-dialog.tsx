import { useMemo } from "react";
import { ExternalLink } from "lucide-react";

import { DetailRow, MicroLabel } from "@/components/common/detail-row";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Badge } from "@/components/ui/badge";
import { fmtDate, fmtDateTime, fmtMetricValue } from "@/lib/format";
import { evidenceKindMeta } from "@/lib/labels";
import type { Evidence, SourceRef } from "@/lib/types";

function safeUrl(value: string | null | undefined): string | null {
  if (!value) return null;
  return /^https?:\/\//i.test(value) ? value : null;
}

interface SourceDialogProps {
  citation: SourceRef | null;
  evidenceList: Evidence[];
  onOpenChange: (open: boolean) => void;
  onOpenEvidence: (evidenceId: string) => void;
}

/** 对话引用来源 Dialog：展示可追溯字段；若能匹配黑板证据，可继续打开完整证据。 */
export function SourceDialog({
  citation,
  evidenceList,
  onOpenChange,
  onOpenEvidence,
}: SourceDialogProps) {
  const matched = useMemo(() => {
    if (!citation) return null;
    const docId = citation.doc_id;
    if (!docId) return null;
    return (
      evidenceList.find(
        (item) =>
          item.source?.doc_id === docId &&
          (!citation.chunk_id || item.source?.chunk_id === citation.chunk_id),
      ) ??
      evidenceList.find((item) => item.source?.doc_id === docId) ??
      null
    );
  }, [citation, evidenceList]);

  const href = safeUrl(citation?.url);

  return (
    <Dialog open={Boolean(citation)} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>{citation?.name || "引用来源"}</DialogTitle>
          <DialogDescription>对话引用的来源与可追溯信息</DialogDescription>
        </DialogHeader>

        {citation ? (
          <dl className="mt-2 rounded-lg border border-border bg-surface-2 px-3 py-1">
            <DetailRow label="来源名称">{citation.name || "—"}</DetailRow>
            <DetailRow label="文档 ID" mono>
              {citation.doc_id || "—"}
            </DetailRow>
            <DetailRow label="片段 ID" mono>
              {citation.chunk_id || "—"}
            </DetailRow>
            <DetailRow label="发布时间" mono>
              {fmtDateTime(citation.release_time)}
            </DetailRow>
            <DetailRow label="来源链接">
              {href ? (
                <a
                  href={href}
                  target="_blank"
                  rel="noreferrer noopener"
                  className="inline-flex max-w-full items-center gap-1 break-all text-info-ink underline decoration-1 underline-offset-2 hover:text-foreground"
                >
                  {href}
                  <ExternalLink className="size-3 shrink-0" aria-hidden="true" />
                </a>
              ) : (
                "—"
              )}
            </DetailRow>
          </dl>
        ) : null}

        {matched ? (
          <div className="mt-3 rounded-lg border border-border bg-surface-2 p-2.5">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <MicroLabel>匹配到黑板证据</MicroLabel>
              <Badge variant="outline">{evidenceKindMeta(matched.kind).label}</Badge>
            </div>
            <p className="mt-1 text-caption font-medium text-foreground">{matched.title}</p>
            <p className="mt-0.5 break-all font-mono text-tiny text-muted-foreground">
              {matched.evidence_id} · as_of {fmtDate(matched.as_of)}
            </p>
            {matched.value !== null && matched.value !== undefined ? (
              <p className="metric-value mt-1 text-caption text-foreground">
                {fmtMetricValue(matched.value, matched.unit)}
              </p>
            ) : null}
            <Button
              variant="outline"
              size="sm"
              className="mt-2"
              onClick={() => {
                onOpenChange(false);
                onOpenEvidence(matched.evidence_id);
              }}
            >
              查看完整证据
            </Button>
          </div>
        ) : (
          <p className="mt-3 text-caption leading-relaxed text-muted-foreground">
            该引用未在关联决策卡的黑板快照中匹配到完整证据；可复制 doc_id / chunk_id
            到证据板检索，或等待编排层补齐证据检索接口。
          </p>
        )}
      </DialogContent>
    </Dialog>
  );
}
