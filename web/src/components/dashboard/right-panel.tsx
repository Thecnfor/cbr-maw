import { useId } from "react";
import {
  BadgeCheck,
  Database,
  Download,
  FileText,
  Scale,
  ShieldCheck,
} from "lucide-react";

import { Card } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ConflictsPanel } from "@/components/dashboard/conflicts-panel";
import { DataCardsPanel } from "@/components/dashboard/data-cards-panel";
import { EvidenceBoard } from "@/components/dashboard/evidence-board";
import { ExportPanel } from "@/components/dashboard/export-panel";
import { VerificationPanel } from "@/components/dashboard/verification-panel";
import type { DataCardsResource, TraceResource } from "@/lib/resources";
import type { DecisionCard } from "@/lib/types";

export const DASHBOARD_TABS = [
  "evidence",
  "conflicts",
  "verification",
  "data",
  "export",
] as const;

export type DashboardTab = (typeof DASHBOARD_TABS)[number];

export function isDashboardTab(value: string | null | undefined): value is DashboardTab {
  return Boolean(value) && (DASHBOARD_TABS as readonly string[]).includes(value as string);
}

interface RightPanelProps {
  decision: DecisionCard;
  tab: DashboardTab;
  onTabChange: (tab: DashboardTab) => void;
  onOpenEvidence: (evidenceId: string) => void;
  missingEvidenceIds: string[];
  trace: TraceResource;
  dataCards: DataCardsResource;
  scenarioName: string;
}

/** 右栏：证据板 / 分歧 / 核验与审计 / 数据卡 / 导出，Radix Tabs 组织。 */
export function RightPanel({
  decision,
  tab,
  onTabChange,
  onOpenEvidence,
  missingEvidenceIds,
  trace,
  dataCards,
  scenarioName,
}: RightPanelProps) {
  const titleId = useId();
  const evidence = decision.evidence ?? [];
  const conflicts = decision.conflicts ?? [];
  const issues = decision.verification?.issues ?? [];

  return (
    <Card
      asChild
      className="flex min-w-0 flex-col overflow-hidden min-[1180px]:sticky min-[1180px]:top-4 min-[1180px]:h-[calc(100dvh-84px)]"
    >
      <section aria-labelledby={titleId}>
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border px-4 py-2.5">
          <h2
            id={titleId}
            className="flex items-center gap-2 text-desc font-semibold tracking-tight text-foreground"
          >
            <ShieldCheck className="size-4 text-muted-foreground" aria-hidden="true" />
            协同证据与审计
          </h2>
          <span
            className="metric-value max-w-[190px] truncate text-caption text-muted-foreground"
            title={decision.run_id}
          >
            {decision.run_id}
          </span>
        </div>

        <Tabs
          value={tab}
          onValueChange={(value) => {
            if (isDashboardTab(value)) onTabChange(value);
          }}
          className="flex min-h-0 min-w-0 flex-1 flex-col"
        >
          <div className="px-2">
            <TabsList aria-label="协同证据与审计分区">
              <TabsTrigger value="evidence">
                <FileText className="hidden sm:inline" aria-hidden="true" />
                证据
                <span className="metric-value text-tiny text-muted-foreground">
                  {evidence.length}
                </span>
              </TabsTrigger>
              <TabsTrigger value="conflicts">
                <Scale className="hidden sm:inline" aria-hidden="true" />
                分歧
                <span className="metric-value text-tiny text-muted-foreground">
                  {conflicts.length}
                </span>
              </TabsTrigger>
              <TabsTrigger value="verification">
                <BadgeCheck className="hidden sm:inline" aria-hidden="true" />
                核验
                {issues.length ? (
                  <span className="metric-value text-tiny text-destructive-ink">
                    {issues.length}
                  </span>
                ) : null}
              </TabsTrigger>
              <TabsTrigger value="data">
                <Database className="hidden sm:inline" aria-hidden="true" />
                数据卡
                {dataCards.cards.length ? (
                  <span className="metric-value text-tiny text-muted-foreground">
                    {dataCards.cards.length}
                  </span>
                ) : null}
              </TabsTrigger>
              <TabsTrigger value="export">
                <Download className="hidden sm:inline" aria-hidden="true" />
                导出
              </TabsTrigger>
            </TabsList>
          </div>

          <TabsContent
            value="evidence"
            forceMount
            className="min-h-0 flex-1 overflow-hidden p-4"
          >
            <EvidenceBoard
              evidences={evidence}
              missingIds={missingEvidenceIds}
              onOpenEvidence={onOpenEvidence}
            />
          </TabsContent>

          <TabsContent
            value="conflicts"
            className="scrollbar-thin min-h-0 flex-1 overflow-y-auto p-4"
          >
            <ConflictsPanel conflicts={conflicts} />
          </TabsContent>

          <TabsContent
            value="verification"
            className="scrollbar-thin min-h-0 flex-1 overflow-y-auto p-4"
          >
            <VerificationPanel decision={decision} trace={trace} />
          </TabsContent>

          <TabsContent
            value="data"
            className="scrollbar-thin min-h-0 flex-1 overflow-y-auto p-4"
          >
            <DataCardsPanel resource={dataCards} />
          </TabsContent>

          <TabsContent
            value="export"
            className="scrollbar-thin min-h-0 flex-1 overflow-y-auto p-4"
          >
            <ExportPanel
              decision={decision}
              evidence={evidence}
              trace={trace.events}
              scenarioName={scenarioName}
            />
          </TabsContent>
        </Tabs>
      </section>
    </Card>
  );
}
