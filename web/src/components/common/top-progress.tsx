/**
 * 顶部 2px 运行进度条：只表达「有请求正在进行」，不伪造百分比。
 * 固定在视口顶部，位于顶栏之上、弹层之下；只动 transform。
 */
export function TopProgress({
  active,
  label = "请求进行中",
}: {
  active: boolean;
  label?: string;
}) {
  if (!active) return null;
  return (
    <div
      className="pointer-events-none fixed inset-x-0 top-0 z-40 h-0.5 overflow-hidden"
      role="progressbar"
      aria-label={label}
      aria-valuetext={label}
    >
      <div className="h-full w-1/3 bg-primary animate-run-progress" />
    </div>
  );
}
