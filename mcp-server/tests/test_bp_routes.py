"""BlueprintMCP ルート許可リストの単体テスト。"""

from __future__ import annotations

import unittest

from ue_remote.bp_routes import ALLOWED, DENIED, describe, lookup
from ue_remote.errors import BlueprintRouteError


class BlueprintRouteTests(unittest.TestCase):
    def test_read_and_write_route_counts(self) -> None:
        read_routes = [route for route in ALLOWED.values() if not route.write]
        write_routes = [route for route in ALLOWED.values() if route.write]

        self.assertEqual(20, len(read_routes))
        self.assertEqual(37, len(write_routes))
        self.assertFalse(lookup("/api/graph").write)
        self.assertFalse(lookup("/api/diff-blueprints").write)
        self.assertTrue(lookup("/api/add-node").write)
        self.assertTrue(lookup("/api/validate-blueprint").write)

    def test_snapshot_graph_is_write_route(self) -> None:
        route = lookup("/api/snapshot-graph")

        self.assertEqual("POST", route.verb)
        self.assertTrue(route.write)

    def test_denied_route_raises_with_reason(self) -> None:
        with self.assertRaises(BlueprintRouteError) as caught:
            lookup("/api/shutdown")

        self.assertEqual("/api/shutdown", caught.exception.route)
        self.assertEqual(DENIED["/api/shutdown"], caught.exception.reason)
        self.assertIn("共用PC", str(caught.exception))

    def test_unknown_route_is_out_of_phase(self) -> None:
        with self.assertRaises(BlueprintRouteError) as caught:
            lookup("/api/create-material")

        self.assertEqual("Phase 3 の対象外", caught.exception.reason)

    def test_leading_slash_is_optional(self) -> None:
        self.assertIs(lookup("api/graph"), lookup("/api/graph"))

    def test_describe_returns_mcp_friendly_dictionaries(self) -> None:
        descriptions = describe()

        self.assertEqual(len(ALLOWED), len(descriptions))
        self.assertEqual(
            {"path", "verb", "write", "summary"}, set(descriptions[0].keys())
        )
        self.assertEqual("/api/health", descriptions[0]["path"])


if __name__ == "__main__":
    unittest.main()
