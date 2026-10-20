#!/usr/bin/env python
"""飞书文本数据 ETL：JSONL(zip) -> 时点化政策/新闻语料 CSV。

数据链路::

    data/raw/feishu/文本数据8.2.zip   (9 个 JSONL, 解压 ~590MB)
        -> 流式解析 + 清洗 + 严格日期过滤(PIT) + doc_id/title+date 去重
        -> 分层抽样(来源/关键词分层 + 每日配额 + 30MB 预算水位填充 + 每日保底)
        -> data/custom/policy_news.csv         (UTF-8-SIG, 6 列)
        -> data/custom/text_manifest.json      (来源分布/每日文档量/抽样规则/校验)

设计要点
--------
1. **流式**：zip 成员逐个 ``ZipFile.open`` + 按行 JSON 解析，任何时刻不在内存中
   保留原始 590MB；正文在解析时即清洗并截断（黄金/跨境单篇最长 116 万字符）。
2. **严格 PIT**：``publish_time`` 必须是合法 ``YYYY-MM-DD``（可带时分，只取日期），
   解析失败（如 ``????-01-28``）直接丢弃，绝不猜测年份；输出只保留日期。
3. **两遍**：第一遍抽候选并写临时 JSONL 缓存（同时得到每日/每来源计数）；第二遍按
   配额选样写 CSV。超预算时只重跑第二遍，无需重读 zip。
4. **分层抽样**：政策/财经来源整层保留（中国政府网、证券时报），跨境/黄金按每日配额，
   人民日报/光明日报先取金融政策关键词命中、再按每日配额补常规样本；每个有候选的
   日期至少保留 1 篇，保证 2017–2025 每个交易日都有语料。

用法::

    .venv\\Scripts\\python.exe scripts/build_text_corpus.py
    .venv\\Scripts\\python.exe scripts/build_text_corpus.py --start 2017-01-01 --end 2025-09-30
    .venv\\Scripts\\python.exe scripts/build_text_corpus.py --content-chars 350 --max-file-mb 0 \\
        --newspaper-daily-cap 80        # 口径 B：约 3 万篇 + 短正文（不受 30MB 限制）

产物列：``doc_id,publish_time,title,content,source,url``（UTF-8-SIG）。
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import statistics
import sys
import tempfile
import time
import unicodedata
import zipfile
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

# --------------------------------------------------------------------------- #
# 常量
# --------------------------------------------------------------------------- #
#: 输出 CSV 列（对应 configs/data_mapping.yaml 的 documents 映射）
CSV_COLUMNS: tuple[str, ...] = ("doc_id", "publish_time", "title", "content", "source", "url")
#: 期望来源（zip 成员名）。顺序即处理顺序，同时决定 title+date 去重时的保留优先级
SOURCE_ORDER: tuple[str, ...] = (
    "中国政府网",
    "证卷时报",  # 原文如此（非"证券时报"），保持与数据一致
    "跨境",
    "黄金",
    "人民日报",
    "光明日报",
    "IMF全",
    "BIS",
    "Reddit",
)
#: 金融/政策/跨境关键词：用于人民日报/光明日报的高价值筛选与分层
POLICY_KEYWORDS: tuple[str, ...] = (
    "跨境", "汇率", "人民币", "外汇", "外储", "外资", "资本流动", "资本项目", "结售汇",
    "离岸", "在岸", "中间价", "贬值", "升值", "美元", "美联储", "加息", "降息", "降准",
    "逆回购", "公开市场", "MLF", "LPR", "流动性", "债券", "国债", "收益率", "利差",
    "信用", "违约", "债市", "股市", "股票", "金融风险", "系统性风险", "监管", "央行",
    "人民银行", "证监会", "外汇局", "财政部", "政策", "改革", "对外开放", "自贸区",
    "一带一路", "关税", "贸易", "出口", "进口", "国际收支", "银行", "保险", "信托",
    "融资", "北向", "南向", "沪港通", "深港通", "债券通", "风险", "危机", "波动",
    "泡沫", "去杠杆", "稳增长", "货币政策", "财政政策",
)  # fmt: skip

DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})(?:[ T](\d{2}):(\d{2})(?::(\d{2}))?)?")
WHITESPACE_RE = re.compile(r"\s+")
CONTROL_RE = re.compile(r"[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]")
SENTENCE_END = "。！？；.!?;"
NULL_TOKENS = {"", "nan", "none", "null", "na", "n/a", "-"}


# --------------------------------------------------------------------------- #
# 分层定义
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Tier:
    """一个抽样层：来源 + 关键词标记，对应预算权重与每日上限。

    Attributes:
        key: 层标识（写入 manifest）。
        sources: 该层来源名。
        kw_flag: ``True`` 仅关键词命中 / ``False`` 仅未命中 / ``None`` 不区分。
        share: 非强制层在剩余预算中的权重（水位填充比例）。
        daily_cap: 每层每日上限（0 表示不限）。
        total_cap: 该层全局上限（0 表示不限）。
        mandatory: 是否整层保留（先于水位填充占用预算）。
    """

    key: str
    sources: tuple[str, ...]
    kw_flag: bool | None
    share: float
    daily_cap: int
    total_cap: int = 0
    mandatory: bool = False


#: 分层定义（顺序即"每日保底"时的优先级）
TIERS: tuple[Tier, ...] = (
    # 政策与财经：量小、价值最高 -> 整层保留
    Tier("policy_gov", ("中国政府网",), None, 0.00, 20, mandatory=True),
    Tier("securities_media", ("证卷时报",), None, 0.00, 20, mandatory=True),
    Tier("crossborder_filings", ("跨境",), None, 0.18, 3),
    Tier("people_daily_kw", ("人民日报",), True, 0.20, 80),
    Tier("gm_daily_kw", ("光明日报",), True, 0.17, 80),
    Tier("gold_filings", ("黄金",), None, 0.14, 3),
    Tier("people_daily_other", ("人民日报",), False, 0.10, 80),
    Tier("gm_daily_other", ("光明日报",), False, 0.08, 80),
    # 英文外部政策源：帮助有限，只留少量（每日 1 篇 + 全局上限）
    Tier("imf_policy", ("IMF全",), None, 0.02, 1, 200),
    Tier("bis_policy", ("BIS",), None, 0.01, 1, 100),
)


def tier_of(source: str, kw_flag: bool | None, tiers: tuple[Tier, ...]) -> int | None:
    """返回 ``(source, kw_flag)`` 所属分层下标（先精确匹配关键词标记，再退回 None 层）。"""
    for index, tier in enumerate(tiers):
        if source in tier.sources and tier.kw_flag == kw_flag:
            return index
    if kw_flag is not None:
        for index, tier in enumerate(tiers):
            if source in tier.sources and tier.kw_flag is None:
                return index
    return None


# --------------------------------------------------------------------------- #
# 基础工具
# --------------------------------------------------------------------------- #
def _setup_stdout() -> None:
    """Windows 控制台输出中文时避免 UnicodeEncodeError。"""
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except (AttributeError, ValueError):  # pragma: no cover
        pass


def parse_publish_date(raw: object) -> date | None:
    """严格解析 ``publish_time``；非法/缺失（如 ``????-01-28``）返回 None。

    只接受 ``YYYY-MM-DD`` 开头的字符串（可带时分，但只取日期）。不做模糊推断：
    异常日期一律丢弃，避免引入未来信息。
    """
    if not isinstance(raw, str):
        return None
    match = DATE_RE.match(raw.strip())
    if not match:
        return None
    try:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None


def clean_text(raw: object) -> str:
    """清洗文本：NFC 归一、去控制符/零宽字符、空白折叠、剔除 ``nan`` 等占位值。"""
    if not isinstance(raw, str):
        return ""
    text = unicodedata.normalize("NFC", raw)
    text = text.replace("\u3000", " ").replace("\ufeff", "").replace("\u200b", "")
    text = CONTROL_RE.sub(" ", text)
    text = WHITESPACE_RE.sub(" ", text).strip()
    if text.lower() in NULL_TOKENS:
        return ""
    return text


def truncate_content(text: str, limit: int) -> tuple[str, bool]:
    """按句界把正文截断到 ``limit`` 字符以内；返回 ``(正文, 是否截断)``。"""
    if len(text) <= limit:
        return text, False
    window = text[:limit]
    floor = int(limit * 0.85)
    for idx in range(len(window) - 1, floor - 1, -1):
        if window[idx] in SENTENCE_END:
            return window[: idx + 1].rstrip(), True
    return window.rstrip(), True


def has_policy_keyword(text: str) -> bool:
    """是否命中金融/政策/跨境关键词（≥1 个不同关键词即视为高价值）。"""
    return any(keyword in text for keyword in POLICY_KEYWORDS)


def even_pick(index: int, total: int, keep: int) -> bool:
    """等距抽样（Bresenham）：从 ``total`` 条中均匀取 ``keep`` 条。

    确定性、与输入顺序绑定；同一天内均匀铺开，不会只截取头部（源文件按板块聚集）。
    """
    if keep <= 0 or total <= 0:
        return False
    if keep >= total:
        return True
    return (index * keep) // total != ((index + 1) * keep) // total


def sha256_file(path: Path) -> str:
    """计算文件 sha256。"""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


# --------------------------------------------------------------------------- #
# 参数
# --------------------------------------------------------------------------- #
def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """解析命令行参数。"""
    parser = argparse.ArgumentParser(
        description="飞书文本数据 -> 时点化政策/新闻语料 CSV（分层抽样，流式读 zip）",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--zip-path", default="data/raw/feishu/文本数据8.2.zip", help="飞书文本数据 zip 路径"
    )
    parser.add_argument("--out", default="data/custom/policy_news.csv", help="输出 CSV 路径")
    parser.add_argument(
        "--manifest", default="data/custom/text_manifest.json", help="输出 manifest 路径"
    )
    parser.add_argument(
        "--calendar-path",
        default="data/samples/market_daily.csv",
        help="交易日历来源（读 trade_date 列；缺失时退化为工作日）",
    )
    parser.add_argument("--start", default="2017-01-01", help="起始日期（含）")
    parser.add_argument("--end", default="2025-09-30", help="结束日期（含）")
    parser.add_argument(
        "--content-chars",
        type=int,
        default=1500,
        help="正文截断长度（字符；规范区间 1500–2500，取下限以容纳更多文档）",
    )
    parser.add_argument(
        "--min-content-chars", type=int, default=60, help="清洗后正文最少字符数，过短丢弃"
    )
    parser.add_argument(
        "--max-file-mb",
        type=float,
        default=30.0,
        help="输出 CSV 大小上限（MB）；0 表示不限（口径 B 可配合 --content-chars 350）",
    )
    parser.add_argument(
        "--target-docs", type=int, default=0, help="文档数上限；0 表示不限（由预算决定）"
    )
    parser.add_argument(
        "--newspaper-daily-cap",
        type=int,
        default=None,
        help="覆盖 人民日报/光明日报 每层每日上限（规范上限 80）",
    )
    parser.add_argument(
        "--policy-daily-cap", type=int, default=None, help="覆盖 中国政府网/证卷时报 每日上限"
    )
    parser.add_argument("--crossborder-daily-cap", type=int, default=None, help="覆盖 跨境 每日上限")
    parser.add_argument("--gold-daily-cap", type=int, default=None, help="覆盖 黄金 每日上限")
    parser.add_argument(
        "--external-daily-cap", type=int, default=None, help="覆盖 IMF/BIS 每日上限（0=排除）"
    )
    parser.add_argument(
        "--external-total-cap", type=int, default=None, help="IMF/BIS 全局上限（0=排除）"
    )
    parser.add_argument(
        "--keep-cache", action="store_true", help="保留候选缓存 JSONL（便于调参只重跑第二遍）"
    )
    parser.add_argument("--cache-path", default="", help="自定义候选缓存路径（默认系统临时目录）")
    parser.add_argument("--seed", type=int, default=0, help="保留参数（确定性抽样，无需随机种子）")
    args = parser.parse_args(argv)
    args.start_date = _parse_cli_date(args.start, "--start")
    args.end_date = _parse_cli_date(args.end, "--end")
    if args.start_date > args.end_date:
        parser.error("--start 不能晚于 --end")
    if not 100 <= args.content_chars <= 20000:
        parser.error("--content-chars 需在 [100, 20000]")
    if args.max_file_mb < 0:
        parser.error("--max-file-mb 不能为负")
    if args.min_content_chars < 1:
        parser.error("--min-content-chars 需 ≥1")
    if args.target_docs < 0:
        parser.error("--target-docs 不能为负")
    return args


def _parse_cli_date(text: str, flag: str) -> date:
    """解析命令行日期参数。"""
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise SystemExit(f"{flag} 日期格式需为 YYYY-MM-DD: {text}") from exc


def build_tiers(args: argparse.Namespace) -> tuple[Tier, ...]:
    """按命令行覆盖项构造分层配置；被禁用（上限为 0）的层直接移除。"""
    tiers: list[Tier] = []
    for tier in TIERS:
        daily_cap, total_cap = tier.daily_cap, tier.total_cap
        if tier.key in ("policy_gov", "securities_media") and args.policy_daily_cap is not None:
            daily_cap = args.policy_daily_cap
        if tier.key in ("people_daily_kw", "gm_daily_kw", "people_daily_other", "gm_daily_other"):
            if args.newspaper_daily_cap is not None:
                daily_cap = args.newspaper_daily_cap
        if tier.key == "crossborder_filings" and args.crossborder_daily_cap is not None:
            daily_cap = args.crossborder_daily_cap
        if tier.key == "gold_filings" and args.gold_daily_cap is not None:
            daily_cap = args.gold_daily_cap
        if tier.key in ("imf_policy", "bis_policy"):
            if args.external_daily_cap is not None:
                daily_cap = args.external_daily_cap
            if args.external_total_cap is not None:
                total_cap = args.external_total_cap
            if daily_cap <= 0 or total_cap == 0:
                continue  # 排除英文外部源
        if daily_cap == 0 and not tier.mandatory:
            continue  # 该层禁用
        tiers.append(
            Tier(
                key=tier.key,
                sources=tier.sources,
                kw_flag=tier.kw_flag,
                share=tier.share,
                daily_cap=daily_cap,
                total_cap=total_cap,
                mandatory=tier.mandatory,
            )
        )
    return tuple(tiers)


def kw_split_sources(tiers: tuple[Tier, ...]) -> set[str]:
    """需要按关键词切分的来源集合（人民日报/光明日报）。"""
    return {source for tier in tiers if tier.kw_flag is not None for source in tier.sources}


# --------------------------------------------------------------------------- #
# 第一遍：抽候选
# --------------------------------------------------------------------------- #
@dataclass
class SourceStats:
    """单来源处理漏斗统计与预算估算累计量。"""

    raw_lines: int = 0
    parse_errors: int = 0
    bad_time: int = 0
    out_of_range: int = 0
    empty_title: int = 0
    empty_body: int = 0
    short_body: int = 0
    duplicate_doc_id: int = 0
    duplicate_title_date: int = 0
    kept: int = 0
    truncated: int = 0
    content_chars: int = 0
    title_chars: int = 0
    url_bytes: int = 0
    bad_time_samples: list[str] = field(default_factory=list)


@dataclass
class CollectResult:
    """第一遍结果。"""

    group_counts: dict[tuple[str, bool | None, str], int]
    stats: dict[str, SourceStats]
    member_bytes: dict[str, int]
    cache_path: Path
    elapsed: float


def _extract_title(record: dict) -> str:
    """取标题（清洗后）。"""
    return clean_text(record.get("title"))


def _extract_url(record: dict) -> str:
    """取 ``meta_info.url``（缺失/空串返回空）。"""
    meta = record.get("meta_info") or {}
    if not isinstance(meta, dict):
        return ""
    return clean_text(meta.get("url"))


def _extract_body(record: dict) -> str:
    """取正文：``content.full_text`` 优先，退回 ``structured_md``，再退回 ``meta_info.summary``。

    飞书语料里 黄金/跨境（PDF 公告）的 ``full_text`` 常为空、正文在 ``structured_md``；
    Reddit 的 ``full_text`` 存在字面量 ``"nan"``，必须过滤。
    """
    content = record.get("content") or {}
    if isinstance(content, dict):
        for key in ("full_text", "structured_md"):
            text = clean_text(content.get(key))
            if text:
                return text
    meta = record.get("meta_info") or {}
    if isinstance(meta, dict):
        return clean_text(meta.get("summary"))
    return ""


def collect_candidates(
    args: argparse.Namespace,
    tiers: tuple[Tier, ...],
    split_sources: set[str],
) -> CollectResult:
    """第一遍：流式读 zip、清洗/过滤/去重，候选写入缓存 JSONL 并统计分组计数。"""
    zip_path = Path(args.zip_path)
    if not zip_path.exists():
        raise SystemExit(f"找不到输入 zip: {zip_path}")
    cache_path = (
        Path(args.cache_path)
        if args.cache_path
        else Path(tempfile.gettempdir())
        / f"cbr_text_corpus_{hashlib.sha1(str(zip_path.resolve()).encode()).hexdigest()[:10]}.jsonl"
    )
    started = time.time()
    stats: dict[str, SourceStats] = {name: SourceStats() for name in SOURCE_ORDER}
    member_bytes: dict[str, int] = {}
    group_counts: dict[tuple[str, bool | None, str], int] = defaultdict(int)
    seen_ids: set[str] = set()
    seen_title_date: set[str] = set()
    unknown_members: list[str] = []

    with zipfile.ZipFile(zip_path) as archive:
        members = {
            info.filename: info for info in archive.infolist() if info.filename.endswith(".jsonl")
        }
        if not members:
            raise SystemExit(f"{zip_path} 内没有 .jsonl 成员")
        ordered = [name for name in SOURCE_ORDER if name in members]
        ordered += [name for name in members if name not in ordered]
        with cache_path.open("w", encoding="utf-8", newline="\n") as cache:
            for member in ordered:
                info = members[member]
                source = member[:-6]
                member_bytes[member] = info.file_size
                stat = stats.setdefault(source, SourceStats())
                if source not in SOURCE_ORDER:
                    unknown_members.append(member)
                per_member_t0 = time.time()
                with archive.open(info) as handle:
                    for line in handle:
                        if not line.strip():
                            continue
                        stat.raw_lines += 1
                        try:
                            record = json.loads(line)
                        except (json.JSONDecodeError, UnicodeDecodeError):
                            stat.parse_errors += 1
                            continue
                        if not isinstance(record, dict):
                            stat.parse_errors += 1
                            continue
                        published = parse_publish_date(record.get("publish_time"))
                        if published is None:
                            stat.bad_time += 1
                            if len(stat.bad_time_samples) < 5:
                                stat.bad_time_samples.append(str(record.get("publish_time"))[:24])
                            continue
                        if not (args.start_date <= published <= args.end_date):
                            stat.out_of_range += 1
                            continue
                        title = _extract_title(record)
                        if not title:
                            stat.empty_title += 1
                            continue
                        body = _extract_body(record)
                        if not body:
                            stat.empty_body += 1
                            continue
                        if len(body) < args.min_content_chars:
                            stat.short_body += 1
                            continue
                        doc_id = clean_text(record.get("doc_id")) or (
                            f"{source}_{published.isoformat()}_"
                            f"{hashlib.sha1((title + body[:64]).encode()).hexdigest()[:8]}"
                        )
                        if doc_id in seen_ids:
                            stat.duplicate_doc_id += 1
                            continue
                        title_key = hashlib.sha1(
                            f"{published.isoformat()}|{title}".encode()
                        ).hexdigest()
                        if title_key in seen_title_date:
                            stat.duplicate_title_date += 1
                            continue
                        seen_ids.add(doc_id)
                        seen_title_date.add(title_key)

                        content, truncated = truncate_content(body, args.content_chars)
                        stat.truncated += int(truncated)
                        url = _extract_url(record)
                        kw_flag: bool | None = None
                        if source in split_sources:
                            kw_flag = has_policy_keyword(f"{title} {content}")
                        day = published.isoformat()
                        group_counts[(source, kw_flag, day)] += 1
                        stat.kept += 1
                        stat.content_chars += len(content)
                        stat.title_chars += len(title)
                        stat.url_bytes += len(url.encode("utf-8"))
                        cache.write(
                            json.dumps(
                                {
                                    "doc_id": doc_id,
                                    "publish_time": day,
                                    "title": title,
                                    "content": content,
                                    "source": source,
                                    "url": url,
                                    "kw": kw_flag,
                                },
                                ensure_ascii=False,
                            )
                        )
                        cache.write("\n")
                print(
                    f"[collect] {source:<8} 行={stat.raw_lines:>6} 保留={stat.kept:>6} "
                    f"坏日期={stat.bad_time:>5} 出区间={stat.out_of_range:>6} "
                    f"空标题={stat.empty_title:>4} 空正文={stat.empty_body:>4} "
                    f"过短={stat.short_body:>3} 重复={stat.duplicate_doc_id + stat.duplicate_title_date:>4} "
                    f"{time.time() - per_member_t0:.1f}s"
                )
    if unknown_members:
        print(f"[WARN] 未登记来源（将不进入分层，自动丢弃）: {unknown_members}")
    return CollectResult(
        group_counts=dict(group_counts),
        stats=stats,
        member_bytes=member_bytes,
        cache_path=cache_path,
        elapsed=time.time() - started,
    )


# --------------------------------------------------------------------------- #
# 配额分配
# --------------------------------------------------------------------------- #
def mean_bytes_per_doc(stats: dict[str, SourceStats]) -> dict[str, float]:
    """按来源估算单篇 CSV 字节数（正文/标题按 UTF-8 3 字节/字 + URL + 字段开销）。"""
    result: dict[str, float] = {}
    for source, stat in stats.items():
        if stat.kept <= 0:
            result[source] = 4200.0
            continue
        result[source] = (
            stat.content_chars / stat.kept * 3.0
            + stat.title_chars / stat.kept * 3.0
            + stat.url_bytes / stat.kept
            + 140.0
        )
    return result


def allocate(
    group_counts: dict[tuple[str, bool | None, str], int],
    stats: dict[str, SourceStats],
    tiers: tuple[Tier, ...],
    budget_bytes: float | None,
    target_docs: int,
) -> tuple[dict[tuple[str, bool | None, str], int], dict[str, float], dict[str, int]]:
    """按分层权重与字节预算分配每个分组的保留篇数。

    Returns:
        ``(group_keep, tier_fraction, tier_keep)``。
    """
    unit_bytes = mean_bytes_per_doc(stats)

    # 1) 每日上限
    capped: dict[tuple[str, bool | None, str], int] = {}
    for group, count in group_counts.items():
        index = tier_of(group[0], group[1], tiers)
        if index is None:
            continue
        cap = tiers[index].daily_cap
        capped[group] = min(count, cap) if cap > 0 else count

    # 2) 每日保底：每个有候选的日期至少 1 篇（关键词层优先，其次分层优先级）
    by_day: dict[str, list[tuple[str, bool | None, str]]] = defaultdict(list)
    for group, count in capped.items():
        if count > 0:
            by_day[group[2]].append(group)
    forced: dict[tuple[str, bool | None, str], int] = defaultdict(int)
    for groups in by_day.values():
        best = min(
            groups,
            key=lambda g: (
                0 if g[1] is True else (1 if g[1] is None else 2),
                tier_of(g[0], g[1], tiers) or 0,
                SOURCE_ORDER.index(g[0]) if g[0] in SOURCE_ORDER else 99,
            ),
        )
        forced[best] = 1

    # 3) 强制层整层保留；其余层计算可用字节
    group_keep: dict[tuple[str, bool | None, str], int] = {
        group: forced.get(group, 0) for group in capped
    }
    remaining_budget = float(budget_bytes) if budget_bytes else math.inf
    optional_avail: dict[int, float] = defaultdict(float)
    optional_extra: dict[tuple[str, bool | None, str], int] = {}
    for group, count in capped.items():
        index = tier_of(group[0], group[1], tiers)
        assert index is not None
        unit = unit_bytes.get(group[0], 4200.0)
        extra = count - forced.get(group, 0)
        if tiers[index].mandatory:
            group_keep[group] = count
            remaining_budget -= count * unit
            continue
        remaining_budget -= forced.get(group, 0) * unit  # 每日保底同样占用预算
        if extra <= 0:
            continue
        optional_extra[group] = extra
        optional_avail[index] += extra * unit
    if budget_bytes:
        remaining_budget = max(0.0, remaining_budget)
    for index, tier in enumerate(tiers):
        if tier.total_cap > 0 and index in optional_avail:
            tier_unit = statistics.mean(
                [unit_bytes.get(source, 4200.0) for source in tier.sources]
            )
            optional_avail[index] = min(optional_avail[index], tier.total_cap * tier_unit)

    # 4) 水位填充：非强制层按 share 分配剩余预算，被上限截断的层把余量让给其他层
    alloc = {index: 0.0 for index in optional_avail}
    budget_left = remaining_budget
    active = [index for index in optional_avail if optional_avail[index] > 1]
    guard = 0
    while active and budget_left > 1 and guard < 20:
        guard += 1
        share_total = sum(tiers[index].share for index in active) or 1.0
        proposed = {
            index: min(
                budget_left * tiers[index].share / share_total,
                optional_avail[index] - alloc[index],
            )
            for index in active
        }
        spent = sum(value for value in proposed.values() if value > 0)
        for index, value in proposed.items():
            if value > 0:
                alloc[index] += value
        if spent <= 1:
            break
        budget_left -= spent
        active = [index for index in active if optional_avail[index] - alloc[index] > 1]

    # 5) 按层比例落到分组（最大余数法：避免小组因 floor 被全部抹掉）
    tier_fraction: dict[str, float] = {}
    for index, tier in enumerate(tiers):
        available = optional_avail.get(index, 0.0)
        if tier.mandatory or not budget_bytes:
            fraction = 1.0  # 整层保留 / 不限预算
        else:
            fraction = min(1.0, alloc.get(index, 0.0) / available) if available > 0 else 0.0
        tier_fraction[tier.key] = round(fraction, 6)
        if fraction <= 0:
            continue
        in_tier = [
            (group, extra)
            for group, extra in optional_extra.items()
            if tier_of(group[0], group[1], tiers) == index
        ]
        if not in_tier:
            continue
        ideal = [(group, fraction * extra) for group, extra in in_tier]
        cap_by_group = dict(in_tier)
        base = {group: int(math.floor(value)) for group, value in ideal}
        target_total = int(round(sum(value for _, value in ideal)))
        if tier.total_cap > 0:
            target_total = min(target_total, tier.total_cap)
        deficit = target_total - sum(base.values())
        if deficit > 0:
            order = sorted(
                ideal, key=lambda item: (item[1] - math.floor(item[1]), item[1]), reverse=True
            )
            for group, _value in order[:deficit]:
                if base[group] + 1 <= cap_by_group[group]:
                    base[group] += 1
        for group, take in base.items():
            group_keep[group] += take

    # 6) 文档数上限
    total = sum(group_keep.values())
    if target_docs > 0 and total > target_docs:
        scale = target_docs / total
        group_keep = {
            group: max(1 if forced.get(group) else 0, int(math.floor(value * scale)))
            for group, value in group_keep.items()
        }

    tier_keep: dict[str, int] = {}
    for index, tier in enumerate(tiers):
        tier_keep[tier.key] = sum(
            value
            for group, value in group_keep.items()
            if tier_of(group[0], group[1], tiers) == index
        )
    return group_keep, tier_fraction, tier_keep


# --------------------------------------------------------------------------- #
# 第二遍：写 CSV
# --------------------------------------------------------------------------- #
def write_csv(
    args: argparse.Namespace,
    group_keep: dict[tuple[str, bool | None, str], int],
    group_counts: dict[tuple[str, bool | None, str], int],
    tiers: tuple[Tier, ...],
    cache_path: Path,
) -> dict:
    """第二遍：按配额从缓存等距选样并写 CSV。"""
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    seen: dict[tuple[str, bool | None, str], int] = defaultdict(int)
    priority = {name: index for index, name in enumerate(SOURCE_ORDER)}
    rows: list[tuple[date, int, str, str, str, str, str, str]] = []
    with cache_path.open("r", encoding="utf-8") as cache:
        for line in cache:
            if not line.strip():
                continue
            record = json.loads(line)
            source = record["source"]
            kw_raw = record.get("kw")
            kw_flag = None if kw_raw is None else bool(kw_raw)
            day = record["publish_time"]
            group = (source, kw_flag, day)
            total = group_counts.get(group, 0)
            index = seen[group]
            seen[group] += 1
            if not even_pick(index, total, group_keep.get(group, 0)):
                continue
            rows.append(
                (
                    date.fromisoformat(day),
                    priority.get(source, 99),
                    record["doc_id"],
                    day,
                    record["title"],
                    record["content"],
                    source,
                    record["url"],
                )
            )
    rows.sort(key=lambda item: (item[0], item[1], item[2]))
    tmp_path = out_path.with_name(out_path.name + ".tmp")
    with tmp_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(CSV_COLUMNS)
        for _published, _prio, doc_id, publish_time, title, content, source, url in rows:
            writer.writerow([doc_id, publish_time, title, content, source, url])
    tmp_path.replace(out_path)
    size = out_path.stat().st_size
    return {"rows": rows, "size": size, "sha256": sha256_file(out_path)}


# --------------------------------------------------------------------------- #
# 交易日历 / manifest
# --------------------------------------------------------------------------- #
def load_calendar(path: str) -> tuple[list[date], str]:
    """读取项目交易日历（``data/samples/market_daily.csv`` 的 ``trade_date`` 列）。"""
    calendar_path = Path(path)
    if calendar_path.exists():
        import pandas as pd  # 局部导入：仅统计阶段需要

        frame = pd.read_csv(calendar_path, usecols=["trade_date"])
        days = sorted({date.fromisoformat(str(value)[:10]) for value in frame["trade_date"]})
        return days, f"{calendar_path} (trade_date)"
    return [], "weekday-fallback"


def weekday_days(start: date, end: date) -> list[date]:
    """区间内的工作日（周一至周五，未做节假日调整）。"""
    days: list[date] = []
    current = start
    while current <= end:
        if current.weekday() < 5:
            days.append(current)
        current += timedelta(days=1)
    return days


def summarize(values: list[int]) -> dict[str, float | int]:
    """每日文档量分位统计。"""
    if not values:
        return {"n_days": 0, "min": 0, "p25": 0, "median": 0, "p75": 0, "max": 0, "mean": 0.0}
    ordered = sorted(values)
    return {
        "n_days": len(ordered),
        "min": ordered[0],
        "p25": ordered[int(len(ordered) * 0.25)],
        "median": statistics.median(ordered),
        "p75": ordered[int(len(ordered) * 0.75)],
        "max": ordered[-1],
        "mean": round(sum(ordered) / len(ordered), 3),
    }


def build_manifest(
    args: argparse.Namespace,
    collected: CollectResult,
    result: dict,
    tiers: tuple[Tier, ...],
    tier_fraction: dict[str, float],
    tier_keep: dict[str, int],
    split_sources: set[str],
    elapsed_total: float,
    attempts: int,
) -> dict:
    """组装 manifest：来源分布、日期范围、每日覆盖、抽样规则、文件校验信息。"""
    rows = result["rows"]
    daily: dict[str, int] = defaultdict(int)
    source_counts: dict[str, int] = defaultdict(int)
    content_lengths: list[int] = []
    for published, _prio, _doc_id, _pt, _title, content, source, _url in rows:
        daily[published.isoformat()] += 1
        source_counts[source] += 1
        content_lengths.append(len(content))

    calendar, calendar_source = load_calendar(args.calendar_path)
    cal_in_range = [day for day in calendar if args.start_date <= day <= args.end_date]
    if cal_in_range:
        missing_trading = [day for day in cal_in_range if day.isoformat() not in daily]
        coverage_basis = "project-trading-calendar"
        trading_total, trading_missing = len(cal_in_range), len(missing_trading)
    else:
        missing_trading, coverage_basis, trading_total, trading_missing = [], "weekday-fallback", 0, 0
    weekdays = weekday_days(args.start_date, args.end_date)
    missing_weekdays = [day for day in weekdays if day.isoformat() not in daily]
    days_with_docs = sorted(date.fromisoformat(day) for day in daily)
    lengths_sorted = sorted(content_lengths)

    filtering = {
        "raw_lines": sum(stat.raw_lines for stat in collected.stats.values()),
        "parse_errors": sum(stat.parse_errors for stat in collected.stats.values()),
        "bad_publish_time": sum(stat.bad_time for stat in collected.stats.values()),
        "out_of_range": sum(stat.out_of_range for stat in collected.stats.values()),
        "empty_title": sum(stat.empty_title for stat in collected.stats.values()),
        "empty_body": sum(stat.empty_body for stat in collected.stats.values()),
        "short_body": sum(stat.short_body for stat in collected.stats.values()),
        "duplicate_doc_id": sum(stat.duplicate_doc_id for stat in collected.stats.values()),
        "duplicate_title_date": sum(
            stat.duplicate_title_date for stat in collected.stats.values()
        ),
        "candidates_kept": sum(stat.kept for stat in collected.stats.values()),
        "content_truncated": sum(stat.truncated for stat in collected.stats.values()),
        "selected": len(rows),
    }
    per_source = {}
    for source, stat in collected.stats.items():
        per_source[source] = {
            "raw_lines": stat.raw_lines,
            "kept_candidates": stat.kept,
            "selected": source_counts.get(source, 0),
            "share": round(source_counts.get(source, 0) / len(rows), 4) if rows else 0.0,
            "bad_publish_time": stat.bad_time,
            "out_of_range": stat.out_of_range,
            "empty_body": stat.empty_body,
            "short_body": stat.short_body,
            "duplicate": stat.duplicate_doc_id + stat.duplicate_title_date,
            "bad_time_samples": stat.bad_time_samples,
        }
    return {
        "artifact": "policy_news",
        "description": "飞书文本数据（9 个 JSONL）经清洗/严格 PIT 过滤/分层抽样后的政策与财经文本语料",
        "generated_at": datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds"),
        "generator": {
            "script": "scripts/build_text_corpus.py",
            "command": " ".join(["python", *sys.argv]).strip(),
            "determinism": "等距抽样（Bresenham）+ 固定来源顺序，无需随机种子；同输入必得同输出",
        },
        "input": {
            "zip": str(Path(args.zip_path)),
            "zip_bytes": Path(args.zip_path).stat().st_size,
            "zip_mb": round(Path(args.zip_path).stat().st_size / 1024 / 1024, 1),
            "members": {
                name: {
                    "uncompressed_bytes": size,
                    "raw_lines": collected.stats.get(name[:-6], SourceStats()).raw_lines,
                }
                for name, size in collected.member_bytes.items()
            },
            "source_order": list(SOURCE_ORDER),
        },
        "schema": {
            "columns": list(CSV_COLUMNS),
            "encoding": "utf-8-sig",
            "publish_time_format": "YYYY-MM-DD（仅日期；严格 PIT，无未来信息）",
            "content_max_chars": args.content_chars,
            "content_min_chars": args.min_content_chars,
            "mapping_hint": {
                "file": Path(args.out).name,
                "publish_time_column": "publish_time",
                "title_column": "title",
                "body_column": "content",
                "source_column": "source",
                "url_column": "url",
                "doc_id_column": "doc_id",
            },
        },
        "date_range": {
            "requested_start": args.start_date.isoformat(),
            "requested_end": args.end_date.isoformat(),
            "min": days_with_docs[0].isoformat() if days_with_docs else None,
            "max": days_with_docs[-1].isoformat() if days_with_docs else None,
        },
        "n_documents": len(rows),
        "source_distribution": {
            source: {
                "n": count,
                "share": round(count / len(rows), 4) if rows else 0.0,
                "kept_candidates": collected.stats[source].kept if source in collected.stats else 0,
            }
            for source, count in sorted(source_counts.items(), key=lambda kv: (-kv[1], kv[0]))
        },
        "source_funnel": per_source,
        "daily": {
            "n_days_with_docs": len(daily),
            "n_calendar_days_in_range": (args.end_date - args.start_date).days + 1,
            "docs_per_calendar_day": summarize(list(daily.values())),
            "docs_per_trading_day": summarize([daily.get(day.isoformat(), 0) for day in cal_in_range]),
            "coverage_basis": coverage_basis,
            "calendar_source": calendar_source,
            "trading_days_total": trading_total,
            "trading_days_missing": trading_missing,
            "trading_day_coverage": round(1 - trading_missing / trading_total, 4)
            if trading_total
            else None,
            "weekdays_total": len(weekdays),
            "weekdays_missing": len(missing_weekdays),
            "weekday_coverage": round(1 - len(missing_weekdays) / len(weekdays), 4)
            if weekdays
            else None,
            "missing_trading_day_examples": [day.isoformat() for day in missing_trading[:20]],
            "missing_weekday_examples": [day.isoformat() for day in missing_weekdays[:20]],
            "daily_counts": {day.isoformat(): daily[day.isoformat()] for day in days_with_docs},
        },
        "content_chars": {
            "min": lengths_sorted[0] if lengths_sorted else 0,
            "p25": lengths_sorted[int(len(lengths_sorted) * 0.25)] if lengths_sorted else 0,
            "median": statistics.median(lengths_sorted) if lengths_sorted else 0,
            "p75": lengths_sorted[int(len(lengths_sorted) * 0.75)] if lengths_sorted else 0,
            "max": lengths_sorted[-1] if lengths_sorted else 0,
            "mean": round(sum(lengths_sorted) / len(lengths_sorted), 1) if lengths_sorted else 0.0,
        },
        "sampling": {
            "strategy": "分层（来源×关键词）+ 每日配额 + 字节预算水位填充 + 每日保底 1 篇 + 等距抽样",
            "budget_mb_requested": args.max_file_mb or None,
            "budget_bytes": int(args.max_file_mb * 1024 * 1024) if args.max_file_mb else None,
            "budget_fit_attempts": attempts,
            "target_docs": args.target_docs or None,
            "policy_keywords": list(POLICY_KEYWORDS),
            "kw_split_sources": sorted(split_sources),
            "tiers": [
                {
                    "key": tier.key,
                    "sources": list(tier.sources),
                    "kw_only": tier.kw_flag,
                    "mandatory": tier.mandatory,
                    "budget_share": tier.share,
                    "daily_cap": tier.daily_cap,
                    "total_cap": tier.total_cap or None,
                    "fraction_applied": tier_fraction.get(tier.key, 0.0),
                    "kept": tier_keep.get(tier.key, 0),
                }
                for tier in tiers
            ],
        },
        "filtering": filtering,
        "files": {
            "csv": {
                "path": str(Path(args.out)),
                "bytes": result["size"],
                "mb": round(result["size"] / 1024 / 1024, 2),
                "sha256": result["sha256"],
                "rows": len(rows),
            },
            "manifest": {"path": str(Path(args.manifest))},
        },
        "timing": {
            "collect_seconds": round(collected.elapsed, 1),
            "total_seconds": round(elapsed_total, 1),
        },
        "known_limitations": [
            "publish_time 只保留日期（原始数据无可靠时分），系统按 00:00 处理：媒体文档当日可用，"
            "政策文档也当日可用（features/text.py 的 15:00 切点对纯日期不生效），存在轻微日内前视；"
            "若需严格，建议把 中国政府网 加入该模块 POLICY_SOURCES（本次未改 src/）。",
            "证卷时报 472 篇中 255 篇 publish_time 为 ????-MM-DD 等不可恢复格式，已按严格 PIT 丢弃。",
            "黄金/跨境 是单一上市公司（山东黄金、跨境通等）的 PDF 公告语料，正文取自 content.structured_md，"
            "主题偏公司融资/再融资公告，并非“黄金/跨境主题新闻”。",
            "来源时间覆盖不均衡：人民日报/中国政府网仅 2021+、黄金仅 2023+；2017–2020 的每日覆盖主要依赖"
            "光明日报 + 跨境 + IMF/BIS。",
            "BIS/IMF 为英文语料，中文关键词词典命中为 0，保留过多会稀释 text_risk_ratio；"
            "已限每日 1 篇 + 全局 300 篇（--external-daily-cap 0 可完全排除）。",
            "正文按字符截断到 content_max_chars（默认 1500），黄金/跨境长公告（平均 1.6 万字符）信息损失较大。",
            "Reddit 1999 篇全部为 2013–2014 年，落在 2017–2025 区间外，未纳入。",
            "CSV 体积与文档数目标不可同时满足：中文 UTF-8 约 3 字节/字，1500 字/篇约 4.5KB/篇，"
            "30MB 上限约容纳 7–8k 篇；若要 3 万篇，用 --content-chars 350 --max-file-mb 0。",
        ],
    }


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #
def main(argv: list[str] | None = None) -> int:
    """入口：抽候选 -> 分配配额 -> 写 CSV（预算自动拟合）-> 写 manifest。"""
    _setup_stdout()
    started = time.time()
    args = parse_args(argv)
    tiers = build_tiers(args)
    split_sources = kw_split_sources(tiers)
    print(f"[1/3] 流式扫描 {args.zip_path}（{Path(args.zip_path).stat().st_size / 1024 / 1024:.0f} MB）...")
    collected = collect_candidates(args, tiers, split_sources)
    candidates = sum(stat.kept for stat in collected.stats.values())
    print(f"      候选 {candidates} 篇 | 用时 {collected.elapsed:.1f}s | 缓存 {collected.cache_path}")

    requested_mb = args.max_file_mb
    budget_mb = requested_mb
    attempt = 0
    previous_keep: dict[tuple[str, bool | None, str], int] | None = None
    samples: list[tuple[float, float]] = []  # (预算 MB, 实际 MB)
    while True:
        attempt += 1
        budget_bytes = budget_mb * 1024 * 1024 if budget_mb else None
        print(f"[2/3] 分配配额（预算 {budget_mb if budget_mb else '不限'} MB，第 {attempt} 次）...")
        group_keep, tier_fraction, tier_keep = allocate(
            collected.group_counts, collected.stats, tiers, budget_bytes, args.target_docs
        )
        print(
            "      分层: "
            + ", ".join(f"{tier.key}={tier_keep.get(tier.key, 0)}" for tier in tiers)
            + f" | 合计 {sum(group_keep.values())}"
        )
        result = write_csv(args, group_keep, collected.group_counts, tiers, collected.cache_path)
        size_mb = result["size"] / 1024 / 1024
        samples.append((budget_mb, size_mb))
        print(f"[3/3] 写出 {args.out}: {len(result['rows'])} 篇, {size_mb:.2f} MB")
        if not requested_mb or group_keep == previous_keep:
            break  # 不限大小，或已取满全部候选
        if requested_mb * 0.93 <= size_mb <= requested_mb:
            break  # 命中预算区间
        if attempt >= 6:
            break
        # 割线法拟合 budget->size（size 含"每日保底/强制层"固定分量，不能纯比例缩放）
        if len(samples) >= 2 and samples[-2][0] != samples[-1][0]:
            (b1, s1), (b2, s2) = samples[-2], samples[-1]
            slope = (s2 - s1) / (b2 - b1)
            intercept = s2 - slope * b2
            next_budget = (
                (requested_mb * 0.985 - intercept) / slope if slope > 0.01 else budget_mb
            )
        else:
            next_budget = budget_mb * (requested_mb * 0.985 / size_mb)
        next_budget = min(max(next_budget, 1.0), max(requested_mb * 1.5, 2.0))
        if abs(next_budget - budget_mb) < 0.05:
            break
        previous_keep = group_keep
        budget_mb = next_budget
        print(f"      预算拟合 -> {budget_mb:.2f} MB 重写（不重读 zip）...")

    manifest = build_manifest(
        args, collected, result, tiers, tier_fraction, tier_keep, split_sources,
        time.time() - started, attempt,
    )  # fmt: skip
    manifest_path = Path(args.manifest)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"      manifest -> {manifest_path}")
    if not args.keep_cache:
        collected.cache_path.unlink(missing_ok=True)

    daily = manifest["daily"]
    print(
        f"[DONE] {manifest['n_documents']} 篇 | {manifest['date_range']['min']} ~ "
        f"{manifest['date_range']['max']} | 交易日覆盖 {daily['trading_day_coverage']} "
        f"| CSV {manifest['files']['csv']['mb']} MB | 用时 {time.time() - started:.1f}s"
    )
    for source, item in manifest["source_distribution"].items():
        print(f"       {source:<8} {item['n']:>6} ({item['share']:.1%})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
