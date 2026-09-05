"""設定ファイルと環境変数の優先順位を検証する。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from mcp.ue_remote.config import ConfigError, load_config


class ConfigTests(unittest.TestCase):
    def test_environment_overrides_toml(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config_path = Path(temporary) / "config.toml"
            config_path.write_text(
                """
host = "toml-host"
port = 30010
timeout_seconds = 4.5
developer_id = "toml-developer"
expected_project = "toml-project"

[lock]
ttl_seconds = 123
heartbeat_seconds = 45

[audit]
local_dir = "~/audit-test"
remote_flush_every = 7
""".strip(),
                encoding="utf-8",
            )
            config = load_config(
                config_path,
                {
                    "UE_REMOTE_HOST": "env-host",
                    "UE_REMOTE_PORT": "30123",
                    "UE_REMOTE_DEVELOPER_ID": "env-developer",
                    "UE_REMOTE_PROJECT": "env-project",
                },
            )

        self.assertEqual("env-host", config.host)
        self.assertEqual(30123, config.port)
        self.assertEqual("env-developer", config.developer_id)
        self.assertEqual("env-project", config.expected_project)
        self.assertEqual(4.5, config.timeout_seconds)
        self.assertEqual(123, config.lock.ttl_seconds)
        self.assertEqual(45, config.lock.heartbeat_seconds)
        self.assertEqual(7, config.audit.remote_flush_every)
        self.assertFalse(str(config.audit.local_dir).startswith("~"))

    def test_environment_only_configuration(self) -> None:
        config = load_config(
            "/path/that/does/not/exist/config.toml",
            {"UE_REMOTE_DEVELOPER_ID": "env-only"},
        )

        self.assertEqual("127.0.0.1", config.host)
        self.assertEqual(30010, config.port)
        self.assertEqual("env-only", config.developer_id)
        self.assertIsNone(config.expected_project)

    def test_missing_developer_id_is_an_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            missing_path = Path(temporary) / "missing.toml"
            with self.assertRaisesRegex(ConfigError, "developer_id が未設定"):
                load_config(missing_path, {})


if __name__ == "__main__":
    unittest.main()
