import { cn } from "@/lib/utils";

interface SparklineProps {
  values: (number | null)[];
  className?: string;
  label?: string;
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

/** 期限结构迷你趋势：纯 SVG、无渐变/发光，只表达 5→10→20 日的概率走向。 */
export function Sparkline({
  values,
  className,
  label = "5 / 10 / 20 日高压力概率期限结构",
}: SparklineProps) {
  const width = 160;
  const height = 40;
  const pad = 4;
  const usable = values.filter((value): value is number => typeof value === "number");

  if (!usable.length) {
    return <div className={cn("h-10 w-full", className)} aria-hidden="true" />;
  }

  const step = (width - pad * 2) / Math.max(values.length - 1, 1);
  const points = values.map((value, index) => {
    if (typeof value !== "number") return null;
    return {
      x: pad + index * step,
      y: height - pad - clamp(value, 0, 1) * (height - pad * 2),
    };
  });
  const drawn = points.filter((point): point is { x: number; y: number } => point !== null);
  const path = drawn
    .map((point, index) => `${index === 0 ? "M" : "L"}${point.x.toFixed(1)},${point.y.toFixed(1)}`)
    .join(" ");
  const last = drawn.at(-1);

  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      className={cn("h-10 w-full", className)}
      role="img"
      aria-label={label}
      preserveAspectRatio="none"
    >
      <path
        d={path}
        fill="none"
        stroke="var(--viz-1)"
        strokeWidth={1.5}
        strokeLinecap="round"
        strokeLinejoin="round"
        vectorEffect="non-scaling-stroke"
      />
      {last ? <circle cx={last.x} cy={last.y} r={2.5} fill="var(--viz-1)" /> : null}
    </svg>
  );
}
