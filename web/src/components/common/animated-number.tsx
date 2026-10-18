import { useEffect, useRef, useState } from "react";

import { usePrefersReducedMotion } from "@/lib/motion";

interface AnimatedNumberProps {
  value: number | null;
  format: (value: number) => string;
  duration?: number;
  className?: string;
}

/**
 * KPI count-up：仅首次出现（或数值变化）时从当前显示值过渡到目标值。
 * reduced-motion 直接落位；动画只写文本，不改布局。
 */
export function AnimatedNumber({
  value,
  format,
  duration = 680,
  className,
}: AnimatedNumberProps) {
  const reduced = usePrefersReducedMotion();
  const [display, setDisplay] = useState(() => (reduced ? (value ?? 0) : 0));
  const displayRef = useRef(reduced ? (value ?? 0) : 0);
  const frameRef = useRef<number | null>(null);
  const formatRef = useRef(format);
  formatRef.current = format;

  useEffect(() => {
    if (value === null || !Number.isFinite(value)) return;

    if (frameRef.current !== null) {
      cancelAnimationFrame(frameRef.current);
      frameRef.current = null;
    }

    if (reduced) {
      displayRef.current = value;
      setDisplay(value);
      return;
    }

    const from = displayRef.current;
    if (from === value) return;

    const start = performance.now();
    const tick = (now: number) => {
      const progress = Math.min(1, (now - start) / duration);
      const eased = 1 - Math.pow(1 - progress, 3);
      const next = from + (value - from) * eased;
      displayRef.current = next;
      setDisplay(next);
      if (progress < 1) {
        frameRef.current = requestAnimationFrame(tick);
      } else {
        displayRef.current = value;
        setDisplay(value);
        frameRef.current = null;
      }
    };
    frameRef.current = requestAnimationFrame(tick);

    return () => {
      if (frameRef.current !== null) {
        cancelAnimationFrame(frameRef.current);
        frameRef.current = null;
      }
    };
  }, [value, reduced, duration]);

  if (value === null || !Number.isFinite(value)) {
    return <span className={className}>—</span>;
  }

  return <span className={className}>{formatRef.current(display)}</span>;
}
