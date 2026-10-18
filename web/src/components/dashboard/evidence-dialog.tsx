import { useEffect, useMemo, useState } from "react";
import { CheckCircle2, ExternalLink, FileText } from "lucide-react";

import { DetailRow } from "@/components/common/detail-row";
import { EmptyState } from "@/components/common/empty-state";
import { ErrorState } from "@/components/common/error-state";
import { Badge } from "@/components/ui/badge";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { errorMessage, getEvidence, isAbortError } from "@/lib/api";
import { evidenceKindMeta } from "@/lib/labels";
import { fmtDate, fmtDateTime, fmtMetricValue } from "@/lib/format";
import type { Evidence, SourceRef } from "@/lib/types";

function safeUrl(value: string | null | undefined): string | null {
  if (!value) return null;
  return /^https?:\/\//i.test(value) ? value : null;
}

function SourceLink({ url }: { url: string | null | undefined }) {
  const href = safeUrl(url);
  if (!href) return null;
  return (
    <a
      href={href}
      target="_blank"
      rel="noreferrer noopener"
      className="inline-flex max-w-full items-center gap-1 break-all text-info-ink underline decoration-1 underline-offset-2 hover:text-foreground"
    >
      <span className="break-all">{href}</span>
      <ExternalLink className="size-3 shrink-0" aria-hidden="true" />
    </a>
  );
}

function CitationList({ citations }: { citations: SourceRef[] }) {
  if (!citations.length) return null;
  return (
    <div className="mt-3">
      <div className="text-caption font-medium text-muted-foreground">引文（{citations.length}）</div>
      <ul className="mt-1 space-y-1.5">
        {citations.map((citation, index) => (
          <li
            key={`${citation.doc_id ?? citation.name}-${index}`}
            className="rounded-md border border-border bg-surface-2 px-2 py-1.5 text-caption"
          >
            <div className="font-medium text-foreground">{citation.name || "—"}</div>
            <div className="mt-0.5 flex flex-wrap gap-x-3 gap-y-0.5 text-tiny text-muted-foreground">
              {citation.doc_id ? <span className="font-mono">doc {citation.doc_id}</span> : null}
              {citation.chunk_id ? (
                <span className="font-mono">chunk {citation.chunk_id}</span>
              ) : null}
              {citation.release_time ? (
                <span>发布 {fmtDateTime(citation.release_time)}</span>
              ) : null}
            </div>
            <SourceLink url={citation.url} />
          </li>
        ))}
      </ul>
    </div>
  );
}

function EvidenceBody({ evidence }: { evidence: Evidence }) {
  const kind = evidenceKindMeta(evidence.kind);
  const payload = evidence.payload ?? {};
  const hasPayload = Object.keys(payload).length > 0;
  const citations = evidence.citations ?? [];

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant="outline">{kind.label}</Badge>
        {evidence.verified === true ? (
          <Badge variant="success">
            <CheckCircle2 className="size-3" aria-hidden="true" />
            已核验
          </Badge>
        ) : evidence.verified === false ? (
          <Badge variant="destructive">未通过核验</Badge>
        ) : (
          <Badge variant="muted">未标注核验</Badge>
        )}
        {evidence.value !== null && evidence.value !== undefined ? (
          <span className="metric-value text-body text-foreground">
            {fmtMetricValue(evidence.value, evidence.unit)}
          </span>
        ) : null}
      </div>

      {evidence.summary ? (
        <p className="whitespace-pre-line text-body leading-relaxed text-foreground/85">
          {evidence.summary}
        </p>
      ) : null}

      <dl className="rounded-lg border border-border bg-surface-2 px-3 py-1">
        <DetailRow label="证据 ID" mono>
          {evidence.evidence_id}
        </DetailRow>
        <DetailRow label="证据类型">{kind.label}</DetailRow>
        <DetailRow label="证据时点" mono>
          {fmtDate(evidence.as_of)}
        </DetailRow>
        <DetailRow label="产出方">{evidence.produced_by || "—"}</DetailRow>
        <DetailRow label="来源">{evidence.source?.name || "—"}</DetailRow>
        {evidence.source?.doc_id ? (
          <DetailRow label="文档 ID" mono>
            {evidence.source.doc_id}
          </DetailRow>
        ) : null}
        {evidence.source?.chunk_id ? (
          <DetailRow label="片段 ID" mono>
            {evidence.source.chunk_id}
          </DetailRow>
        ) : null}
        {evidence.source?.release_time ? (
          <DetailRow label="发布时间" mono>
            {fmtDateTime(evidence.source.release_time)}
          </DetailRow>
        ) : null}
        <DetailRow label="来源链接">
          <SourceLink url={evidence.source?.url} />
          {!evidence.source?.url ? "—" : null}
        </DetailRow>
        {evidence.tool ? (
          <>
            <DetailRow label="工具" mono>
              {evidence.tool.name} v{evidence.tool.version}
            </DetailRow>
            <DetailRow label="工具耗时" mono>
              {evidence.tool.elapsed_ms ?? 0} ms
            </DetailRow>
            <DetailRow label="输入哈希" mono>
              {evidence.tool.inputs_hash || "—"}
            </DetailRow>
          </>
        ) : null}
        <DetailRow label="证据哈希" mono>
          {evidence.hash || "—"}
        </DetailRow>
        <DetailRow label="生成时间" mono>
          {fmtDateTime(evidence.created_at)}
        </DetailRow>
      </dl>

      <div>
        <div className="text-caption font-medium text-muted-foreground">payload</div>
        {hasPayload ? (
          <pre className="scrollbar-thin terminal mt-1 max-h-56 overflow-auto p-2.5 font-mono text-caption leading-relaxed">
            {JSON.stringify(payload, null, 2)}
          </pre>
        ) : (
          <p className="mt-1 text-caption text-muted-foreground">该证据无结构化 payload。</p>
        )}
      </div>

      <CitationList citations={citations} />

      <p className="border-t border-border pt-2 text-caption leading-relaxed text-muted-foreground">
        证据来自本次协同运行的黑板快照；数值型证据可按工具名 + 版本 + 输入哈希重算复核。
      </p>
    </div>
  );
}

interface EvidenceDialogProps {
  evidenceId: string | null;
  evidenceList: Evidence[];
  onOpenChange: (open: boolean) => void;
}

/** 证据 Dialog：优先使用决策卡黑板快照；缺失时回退 GET /api/evidence/{id}。 */
export function EvidenceDialog({ evidenceId, evidenceList, onOpenChange }: EvidenceDialogProps) {
  const [evidence, setEvidence] = useState<Evidence | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<unknown>(null);

  const localMatch = useMemo(
    () => evidenceList.find((item) => item.evidence_id === evidenceId) ?? null,
    [evidenceId, evidenceList],
  );

  useEffect(() => {
    if (!evidenceId) {
      setEvidence(null);
      setError(null);
      setLoading(false);
      return;
    }
    if (localMatch) {
      setEvidence(localMatch);
      setError(null);
      setLoading(false);
      return;
    }

    let active = true;
    const controller = new AbortController();
    setEvidence(null);
    setError(null);
    setLoading(true);
    void getEvidence(evidenceId, controller.signal)
      .then((item) => {
        if (!active) return;
        setEvidence(item);
        setLoading(false);
      })
      .catch((reason: unknown) => {
        if (!active || isAbortError(reason)) return;
        setError(reason);
        setLoading(false);
      });

    return () => {
      active = false;
      controller.abort();
    };
  }, [evidenceId, localMatch]);

  const kind = evidence ? evidenceKindMeta(evidence.kind) : null;

  return (
    <Dialog open={Boolean(evidenceId)} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle className="pr-6">
            {evidence?.title || (loading ? "证据详情" : "证据不可解析")}
          </DialogTitle>
          <DialogDescription className="break-all">
            {evidence
              ? `${kind?.label ?? "证据"} · as_of ${fmtDate(evidence.as_of)} · ${evidence.evidence_id}`
              : evidenceId
                ? `evidence_id：${evidenceId}`
                : ""}
          </DialogDescription>
        </DialogHeader>

        <div className="mt-3">
          {loading ? (
            <div className="space-y-2" aria-busy="true" aria-label="证据加载中">
              <Skeleton className="h-4 w-2/5" />
              <Skeleton className="h-3 w-full" />
              <Skeleton className="h-3 w-4/5" />
              <Skeleton className="h-24 w-full" />
            </div>
          ) : error ? (
            <ErrorState
              title="证据读取失败"
              message={errorMessage(error)}
              hint={
                evidenceId
                  ? `被引用的证据 ${evidenceId} 未通过黑板 / artifacts 暴露；这不是界面错误，可在服务日志确认证据检索接口。`
                  : undefined
              }
            />
          ) : evidence ? (
            <EvidenceBody evidence={evidence} />
          ) : (
            <EmptyState
              title="没有可展示的证据"
              icon={<FileText />}
              description="请从证据板选择一条证据。"
            />
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
