"""Remote Control HTTP クライアントの単体テスト。"""

from __future__ import annotations

import json
import socket
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from ue_remote.config import Config
from ue_remote.errors import (
    PythonExecutionError,
    RemoteControlHTTPError,
    RemoteControlUnreachable,
)
from ue_remote.rc_client import PYTHON_LIBRARY, RemoteControlClient


class FakeRemoteControlHandler(BaseHTTPRequestHandler):
    def do_PUT(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        self.server.last_path = self.path  # type: ignore[attr-defined]
        self.server.last_request = json.loads(self.rfile.read(length))  # type: ignore[attr-defined]
        status = self.server.response_status  # type: ignore[attr-defined]
        body = self.server.response_body  # type: ignore[attr-defined]
        encoded = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, format: str, *args: Any) -> None:
        return


class RemoteControlClientTests(unittest.TestCase):
    def setUp(self) -> None:
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), FakeRemoteControlHandler)
        self.server.response_status = 200  # type: ignore[attr-defined]
        self.server.response_body = {}  # type: ignore[attr-defined]
        self.server.last_request = None  # type: ignore[attr-defined]
        self.server_thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.server_thread.start()
        self.client = self._client(self.server.server_address[1])

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.server_thread.join(timeout=2)

    @staticmethod
    def _client(port: int) -> RemoteControlClient:
        return RemoteControlClient(
            Config(
                host="127.0.0.1",
                port=port,
                timeout_seconds=1.0,
                developer_id="tester",
                expected_project=None,
            )
        )

    def test_execute_python_success(self) -> None:
        self.server.response_body = {  # type: ignore[attr-defined]
            "ReturnValue": True,
            "CommandResult": "Success",
            "LogOutput": [{"Type": "Info", "Output": "完了"}],
        }

        result = self.client.execute_python("print('ok')\nvalue = 1")

        self.assertTrue(result.ok)
        self.assertEqual(["完了"], result.log_output)
        request = self.server.last_request  # type: ignore[attr-defined]
        self.assertEqual(PYTHON_LIBRARY, request["objectPath"])
        self.assertEqual("ExecutePythonCommandEx", request["functionName"])
        self.assertEqual(
            "exec(\"print('ok')\\nvalue = 1\")", request["parameters"]["PythonCommand"]
        )

    def test_execute_python_failure_preserves_log_output(self) -> None:
        self.server.response_body = {  # type: ignore[attr-defined]
            "Wrapper": {
                "ReturnValue": False,
                "CommandResult": "Failure",
                "LogOutput": [{"Output": "NameError: name 'x' is not defined"}],
            }
        }

        with self.assertRaises(PythonExecutionError) as caught:
            self.client.execute_python("print(x)")

        self.assertEqual(["NameError: name 'x' is not defined"], caught.exception.log_output)

    def test_run_python_json_finds_marker_at_arbitrary_depth(self) -> None:
        marker = "__result_json__"
        self.server.response_body = {  # type: ignore[attr-defined]
            "outer": [
                {"irrelevant": "UE log"},
                {
                    "deeper": {
                        "LogOutput": [
                            {"Output": f"LogPython: {marker}{json.dumps({'ok': True, 'n': 3})}"}
                        ]
                    }
                },
            ],
            "ReturnValue": True,
        }

        value = self.client.run_python_json("print('marker output')", marker)

        self.assertEqual({"ok": True, "n": 3}, value)

    def test_unreachable_server_is_normalised(self) -> None:
        reserved = socket.socket()
        reserved.bind(("127.0.0.1", 0))
        port = reserved.getsockname()[1]
        try:
            with self.assertRaises(RemoteControlUnreachable):
                self._client(port).execute_python("pass")
        finally:
            reserved.close()

    def test_http_500_is_normalised_with_status(self) -> None:
        self.server.response_status = 500  # type: ignore[attr-defined]
        self.server.response_body = {"error": "fake failure"}  # type: ignore[attr-defined]

        with self.assertRaises(RemoteControlHTTPError) as caught:
            self.client.execute_python("pass")

        self.assertEqual(500, caught.exception.status_code)
        self.assertIn("fake failure", caught.exception.body)


if __name__ == "__main__":
    unittest.main()
