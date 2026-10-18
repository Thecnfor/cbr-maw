"""自建数据接入端到端测试（Lead 维护）。

验证：用户按 ``data/custom`` + 文件格式提供 CSV 后，``data.dataset=custom`` 能让
``build_data_provider`` 自动并入用户数据（缺失序列回退 SYNTHETIC），数据卡标记
``user-provided``，且共享风险信号/历史序列接口可用——即“数据到位即可接入”。
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from cbr.config import load_settings
from cbr.data import build_data_provider


def _write_custom_fixture(custom_dir: Path) -> None:
    dates = pd.date_range("2024-01-02", periods=40, freq="B")
    pd.DataFrame(
        {
            "date": dates,
            "csi300": np.linspace(3000, 3300, len(dates)),
            "credit_spread": np.linspace(80, 130, len(dates)),
        }
    ).to_csv(custom_dir / "my_market.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(
        {
            "publish_time": ["2024-01-05 10:00:00", "2024-01-08 16:00:00"],
            "title": ["测试政策一", "测试新闻二"],
            "content": ["流动性保持合理充裕。", "跨境资金流出压力上升。"],
            "source": ["中国人民银行", "财经媒体"],
            "url": ["https://example.com/1", "https://example.com/2"],
        }
    ).to_csv(custom_dir / "policy_news.csv", index=False, encoding="utf-8-sig")


def test_custom_provider_end_to_end(tmp_path: Path) -> None:
    custom_dir = tmp_path / "custom"
    custom_dir.mkdir()
    _write_custom_fixture(custom_dir)

    settings = load_settings()
    settings.data.dataset = "custom"
    settings.data.custom_data_dir = str(custom_dir)

    provider = build_data_provider(settings)
    assert provider.source_label == "custom+synthetic"

    cards = provider.data_cards()
    assert len(cards) >= 5
    assert any(card.source == "user-provided" for card in cards)

    as_of = pd.Timestamp("2024-01-15")
    signal = provider.risk_signal(as_of)
    assert signal.as_of == as_of.date()
    assert signal.horizons and signal.evidence_id

    history = provider.history("market.cn_equity.csi300", as_of, 20)
    assert history, "用户自建序列应可被工具/智能体读取"
    assert len(history) <= 20

    snapshot = provider.market_snapshot(as_of)
    assert snapshot.as_of == as_of.date()
