import type { RiskSignal } from "@/lib/types";

const numberFormatterCache = new Map<string, Intl.NumberFormat>();

function numberFormatter(digits: number): Intl.NumberFormat {
  const key = String(digits);
  let formatter = numberFormatterCache.get(key);
  if (!formatter) {
    formatter = new Intl.NumberFormat("zh-CN", {
      minimumFractionDigits: digits,
      maximumFractionDigits: digits,
    });
    numberFormatterCache.set(key, formatter);
  }
  return formatter;
}

export function toNumber(value: unknown): number | null {
  if (value === null || value === undefined || typeof value === "boolean") return null;
  if (typeof value === "number") return Number.isFinite(value) ? value : null;
  if (typeof value === "string") {
    const trimmed = value.trim();
    if (!trimmed) return null;
    const parsed = Number(trimmed);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

/** 比率 → 百分比；无法解析返回「—」。值 ≤ 1 时按 0-1 比率处理。 */
export function fmtPct(value: unknown, digits = 1, ratio = true): string {
  const number = toNumber(value);
  if (number === null) return "—";
  const pct = ratio && Math.abs(number) <= 1 ? number * 100 : number;
  return `${pct.toFixed(digits)}%`;
}

export function fmtNum(value: unknown, digits = 2): string {
  const number = toNumber(value);
  if (number === null) {
    if (typeof value === "string" && value.trim()) return value;
    return "—";
  }
  return numberFormatter(digits).format(number);
}

export function fmtInteger(value: unknown): string {
  return fmtNum(value, 0);
}

/** 指标值按单位格式化（probability / ratio / bp / z / loss_ratio）。 */
export function fmtMetricValue(value: unknown, unit: unknown): string {
  const unitText = String(unit ?? "").trim();
  const number = toNumber(value);
  if (number === null) {
    if (typeof value === "string" && value.trim()) return value;
    return "—";
  }
  switch (unitText.toLowerCase()) {
    case "probability":
    case "prob":
    case "ratio":
    case "percent":
    case "%":
      return fmtPct(number);
    case "loss_ratio":
      return fmtPct(number, 2);
    case "bp":
    case "bp.":
      return `${fmtNum(number, 0)} bp`;
    case "z":
      return `${fmtNum(number, 2)} z`;
    default:
      return unitText ? `${fmtNum(number, 2)} ${unitText}` : fmtNum(number, 2);
  }
}

function pad(value: number): string {
  return String(value).padStart(2, "0");
}

export function fmtDate(value: unknown): string {
  const text = String(value ?? "").trim();
  if (!text) return "—";
  if (/^\d{4}-\d{2}-\d{2}/.test(text)) return text.slice(0, 10);
  const parsed = new Date(text);
  if (Number.isNaN(parsed.getTime())) return text.slice(0, 10) || "—";
  return `${parsed.getFullYear()}-${pad(parsed.getMonth() + 1)}-${pad(parsed.getDate())}`;
}

export function fmtDateTime(value: unknown): string {
  const text = String(value ?? "").trim();
  if (!text) return "—";
  const parsed = new Date(text);
  if (Number.isNaN(parsed.getTime())) return text.slice(0, 16);
  return `${parsed.getFullYear()}-${pad(parsed.getMonth() + 1)}-${pad(parsed.getDate())} ${pad(
    parsed.getHours(),
  )}:${pad(parsed.getMinutes())}`;
}

export function fmtClock(value: unknown): string {
  const parsed =
    typeof value === "number" ? new Date(value) : new Date(String(value ?? "").trim());
  if (Number.isNaN(parsed.getTime())) return String(value ?? "").slice(11, 19) || "--:--:--";
  return `${pad(parsed.getHours())}:${pad(parsed.getMinutes())}:${pad(parsed.getSeconds())}`;
}

export function fmtDuration(milliseconds: unknown): string {
  const number = toNumber(milliseconds) ?? 0;
  if (number < 1000) return `${Math.round(number)} ms`;
  if (number < 60_000) return `${(number / 1000).toFixed(1)} s`;
  return `${(number / 60_000).toFixed(1)} min`;
}

export function fmtTokens(value: unknown): string {
  const number = toNumber(value);
  if (number === null) return "—";
  if (number >= 1_000_000) return `${(number / 1_000_000).toFixed(1)}M`;
  if (number >= 1_000) return `${(number / 1_000).toFixed(1)}k`;
  return String(Math.round(number));
}

export function fmtUsd(value: unknown): string {
  const number = toNumber(value);
  if (number === null) return "—";
  if (number === 0) return "$0";
  if (Math.abs(number) < 1) return `$${number.toFixed(3)}`;
  return `$${number.toFixed(2)}`;
}

/**
 * 协同成本：后端 `cost_usd` 是按工具调用/token/延迟折算的**统一成本单位**，
 * 不是美元账单；界面显示为无货币符号的数值，避免误导。
 */
export function fmtCostUnits(value: unknown): string {
  const number = toNumber(value);
  if (number === null) return "—";
  return number.toFixed(3);
}

/** 历史分位：0-1 比率或 0-100 百分数统一成 0-100。 */
export function percentilePercent(value: unknown): number | null {
  const number = toNumber(value);
  if (number === null) return null;
  return number <= 1 ? number * 100 : number;
}

export interface HorizonPoint {
  horizon: number;
  value: number | null;
}

export function horizonsOf(signal: RiskSignal | null | undefined): HorizonPoint[] {
  const raw = signal?.horizons ?? {};
  return Object.entries(raw)
    .map(([key, value]) => ({ horizon: Number(key), value: toNumber(value) }))
    .filter((item) => Number.isFinite(item.horizon))
    .sort((a, b) => a.horizon - b.horizon);
}

export function todayISO(): string {
  const now = new Date();
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

export function shiftISODate(iso: string, days: number): string {
  const date = new Date(`${iso}T00:00:00`);
  if (Number.isNaN(date.getTime())) return iso;
  date.setDate(date.getDate() + days);
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

export function isISODate(value: string | null | undefined): value is string {
  return typeof value === "string" && /^\d{4}-\d{2}-\d{2}$/.test(value);
}

export function truncateMiddle(value: string, head = 18, tail = 8): string {
  if (value.length <= head + tail + 1) return value;
  return `${value.slice(0, head)}…${value.slice(-tail)}`;
}
