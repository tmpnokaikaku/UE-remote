#!/usr/bin/env python3
"""Unreal Engine Remote Control API の能力を一括測定する。"""

from __future__ import annotations

import argparse
import json
import os
import socket
import statistics
import sys
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable


MAX_BODY_CHARS = 20_000
PYTHON_LIBRARY = "/Script/PythonScriptPlugin.Default__PythonScriptLibrary"
PYTHON_MARKER = "__ue_remote_probe_ok__"
ENV_MARKER = "__ue_remote_probe_env_json__"
LATENCY_THROTTLE_HINT_THRESHOLD_MS = 100.0
LATENCY_THROTTLE_HINT = (
    "エディタの CPU スロットリングの可能性があります。Editor Preferences > Performance > "
    '"Use Less CPU when in Background" (`bThrottleCPUWhenNotForeground`) を無効にすると改善する'
    "可能性があります"
)
BATCH_SKIP_REASON = (
    "既定では実行しません（エディタをクラッシュさせる既知の不具合があります。"
    "--include-batch で明示的に有効化できます）"
)
BATCH_WARNING = (
    "WARN: /remote/batch を実行します。既知のエンジン不具合によりエディタがクラッシュする可能性があります。"
)


@dataclass
class HttpExchange:
    method: str
    url: str
    ok: bool
    duration_ms: float
    status_code: int | None = None
    error: str | None = None
    response_body: str = ""
    response_body_truncated: bool = False
    json_valid: bool = False


@dataclass
class CheckResult:
    key: str
    name: str
    status: str
    reason: str
    duration_ms: float
    details: dict[str, Any] = field(default_factory=dict)
    http: list[HttpExchange] = field(default_factory=list)


@dataclass
class ProbeContext:
    host: str
    port: int
    timeout: float
    tcp_ok: bool = False
    python_ok: bool = False
    include_batch: bool = False

    @property
    def base_url(self) -> str:
        # urllib で IPv6 リテラルを扱える形にする。
        host = f"[{self.host}]" if ":" in self.host and not self.host.startswith("[") else self.host
        return f"http://{host}:{self.port}"


@dataclass(frozen=True)
class CheckSpec:
    key: str
    name: str
    run: Callable[[ProbeContext], CheckResult]
    needs_tcp: bool = False
    needs_python: bool = False
    needs_batch_opt_in: bool = False


def elapsed_ms(start: float) -> float:
    return round((time.perf_counter() - start) * 1000.0, 3)


def shorten_body(body: str) -> tuple[str, bool]:
    if len(body) <= MAX_BODY_CHARS:
        return body, False
    return body[:MAX_BODY_CHARS], True


def request_json(
    context: ProbeContext,
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
) -> tuple[HttpExchange, Any | None]:
    """HTTP 例外もレスポンスとして回収し、呼び出し元へ例外を漏らさない。"""
    url = context.base_url + path
    encoded = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=encoded,
        method=method,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    start = time.perf_counter()
    status_code: int | None = None
    raw_bytes = b""
    error: str | None = None
    try:
        with urllib.request.urlopen(request, timeout=context.timeout) as response:
            status_code = response.status
            raw_bytes = response.read()
    except urllib.error.HTTPError as exc:
        status_code = exc.code
        error = f"HTTP {exc.code}: {exc.reason}"
        try:
            raw_bytes = exc.read()
        except Exception as read_exc:  # 応答 body の回収失敗も診断情報に留める。
            error += f"; response body read failed: {type(read_exc).__name__}: {read_exc}"
    except (urllib.error.URLError, TimeoutError, socket.timeout, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        error = f"{type(exc).__name__}: {reason}"
    except Exception as exc:  # urllib 周辺の予期しない失敗でもプローブ全体は継続する。
        error = f"{type(exc).__name__}: {exc}"

    raw_text = raw_bytes.decode("utf-8", errors="replace")
    stored_body, truncated = shorten_body(raw_text)
    parsed: Any | None = None
    json_valid = False
    if raw_text:
        try:
            parsed = json.loads(raw_text)
            json_valid = True
        except (json.JSONDecodeError, UnicodeError):
            pass
    ok = error is None and status_code is not None and 200 <= status_code < 300
    exchange = HttpExchange(
        method=method,
        url=url,
        ok=ok,
        duration_ms=elapsed_ms(start),
        status_code=status_code,
        error=error,
        response_body=stored_body,
        response_body_truncated=truncated,
        json_valid=json_valid,
    )
    return exchange, parsed


def fail_reason(exchange: HttpExchange, require_json: bool = False) -> str:
    if exchange.error:
        return exchange.error
    if not exchange.ok:
        return f"HTTP status {exchange.status_code}"
    if require_json and not exchange.json_valid:
        return "応答 body が有効な JSON ではありません"
    return "期待した応答が得られませんでした"


def tcp_check(context: ProbeContext) -> CheckResult:
    start = time.perf_counter()
    try:
        with socket.create_connection((context.host, context.port), timeout=context.timeout):
            pass
        context.tcp_ok = True
        return CheckResult("tcp", "TCP 到達性", "OK", "TCP 接続に成功", elapsed_ms(start))
    except (TimeoutError, socket.timeout, OSError) as exc:
        return CheckResult(
            "tcp",
            "TCP 到達性",
            "FAIL",
            f"{type(exc).__name__}: {exc}",
            elapsed_ms(start),
        )
    except Exception as exc:
        return CheckResult(
            "tcp", "TCP 到達性", "FAIL", f"{type(exc).__name__}: {exc}", elapsed_ms(start)
        )


def find_route_list(value: Any) -> Any:
    """既知のキー名を大小文字に依存せず探し、応答形状の揺れを許容する。"""
    if isinstance(value, dict):
        for key, item in value.items():
            if key.lower() in {"routes", "httproutes"}:
                return item
        for item in value.values():
            found = find_route_list(item)
            if found is not None:
                return found
    elif isinstance(value, list):
        for item in value:
            found = find_route_list(item)
            if found is not None:
                return found
    return None


def info_check(context: ProbeContext) -> CheckResult:
    exchange, parsed = request_json(context, "GET", "/remote/info")
    ok = exchange.ok and exchange.json_valid
    routes = find_route_list(parsed) if parsed is not None else None
    details = {"routes": routes if routes is not None else parsed}
    return CheckResult(
        "remote_info",
        "GET /remote/info",
        "OK" if ok else "FAIL",
        "Remote Control のルート一覧を取得" if ok else fail_reason(exchange, True),
        exchange.duration_ms,
        details,
        [exchange],
    )


def python_call(context: ProbeContext, command: str) -> tuple[HttpExchange, Any | None]:
    return request_json(
        context,
        "PUT",
        "/remote/object/call",
        {
            "objectPath": PYTHON_LIBRARY,
            "functionName": "ExecutePythonCommandEx",
            "parameters": {"PythonCommand": command},
            "generateTransaction": True,
        },
    )


def iter_strings(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from iter_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from iter_strings(item)


def python_check(context: ProbeContext) -> CheckResult:
    exchange, parsed = python_call(context, f"print('{PYTHON_MARKER}')")
    marker_found = PYTHON_MARKER in exchange.response_body
    if parsed is not None:
        marker_found = marker_found or any(PYTHON_MARKER in item for item in iter_strings(parsed))
    ok = exchange.ok and marker_found
    context.python_ok = ok
    if ok:
        reason = "Python を実行し、確認用出力を検出"
    elif not exchange.ok:
        reason = fail_reason(exchange)
    else:
        reason = "HTTP 呼び出しは成功しましたが、確認用出力を検出できません"
    return CheckResult(
        "python_execution",
        "Python 実行可否",
        "OK" if ok else "FAIL",
        reason,
        exchange.duration_ms,
        {"marker": PYTHON_MARKER, "marker_found": marker_found},
        [exchange],
    )


def environment_command() -> str:
    script = f"""import unreal
import json
import os
import re
import time

project_file = unreal.Paths.get_project_file_path()
saved_dir = unreal.Paths.project_saved_dir()
info = {{
    "engine_version": unreal.SystemLibrary.get_engine_version(),
    "project_name": os.path.splitext(os.path.basename(project_file))[0],
    "project_file_path": project_file,
    "project_dir": unreal.Paths.project_dir(),
    "saved_dir": saved_dir,
    "enabled_plugins": [],
    "symbols": {{}},
    "editor_throttle": None,
    "saved_write_test": {{"ok": False, "error": None}},
}}

for symbol in (
    "K2Node", "BlueprintEditorLibrary", "EditorAssetLibrary",
    "EditorLevelLibrary", "EditorActorSubsystem", "PluginBlueprintLibrary",
    "PythonScriptLibrary",
):
    info["symbols"][symbol] = hasattr(unreal, symbol)

try:
    plugin_library = getattr(unreal, "PluginBlueprintLibrary", None)
    getter = getattr(plugin_library, "get_enabled_plugin_names", None)
    if callable(getter):
        info["enabled_plugins"] = [str(item) for item in getter()]
except Exception as exc:
    info["plugin_query_error"] = type(exc).__name__ + ": " + str(exc)

# UE のバージョンや Python 公開名によって設定クラス名・プロパティ名が異なるため、
# 設定オブジェクトと ini の順でベストエフォートに取得する。
for class_name in ("EditorPerProjectUserSettings", "EditorPerformanceSettings"):
    try:
        settings_class = getattr(unreal, class_name, None)
        if settings_class is not None:
            settings = unreal.get_default_object(settings_class)
            for property_name in (
                "b_throttle_cpu_when_not_foreground",
                "throttle_cpu_when_not_foreground",
                "bThrottleCPUWhenNotForeground",
            ):
                try:
                    value = settings.get_editor_property(property_name)
                except Exception:
                    continue
                if isinstance(value, bool):
                    info["editor_throttle"] = value
                    break
    except Exception:
        continue
    if info["editor_throttle"] is not None:
        break

if info["editor_throttle"] is None:
    try:
        settings_ini = os.path.join(
            saved_dir, "Config", "WindowsEditor", "EditorPerProjectUserSettings.ini"
        )
        with open(settings_ini, "r", encoding="utf-8-sig", errors="replace") as handle:
            settings_text = handle.read()
        match = re.search(
            r"^\\s*bThrottleCPUWhenNotForeground\\s*=\\s*(True|False|1|0)\\s*(?:[;#].*)?$",
            settings_text,
            flags=re.IGNORECASE | re.MULTILINE,
        )
        if match:
            info["editor_throttle"] = match.group(1).lower() in ("true", "1")
    except Exception:
        pass

probe_path = os.path.join(saved_dir, ".ue_remote_probe_" + str(os.getpid()) + "_" + str(time.time_ns()))
try:
    os.makedirs(saved_dir, exist_ok=True)
    with open(probe_path, "x", encoding="utf-8") as handle:
        handle.write("probe")
    info["saved_write_test"]["ok"] = True
except Exception as exc:
    info["saved_write_test"]["error"] = type(exc).__name__ + ": " + str(exc)
finally:
    try:
        if os.path.exists(probe_path):
            os.remove(probe_path)
    except Exception as exc:
        info["saved_write_test"]["cleanup_error"] = type(exc).__name__ + ": " + str(exc)
        info["saved_write_test"]["ok"] = False

print("{ENV_MARKER}" + json.dumps(info, ensure_ascii=False))
"""
    # 一行の exec に包むことで、Remote Control 側の command mode の差を避ける。
    return f"exec({script!r})"


def extract_marked_json(parsed: Any, raw_body: str) -> tuple[Any | None, str | None]:
    candidates = list(iter_strings(parsed)) if parsed is not None else []
    candidates.append(raw_body)
    decoder = json.JSONDecoder()
    errors: list[str] = []
    for candidate in candidates:
        marker_at = candidate.find(ENV_MARKER)
        if marker_at < 0:
            continue
        text = candidate[marker_at + len(ENV_MARKER) :].lstrip()
        try:
            value, _ = decoder.raw_decode(text)
            return value, None
        except json.JSONDecodeError as exc:
            errors.append(str(exc))
    if errors:
        return None, "環境情報 JSON の解析に失敗: " + errors[0]
    return None, "環境情報を示すマーカーが応答内にありません"


def environment_check(context: ProbeContext) -> CheckResult:
    exchange, parsed = python_call(context, environment_command())
    environment, parse_error = extract_marked_json(parsed, exchange.response_body)
    ok = exchange.ok and isinstance(environment, dict)
    reason = "環境情報を取得" if ok else (fail_reason(exchange) if not exchange.ok else str(parse_error))
    return CheckResult(
        "environment",
        "環境情報の取得",
        "OK" if ok else "FAIL",
        reason,
        exchange.duration_ms,
        {"environment": environment},
        [exchange],
    )


def assets_check(context: ProbeContext) -> CheckResult:
    body = {
        "Query": "",
        "Filter": {
            "PackageNames": [],
            "ClassNames": [],
            "PackagePaths": [],
            "RecursiveClassesExclusionSet": [],
            "RecursivePaths": False,
            "RecursiveClasses": False,
        },
    }
    exchange, parsed = request_json(context, "PUT", "/remote/search/assets", body)
    ok = exchange.ok and exchange.json_valid
    count = len(parsed) if isinstance(parsed, list) else None
    if isinstance(parsed, dict):
        for key in ("Assets", "assets"):
            if isinstance(parsed.get(key), list):
                count = len(parsed[key])
                break
    return CheckResult(
        "asset_search",
        "PUT /remote/search/assets",
        "OK" if ok else "FAIL",
        "Asset Registry 検索に成功" if ok else fail_reason(exchange, True),
        exchange.duration_ms,
        {"result_count": count},
        [exchange],
    )


def describe_check(context: ProbeContext) -> CheckResult:
    exchange, _ = request_json(
        context, "PUT", "/remote/object/describe", {"objectPath": PYTHON_LIBRARY}
    )
    ok = exchange.ok and exchange.json_valid
    return CheckResult(
        "object_describe",
        "PUT /remote/object/describe",
        "OK" if ok else "FAIL",
        "UObject メタデータを取得" if ok else fail_reason(exchange, True),
        exchange.duration_ms,
        {"object_path": PYTHON_LIBRARY},
        [exchange],
    )


def find_batch_responses(value: Any) -> list[Any] | None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key.lower() == "responses" and isinstance(item, list):
                return item
        for item in value.values():
            found = find_batch_responses(item)
            if found is not None:
                return found
    return None


def batch_check(context: ProbeContext) -> CheckResult:
    requests = [
        {"RequestId": "probe-info-1", "URL": "/remote/info", "Verb": "GET", "Body": {}},
        {"RequestId": "probe-info-2", "URL": "/remote/info", "Verb": "GET", "Body": {}},
    ]
    exchange, parsed = request_json(context, "PUT", "/remote/batch", {"Requests": requests})
    responses = find_batch_responses(parsed)
    response_count = len(responses) if responses is not None else 0
    ok = exchange.ok and exchange.json_valid and response_count == 2
    if ok:
        reason = "1 往復で 2 件の応答を取得"
    elif not exchange.ok or not exchange.json_valid:
        reason = fail_reason(exchange, True)
    else:
        reason = f"batch 応答数が 2 件ではありません ({response_count} 件)"
    return CheckResult(
        "batch",
        "PUT /remote/batch",
        "OK" if ok else "FAIL",
        reason,
        exchange.duration_ms,
        {"response_count": response_count},
        [exchange],
    )


def latency_check(context: ProbeContext) -> CheckResult:
    start = time.perf_counter()
    exchanges: list[HttpExchange] = []
    successful: list[float] = []
    for _ in range(5):
        exchange, _ = request_json(context, "GET", "/remote/info")
        exchanges.append(exchange)
        if exchange.ok:
            successful.append(exchange.duration_ms)
    metrics: dict[str, float] = {}
    if successful:
        metrics = {
            "min_ms": round(min(successful), 3),
            "median_ms": round(statistics.median(successful), 3),
            "max_ms": round(max(successful), 3),
        }
    ok = len(successful) == 5
    reason = (
        "5 回すべて成功"
        if ok
        else f"成功した測定は {len(successful)}/5 回" + ("" if successful else "; レイテンシを算出不能")
    )
    details: dict[str, Any] = {"attempts": 5, "successful_attempts": len(successful), **metrics}
    if ok and metrics["median_ms"] > LATENCY_THROTTLE_HINT_THRESHOLD_MS:
        details["diagnostic_hint"] = LATENCY_THROTTLE_HINT
    return CheckResult(
        "latency",
        "レイテンシ測定 (GET /remote/info × 5)",
        "OK" if ok else "FAIL",
        reason,
        elapsed_ms(start),
        details,
        exchanges,
    )


def skipped(spec: CheckSpec, reason: str) -> CheckResult:
    return CheckResult(spec.key, spec.name, "SKIP", reason, 0.0)


def run_checks(context: ProbeContext) -> list[CheckResult]:
    checks = [
        CheckSpec("tcp", "TCP 到達性", tcp_check),
        CheckSpec("remote_info", "GET /remote/info", info_check),
        CheckSpec("python_execution", "Python 実行可否", python_check, needs_tcp=True),
        CheckSpec("environment", "環境情報の取得", environment_check, needs_tcp=True, needs_python=True),
        CheckSpec("asset_search", "PUT /remote/search/assets", assets_check, needs_tcp=True),
        CheckSpec("object_describe", "PUT /remote/object/describe", describe_check, needs_tcp=True),
        CheckSpec(
            "batch",
            "PUT /remote/batch",
            batch_check,
            needs_tcp=True,
            needs_batch_opt_in=True,
        ),
        CheckSpec("latency", "レイテンシ測定 (GET /remote/info × 5)", latency_check, needs_tcp=True),
    ]
    results: list[CheckResult] = []
    for spec in checks:
        if spec.needs_batch_opt_in and not context.include_batch:
            results.append(skipped(spec, BATCH_SKIP_REASON))
        elif spec.needs_tcp and not context.tcp_ok:
            results.append(skipped(spec, "TCP 接続不能のため未実施"))
        elif spec.needs_python and not context.python_ok:
            results.append(skipped(spec, "Python 実行不可のため未実施"))
        else:
            try:
                if spec.needs_batch_opt_in:
                    print(BATCH_WARNING, file=sys.stderr)
                results.append(spec.run(context))
            except Exception as exc:  # 各検査の実装不備も結果化し、後続を止めない。
                results.append(
                    CheckResult(
                        spec.key,
                        spec.name,
                        "FAIL",
                        f"予期しないエラー: {type(exc).__name__}: {exc}",
                        0.0,
                    )
                )
    return results


def result_document(context: ProbeContext, results: list[CheckResult], total_ms: float) -> dict[str, Any]:
    return {
        "probe": "Unreal Engine Remote Control API capability probe",
        "target": {"host": context.host, "port": context.port, "base_url": context.base_url},
        "timeout_seconds": context.timeout,
        "total_duration_ms": round(total_ms, 3),
        "body_limit_chars": MAX_BODY_CHARS,
        "summary": {
            status: sum(result.status == status for result in results)
            for status in ("OK", "FAIL", "SKIP")
        },
        "checks": [asdict(result) for result in results],
    }


def print_summary(document: dict[str, Any]) -> None:
    target = document["target"]
    print(f"UE Remote Control capability probe: {target['host']}:{target['port']}")
    for result in document["checks"]:
        print(
            f"[{result['status']:<4}] {result['name']}: {result['reason']} "
            f"({result['duration_ms']:.1f} ms)"
        )
        if result["key"] == "latency" and "median_ms" in result["details"]:
            details = result["details"]
            print(
                "       latency min/median/max: "
                f"{details['min_ms']:.1f}/{details['median_ms']:.1f}/{details['max_ms']:.1f} ms"
            )
    summary = document["summary"]
    print(
        f"Summary: OK={summary['OK']} FAIL={summary['FAIL']} SKIP={summary['SKIP']} "
        f"total={document['total_duration_ms']:.1f} ms"
    )


def markdown_report(document: dict[str, Any]) -> str:
    target = document["target"]
    lines = [
        "# Unreal Engine Remote Control API 能力プローブ",
        "",
        f"- 接続先: `{target['base_url']}`",
        f"- タイムアウト: {document['timeout_seconds']} 秒",
        f"- 合計所要時間: {document['total_duration_ms']:.1f} ms",
        "",
        "| 状態 | 検査 | 所要時間 (ms) | 理由 |",
        "| --- | --- | ---: | --- |",
    ]
    for result in document["checks"]:
        reason = str(result["reason"]).replace("|", "\\|").replace("\n", " ")
        lines.append(
            f"| {result['status']} | {result['name']} | {result['duration_ms']:.1f} | {reason} |"
        )
    for result in document["checks"]:
        lines.extend(["", f"## {result['name']}", "", f"**{result['status']}** — {result['reason']}"])
        if result["details"]:
            lines.extend(
                ["", "詳細:", "", "~~~json", json.dumps(result["details"], ensure_ascii=False, indent=2), "~~~"]
            )
        for index, exchange in enumerate(result["http"], start=1):
            lines.extend(
                [
                    "",
                    f"### HTTP {index}: `{exchange['method']} {exchange['url']}`",
                    "",
                    f"- status: `{exchange['status_code']}`",
                    f"- duration: {exchange['duration_ms']:.1f} ms",
                    f"- JSON: `{exchange['json_valid']}`",
                    f"- body truncated: `{exchange['response_body_truncated']}`",
                ]
            )
            if exchange["error"]:
                lines.append(f"- error: `{exchange['error']}`")
            lines.extend(["", "~~~json", exchange["response_body"], "~~~"])
    lines.append("")
    return "\n".join(lines)


def write_text(path: str, content: str) -> str | None:
    try:
        output = Path(path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(content, encoding="utf-8")
        return None
    except (OSError, UnicodeError) as exc:
        return f"{type(exc).__name__}: {exc}"


def env_port_default() -> int:
    raw = os.environ.get("UE_REMOTE_PORT", "30010")
    try:
        value = int(raw)
    except ValueError:
        return 30010
    return value if 1 <= value <= 65535 else 30010


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="UE Remote Control API の実機能力を測定します")
    parser.add_argument("--host", default=os.environ.get("UE_REMOTE_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=env_port_default())
    parser.add_argument("--timeout", type=float, default=5.0)
    parser.add_argument(
        "--include-batch",
        action="store_true",
        help="既知の不具合でエディタがクラッシュする可能性がある /remote/batch 検査を実行します",
    )
    parser.add_argument("--json", dest="json_path", metavar="PATH")
    parser.add_argument("--md", dest="md_path", metavar="PATH")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("--port は 1 から 65535 の範囲で指定してください")
    if args.timeout <= 0:
        parser.error("--timeout は 0 より大きい値を指定してください")
    return args


def main() -> int:
    args = parse_args()
    context = ProbeContext(args.host, args.port, args.timeout, include_batch=args.include_batch)
    start = time.perf_counter()
    results = run_checks(context)
    document = result_document(context, results, elapsed_ms(start))
    print_summary(document)

    if args.json_path:
        error = write_text(args.json_path, json.dumps(document, ensure_ascii=False, indent=2) + "\n")
        if error:
            print(f"WARN: JSON レポートを書き込めません: {error}", file=sys.stderr)
        else:
            print(f"JSON report: {args.json_path}")
    if args.md_path:
        error = write_text(args.md_path, markdown_report(document))
        if error:
            print(f"WARN: Markdown レポートを書き込めません: {error}", file=sys.stderr)
        else:
            print(f"Markdown report: {args.md_path}")

    fatal_keys = {"tcp", "remote_info"}
    return 1 if any(result.key in fatal_keys and result.status == "FAIL" for result in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
