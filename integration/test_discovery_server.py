import json
import tempfile
import time
import unittest
from pathlib import Path
from aiohttp.test_utils import TestClient, TestServer
from cryptography.hazmat.primitives.asymmetric import rsa
import jwt
from bridge.core import VERSION
from bridge.discovery_server import discovery_app, load_config
from bridge.http_server import META


class DiscoveryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(self.key.public_key()))
        jwk.update(kid="synthetic", use="sig", alg="RS256")
        (self.root / "jwks.json").write_text(json.dumps({"keys": [jwk]}))
        (self.root / "owner").write_text("auth0|synthetic-owner")
        (self.root / "owner").chmod(0o600)
        (self.root / "enabled").write_text("enabled")
        self.config = {"resource": "https://bridge.example.test/mcp", "oauth_issuer": "https://issuer.example.test/",
            "oauth_subject_file": str(self.root / "owner"), "jwks_file": str(self.root / "jwks.json"),
            "enabled_file": str(self.root / "enabled"), "discord_mode": "guild_mentions"}
        self.client = TestClient(TestServer(discovery_app(self.config)))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        self.temp.cleanup()

    def token(self, **changes):
        now = int(time.time())
        claims = {"iss": self.config["oauth_issuer"], "aud": self.config["resource"],
            "sub": "auth0|synthetic-owner", "iat": now, "exp": now + 600, "scope": "discord:bridge"}
        claims.update(changes)
        return jwt.encode(claims, self.key, algorithm="RS256", headers={"kid": "synthetic"})

    async def call(self, method, token, **params):
        headers = {"Host": "bridge.example.test", "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": VERSION, "Mcp-Method": method}
        if token:
            headers["Authorization"] = "Bearer " + token
        if method == "tools/call":
            headers["Mcp-Name"] = params["name"]
        params["_meta"] = {META + "protocolVersion": VERSION, META + "clientCapabilities": {}}
        return await self.client.post("/mcp", headers=headers,
            json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params})

    async def test_authenticated_catalog_and_no_files_or_delivery(self):
        before = set(self.root.iterdir())
        for method, key in (("server/discover", "capabilities"), ("events/list", "events"), ("tools/list", "tools")):
            response = await self.call(method, self.token())
            self.assertEqual(response.status, 200)
            result = (await response.json())["result"]
            self.assertIn(key, result)
            if method in ("server/discover", "tools/list"):
                self.assertEqual(result["ttlMs"], 0)
                self.assertEqual(result["cacheScope"], "private")
            if key == "events":
                self.assertEqual(result[key][0]["name"], "discord.channel.mentioned")
        self.assertEqual(set(self.root.iterdir()), before)

    async def test_missing_bad_claims_and_expired_token_denied(self):
        tokens = [None, "synthetic-invalid", self.token(aud="https://other.example.test/mcp"),
            self.token(sub="auth0|different-owner"), self.token(scope="openid"),
            self.token(iss="https://other.example.test/"), self.token(exp=int(time.time()) - 1),
            self.token(exp=int(time.time()) + 7200)]
        for token in tokens:
            response = await self.call("tools/list", token)
            self.assertEqual(response.status, 401)

    async def test_valid_owner_cannot_mutate_subscribe_reply_or_initialize(self):
        for method, params in (("events/subscribe", {}), ("events/unsubscribe", {}),
                               ("tools/call", {"name": "discord_reply", "arguments": {"message_id": "1", "text": "test"}}),
                               ("initialize", {})):
            response = await self.call(method, self.token(), **params)
            self.assertEqual(response.status, 404)
            self.assertIn("Discovery only", (await response.json())["error"]["message"])

    async def test_disable_is_immediate(self):
        (self.root / "enabled").write_text("disabled")
        self.assertEqual((await self.call("tools/list", self.token())).status, 401)

    async def test_configuration_needs_private_subject_and_no_bot_settings(self):
        path = self.root / "config.json"
        path.write_text(json.dumps(self.config))
        path.chmod(0o600)
        self.assertEqual(load_config(path), self.config)
        for change in ({"resource": "http://bridge.example.test/mcp"}, {"discord_mode": "all"},
                       {"discord_bot_token_file": "/never/read"}):
            path.write_text(json.dumps({**self.config, **change}))
            with self.assertRaises(ValueError):
                load_config(path)
        (self.root / "owner").write_text("")
        with self.assertRaises(ValueError):
            discovery_app(self.config)
