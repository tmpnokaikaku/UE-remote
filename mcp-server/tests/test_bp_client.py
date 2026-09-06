"""BlueprintMCP HTTP クライアントの単体テスト。"""

from __future__ import annotations

import io
import json
import unittest
import urllib.error
import urllib.parse
from typing import Any
from unittest.mock import patch

from ue_remote.bp_client import BlueprintClient
from ue_remote.config import Config
from ue_remote.errors import (
    BlueprintHTTPError,
    BlueprintRequestError,
    BlueprintResponseError,
    BlueprintUnreachable,
)


class FakeResponse:
    def __init__(self, body: bytes) -> None:
        self.body = body

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *args: Any) -> None:
        return None

    def read(self) -> bytes:
        return self.body


class BlueprintClientTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = BlueprintClient(
            Config(
                host="127.0.0.1",
                port=30010,
                timeout_seconds=1.0,
                developer_id="tester",
                expected_project=None,
                blueprint_port=9847,
                blueprint_timeout_seconds=37.5,
            )
        )

    @patch("urllib.request.urlopen")
    def test_get_builds_query_and_omits_none_and_empty_string(self, urlopen: Any) -> None:
        urlopen.return_value = FakeResponse(b'{"status":"ok"}')

        result = self.client.request(
            "/api/search",
            "get",
            {"query": "Print String", "maxResults": 12, "none": None, "empty": ""},
        )

        request = urlopen.call_args.args[0]
        parsed_url = urllib.parse.urlsplit(request.full_url)
        self.assertEqual("GET", request.get_method())
        self.assertEqual("/api/search", parsed_url.path)
        self.assertEqual(
            {"query": ["Print String"], "maxResults": ["12"]},
            urllib.parse.parse_qs(parsed_url.query),
        )
        self.assertEqual({"status": "ok"}, result)

    @patch("urllib.request.urlopen")
    def test_post_sends_json_body_and_content_type(self, urlopen: Any) -> None:
        urlopen.return_value = FakeResponse(b'{"success":true}')

        self.client.request(
            "/api/add-node", "post", {"blueprint": "BP_Test", "posX": 100}
        )

        request = urlopen.call_args.args[0]
        self.assertEqual("POST", request.get_method())
        self.assertEqual(
            {"blueprint": "BP_Test", "posX": 100},
            json.loads(request.data.decode("utf-8")),
        )
        self.assertEqual("application/json", request.get_header("Content-type"))

    @patch("urllib.request.urlopen")
    def test_post_with_none_payload_sends_empty_object(self, urlopen: Any) -> None:
        urlopen.return_value = FakeResponse(b'{"success":true}')

        self.client.request("/api/list-classes", "POST")

        request = urlopen.call_args.args[0]
        self.assertEqual(b"{}", request.data)
        self.assertEqual("application/json", request.get_header("Content-type"))

    @patch("urllib.request.urlopen")
    def test_error_field_is_application_error(self, urlopen: Any) -> None:
        raw = {"error": "Blueprint not found", "available": ["BP_Other"]}
        urlopen.return_value = FakeResponse(json.dumps(raw).encode("utf-8"))

        with self.assertRaises(BlueprintRequestError) as caught:
            self.client.request("/api/blueprint", "GET", {"name": "missing"})

        self.assertEqual("/api/blueprint", caught.exception.route)
        self.assertEqual("Blueprint not found", caught.exception.message)
        self.assertEqual(raw, caught.exception.raw)

    @patch("urllib.request.urlopen")
    def test_false_success_is_application_error(self, urlopen: Any) -> None:
        raw = {"success": False, "saved": False}
        urlopen.return_value = FakeResponse(json.dumps(raw).encode("utf-8"))

        with self.assertRaises(BlueprintRequestError) as caught:
            self.client.request("/api/create-blueprint", "POST", {})

        self.assertIn("success=false", caught.exception.message)
        self.assertIn("saved", caught.exception.message)
        self.assertEqual(raw, caught.exception.raw)

    @patch("urllib.request.urlopen")
    def test_response_without_success_is_returned(self, urlopen: Any) -> None:
        raw = {"status": "ok", "blueprintCount": 521}
        urlopen.return_value = FakeResponse(json.dumps(raw).encode("utf-8"))

        self.assertEqual(raw, self.client.health())

    @patch("urllib.request.urlopen")
    def test_unreachable_server_is_normalised(self, urlopen: Any) -> None:
        urlopen.side_effect = urllib.error.URLError("connection refused")

        with self.assertRaises(BlueprintUnreachable) as caught:
            self.client.health()

        self.assertEqual("127.0.0.1", caught.exception.host)
        self.assertEqual(9847, caught.exception.port)

    @patch("urllib.request.urlopen")
    def test_http_error_is_normalised_with_status_and_body(self, urlopen: Any) -> None:
        urlopen.side_effect = urllib.error.HTTPError(
            "http://127.0.0.1:9847/api/health",
            503,
            "Service Unavailable",
            {},
            io.BytesIO(b'{"error":"busy"}'),
        )

        with self.assertRaises(BlueprintHTTPError) as caught:
            self.client.health()

        self.assertEqual(503, caught.exception.status_code)
        self.assertIn("busy", caught.exception.body)

    @patch("urllib.request.urlopen")
    def test_broken_json_is_response_error(self, urlopen: Any) -> None:
        urlopen.return_value = FakeResponse(b"not-json")

        with self.assertRaises(BlueprintResponseError):
            self.client.health()

    @patch("urllib.request.urlopen")
    def test_non_object_json_is_response_error(self, urlopen: Any) -> None:
        urlopen.return_value = FakeResponse(b"[]")

        with self.assertRaises(BlueprintResponseError):
            self.client.health()

    @patch("urllib.request.urlopen")
    def test_invalid_verb_is_rejected_without_request(self, urlopen: Any) -> None:
        with self.assertRaises(ValueError):
            self.client.request("/api/health", "PUT")

        urlopen.assert_not_called()

    @patch("urllib.request.urlopen")
    def test_blueprint_timeout_is_used(self, urlopen: Any) -> None:
        urlopen.return_value = FakeResponse(b'{"status":"ok"}')

        self.client.health()

        self.assertEqual(37.5, urlopen.call_args.kwargs["timeout"])

    @patch("urllib.request.urlopen")
    def test_ipv6_host_is_bracketed(self, urlopen: Any) -> None:
        urlopen.return_value = FakeResponse(b'{"status":"ok"}')
        client = BlueprintClient(
            Config(
                host="2001:db8::1",
                port=30010,
                timeout_seconds=1.0,
                developer_id="tester",
                expected_project=None,
            )
        )

        client.health()

        request = urlopen.call_args.args[0]
        self.assertEqual("http://[2001:db8::1]:9847/api/health", request.full_url)


if __name__ == "__main__":
    unittest.main()
