import { clsx, type ClassValue } from "clsx";
import { extendTailwindMerge } from "tailwind-merge";

/**
 * Tailwind v4 自定义字号 token（text-tiny/caption/body/desc/panel/h1/metric）。
 * tailwind-merge 默认不认识这些名字，会把它们当作 text-color 与
 * `text-primary-foreground` 等颜色类判为冲突并丢弃后者（曾导致主按钮黑底黑字）。
 * 这里显式把它们归入 font-size 组，颜色与字号即可共存。
 */
const twMerge = extendTailwindMerge({
  extend: {
    classGroups: {
      "font-size": [
        "text-tiny",
        "text-caption",
        "text-body",
        "text-desc",
        "text-panel",
        "text-h1",
        "text-metric",
      ],
    },
  },
});

/** 合并 Tailwind 类名（clsx + 已扩展的 tailwind-merge），组件统一入口。 */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}
