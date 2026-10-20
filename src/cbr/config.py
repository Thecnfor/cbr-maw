"""配置加载：YAML + 环境变量 + .env + 本地密钥文件。

用法::

    from cbr.config import load_settings, load_roles, load_scenarios
    settings = load_settings()
    roles = load_roles()
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

from .schemas import ExperimentConfig, Role, RoleSpec, Scenario

ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "configs"
SECRETS_DIR = ROOT / "secrets"


def _load_dotenv() -> None:
    """若安装 python-dotenv，则加载项目根目录 .env（不覆盖已有环境变量）。"""
    try:
        from dotenv import load_dotenv

        env_file = ROOT / ".env"
        if env_file.exists():
            load_dotenv(env_file, override=False)
    except ImportError:  # pragma: no cover
        pass


class LLMSettings(BaseModel):
    provider: str = "deepseek"
    model: str = "deepseek-chat"
    base_url: str = "https://api.deepseek.com"
    temperature: float = 0.0
    max_tokens: int = 2000
    mock: bool = True
    api_key_env: str = "DEEPSEEK_API_KEY"
    api_key_file: str = "secrets/deepseek.key"
    timeout_seconds: int = 60
    max_retries: int = 2


class DataSettings(BaseModel):
    dataset: str = "auto"  # auto | custom | public | synthetic
    custom_data_dir: str = "data/custom"
    #: 自建数据缺失序列是否回退 synthetic（真实数据实验应设为 False，避免仿真值混入）
    synthetic_fallback: bool = True
    pit_db: str = "data/pit.duckdb"
    sample_dir: str = "data/samples"
    snapshot_dir: str = "data/processed"
    sample_start: str = "2018-01-01"
    sample_end: str = "2025-09-30"
    label_version: str = "stress_pca_q90"
    high_stress_quantile: float = 0.90
    horizons: list[int] = Field(default_factory=lambda: [5, 10, 20])


class SignalSettings(BaseModel):
    model_version: str = "fusion-xgb-v1"
    baseline: str = "xgboost"
    text_enabled: bool = True
    roll_window: int = 500
    retrain_every: int = 20


class OrchestrationSettings(BaseModel):
    rounds: int = 2
    max_tool_calls_per_agent: int = 6
    max_tokens_per_agent: int = 4000
    numeric_tolerance_abs: float = 1e-6
    numeric_tolerance_rel: float = 1e-3
    modes: list[str] = Field(default_factory=lambda: ["single", "independent", "collaborative"])
    human_in_the_loop: bool = True
    trace_dir: str = "artifacts/traces"
    # 协同成本折算（统一成本单位，用于 J = L + μ·C 与 P3 成本比较）
    cost_per_tool_call: float = 0.001
    cost_per_1k_tokens: float = 0.001
    cost_per_latency_ms: float = 1.0e-5
    coordination_weight_mu: float = 0.1


class ServerSettings(BaseModel):
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    ui_port: int = 8501


class PathSettings(BaseModel):
    artifacts: str = "artifacts"
    docs: str = "docs"
    knowledge: str = "data/knowledge"


class AppSettings(BaseModel):
    app_name: str = "CBR-MAW"
    timezone: str = "Asia/Shanghai"
    llm: LLMSettings = Field(default_factory=LLMSettings)
    data: DataSettings = Field(default_factory=DataSettings)
    signal: SignalSettings = Field(default_factory=SignalSettings)
    orchestration: OrchestrationSettings = Field(default_factory=OrchestrationSettings)
    server: ServerSettings = Field(default_factory=ServerSettings)
    paths: PathSettings = Field(default_factory=PathSettings)


# --------------------------------------------------------------------------- #
# 通用读取
# --------------------------------------------------------------------------- #
def resolve_path(path: str | os.PathLike[str]) -> Path:
    p = Path(path)
    return p if p.is_absolute() else (ROOT / p)


def _read_yaml(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def load_yaml(path: str | os.PathLike[str], default: Any = None) -> Any:
    p = resolve_path(path)
    if not p.exists():
        return default
    return _read_yaml(p)


def load_settings(path: str | None = None) -> AppSettings:
    _load_dotenv()
    config_path = resolve_path(path or os.environ.get("CBR_CONFIG", "configs/app.yaml"))
    raw = _read_yaml(config_path) if config_path.exists() else {}
    settings = AppSettings(**raw)
    # 密钥文件存在时自动关闭 mock
    if not settings.llm.mock:
        pass
    elif resolve_llm_api_key(settings):
        settings.llm.mock = False
    return settings


def resolve_llm_api_key(settings: AppSettings | None = None) -> str | None:
    """按优先级读取 API key：环境变量 > secrets/deepseek.key > .env（已由 load_dotenv 注入）。"""
    settings = settings or load_settings()
    _load_dotenv()
    key = os.environ.get(settings.llm.api_key_env, "").strip()
    if key:
        return key
    key_file = resolve_path(settings.llm.api_key_file)
    if key_file.exists():
        content = key_file.read_text(encoding="utf-8").strip()
        if content:
            return content
    return None


def load_role_specs(path: str = "configs/roles.yaml") -> dict[Role, RoleSpec]:
    raw = load_yaml(path, default={}) or {}
    specs: dict[Role, RoleSpec] = {}
    for key, value in raw.items():
        role = Role(key)
        specs[role] = RoleSpec(role=role, **value)
    return specs


class RoleRegistryImpl:
    """contracts.RoleRegistry 的默认实现：角色规范字典的只读包装。"""

    def __init__(
        self,
        specs: dict[Role, RoleSpec] | None = None,
        path: str = "configs/roles.yaml",
    ) -> None:
        self._specs: dict[Role, RoleSpec] = dict(specs) if specs is not None else load_role_specs(path)

    def get(self, role: Role | str) -> RoleSpec:
        return self._specs[Role(role)]

    def all(self) -> list[RoleSpec]:
        return list(self._specs.values())

    def __contains__(self, role: Role | str) -> bool:
        return Role(role) in self._specs


def load_role_registry(path: str = "configs/roles.yaml") -> RoleRegistryImpl:
    return RoleRegistryImpl(load_role_specs(path))


def load_scenarios(path: str = "configs/scenarios.yaml") -> list[Scenario]:
    raw = load_yaml(path, default=[]) or []
    return [Scenario(**item) for item in raw]


def load_experiment_config(path: str | os.PathLike[str]) -> ExperimentConfig:
    raw = load_yaml(path, default={}) or {}
    return ExperimentConfig(**raw)
