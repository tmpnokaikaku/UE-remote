"""接続先 Unreal プロジェクトの取り違えを防ぐガード。"""

from __future__ import annotations

import json
import textwrap
from dataclasses import dataclass
from typing import Any


_RESULT_MARKER = "UE_REMOTE_GUARD_RESULT:"


@dataclass(frozen=True)
class GuardResult:
    """プロジェクト確認の判定理由を含む結果。"""

    ok: bool
    message: str
    expected_project: str | None
    actual_project: str | None
    project_path: str | None
    warning: str | None = None


def verify(client: Any, expected_project: str | None) -> GuardResult:
    """現在開いている ``.uproject`` のベース名を確認する。"""

    script = textwrap.dedent(
        f"""
        import json
        import os
        import unreal

        _path = str(unreal.Paths.get_project_file_path())
        _filename = _path.replace("\\\\", "/").rsplit("/", 1)[-1]
        _project = os.path.splitext(_filename)[0]
        print({_RESULT_MARKER!r} + json.dumps(
            {{"project_path": _path, "actual_project": _project}},
            ensure_ascii=False,
            separators=(",", ":"),
        ))
        """
    )
    try:
        payload = client.run_python_json(script, _RESULT_MARKER)
    except Exception as exc:  # 通信失敗も理由付きの拒否にする
        return GuardResult(
            False,
            f"プロジェクト情報を取得できませんでした: {type(exc).__name__}: {exc}",
            expected_project,
            None,
            None,
        )

    if not isinstance(payload, dict):
        return GuardResult(
            False,
            "プロジェクト情報を取得できませんでした",
            expected_project,
            None,
            None,
        )

    actual = _optional_str(payload.get("actual_project"))
    path = _optional_str(payload.get("project_path"))
    if expected_project is None:
        warning = "expected_project が未設定です。実際のプロジェクトを確認して設定してください"
        return GuardResult(True, warning, None, actual, path, warning)
    if actual == expected_project:
        return GuardResult(
            True,
            f"期待したプロジェクトを確認しました: {actual}",
            expected_project,
            actual,
            path,
        )
    return GuardResult(
        False,
        f"期待したプロジェクトと違います。実際: {actual}（{path}）",
        expected_project,
        actual,
        path,
    )


class ProjectGuard:
    """期待プロジェクトを保持して繰り返し確認するための薄いラッパー。"""

    def __init__(self, client: Any, expected_project: str | None) -> None:
        self.client = client
        self.expected_project = expected_project

    def verify(self) -> GuardResult:
        return verify(self.client, self.expected_project)


def _optional_str(value: Any) -> str | None:
    return None if value is None else str(value)
