import json
import tempfile
import unittest
from pathlib import Path
from bridge.config import Config
from bridge.core import EVENT_DEFINITION, REPLY_TOOL
from jsonschema import Draft202012Validator


class ConfigTests(unittest.TestCase):
    def test_schemas_are_valid_and_restrict_destination(self):
        for schema in [EVENT_DEFINITION["inputSchema"], EVENT_DEFINITION["payloadSchema"], REPLY_TOOL["inputSchema"]]:
            Draft202012Validator.check_schema(schema)
        errors = list(Draft202012Validator(REPLY_TOOL["inputSchema"]).iter_errors(
            {"message_id": "123", "text": "test", "channel_id": "other"}))
        self.assertTrue(errors)

    def test_configuration_validation_has_no_side_effects(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "config.json"
            data = {"owner_discord_id": "111111111111111111", "bot_discord_id": "222222222222222222",
                    "resource": "https://bridge.example.test/mcp", "oauth_issuer": "https://issuer.example.test",
                    "oauth_subject": "synthetic", "callback_hosts": ["callback.example.test"],
                    **{k: str(Path(root) / k) for k in ["jwks_file", "enabled_file", "discord_bot_token_file", "state_path"]}}
            path.write_text(json.dumps(data))
            self.assertEqual(Config.load(path).listen_host, "127.0.0.1")
            self.assertEqual(len(list(Path(root).iterdir())), 1)
            for mutation in [{"listen_host": "0.0.0.0"}, {"owner_discord_id": "a-username"},
                             {"resource": "http://bridge.test/mcp"}, {"callback_hosts": ["*.test"]}]:
                path.write_text(json.dumps({**data, **mutation}))
                with self.assertRaises(ValueError):
                    Config.load(path)
