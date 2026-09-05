"""ue-remote-mcp のローカル設定を読み込む。"""

from __future__ import annotations

import ast
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10 には tomllib がないため最小限の互換読込を使う。
    tomllib = None  # type: ignore[assignment]


DEFAULT_CONFIG_PATH = Path("~/.config/ue-remote/config.toml")


class ConfigError(ValueError):
    """設定が不足している、または値が不正である。"""


@dataclass(frozen=True)
class LockConfig:
    ttl_seconds: int = 300
    heartbeat_seconds: int = 60


@dataclass(frozen=True)
class AuditConfig:
    local_dir: Path = field(
        default_factory=lambda: Path("~/.local/share/ue-remote/audit").expanduser()
    )
    remote_flush_every: int = 20


@dataclass(frozen=True)
class Config:
    host: str
    port: int
    timeout_seconds: float
    developer_id: str
    expected_project: str | None
    lock: LockConfig = field(default_factory=LockConfig)
    audit: AuditConfig = field(default_factory=AuditConfig)

    # 並行して実装される各コンポーネントからも自然に参照できる別名。
    @property
    def lock_ttl_seconds(self) -> int:
        return self.lock.ttl_seconds

    @property
    def lock_heartbeat_seconds(self) -> int:
        return self.lock.heartbeat_seconds

    @property
    def audit_local_dir(self) -> Path:
        return self.audit.local_dir

    @property
    def audit_remote_flush_every(self) -> int:
        return self.audit.remote_flush_every


def _strip_toml_comment(line: str) -> str:
    """Python 3.10 用の限定パーサで、文字列外のコメントだけを除く。"""
    quote: str | None = None
    escaped = False
    for index, char in enumerate(line):
        if escaped:
            escaped = False
            continue
        if quote == '"' and char == "\\":
            escaped = True
            continue
        if char in {'"', "'"}:
            quote = None if quote == char else char if quote is None else quote
        elif char == "#" and quote is None:
            return line[:index]
    return line


def _parse_toml_compat(data: bytes) -> dict[str, Any]:
    """Python 3.10 でこの設定ファイルに必要な TOML の部分集合を読む。"""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ConfigError(f"設定ファイルが UTF-8 ではありません: {exc}") from exc

    result: dict[str, Any] = {}
    section = result
    for line_number, original in enumerate(text.splitlines(), 1):
        line = _strip_toml_comment(original).strip()
        if not line:
            continue
        if line.startswith("[") and line.endswith("]"):
            section_name = line[1:-1].strip()
            if not section_name:
                raise ConfigError(f"設定ファイルの {line_number} 行目の節名が空です")
            section = result.setdefault(section_name, {})
            if not isinstance(section, dict):
                raise ConfigError(f"設定ファイルの節 [{section_name}] が重複しています")
            continue
        if "=" not in line:
            raise ConfigError(f"設定ファイルの {line_number} 行目を解釈できません")
        key, raw_value = (part.strip() for part in line.split("=", 1))
        try:
            value = ast.literal_eval(raw_value)
        except (SyntaxError, ValueError) as exc:
            raise ConfigError(
                f"設定ファイルの {line_number} 行目の値を解釈できません: {raw_value}"
            ) from exc
        section[key] = value
    return result


def _read_toml(path: Path) -> dict[str, Any]:
    data = path.read_bytes()
    if tomllib is not None:
        try:
            return tomllib.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
            raise ConfigError(f"設定ファイル {path} の TOML が不正です: {exc}") from exc
    return _parse_toml_compat(data)


def _table(value: Any, name: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ConfigError(f"設定 [{name}] はテーブルで指定してください")
    return value


def _string(value: Any, name: str, *, required: bool = True) -> str | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        if required:
            raise ConfigError(f"{name} が未設定です")
        return None
    if not isinstance(value, str):
        raise ConfigError(f"{name} は文字列で指定してください")
    return value.strip()


def _integer(value: Any, name: str, *, minimum: int, maximum: int | None = None) -> int:
    if isinstance(value, bool):
        raise ConfigError(f"{name} は整数で指定してください")
    try:
        converted = int(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{name} は整数で指定してください: {value!r}") from exc
    if isinstance(value, float) and not value.is_integer():
        raise ConfigError(f"{name} は整数で指定してください: {value!r}")
    if converted < minimum or (maximum is not None and converted > maximum):
        range_text = f"{minimum} 以上" + (f" {maximum} 以下" if maximum is not None else "")
        raise ConfigError(f"{name} は {range_text}で指定してください: {converted}")
    return converted


def _positive_float(value: Any, name: str) -> float:
    if isinstance(value, bool):
        raise ConfigError(f"{name} は正の数で指定してください")
    try:
        converted = float(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{name} は正の数で指定してください: {value!r}") from exc
    if converted <= 0:
        raise ConfigError(f"{name} は 0 より大きい値で指定してください: {converted}")
    return converted


def load_config(
    path: str | Path = DEFAULT_CONFIG_PATH,
    environ: Mapping[str, str] | None = None,
) -> Config:
    """TOML を読み、環境変数による上書きを適用する。"""
    config_path = Path(path).expanduser()
    values = _read_toml(config_path) if config_path.is_file() else {}
    env = os.environ if environ is None else environ
    lock_values = _table(values.get("lock"), "lock")
    audit_values = _table(values.get("audit"), "audit")

    host_value: Any = env.get("UE_REMOTE_HOST", values.get("host", "127.0.0.1"))
    port_value: Any = env.get("UE_REMOTE_PORT", values.get("port", 30010))
    developer_value: Any = env.get("UE_REMOTE_DEVELOPER_ID", values.get("developer_id"))
    project_value: Any = env.get("UE_REMOTE_PROJECT", values.get("expected_project"))

    host = _string(host_value, "host")
    developer_id = _string(developer_value, "developer_id")
    expected_project = _string(project_value, "expected_project", required=False)
    assert host is not None and developer_id is not None

    local_dir_value = audit_values.get("local_dir", "~/.local/share/ue-remote/audit")
    local_dir_string = _string(local_dir_value, "audit.local_dir")
    assert local_dir_string is not None

    return Config(
        host=host,
        port=_integer(port_value, "port", minimum=1, maximum=65535),
        timeout_seconds=_positive_float(values.get("timeout_seconds", 15.0), "timeout_seconds"),
        developer_id=developer_id,
        expected_project=expected_project,
        lock=LockConfig(
            ttl_seconds=_integer(
                lock_values.get("ttl_seconds", 300), "lock.ttl_seconds", minimum=1
            ),
            heartbeat_seconds=_integer(
                lock_values.get("heartbeat_seconds", 60),
                "lock.heartbeat_seconds",
                minimum=1,
            ),
        ),
        audit=AuditConfig(
            local_dir=Path(local_dir_string).expanduser(),
            remote_flush_every=_integer(
                audit_values.get("remote_flush_every", 20),
                "audit.remote_flush_every",
                minimum=1,
            ),
        ),
    )
