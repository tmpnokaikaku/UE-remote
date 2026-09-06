from __future__ import annotations

import unittest
from dataclasses import dataclass
from typing import Any, Callable

from ue_remote.bp_tools import (
    ue_bp_add_node,
    ue_bp_add_variable,
    ue_bp_call,
    ue_bp_connect_pins,
    ue_bp_create_blueprint,
    ue_bp_create_graph,
    ue_bp_delete_node,
    ue_bp_disconnect_pin,
    ue_bp_get_blueprint,
    ue_bp_get_graph,
    ue_bp_get_pin_info,
    ue_bp_health,
    ue_bp_list_blueprints,
    ue_bp_list_functions,
    ue_bp_routes,
    ue_bp_search,
    ue_bp_set_pin_default,
    ue_bp_validate_blueprint,
)
from ue_remote.errors import BlueprintRequestError, BlueprintUnreachable


@dataclass
class FakeResult:
    ok: bool
    message: str = ""
    kind: str = ""


class FakeBlueprintClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, Any] | None]] = []
        self.error: Exception | None = None

    def request(
        self,
        route: str,
        verb: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.calls.append((route, verb, payload))
        if self.error is not None:
            raise self.error
        return {"route": route, "verb": verb, "payload": payload}


class FakeSession:
    def __init__(self) -> None:
        self.bp_client = FakeBlueprintClient()
        self.read_result = FakeResult(True)
        self.write_result = FakeResult(True)
        self.read_calls = 0
        self.write_calls = 0
        self.audit_calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def require_read(self) -> FakeResult:
        self.read_calls += 1
        return self.read_result

    def require_write(self) -> FakeResult:
        self.write_calls += 1
        return self.write_result

    def record_tool_call(self, *args: Any, **kwargs: Any) -> FakeResult:
        self.audit_calls.append((args, kwargs))
        return FakeResult(True)


class BlueprintToolsTest(unittest.TestCase):
    def test_read_route_uses_only_read_guard(self) -> None:
        session = FakeSession()

        result = ue_bp_get_graph(session, "BP_Test", "EventGraph")  # type: ignore[arg-type]

        self.assertTrue(result.ok)
        self.assertEqual(session.read_calls, 1)
        self.assertEqual(session.write_calls, 0)
        self.assertEqual(len(session.audit_calls), 1)

    def test_write_route_uses_write_guard(self) -> None:
        session = FakeSession()

        result = ue_bp_delete_node(session, "BP_Test", "NODE")  # type: ignore[arg-type]

        self.assertTrue(result.ok)
        self.assertEqual(session.read_calls, 0)
        self.assertEqual(session.write_calls, 1)
        self.assertEqual(len(session.audit_calls), 1)

    def test_guard_and_lock_rejection_do_not_send_http(self) -> None:
        read_session = FakeSession()
        read_session.read_result = FakeResult(False, "別プロジェクトです", "guard")
        write_session = FakeSession()
        write_session.write_result = FakeResult(False, "他の利用者が保持中です", "lock")

        read_result = ue_bp_get_blueprint(read_session, "BP_Test")  # type: ignore[arg-type]
        write_result = ue_bp_delete_node(write_session, "BP_Test", "NODE")  # type: ignore[arg-type]

        self.assertFalse(read_result.ok)
        self.assertFalse(write_result.ok)
        self.assertEqual(read_session.bp_client.calls, [])
        self.assertEqual(write_session.bp_client.calls, [])
        self.assertEqual(len(read_session.audit_calls), 1)
        self.assertEqual(len(write_session.audit_calls), 1)
        self.assertEqual(read_session.audit_calls[0][1]["error_type"], "GuardRejected")
        self.assertEqual(write_session.audit_calls[0][1]["error_type"], "LockRejected")

    def test_explicit_tools_build_cpp_routes_verbs_and_payloads(self) -> None:
        cases: list[
            tuple[
                str,
                Callable[[FakeSession], Any],
                tuple[str, str, dict[str, Any] | None],
            ]
        ] = [
            ("health", lambda s: ue_bp_health(s), ("/api/health", "GET", None)),
            (
                "list",
                lambda s: ue_bp_list_blueprints(s, "Patient", "Actor", "regular"),
                (
                    "/api/list",
                    "GET",
                    {"filter": "Patient", "parentClass": "Actor", "type": "regular"},
                ),
            ),
            (
                "blueprint",
                lambda s: ue_bp_get_blueprint(s, "BP_Test"),
                ("/api/blueprint", "GET", {"name": "BP_Test"}),
            ),
            (
                "graph",
                lambda s: ue_bp_get_graph(s, "BP_Test", "EventGraph"),
                ("/api/graph", "GET", {"name": "BP_Test", "graph": "EventGraph"}),
            ),
            (
                "search",
                lambda s: ue_bp_search(s, "PrintString", "/Game/Test", 12),
                (
                    "/api/search",
                    "GET",
                    {"query": "PrintString", "path": "/Game/Test", "maxResults": 12},
                ),
            ),
            (
                "pin info",
                lambda s: ue_bp_get_pin_info(s, "BP_Test", "NODE", "then"),
                (
                    "/api/get-pin-info",
                    "POST",
                    {"blueprint": "BP_Test", "nodeId": "NODE", "pinName": "then"},
                ),
            ),
            (
                "functions",
                lambda s: ue_bp_list_functions(s, "KismetSystemLibrary", "Print"),
                (
                    "/api/list-functions",
                    "POST",
                    {"className": "KismetSystemLibrary", "filter": "Print"},
                ),
            ),
            (
                "create blueprint",
                lambda s: ue_bp_create_blueprint(
                    s, "BP_New", "/Game/Test", "Actor", "Normal"
                ),
                (
                    "/api/create-blueprint",
                    "POST",
                    {
                        "blueprintName": "BP_New",
                        "packagePath": "/Game/Test",
                        "parentClass": "Actor",
                        "blueprintType": "Normal",
                    },
                ),
            ),
            (
                "create graph",
                lambda s: ue_bp_create_graph(s, "BP_Test", "Run", "function"),
                (
                    "/api/create-graph",
                    "POST",
                    {"blueprint": "BP_Test", "graphName": "Run", "graphType": "function"},
                ),
            ),
            (
                "add node",
                lambda s: ue_bp_add_node(
                    s,
                    "BP_Test",
                    "EventGraph",
                    "CallFunction",
                    function_name="PrintString",
                    class_name="KismetSystemLibrary",
                    pos_x=100,
                    pos_y=200,
                ),
                (
                    "/api/add-node",
                    "POST",
                    {
                        "blueprint": "BP_Test",
                        "graph": "EventGraph",
                        "nodeType": "CallFunction",
                        "functionName": "PrintString",
                        "className": "KismetSystemLibrary",
                        "posX": 100,
                        "posY": 200,
                    },
                ),
            ),
            (
                "delete node",
                lambda s: ue_bp_delete_node(s, "BP_Test", "NODE"),
                (
                    "/api/delete-node",
                    "POST",
                    {"blueprint": "BP_Test", "nodeId": "NODE"},
                ),
            ),
            (
                "connect pins",
                lambda s: ue_bp_connect_pins(s, "BP_Test", "A", "then", "B", "execute"),
                (
                    "/api/connect-pins",
                    "POST",
                    {
                        "blueprint": "BP_Test",
                        "sourceNodeId": "A",
                        "sourcePinName": "then",
                        "targetNodeId": "B",
                        "targetPinName": "execute",
                    },
                ),
            ),
            (
                "disconnect pin",
                lambda s: ue_bp_disconnect_pin(s, "BP_Test", "A", "then", "B", "execute"),
                (
                    "/api/disconnect-pin",
                    "POST",
                    {
                        "blueprint": "BP_Test",
                        "nodeId": "A",
                        "pinName": "then",
                        "targetNodeId": "B",
                        "targetPinName": "execute",
                    },
                ),
            ),
            (
                "pin default",
                lambda s: ue_bp_set_pin_default(s, "BP_Test", "NODE", "Value", "42"),
                (
                    "/api/set-pin-default",
                    "POST",
                    {"blueprint": "BP_Test", "nodeId": "NODE", "pinName": "Value", "value": "42"},
                ),
            ),
            (
                "add variable",
                lambda s: ue_bp_add_variable(
                    s, "BP_Test", "Health", "float", "Stats", True, "100.0"
                ),
                (
                    "/api/add-variable",
                    "POST",
                    {
                        "blueprint": "BP_Test",
                        "variableName": "Health",
                        "variableType": "float",
                        "category": "Stats",
                        "isArray": True,
                        "defaultValue": "100.0",
                    },
                ),
            ),
            (
                "validate",
                lambda s: ue_bp_validate_blueprint(s, "BP_Test"),
                ("/api/validate-blueprint", "POST", {"blueprint": "BP_Test"}),
            ),
        ]

        for label, call, expected in cases:
            with self.subTest(tool=label):
                session = FakeSession()
                result = call(session)
                self.assertTrue(result.ok)
                self.assertEqual(session.bp_client.calls, [expected])
                self.assertEqual(len(session.audit_calls), 1)

    def test_none_payload_values_are_omitted(self) -> None:
        session = FakeSession()

        result = ue_bp_disconnect_pin(
            session, "BP_Test", "NODE", "Value"
        )  # type: ignore[arg-type]

        self.assertTrue(result.ok)
        self.assertEqual(
            session.bp_client.calls,
            [
                (
                    "/api/disconnect-pin",
                    "POST",
                    {"blueprint": "BP_Test", "nodeId": "NODE", "pinName": "Value"},
                )
            ],
        )

    def test_generic_call_uses_allowlist_read_write_classification(self) -> None:
        read_session = FakeSession()
        write_session = FakeSession()

        read_result = ue_bp_call(read_session, "/api/health")  # type: ignore[arg-type]
        write_result = ue_bp_call(
            write_session, "/api/add-variable", {"blueprint": "BP_Test"}
        )  # type: ignore[arg-type]

        self.assertTrue(read_result.ok)
        self.assertTrue(write_result.ok)
        self.assertEqual((read_session.read_calls, read_session.write_calls), (1, 0))
        self.assertEqual((write_session.read_calls, write_session.write_calls), (0, 1))

    def test_generic_call_rejects_denied_and_unknown_routes_before_http(self) -> None:
        for route in ("/api/shutdown", "/api/create-material"):
            with self.subTest(route=route):
                session = FakeSession()

                result = ue_bp_call(session, route)  # type: ignore[arg-type]

                self.assertFalse(result.ok)
                self.assertEqual(session.bp_client.calls, [])
                self.assertEqual(session.read_calls, 0)
                self.assertEqual(session.write_calls, 0)
                self.assertIn("ue_bp_routes", result.text)
                self.assertEqual(len(session.audit_calls), 1)
                self.assertEqual(
                    session.audit_calls[0][1]["error_type"], "BlueprintRouteError"
                )

    def test_blueprint_request_error_is_normalised_and_audited(self) -> None:
        session = FakeSession()
        session.bp_client.error = BlueprintRequestError(
            "/api/add-node", "Missing required field: nodeType", {"error": "bad"}
        )

        result = ue_bp_add_node(
            session, "BP_Test", "EventGraph", "CallFunction"
        )  # type: ignore[arg-type]

        self.assertFalse(result.ok)
        self.assertIn("送信引数", result.text)
        self.assertIn("/api/add-node", result.text)
        self.assertEqual(len(session.audit_calls), 1)
        self.assertEqual(
            session.audit_calls[0][1]["error_type"], "BlueprintRequestError"
        )

    def test_unreachable_error_has_recovery_guidance_and_is_audited(self) -> None:
        session = FakeSession()
        session.bp_client.error = BlueprintUnreachable(
            "100.0.0.1", 9847, OSError("offline")
        )

        result = ue_bp_health(session)  # type: ignore[arg-type]

        self.assertFalse(result.ok)
        self.assertIn("NetBird", result.text)
        self.assertIn("Unreal Editor", result.text)
        self.assertIn("BlueprintMCP プラグイン", result.text)
        self.assertEqual(len(session.audit_calls), 1)

    def test_routes_tool_is_read_only_and_audited(self) -> None:
        session = FakeSession()

        result = ue_bp_routes(session)  # type: ignore[arg-type]

        self.assertTrue(result.ok)
        self.assertIn("/api/add-node", result.text)
        # 静的な一覧なので、ガードにもロックにも問い合わせない。
        self.assertEqual((session.read_calls, session.write_calls), (0, 0))
        self.assertEqual(session.bp_client.calls, [])
        self.assertEqual(len(session.audit_calls), 1)


if __name__ == "__main__":
    unittest.main()
