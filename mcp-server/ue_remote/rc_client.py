"""Unreal Engine Remote Control API の HTTP クライアント。"""

from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request
from typing import Any, Iterable

from .config import Config
from .errors import (
    PythonExecutionError,
    RemoteControlHTTPError,
    RemoteControlResponseError,
    RemoteControlUnreachable,
)
from .interfaces import PythonResult


PYTHON_LIBRARY = "/Script/PythonScriptPlugin.Default__PythonScriptLibrary"


def _iter_strings(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _iter_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _iter_strings(item)


def _find_key(value: Any, wanted: str) -> Any:
    """応答の入れ子とキーの大小文字の揺れを許容して値を探す。"""
    if isinstance(value, dict):
        for key, item in value.items():
            if key.lower() == wanted.lower():
                return item
        for item in value.values():
            found = _find_key(item, wanted)
            if found is not None:
                return found
    elif isinstance(value, list):
        for item in value:
            found = _find_key(item, wanted)
            if found is not None:
                return found
    return None


def _normalise_logs(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        logs: list[str] = []
        for item in value:
            if isinstance(item, str):
                logs.append(item)
            elif isinstance(item, dict):
                output = next(
                    (entry for key, entry in item.items() if key.lower() == "output"), None
                )
                logs.append(str(output) if output is not None else json.dumps(item, ensure_ascii=False))
            else:
                logs.append(str(item))
        return logs
    return [str(value)]


class RemoteControlClient:
    """Config で指定された Unreal Editor と HTTP で通信する。"""

    def __init__(self, config: Config) -> None:
        self._host = config.host
        self._port = config.port
        self._timeout = config.timeout_seconds
        host_for_url = (
            f"[{self._host}]"
            if ":" in self._host and not self._host.startswith("[")
            else self._host
        )
        self._base_url = f"http://{host_for_url}:{self._port}"

    def _request_json(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        encoded = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            self._base_url + path,
            data=encoded,
            method=method,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            try:
                response_body = exc.read().decode("utf-8", errors="replace")
            except OSError:
                response_body = ""
            raise RemoteControlHTTPError(exc.code, response_body) from exc
        except (urllib.error.URLError, TimeoutError, socket.timeout, OSError) as exc:
            raise RemoteControlUnreachable(self._host, self._port, exc) from exc

        try:
            parsed = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RemoteControlResponseError(
                f"Remote Control API の応答が有効な JSON ではありません: {exc}"
            ) from exc
        if not isinstance(parsed, dict):
            raise RemoteControlResponseError(
                f"Remote Control API の応答が JSON オブジェクトではありません: "
                f"{type(parsed).__name__}"
            )
        return parsed

    def call_object(
        self,
        object_path: str,
        function_name: str,
        parameters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._request_json(
            "PUT",
            "/remote/object/call",
            {
                "objectPath": object_path,
                "functionName": function_name,
                "parameters": {} if parameters is None else parameters,
                "generateTransaction": True,
            },
        )

    def execute_python(self, script: str) -> PythonResult:
        # 一行の exec に包み、Remote Control の command mode の差を避ける。
        raw = self.call_object(
            PYTHON_LIBRARY,
            "ExecutePythonCommandEx",
            {"PythonCommand": f"exec({script!r})"},
        )
        return_value = _find_key(raw, "ReturnValue")
        command_value = _find_key(raw, "CommandResult")
        command_result = None if command_value is None else str(command_value)
        log_output = _normalise_logs(_find_key(raw, "LogOutput"))

        if isinstance(return_value, bool):
            ok = return_value
        else:
            # UE のバージョン差で結果フィールドが省略されても、2xx 応答は実行済みと扱う。
            # CommandResult は成功状態ではなく任意のコマンド出力なので判定には使わない。
            ok = True

        result = PythonResult(ok=ok, log_output=log_output, command_result=command_result, raw=raw)
        if not ok:
            raise PythonExecutionError(log_output, command_result, raw)
        return result

    def run_python_json(self, script: str, marker: str) -> Any:
        """Python の標準出力に埋め込まれたマーカ直後の JSON を返す。"""
        if not marker:
            raise ValueError("marker は空文字列にできません")
        result = self.execute_python(script)
        decoder = json.JSONDecoder()
        parse_errors: list[str] = []
        for candidate in _iter_strings(result.raw):
            search_from = 0
            while True:
                marker_at = candidate.find(marker, search_from)
                if marker_at < 0:
                    break
                marked_text = candidate[marker_at + len(marker) :].lstrip()
                try:
                    value, _ = decoder.raw_decode(marked_text)
                    return value
                except json.JSONDecodeError as exc:
                    parse_errors.append(str(exc))
                search_from = marker_at + len(marker)
        if parse_errors:
            raise RemoteControlResponseError(
                f"マーカ {marker!r} に続く JSON を解析できません: {parse_errors[0]}"
            )
        raise RemoteControlResponseError(f"応答内に JSON マーカ {marker!r} がありません")

    def get_property(self, object_path: str, property_name: str) -> dict[str, Any]:
        return self._request_json(
            "PUT",
            "/remote/object/property",
            {
                "objectPath": object_path,
                "propertyName": property_name,
                "access": "READ_ACCESS",
            },
        )

    def set_property(
        self, object_path: str, property_name: str, value: Any
    ) -> dict[str, Any]:
        return self._request_json(
            "PUT",
            "/remote/object/property",
            {
                "objectPath": object_path,
                "propertyName": property_name,
                "propertyValue": value,
                "access": "WRITE_ACCESS",
                "generateTransaction": True,
            },
        )

    def search_assets(self, query: str, limit: int = 50) -> dict[str, Any]:
        if limit < 1:
            raise ValueError("limit は 1 以上で指定してください")
        return self._request_json(
            "PUT",
            "/remote/search/assets",
            {
                "Query": query,
                "Limit": limit,
                "Filter": {
                    "PackageNames": [],
                    "ClassNames": [],
                    "PackagePaths": [],
                    "RecursiveClassesExclusionSet": [],
                    "RecursivePaths": False,
                    "RecursiveClasses": False,
                },
            },
        )

    def describe_object(self, object_path: str) -> dict[str, Any]:
        return self._request_json(
            "PUT", "/remote/object/describe", {"objectPath": object_path}
        )

    def info(self) -> dict[str, Any]:
        return self._request_json("GET", "/remote/info")

    # /remote/batch は UE 5.5.4 の既知の不具合でエディタをクラッシュさせるため、
    # 誤って呼べるメソッドも含めて一切実装しない。
