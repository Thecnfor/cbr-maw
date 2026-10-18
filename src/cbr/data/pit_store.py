"""Point-in-time 存储（DuckDB）：序列观测与文本文档的时点数据库。

核心表结构（与架构文档 3.1 一致）：

.. code-block:: sql

    series_obs(series_id, obs_date, value, release_time, source, unit)
    documents(doc_id, publish_time, source, title, body, url, hash)
    series_meta(...)   -- 数据卡元数据（额外表，便于 UI/API 直接读取）

所有读取接口都显式接收 ``as_of``，只返回 ``release_time <= as_of 当日 23:59:59``
（文档为 ``publish_time``）的记录，从存储层保证 point-in-time 语义。
``series_meta`` 用于持久化 ``DataCard``，避免每次从头推导覆盖期。
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable

import duckdb
import pandas as pd

from cbr.data.catalog import (
    MONTHLY_SERIES_IDS,
    SERIES_SPECS,
    build_data_cards,
    canonical_series_id,
    series_unit,
)
from cbr.data.dataset import MarketDataset, as_of_timestamp
from cbr.schemas import DataCard

#: 观测表建表语句
_CREATE_SERIES_OBS = """
CREATE TABLE IF NOT EXISTS series_obs (
    series_id VARCHAR NOT NULL,
    obs_date DATE NOT NULL,
    value DOUBLE,
    release_time TIMESTAMP NOT NULL,
    source VARCHAR,
    unit VARCHAR
)
"""

#: 文档表建表语句
_CREATE_DOCUMENTS = """
CREATE TABLE IF NOT EXISTS documents (
    doc_id VARCHAR PRIMARY KEY,
    publish_time TIMESTAMP NOT NULL,
    source VARCHAR,
    title VARCHAR,
    body VARCHAR,
    url VARCHAR,
    hash VARCHAR
)
"""

#: 数据卡元数据表
_CREATE_SERIES_META = """
CREATE TABLE IF NOT EXISTS series_meta (
    series_id VARCHAR PRIMARY KEY,
    name VARCHAR,
    source VARCHAR,
    frequency VARCHAR,
    coverage_start DATE,
    coverage_end DATE,
    release_lag_days INTEGER,
    pit_grade VARCHAR,
    unit VARCHAR,
    notes VARCHAR
)
"""


class PitStore:
    """DuckDB 时点存储封装。

    典型用法::

        store = PitStore("data/pit.duckdb")            # 只读
        rows = store.history("market.cn_equity.csi300", date(2024, 8, 5), 120)
        store.asof_values(date(2024, 8, 5))

        # 构建（scripts/build_dataset.py）
        store = PitStore("data/pit.duckdb", read_only=False)
        store.load_dataset(dataset, replace=True)

    Attributes:
        db_path: 数据库文件路径；``":memory:"`` 表示内存库。
    """

    def __init__(self, db_path: str | Path, read_only: bool | None = None) -> None:
        self.db_path = str(db_path)
        self.read_only = read_only
        self._conn: duckdb.DuckDBPyConnection | None = None

    # ------------------------------------------------------------------ #
    # 连接管理
    # ------------------------------------------------------------------ #
    @property
    def connection(self) -> duckdb.DuckDBPyConnection:
        """惰性打开 DuckDB 连接（文件不存在且只读时报错）。"""
        if self._conn is None:
            if self.db_path != ":memory:":
                path = Path(self.db_path)
                if not path.is_absolute():
                    path = Path(__file__).resolve().parents[3] / path
                self.db_path = str(path)
                path.parent.mkdir(parents=True, exist_ok=True)
                read_only = self.read_only if self.read_only is not None else path.exists()
                self._conn = duckdb.connect(str(path), read_only=bool(read_only))
            else:
                self._conn = duckdb.connect(":memory:")
        return self._conn

    def close(self) -> None:
        """关闭连接（可重复调用）。"""
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> "PitStore":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ------------------------------------------------------------------ #
    # 构建 / 写入
    # ------------------------------------------------------------------ #
    def initialize_schema(self) -> None:
        """创建（或确保存在）三张核心表。"""
        conn = self.connection
        for sql in (_CREATE_SERIES_OBS, _CREATE_DOCUMENTS, _CREATE_SERIES_META):
            conn.execute(sql)

    def load_dataset(self, dataset: MarketDataset, replace: bool = True) -> dict[str, int]:
        """把 ``MarketDataset`` 写入 PIT 数据库（写模式）。

        Args:
            dataset: 待写入的数据集。
            replace: 是否先清空既有表（默认 True，保证库与数据集一致）。

        Returns:
            ``{"series_obs": n, "documents": m, "series_meta": k}`` 行数统计。
        """
        conn = self.connection
        self.initialize_schema()
        if replace:
            conn.execute("DELETE FROM series_obs")
            conn.execute("DELETE FROM documents")
            conn.execute("DELETE FROM series_meta")
        obs = dataset.obs.dropna(subset=["value"]).copy()
        obs["obs_date"] = pd.to_datetime(obs["obs_date"]).dt.date
        obs["release_time"] = pd.to_datetime(obs["release_time"])
        obs = obs.loc[:, ["series_id", "obs_date", "value", "release_time", "source", "unit"]]
        conn.register("obs_df", obs)
        conn.execute("INSERT INTO series_obs SELECT * FROM obs_df")
        conn.unregister("obs_df")
        docs = dataset.documents.copy()
        docs["publish_time"] = pd.to_datetime(docs["publish_time"])
        docs = docs.loc[:, ["doc_id", "publish_time", "source", "title", "body", "url", "hash"]]
        if not docs.empty:
            conn.register("docs_df", docs)
            conn.execute("INSERT OR REPLACE INTO documents SELECT * FROM docs_df")
            conn.unregister("docs_df")
        cards = dataset.data_cards()
        self.load_data_cards(cards)
        return {
            "series_obs": int(conn.execute("SELECT count(*) FROM series_obs").fetchone()[0]),
            "documents": int(conn.execute("SELECT count(*) FROM documents").fetchone()[0]),
            "series_meta": int(conn.execute("SELECT count(*) FROM series_meta").fetchone()[0]),
        }

    def load_data_cards(self, cards: Iterable[DataCard]) -> int:
        """写入/更新数据卡元数据（``series_meta`` 表）。"""
        records = [
            {
                "series_id": card.series_id,
                "name": card.name,
                "source": card.source,
                "frequency": card.frequency,
                "coverage_start": card.coverage_start,
                "coverage_end": card.coverage_end,
                "release_lag_days": card.release_lag_days,
                "pit_grade": card.pit_grade,
                "unit": card.unit,
                "notes": card.notes,
            }
            for card in cards
        ]
        if not records:
            return 0
        conn = self.connection
        self.initialize_schema()
        frame = pd.DataFrame(records)
        conn.register("cards_df", frame)
        conn.execute("INSERT OR REPLACE INTO series_meta SELECT * FROM cards_df")
        conn.unregister("cards_df")
        return len(records)

    # ------------------------------------------------------------------ #
    # Point-in-time 查询
    # ------------------------------------------------------------------ #
    def asof(
        self,
        series_id: str,
        as_of: date | datetime | str | pd.Timestamp,
        lookback: int | None = None,
    ) -> pd.DataFrame:
        """返回序列截至 ``as_of`` 的观测（``release_time <= as_of``）。

        Args:
            series_id: 序列 ID（支持别名归一化）。
            as_of: 时点（含当日已发布信息）。
            lookback: 仅返回最近 ``lookback`` 条（None 表示全部）。

        Returns:
            列 ``series_id, obs_date, value, release_time, source, unit`` 的 DataFrame，
            按 ``obs_date`` 升序。
        """
        sid = canonical_series_id(series_id)
        end_ts = as_of_timestamp(as_of).to_pydatetime()
        sql = (
            "SELECT series_id, obs_date, value, release_time, source, unit FROM series_obs "
            "WHERE series_id = ? AND release_time <= ? ORDER BY obs_date ASC"
        )
        frame = self.connection.execute(sql, [sid, end_ts]).fetch_df()
        if lookback is not None and lookback > 0:
            frame = frame.tail(int(lookback)).reset_index(drop=True)
        return frame

    def history(
        self,
        series_id: str,
        as_of: date | datetime | str | pd.Timestamp,
        lookback: int = 120,
    ) -> list[dict[str, Any]]:
        """返回截至 ``as_of`` 的历史序列 ``[{"date": date, "value": float}, ...]``。"""
        frame = self.asof(series_id, as_of, lookback=lookback)
        out: list[dict[str, Any]] = []
        for row in frame.itertuples(index=False):
            value = row.value
            if value is None or pd.isna(value):
                continue
            obs_date = row.obs_date
            if isinstance(obs_date, pd.Timestamp):
                obs_date = obs_date.date()
            out.append({"date": obs_date, "value": float(value)})
        return out

    def asof_values(
        self,
        as_of: date | datetime | str | pd.Timestamp,
        series_ids: Iterable[str] | None = None,
    ) -> dict[str, float]:
        """返回 ``as_of`` 当日各序列的最新可得值。"""
        end_ts = as_of_timestamp(as_of).to_pydatetime()
        params: list[Any] = [end_ts]
        where = "release_time <= ?"
        if series_ids is not None:
            ids = [canonical_series_id(s) for s in series_ids]
            if not ids:
                return {}
            placeholders = ", ".join(["?"] * len(ids))
            where += f" AND series_id IN ({placeholders})"
            params.extend(ids)
        sql = f"""
            SELECT series_id, value FROM (
                SELECT series_id, value,
                       ROW_NUMBER() OVER (PARTITION BY series_id ORDER BY obs_date DESC, release_time DESC) AS rn
                FROM series_obs WHERE {where}
            ) WHERE rn = 1
        """
        frame = self.connection.execute(sql, params).fetch_df()
        values: dict[str, float] = {}
        for row in frame.itertuples(index=False):
            if row.value is None or pd.isna(row.value):
                continue
            values[str(row.series_id)] = float(row.value)
        return values

    def documents_asof(
        self,
        as_of: date | datetime | str | pd.Timestamp,
        limit: int | None = None,
    ) -> pd.DataFrame:
        """返回 ``publish_time <= as_of`` 的文档（时点过滤）。"""
        end_ts = as_of_timestamp(as_of).to_pydatetime()
        sql = (
            "SELECT doc_id, publish_time, source, title, body, url, hash FROM documents "
            "WHERE publish_time <= ? ORDER BY publish_time ASC"
        )
        frame = self.connection.execute(sql, [end_ts]).fetch_df()
        if limit is not None and limit > 0:
            frame = frame.head(int(limit)).reset_index(drop=True)
        return frame

    # ------------------------------------------------------------------ #
    # 数据卡 / 覆盖期
    # ------------------------------------------------------------------ #
    def data_cards(self) -> list[DataCard]:
        """返回全部数据卡（优先读 ``series_meta``；表空则按目录兜底）。"""
        try:
            frame = self.connection.execute(
                "SELECT series_id, name, source, frequency, coverage_start, coverage_end, "
                "release_lag_days, pit_grade, unit, notes FROM series_meta ORDER BY series_id"
            ).fetch_df()
        except duckdb.CatalogException:  # pragma: no cover - 空库兜底
            return build_data_cards()
        if frame.empty:
            return build_data_cards()
        cards: list[DataCard] = []
        for row in frame.itertuples(index=False):
            cards.append(
                DataCard(
                    series_id=str(row.series_id),
                    name=str(row.name or row.series_id),
                    source=str(row.source or "unknown"),
                    frequency=str(row.frequency or "daily"),
                    coverage_start=row.coverage_start,
                    coverage_end=row.coverage_end,
                    release_lag_days=int(row.release_lag_days or 0),
                    pit_grade=str(row.pit_grade or "strict"),
                    unit=row.unit,
                    notes=str(row.notes or ""),
                )
            )
        return cards

    def coverage(self) -> dict[str, tuple[date | None, date | None]]:
        """返回每个序列的实际覆盖期 ``{series_id: (start, end)}``。"""
        frame = self.connection.execute(
            "SELECT series_id, min(obs_date) AS start, max(obs_date) AS end "
            "FROM series_obs GROUP BY series_id ORDER BY series_id"
        ).fetch_df()
        out: dict[str, tuple[date | None, date | None]] = {}
        for row in frame.itertuples(index=False):
            out[str(row.series_id)] = (row.start, row.end)
        return out

    def counts(self) -> dict[str, int]:
        """返回各表行数统计（健康检查/API 使用）。"""
        return {
            "series_obs": int(self.connection.execute("SELECT count(*) FROM series_obs").fetchone()[0]),
            "documents": int(self.connection.execute("SELECT count(*) FROM documents").fetchone()[0]),
            "series_meta": int(self.connection.execute("SELECT count(*) FROM series_meta").fetchone()[0]),
        }

    # ------------------------------------------------------------------ #
    # 重建数据集（供 Provider 计算特征/标签）
    # ------------------------------------------------------------------ #
    def load_market_dataset(self, with_documents: bool = True) -> MarketDataset:
        """把库内观测/文档读回 ``MarketDataset``（用于特征与标签计算）。

        注意：读回的是**全量历史**，具体特征/信号计算仍必须通过 ``as_of`` 接口
        或滚动统计（只含 t 及以前）来保证时点正确；不要在全量数据上做全局统计。

        Args:
            with_documents: 是否读取文档表（文本特征需要）。

        Returns:
            ``MarketDataset``。
        """
        obs = self.connection.execute(
            "SELECT series_id, obs_date, value, release_time, source, unit FROM series_obs "
            "ORDER BY series_id, obs_date"
        ).fetch_df()
        if obs.empty:
            documents = pd.DataFrame(
                columns=["doc_id", "publish_time", "source", "title", "body", "url", "hash"]
            )
            return MarketDataset.empty()
        documents = (
            self.documents_asof(pd.Timestamp("2100-01-01"))
            if with_documents
            else pd.DataFrame(columns=["doc_id", "publish_time", "source", "title", "body", "url", "hash"])
        )
        source = "synthetic-simulation"
        if not obs.empty:
            sources = obs["source"].dropna().unique()
            if len(sources) == 1:
                source = str(sources[0])
            else:
                source = "mixed"
        return MarketDataset(obs=obs, documents=documents, seed=0, source=source, meta={"from_pit_store": True})

    # ------------------------------------------------------------------ #
    # 构造工厂
    # ------------------------------------------------------------------ #
    @classmethod
    def from_dataset(
        cls,
        dataset: MarketDataset,
        db_path: str | Path = "data/pit.duckdb",
    ) -> "PitStore":
        """新建/覆盖 ``db_path`` 并写入数据集（写模式）。"""
        store = cls(db_path, read_only=False)
        store.load_dataset(dataset, replace=True)
        return store

    @classmethod
    def open(cls, db_path: str | Path = "data/pit.duckdb") -> "PitStore":
        """以只读模式打开已有数据库；文件不存在时抛 ``FileNotFoundError``。"""
        path = Path(db_path)
        if not path.is_absolute():
            path = Path(__file__).resolve().parents[3] / path
        if not path.exists():
            raise FileNotFoundError(f"PIT 数据库不存在: {path}；请先运行 python scripts/build_dataset.py")
        store = cls(path, read_only=True)
        # 触发连接校验表存在
        try:
            store.connection.execute("SELECT count(*) FROM series_obs").fetchone()
        except duckdb.CatalogException as exc:  # pragma: no cover
            raise ValueError(f"PIT 数据库缺少 series_obs 表: {path}") from exc
        return store


def build_pit_store(dataset: MarketDataset, db_path: str | Path = "data/pit.duckdb") -> PitStore:
    """便捷函数：由数据集构建 PIT 数据库并返回只读实例。"""
    PitStore.from_dataset(dataset, db_path).close()
    return PitStore.open(db_path)
