"""用户自建数据集适配器（CSV / Parquet，可配置字段映射）。

用户提供自建数据时，把文件放入 ``data/custom/``（默认），通过
``configs/data_mapping.yaml`` 配置字段映射；未提供配置时按列名启发式自动识别：

- 日期列候选：``date / trade_date / 日期 / 交易日期 / obs_date / time / datetime``；
- 发布时点列候选：``release_time / 发布时间 / publish_time / availability_time``；
- 数值列：所有可解析为数值的列（跳过 ID/文本列）；
- 文档文件：文件名含 ``doc/news/text/policy/语料`` 或含标题+正文列组合。

行为约定：

- 用户数据未到位（``data/custom`` 为空或无可用文件）时 ``has_custom=False``，
  上层 ``build_data_provider`` 自动回退 synthetic；
- 用户数据具有更高优先级，但仍必须遵守 point-in-time（``release_time`` 缺省时
  按观测日 16:00 近似）；
- 序列 ID 尽量映射到 ``cbr.data.series`` 的规范 ID（按文件名/列名启发式），
  无法识别时使用 ``custom.<文件名>.<列名>``。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from cbr.config import resolve_path
from cbr.data.catalog import SERIES_SPECS, SYNTHETIC_SOURCE, series_unit
from cbr.data.dataset import DOC_COLUMNS, OBS_COLUMNS, MarketDataset
from cbr.schemas import DataCard

#: 默认映射配置路径
DEFAULT_MAPPING_PATH = "configs/data_mapping.yaml"
#: 日期列候选（按优先级）
DATE_COLUMNS: tuple[str, ...] = (
    "date",
    "trade_date",
    "obs_date",
    "日期",
    "交易日期",
    "时间",
    "time",
    "datetime",
    "Date",
)
#: 发布时点列候选
RELEASE_COLUMNS: tuple[str, ...] = (
    "release_time",
    "publish_time",
    "发布时间",
    "公布时间",
    "availability_time",
    "released_at",
)
#: 文档列候选
DOC_TITLE_COLUMNS: tuple[str, ...] = ("title", "标题", "headline", "news_title")
DOC_BODY_COLUMNS: tuple[str, ...] = ("body", "content", "正文", "内容", "text", "summary")
DOC_DOCID_COLUMNS: tuple[str, ...] = ("doc_id", "id", "文档id", "docid")
DOC_SOURCE_COLUMNS: tuple[str, ...] = ("source", "来源", "media", "publisher")
DOC_URL_COLUMNS: tuple[str, ...] = ("url", "link", "链接", "网址")
DOC_TIME_COLUMNS: tuple[str, ...] = DOC_TITLE_COLUMNS  # 仅用于类型提示（见函数内实现）

#: 文件名/列名 -> 规范序列 ID 启发式
_SERIES_HINTS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("csi300", "hs300", "沪深300", "000300", "sp500_cn"), "market.cn_equity.csi300"),
    (("csi500", "中证500", "000905"), "market.cn_equity.csi500"),
    (("turnover", "成交额", "amount"), "market.cn_equity.turnover"),
    (("cgb_2y", "cgb2", "国债2", "2y"), "market.cn_bond.cgb_2y"),
    (("cgb_10y", "cgb10", "国债10", "10y"), "market.cn_bond.cgb_10y"),
    (("repo", "回购", "资金利率"), "market.cn_bond.repo_7d"),
    (("credit", "信用利差", "spread"), "rates.credit.aa_spread"),
    (("usdcny", "cny", "在岸", "人民币在岸"), "market.fx.usdcny"),
    (("usdcnh", "cnh", "离岸"), "market.fx.usdcnh"),
    (("dxy", "美元指数", "dollar"), "market.global.dxy"),
    (("vix", "恐慌"), "market.global.vix"),
    (("sp500", "标普", "gspc"), "market.global.sp500"),
    (("us10y", "美债10", "tnx"), "market.global.us10y"),
    (("northbound", "北向"), "crossborder.flows.northbound_net"),
    (("southbound", "南向"), "crossborder.flows.southbound_net"),
    (("ah_premium", "ah溢价", "ah"), "crossborder.flows.ah_premium"),
    (("pmi", "制造业pmi"), "macro.pmi.manufacturing"),
    (("cpi", "通胀"), "macro.cpi.yoy"),
    (("social_financing", "社融"), "macro.social_financing.yoy"),
    (("fx_reserves", "外储", "外汇储备"), "macro.fx_reserves"),
    (("lpr", "贷款市场报价"), "macro.lpr.1y"),
)


@dataclass
class SeriesMapping:
    """单条用户序列的字段映射。

    Attributes:
        series_id: 目标序列 ID（建议使用 ``cbr.data.series`` 规范 ID）。
        file: 相对 ``custom_data_dir`` 的文件名。
        value_column: 数值列名。
        date_column: 日期列名。
        release_time_column: 发布时点列名（None 时用观测日 + 时滞近似）。
        release_lag_days: 发布时滞（自然日）。
        unit: 单位（None 时从序列目录推断）。
        frequency: ``daily`` / ``monthly`` / ``event`` / ``text``。
        source: 数据来源标记。
        name: 中文名称（None 时从序列目录推断）。
        sheet: Excel/多 sheet 文件时可选（CSV/Parquet 忽略）。
    """

    series_id: str
    file: str
    value_column: str
    date_column: str | None = None
    release_time_column: str | None = None
    release_lag_days: int = 0
    unit: str | None = None
    frequency: str = "daily"
    source: str = "user-provided"
    name: str | None = None
    sheet: str | None = None


@dataclass
class DocumentMapping:
    """用户文本数据映射。"""

    file: str
    publish_time_column: str | None = None
    title_column: str | None = None
    body_column: str | None = None
    source_column: str | None = None
    url_column: str | None = None
    doc_id_column: str | None = None
    source_name: str = "user-provided"


@dataclass
class CustomMapping:
    """``configs/data_mapping.yaml`` 的结构。"""

    custom_data_dir: str = "data/custom"
    series: list[SeriesMapping] = field(default_factory=list)
    documents: list[DocumentMapping] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# 读取映射配置
# --------------------------------------------------------------------------- #
def load_mapping(path: str | Path = DEFAULT_MAPPING_PATH) -> CustomMapping:
    """读取字段映射配置；文件缺失或为空时返回空映射。"""
    resolved = resolve_path(path)
    if not resolved.exists():
        return CustomMapping()
    raw = yaml.safe_load(resolved.read_text(encoding="utf-8")) or {}
    series = [SeriesMapping(**item) for item in raw.get("series", []) or []]
    documents = [DocumentMapping(**item) for item in raw.get("documents", []) or []]
    return CustomMapping(
        custom_data_dir=str(raw.get("custom_data_dir", "data/custom")),
        series=series,
        documents=documents,
    )


# --------------------------------------------------------------------------- #
# 列名启发式
# --------------------------------------------------------------------------- #
def _find_column(columns: list[str], candidates: tuple[str, ...]) -> str | None:
    """在列名中按候选（忽略大小写）查找第一个匹配列。"""
    lowered = {str(col).strip().lower(): str(col) for col in columns}
    for candidate in candidates:
        if candidate.lower() in lowered:
            return lowered[candidate.lower()]
    return None


def _guess_series_id(file_stem: str, column: str) -> str:
    """根据文件名 + 列名猜测规范序列 ID。"""
    haystack = f"{file_stem} {column}".lower()
    for keywords, series_id in _SERIES_HINTS:
        if any(keyword.lower() in haystack for keyword in keywords):
            return series_id
    return f"custom.{file_stem}.{column}"


def _read_table(path: Path) -> pd.DataFrame:
    """读取 CSV / Parquet 文件（CSV 自动尝试 utf-8 / gbk）。"""
    suffix = path.suffix.lower()
    if suffix in (".parquet", ".pq"):
        return pd.read_parquet(path)
    if suffix in (".csv", ".txt"):
        for encoding in ("utf-8-sig", "utf-8", "gbk"):
            try:
                return pd.read_csv(path, encoding=encoding)
            except UnicodeDecodeError:
                continue
        return pd.read_csv(path)
    raise ValueError(f"不支持的自建数据文件类型: {path.name}")


# --------------------------------------------------------------------------- #
# 适配器
# --------------------------------------------------------------------------- #
class CustomDatasetAdapter:
    """用户自建数据适配器：扫描目录、应用映射、产出 ``MarketDataset``。

    Args:
        mapping_path: 字段映射配置路径。
        custom_data_dir: 覆盖映射中的自定义数据目录（便于测试使用临时目录）。
    """

    def __init__(
        self,
        mapping_path: str | Path = DEFAULT_MAPPING_PATH,
        custom_data_dir: str | Path | None = None,
        source: str = "user-provided",
    ) -> None:
        self.mapping = load_mapping(mapping_path)
        self.custom_dir = resolve_path(custom_data_dir or self.mapping.custom_data_dir)
        self.source = source
        self.warnings: list[str] = []

    # -- 探测 -------------------------------------------------------------
    def discover_files(self) -> list[Path]:
        """扫描可用数据文件（csv/parquet）。"""
        if not self.custom_dir.exists():
            return []
        files = [
            path
            for path in sorted(self.custom_dir.rglob("*"))
            if path.is_file() and path.suffix.lower() in (".csv", ".parquet", ".pq", ".txt")
        ]
        return files

    @property
    def has_custom(self) -> bool:
        """是否存在可用的用户自建数据（文件存在且能识别出至少一条序列）。"""
        return len(self.detect_series_plan()) > 0 or len(self.detect_document_plan()) > 0

    def detect_series_plan(self) -> list[SeriesMapping]:
        """返回数值序列读取计划（显式映射优先，否则自动识别）。"""
        plan = [item for item in self.mapping.series if (self.custom_dir / item.file).exists()]
        planned_files = {item.file for item in plan}
        for path in self.discover_files():
            if path.name in planned_files or self._is_document_file(path):
                continue
            try:
                frame = _read_table(path)
            except (OSError, ValueError) as exc:
                self.warnings.append(f"读取 {path.name} 失败: {exc}")
                continue
            date_column = _find_column(list(frame.columns), DATE_COLUMNS)
            if date_column is None:
                continue
            numeric_columns = [
                str(col)
                for col in frame.columns
                if str(col) != date_column and pd.api.types.is_numeric_dtype(frame[col])
            ]
            for column in numeric_columns:
                series_id = _guess_series_id(path.stem, column)
                plan.append(
                    SeriesMapping(
                        series_id=series_id,
                        file=path.name,
                        value_column=column,
                        date_column=date_column,
                        unit=series_unit(series_id),
                        source=self.source,
                        name=SERIES_SPECS[series_id].name if series_id in SERIES_SPECS else column,
                    )
                )
        # 去重（同一 series_id 只保留第一条）
        seen: set[str] = set()
        unique: list[SeriesMapping] = []
        for item in plan:
            if item.series_id in seen:
                self.warnings.append(f"序列 {item.series_id} 重复映射，保留首条")
                continue
            seen.add(item.series_id)
            unique.append(item)
        return unique

    @staticmethod
    def _is_document_file(path: Path) -> bool:
        """按文件名判断是否为文本/文档文件。"""
        stem = path.stem.lower()
        return any(token in stem for token in ("doc", "news", "text", "policy", "语料", "新闻", "政策"))

    def detect_document_plan(self) -> list[DocumentMapping]:
        """返回文档读取计划（显式映射优先，否则自动识别）。"""
        plan = [item for item in self.mapping.documents if (self.custom_dir / item.file).exists()]
        planned = {item.file for item in plan}
        for path in self.discover_files():
            if path.name in planned or not self._is_document_file(path):
                continue
            try:
                frame = _read_table(path)
            except (OSError, ValueError) as exc:
                self.warnings.append(f"读取文档 {path.name} 失败: {exc}")
                continue
            title_col = _find_column(list(frame.columns), DOC_TITLE_COLUMNS)
            time_col = _find_column(list(frame.columns), RELEASE_COLUMNS + DATE_COLUMNS)
            if title_col is None or time_col is None:
                continue
            plan.append(
                DocumentMapping(
                    file=path.name,
                    publish_time_column=time_col,
                    title_column=title_col,
                    body_column=_find_column(list(frame.columns), DOC_BODY_COLUMNS),
                    source_column=_find_column(list(frame.columns), DOC_SOURCE_COLUMNS),
                    url_column=_find_column(list(frame.columns), DOC_URL_COLUMNS),
                    doc_id_column=_find_column(list(frame.columns), DOC_DOCID_COLUMNS),
                    source_name=self.source,
                )
            )
        return plan

    # -- 读取 -------------------------------------------------------------
    def load(self) -> tuple[MarketDataset, list[DataCard]]:
        """读取用户数据，返回 ``(数据集, 数据卡列表)``。

        没有任何可用文件时返回空数据集（``has_custom=False`` 的调用方应回退）。
        """
        obs_parts: list[pd.DataFrame] = []
        cards: list[DataCard] = []
        for item in self.detect_series_plan():
            path = self.custom_dir / item.file
            try:
                frame = _read_table(path)
            except (OSError, ValueError) as exc:
                self.warnings.append(f"读取 {item.file} 失败: {exc}")
                continue
            date_col = item.date_column or _find_column(list(frame.columns), DATE_COLUMNS)
            if date_col is None or item.value_column not in frame.columns:
                self.warnings.append(f"{item.file} 缺少日期列或数值列 {item.value_column}")
                continue
            obs = pd.DataFrame(
                {
                    "series_id": item.series_id,
                    "obs_date": pd.to_datetime(frame[date_col], errors="coerce").dt.normalize(),
                    "value": pd.to_numeric(frame[item.value_column], errors="coerce"),
                    "source": item.source,
                    "unit": item.unit or series_unit(item.series_id),
                }
            )
            release_col = item.release_time_column or _find_column(list(frame.columns), RELEASE_COLUMNS)
            if release_col is not None:
                obs["release_time"] = pd.to_datetime(frame[release_col], errors="coerce")
            else:
                obs["release_time"] = obs["obs_date"] + pd.Timedelta(days=item.release_lag_days, hours=16)
            obs = obs.dropna(subset=["obs_date", "value", "release_time"])
            if obs.empty:
                self.warnings.append(f"{item.file}:{item.value_column} 没有有效数据")
                continue
            obs_parts.append(obs.loc[:, list(OBS_COLUMNS)])
            start = obs["obs_date"].min().date()
            end = obs["obs_date"].max().date()
            cards.append(
                DataCard(
                    series_id=item.series_id,
                    name=item.name or (SERIES_SPECS[item.series_id].name if item.series_id in SERIES_SPECS else item.series_id),
                    source=item.source,
                    frequency=item.frequency,  # type: ignore[arg-type]
                    coverage_start=start,
                    coverage_end=end,
                    release_lag_days=item.release_lag_days,
                    pit_grade="approximate" if release_col is None else "strict",
                    unit=item.unit or series_unit(item.series_id),
                    notes="用户自建数据（字段映射来自 configs/data_mapping.yaml）",
                )
            )
        doc_parts: list[pd.DataFrame] = []
        for item in self.detect_document_plan():
            path = self.custom_dir / item.file
            try:
                frame = _read_table(path)
            except (OSError, ValueError) as exc:
                self.warnings.append(f"读取文档 {item.file} 失败: {exc}")
                continue
            time_col = item.publish_time_column or _find_column(list(frame.columns), RELEASE_COLUMNS + DATE_COLUMNS)
            title_col = item.title_column or _find_column(list(frame.columns), DOC_TITLE_COLUMNS)
            if time_col is None or title_col is None:
                continue
            body_col = item.body_column or _find_column(list(frame.columns), DOC_BODY_COLUMNS)
            source_col = item.source_column or _find_column(list(frame.columns), DOC_SOURCE_COLUMNS)
            url_col = item.url_column or _find_column(list(frame.columns), DOC_URL_COLUMNS)
            id_col = item.doc_id_column or _find_column(list(frame.columns), DOC_DOCID_COLUMNS)
            body_col = body_col if body_col in frame.columns else None
            source_col = source_col if source_col in frame.columns else None
            url_col = url_col if url_col in frame.columns else None
            id_col = id_col if id_col in frame.columns else None
            docs = pd.DataFrame(
                {
                    "doc_id": (
                        frame[id_col].astype(str)
                        if id_col
                        else [f"{path.stem}_{i:05d}" for i in range(len(frame))]
                    ),
                    "publish_time": pd.to_datetime(frame[time_col], errors="coerce"),
                    "source": (frame[source_col].astype(str) if source_col else item.source_name),
                    "title": frame[title_col].astype(str),
                    "body": (frame[body_col].astype(str) if body_col else frame[title_col].astype(str)),
                    "url": (frame[url_col].astype(str) if url_col else ""),
                    "hash": "",
                }
            )
            docs = docs.dropna(subset=["publish_time"])
            docs["hash"] = docs.apply(
                lambda row: _stable_hash(f"{row['doc_id']}|{row['title']}|{row['body']}"), axis=1
            )
            doc_parts.append(docs.loc[:, list(DOC_COLUMNS)])
        obs_frame = (
            pd.concat(obs_parts, ignore_index=True)
            if obs_parts
            else MarketDataset.empty().obs
        )
        docs_frame = (
            pd.concat(doc_parts, ignore_index=True)
            if doc_parts
            else MarketDataset.empty().documents
        )
        dataset = MarketDataset(
            obs=obs_frame,
            documents=docs_frame,
            seed=0,
            source=self.source,
            meta={"custom": True, "warnings": self.warnings},
        )
        return dataset, cards


def _stable_hash(text: str) -> str:
    """稳定哈希（sha256 前 32 位，用于文档去重/引文核验）。"""
    import hashlib

    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:32]


def has_custom_data(
    mapping_path: str | Path = DEFAULT_MAPPING_PATH,
    custom_data_dir: str | Path | None = None,
) -> bool:
    """便捷函数：判断是否存在可用的用户自建数据。"""
    return CustomDatasetAdapter(mapping_path=mapping_path, custom_data_dir=custom_data_dir).has_custom
