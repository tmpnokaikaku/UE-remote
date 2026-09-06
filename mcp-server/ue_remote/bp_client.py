"""BlueprintMCP プラグインの HTTP クライアント。"""

from __future__ import annotations

import json
import socket
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from .config import Config
from .errors import (
    BlueprintHTTPError,
    BlueprintRequestError,
    BlueprintResponseError,
    BlueprintUnreachable,
)


class BlueprintClient:
    """BlueprintMCP プラグイン (:9847) の HTTP クライアント。"""

    def __init__(self, config: Config) -> None:
        self._host = config.host
        self._port = config.blueprint_port
        self._timeout = config.blueprint_timeout_seconds
        host_for_url = (
            f"[{self._host}]"
            if ":" in self._host and not self._host.startswith("[")
            else self._host
        )
        self._base_url = f"http://{host_for_url}:{self._port}"

    def request(
        self,
        route: str,
        verb: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """指定した BlueprintMCP ルートを呼び出し、JSON 応答を返す。"""

        method = verb.upper()
        if method not in {"GET", "POST"}:
            raise ValueError("verb は GET または POST で指定してください")

        url = self._base_url + route
        encoded: bytes | None = None
        headers = {"Accept": "application/json"}
        if method == "GET":
            query = urllib.parse.urlencode(
                [
                    (key, str(value))
                    for key, value in (payload or {}).items()
                    if value is not None and value != ""
                ]
            )
            if query:
                url += ("&" if "?" in url else "?") + query
        else:
            # BlueprintMCP は Content-Length 必須なので、空でも必ず本文を送る。
            encoded = json.dumps(payload or {}, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"

        request = urllib.request.Request(
            url,
            data=encoded,
            method=method,
            headers=headers,
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                raw_body = response.read()
        except urllib.error.HTTPError as exc:
            try:
                response_body = exc.read().decode("utf-8", errors="replace")
            except OSError:
                response_body = ""
            raise BlueprintHTTPError(exc.code, response_body) from exc
        except (urllib.error.URLError, TimeoutError, socket.timeout, OSError) as exc:
            raise BlueprintUnreachable(self._host, self._port, exc) from exc

        try:
            parsed = json.loads(raw_body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise BlueprintResponseError(
                f"BlueprintMCP API の応答が有効な JSON ではありません: {exc}"
            ) from exc
        if not isinstance(parsed, dict):
            raise BlueprintResponseError(
                f"BlueprintMCP API の応答が JSON オブジェクトではありません: "
                f"{type(parsed).__name__}"
            )

        error = parsed.get("error")
        if error is not None and str(error) != "":
            raise BlueprintRequestError(route, str(error), parsed)
        if parsed.get("success") is False:
            preview = json.dumps(parsed, ensure_ascii=False, default=str)
            if len(preview) > 300:
                preview = preview[:300] + "…"
            raise BlueprintRequestError(
                route,
                f"success=false が返されました（応答: {preview}）",
                parsed,
            )
        return parsed

    def health(self) -> dict[str, Any]:
        """BlueprintMCP の稼働状態を返す。"""

        return self.request("/api/health", "GET")
