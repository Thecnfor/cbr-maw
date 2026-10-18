import type { ReactNode } from "react";

import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { shiftISODate, todayISO } from "@/lib/format";
import { MODE_META, MODE_OPTIONS } from "@/lib/labels";
import { useRun } from "@/lib/run-context";
import type { ExperimentMode } from "@/lib/types";
import { cn } from "@/lib/utils";

function ModeSegmented({
  value,
  onChange,
  large = false,
}: {
  value: ExperimentMode;
  onChange: (value: ExperimentMode) => void;
  large?: boolean;
}) {
  return (
    <div
      role="group"
      aria-label="实验模式（消融对照）"
      className={cn(
        "inline-flex items-center gap-0.5 rounded-lg border border-border bg-control-track p-0.5",
        large ? "h-10" : "h-8",
      )}
    >
      {MODE_OPTIONS.map((mode) => {
        const active = mode === value;
        return (
          <button
            key={mode}
            type="button"
            aria-pressed={active}
            onClick={() => onChange(mode)}
            className={cn(
              "rounded-md px-2 text-caption font-medium transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
              large ? "h-8" : "h-7",
              active
                ? "bg-control-active text-foreground"
                : "text-muted-foreground hover:text-foreground",
            )}
            title={MODE_META[mode].label}
          >
            {MODE_META[mode].short}
          </button>
        );
      })}
    </div>
  );
}

function Field({
  label,
  children,
  className,
}: {
  label: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("flex min-w-0 flex-col gap-1", className)}>
      <span className="text-caption text-muted-foreground">{label}</span>
      {children}
    </div>
  );
}

interface RunControlsProps {
  variant?: "topbar" | "page";
  className?: string;
}

/**
 * 运行条件控件：场景 / 时点 / 三模式。
 * 顶栏（xl+）与页面内控制条（<xl）共用同一组状态，任意断点都不会重复出现。
 */
export function RunControls({ variant = "topbar", className }: RunControlsProps) {
  const {
    scenarios,
    scenarioId,
    setScenarioId,
    asOf,
    setAsOf,
    mode,
    setMode,
    scenariosLoading,
  } = useRun();

  const maxDate = shiftISODate(todayISO(), 1);

  const scenarioSelect = (
    <Select
      value={scenarioId}
      onValueChange={setScenarioId}
      disabled={!scenarios.length}
    >
      <SelectTrigger
        aria-label="选择演示场景"
        className={variant === "topbar" ? "w-[176px]" : "h-10 w-full"}
      >
        <SelectValue placeholder={scenariosLoading ? "场景加载中…" : "选择演示场景"} />
      </SelectTrigger>
      <SelectContent>
        {scenarios.map((scenario) => (
          <SelectItem key={scenario.scenario_id} value={scenario.scenario_id}>
            {scenario.name}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );

  const dateInput = (
    <Input
      type="date"
      aria-label="分析时点（Point-in-Time）"
      min="2005-01-01"
      max={maxDate}
      value={asOf}
      onChange={(event) => setAsOf(event.target.value)}
      className={cn(
        "metric-value text-caption",
        variant === "topbar" ? "w-[132px]" : "h-10 w-full",
      )}
    />
  );

  const modeControl = (
    <ModeSegmented value={mode} onChange={setMode} large={variant === "page"} />
  );

  if (variant === "page") {
    return (
      <div className={cn("grid gap-3 sm:grid-cols-2", className)}>
        <Field label="演示场景">{scenarioSelect}</Field>
        <Field label="分析时点（Point-in-Time）">{dateInput}</Field>
        <Field label="实验模式（消融对照）" className="sm:col-span-2">
          {modeControl}
        </Field>
      </div>
    );
  }

  return (
    <div className={cn("flex items-center gap-2", className)}>
      {scenarioSelect}
      {dateInput}
      {modeControl}
    </div>
  );
}
