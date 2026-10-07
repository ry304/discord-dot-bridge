import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
from bridge.callback_probe import ProbeActor, hostname_only
from bridge.auth import AuthError
from bridge.synthetic import OWNER, SECRET


class ProbeTests(unittest.IsolatedAsyncioTestCase):
    async def test_status_only_never_captures_and_declares_oauth(self):
        with tempfile.TemporaryDirectory() as folder:
            actor = ProbeActor(Mock(), "guild_mentions", OWNER, Path(folder) / "host", False)
            catalog = await actor.rpc({"id": 1, "method": "tools/list"}, "synthetic")
            self.assertEqual(catalog["result"]["tools"][-1]["securitySchemes"], [{"type": "oauth2", "scopes": ["discord:bridge"]}])
            actor.deadline = float("inf")
            result = await actor.rpc({"id": 2, "method": "events/subscribe", "params": {
                "name": "discord.channel.mentioned", "arguments": {"owner_id": OWNER},
                "delivery": {"mode": "webhook", "url": "https://callback.example.test/private", "secret": SECRET}}}, "synthetic")
            self.assertIn("error", result)
            self.assertFalse(list(Path(folder).iterdir()))

    async def test_status_authenticated_read_only_and_expiry(self):
        with tempfile.TemporaryDirectory() as folder:
            verifier = Mock()
            actor = ProbeActor(verifier, "guild_mentions", OWNER, Path(folder) / "host")
            catalog = await actor.rpc({"id": 1, "method": "tools/list"}, "synthetic")
            self.assertTrue(catalog["result"]["tools"][-1]["annotations"]["readOnlyHint"])
            request = {"id": 2, "method": "tools/call", "params": {"name": "discord_bridge_status", "arguments": {}}}
            result = await actor.rpc(request, "synthetic")
            self.assertIn('"replies_enabled": false', result["result"]["content"][0]["text"])
            actor.deadline = 0
            result = await actor.rpc(request, "synthetic")
            self.assertIn('"probe_window_open": false', result["result"]["content"][0]["text"])
            await actor.rpc({"id": 3, "method": "events/subscribe", "params": {
                "name": "discord.channel.mentioned", "arguments": {"owner_id": OWNER},
                "delivery": {"mode": "webhook", "url": "https://callback.example.test/private", "secret": SECRET}}}, "synthetic")
            self.assertFalse(list(Path(folder).iterdir()))
            verifier.verify.side_effect = AuthError("denied")
            with self.assertRaises(AuthError):
                await actor.rpc(request, "synthetic")

    async def test_only_hostname_stored_once_no_subscription_success(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "host"
            actor = ProbeActor(Mock(), "guild_mentions", OWNER, path)
            request = {"id": 1, "method": "events/subscribe", "params": {
                "name": "discord.channel.mentioned", "arguments": {"owner_id": OWNER},
                "delivery": {"mode": "webhook", "url": "https://callback.example.test/private-path?private-query", "secret": SECRET}}}
            for owner in ("wrong", OWNER):
                request["params"]["arguments"]["owner_id"] = owner
                response = await actor.rpc(request, "synthetic")
                self.assertIn("error", response)
                self.assertEqual(path.exists(), owner == OWNER)
            self.assertEqual(path.read_text(), "callback.example.test\n")
            request["params"]["delivery"]["url"] = "https://other.example.test/private"
            await actor.rpc(request, "synthetic")
            self.assertEqual(path.read_text(), "callback.example.test\n")
            self.assertEqual(len(list(Path(folder).iterdir())), 1)

    async def test_unauthorized_probe_does_not_write(self):
        with tempfile.TemporaryDirectory() as folder:
            verifier = Mock()
            verifier.verify.side_effect = AuthError("denied")
            actor = ProbeActor(verifier, "guild_mentions", OWNER, Path(folder) / "host")
            with self.assertRaises(AuthError):
                await actor.rpc({"id": 1, "method": "events/subscribe"}, "synthetic")
            self.assertFalse(list(Path(folder).iterdir()))

    async def test_host_validation(self):
        for url in ("http://callback.example.test/x", "https://127.0.0.1/x", "https://[::1]/x",
                    "https://user:secret@example.test/x", "https://example.test:8443/x",
                    "https://example.test/x#secret", "https://bad..example.test/x"):
            with self.assertRaises(ValueError):
                hostname_only(url)
