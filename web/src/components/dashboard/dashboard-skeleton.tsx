import { AnalysisProgress } from "@/components/common/analysis-progress";

/** 与真实布局同尺寸的骨架屏：KPI 2fr/1fr/1fr + 主网格 3:2。 */
export function DashboardSkeleton({ startedAt }: { startedAt: number | null }) {
  return (
    <div className="mt-4 space-y-4" aria-busy="true">
      {startedAt ? <AnalysisProgress active startedAt={startedAt} /> : null}

      <div className="grid gap-3 min-[1180px]:grid-cols-[2fr_1fr_1fr] min-[1180px]:grid-rows-[auto_auto]">
        <div className="skeleton h-[264px] rounded-card min-[1180px]:row-span-2" />
        <div className="skeleton h-[120px] rounded-card" />
        <div className="skeleton h-[120px] rounded-card" />
        <div className="skeleton h-[120px] rounded-card min-[1180px]:col-span-2" />
      </div>

      <div className="grid gap-4 min-[1180px]:grid-cols-[3fr_2fr]">
        <div className="min-w-0 space-y-4">
          <div className="skeleton h-[336px] rounded-card" />
          <div className="grid gap-4 md:grid-cols-[3fr_2fr]">
            <div className="skeleton h-[336px] rounded-card" />
            <div className="skeleton h-[336px] rounded-card" />
          </div>
          <div className="skeleton h-[286px] rounded-card" />
        </div>
        <div className="skeleton h-[640px] rounded-card" />
      </div>
    </div>
  );
}
