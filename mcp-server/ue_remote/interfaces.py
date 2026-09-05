"""MCP サーバ内部で共有する Remote Control の型定義。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass
class PythonResult:
    """Unreal Engine で実行した Python コマンドの結果。"""

    ok: bool
    log_output: list[str]
    command_result: str | None
    raw: dict[str, Any]


class RemoteControlClient(Protocol):
    """Remote Control API を利用するコンポーネントの共通境界。"""

    def call_object(
        self,
        object_path: str,
        function_name: str,
        parameters: dict[str, Any] | None = None,
    ) -> dict[str, Any]: ...

    def execute_python(self, script: str) -> PythonResult: ...

    def get_property(self, object_path: str, property_name: str) -> dict[str, Any]: ...

    def set_property(
        self, object_path: str, property_name: str, value: Any
    ) -> dict[str, Any]: ...

    def search_assets(self, query: str, limit: int = 50) -> dict[str, Any]: ...

    def describe_object(self, object_path: str) -> dict[str, Any]: ...

    def info(self) -> dict[str, Any]: ...
