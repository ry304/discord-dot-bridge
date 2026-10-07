import asyncio
import base64
import contextlib
import http.client
import json
import tempfile
import time
import unittest
from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import patch, Mock

import aiohttp
from aiohttp import web
from cryptography.hazmat.primitives.asymmetric import rsa
import discord
import discord.gateway
import discord.http
import jwt
from standardwebhooks import Webhook
from yarl import URL as YarlURL

from bridge.auth import OAuthVerifier, AuthError
from bridge.core import Bridge, VERSION, iso
from bridge.discord_adapter import DiscordBot, DiscordSender
from bridge.http_server import SerialCore, make_app, INTERNAL, META
from bridge.network import HTTPSWebhook, PinnedHTTPSConnection
from bridge.synthetic import OWNER, BOT, CHANNEL, MESSAGE, SECRET

# The SDK derives Message.created_at from its snowflake; use a synthetic current
# snowflake so the real replay-age filter is exercised without weakening it.
MESSAGE = str(discord.utils.time_snowflake(datetime.now(timezone.utc)))


class LocalAdapters(unittest.IsolatedAsyncioTestCase):
    async def test_live_status_authenticated_read_only(self):
        before = (list(self.events), list(self.replies))
        code, result = await self.rpc("tools/list")
        self.assertEqual(code, 200)
        self.assertIn("discord_bridge_status", [t["name"] for t in result["result"]["tools"]])
        self.actor.discord_ready = lambda: True
        args = {"name": "discord_bridge_status", "arguments": {}}
        code, result = await self.rpc("tools/call", args)
        self.assertEqual(code, 200)
        status = json.loads(result["result"]["content"][0]["text"])
        self.assertEqual(status["mode"], "live")
        self.assertTrue(status["discord_connected"])
        self.assertEqual(status["active_subscriptions"], 0)
        self.assertEqual((list(self.events), list(self.replies)), before)
        self.assertEqual((await self.rpc("tools/call", args, token=self.token(sub="other")))[0], 401)
        self.assertEqual((await self.rpc("tools/call", {**args, "arguments": {"extra": True}}))[0], 400)

    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(self.key.public_key()))
        jwk.update(kid="synthetic-key", alg="RS256", use="sig")
        (self.root / "jwks.json").write_text(json.dumps({"keys": [jwk]}))
        (self.root / "enabled").write_text("enabled")
        self.verifier = OAuthVerifier(issuer="https://issuer.example.test", resource="https://bridge.example.test/mcp",
                                      subject="synthetic-owner", jwks_file=self.root / "jwks.json",
                                      enabled_file=self.root / "enabled")
        self.events, self.replies, self.identifies, self.resumes = [], [], [], []
        self.ws = None
        self.gateway_ready = asyncio.Event()
        @web.middleware
        async def discord_json_content_type(request, handler):
            response = await handler(request)
            if response.content_type == "application/json":
                response.headers["Content-Type"] = "application/json"
            return response
        mock = web.Application(middlewares=[discord_json_content_type])
        mock.router.add_get("/gateway", self.gateway)
        mock.router.add_route("*", "/api/v10/{tail:.*}", self.discord_rest)
        mock.router.add_post("/callback", self.callback)
        self.mock_runner = web.AppRunner(mock, access_log=None)
        await self.mock_runner.setup()
        self.mock_site = web.TCPSite(self.mock_runner, "127.0.0.1", 0)
        await self.mock_site.start()
        self.port = self.mock_site._server.sockets[0].getsockname()[1]

        # Only remote endpoints are mocked. The actual SDK parses Gateway frames
        # and makes local HTTP REST requests; the bridge actor/HTTP/auth are real.
        self.patches = [patch.object(discord.http.Route, "BASE", f"http://127.0.0.1:{self.port}/api/v10"),
                        patch.object(discord.gateway.DiscordWebSocket, "DEFAULT_GATEWAY", YarlURL(f"ws://127.0.0.1:{self.port}/gateway"))]
        for p in self.patches:
            p.start()
        self.bot = DiscordBot(OWNER, BOT, self.ingest)
        await self.bot.__aenter__()
        await self.bot.login("SYNTHETIC-BOT-NOT-A-CREDENTIAL")
        self.gateway_task = asyncio.create_task(self.bot.connect(reconnect=True))
        await asyncio.wait_for(self.gateway_ready.wait(), 5)
        sender = DiscordSender(self.bot, asyncio.get_running_loop())
        hook = HTTPSWebhook(["callback.example.test"], connection_factory=lambda host, address, timeout:
                            http.client.HTTPConnection("127.0.0.1", self.port, timeout=timeout))
        hook.resolve = lambda host: ("8.8.8.8",)  # No real DNS; validation input only.
        def factory():
            core = Bridge(self.root / "state.sqlite3", owner_id=OWNER, bot_id=BOT, bearer=INTERNAL,
                          callback_hosts=["callback.example.test"], webhook=hook, discord=sender)
            core.bind_principal(self.verifier.issuer + "|" + self.verifier.subject)
            return core
        self.actor = SerialCore(factory, self.verifier)
        self.app = make_app(self.actor, self.verifier, allowed_hosts=["bridge.example.test"])
        self.runner = web.AppRunner(self.app, access_log=None)
        await self.runner.setup()
        site = web.TCPSite(self.runner, "127.0.0.1", 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        self.endpoint = f"http://127.0.0.1:{port}"
        self.client = aiohttp.ClientSession()
        self.ingested = asyncio.Event()

    async def asyncTearDown(self):
        await self.client.close()
        await self.runner.cleanup()
        await self.bot.close()
        self.gateway_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self.gateway_task
        await self.actor.close()
        await self.mock_runner.cleanup()
        for p in reversed(self.patches):
            p.stop()
        self.temp.cleanup()

    def token(self, **overrides):
        now = int(time.time())
        claims = {"iss": self.verifier.issuer, "aud": self.verifier.resource, "sub": self.verifier.subject,
                  "scope": "discord:bridge", "iat": now, "nbf": now - 1, "exp": now + 600, **overrides}
        return jwt.encode(claims, self.key, algorithm="RS256", headers={"kid": "synthetic-key", "typ": "at+jwt"})

    async def ingest(self, dispatch, **metadata):
        result = await self.actor.ingest(dispatch, **metadata)
        self.ingested.set()
        return result

    async def gateway(self, request):
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        self.ws = ws
        await ws.send_json({"op": 10, "d": {"heartbeat_interval": 60000}})
        async for msg in ws:
            if msg.type != aiohttp.WSMsgType.TEXT:
                continue
            packet = json.loads(msg.data)
            if packet["op"] == 1:
                await ws.send_json({"op": 11, "d": None})
            elif packet["op"] == 2:
                self.identifies.append(packet["d"])
                await ws.send_json({"op": 0, "t": "READY", "s": 1, "d": {
                    "v": 10, "session_id": "synthetic-session", "user": self.user(BOT, True),
                    "guilds": [], "resume_gateway_url": f"ws://127.0.0.1:{self.port}/gateway",
                    "application": {"id": BOT, "flags": 0}}})
                self.gateway_ready.set()
            elif packet["op"] == 6:
                self.resumes.append(packet["d"])
                await ws.send_json({"op": 0, "t": "RESUMED", "s": 2, "d": {}})
                self.gateway_ready.set()
        return ws

    @staticmethod
    def user(uid, bot=False):
        return {"id": uid, "username": "synthetic", "discriminator": "0000", "avatar": None,
                "bot": bot, "global_name": None}

    def message(self, mid=MESSAGE, content="Synthetic owner request", author=OWNER):
        return {"id": mid, "channel_id": CHANNEL, "author": self.user(author, author == BOT),
                "content": content, "timestamp": iso(time.time()), "edited_timestamp": None,
                "tts": False, "mention_everyone": False, "mentions": [], "mention_roles": [],
                "attachments": [], "embeds": [], "pinned": False, "type": 0, "flags": 0}

    async def discord_rest(self, request):
        tail = request.match_info["tail"]
        if tail == "users/@me":
            return web.json_response(self.user(BOT, True))
        if tail == "oauth2/applications/@me":
            return web.json_response({"id": BOT, "name": "synthetic", "description": "",
                "icon": None, "owner": self.user(OWNER), "bot_public": False,
                "bot_require_code_grant": False, "verify_key": "00" * 32})
        if tail == f"channels/{CHANNEL}" and request.method == "GET":
            return web.json_response({"id": CHANNEL, "type": 1, "recipients": [self.user(OWNER)]})
        if tail == f"channels/{CHANNEL}/messages" and request.method == "POST":
            body = await request.json()
            self.replies.append(body)
            return web.json_response(self.message("555555555555555555", body["content"], BOT))
        return web.json_response({"message": "Unknown mock route"}, status=404)

    async def callback(self, request):
        raw = await request.read()
        payload = Webhook(SECRET).verify(raw.decode(), {k.lower(): v for k, v in request.headers.items()})
        if payload.get("type") == "verification":
            return web.json_response({"challenge": payload["challenge"]})
        self.events.append(payload)
        self.assertEqual(request.headers["webhook-id"], payload["eventId"])
        self.assertTrue(request.headers["X-MCP-Subscription-Id"].startswith("sub_"))
        return web.json_response({})

    async def rpc(self, method, params=None, *, token=None, headers=None, version=VERSION):
        data = {"jsonrpc": "2.0", "id": 1, "method": method, "params": {**(params or {}), "_meta": {
            META + "protocolVersion": version, META + "clientCapabilities": {},
            META + "clientInfo": {"name": "local-mock", "version": "1"}}}}
        h = {"Host": "bridge.example.test", "Authorization": "Bearer " + (token or self.token()),
             "Accept": "application/json, text/event-stream", "MCP-Protocol-Version": version, "Mcp-Method": method}
        if method == "tools/call":
            h["Mcp-Name"] = params["name"]
        h.update(headers or {})
        async with self.client.post(self.endpoint + "/mcp", json=data, headers=h) as response:
            return response.status, await response.json()

    async def subscribe(self):
        params = {"name": "discord.dm.created", "arguments": {"owner_id": OWNER},
                  "delivery": {"mode": "webhook", "url": "https://callback.example.test/callback", "secret": SECRET}}
        status, body = await self.rpc("events/subscribe", params)
        self.assertEqual(status, 200, body)
        return params

    async def test_full_gateway_http_oauth_webhook_and_reply(self):
        status, discovery = await self.rpc("server/discover")
        self.assertEqual(status, 200)
        self.assertEqual(discovery["result"]["supportedVersions"], [VERSION])
        params = await self.subscribe()
        self.assertEqual(self.identifies[0]["intents"], 4096)
        await self.ws.send_json({"op": 0, "t": "MESSAGE_CREATE", "s": 2, "d": self.message()})
        await asyncio.wait_for(self.ingested.wait(), 5)
        await self.actor.pump()
        self.assertEqual(len(self.events), 1)
        self.assertEqual(self.events[0]["data"]["text"], "Synthetic owner request")
        reply = {"name": "discord_reply", "arguments": {"message_id": MESSAGE, "text": "Synthetic dot response"}}
        for _ in range(2):
            status, body = await self.rpc("tools/call", reply)
            self.assertEqual(status, 200, body)
            self.assertFalse(body["result"]["isError"])
        self.assertEqual(len(self.replies), 1)
        self.assertTrue(self.replies[0]["enforce_nonce"])
        self.assertEqual(self.replies[0]["allowed_mentions"]["parse"], [])
        self.assertEqual((await self.rpc("events/unsubscribe", params))[0], 200)

    async def test_modern_metadata_headers_errors_and_discovery(self):
        status, value = await self.rpc("events/list", headers={"Mcp-Method": "tools/list"})
        self.assertEqual((status, value["error"]["code"]), (400, -32020))
        status, value = await self.rpc("server/discover", version="2025-11-25")
        self.assertEqual((status, value["error"]["code"]), (400, -32022))
        self.assertEqual((await self.rpc("not/a/method"))[0], 404)
        self.assertEqual((await self.rpc("events/list", token="invalid"))[0], 401)
        async with self.client.get(self.endpoint + "/.well-known/oauth-protected-resource", headers={"Host": "bridge.example.test"}) as r:
            self.assertEqual((await r.json())["resource"], self.verifier.resource)
        async with self.client.get(self.endpoint + "/mcp", headers={"Host": "bridge.example.test"}) as r:
            self.assertEqual(r.status, 405)

    async def test_oauth_rejects_bad_claims_and_persistent_revocation(self):
        for changes in [{"sub": "other"}, {"aud": "https://other.test"}, {"iss": "https://other.test"},
                        {"scope": "other"}, {"exp": int(time.time()) - 1}, {"nbf": int(time.time()) + 60}]:
            self.assertEqual((await self.rpc("events/list", token=self.token(**changes)))[0], 401)
        await self.subscribe()
        (self.root / "enabled").write_text("disabled")
        self.assertEqual((await self.rpc("events/list"))[0], 401)
        self.assertEqual(await self.actor.pump(), 0)

    async def test_gateway_resume_and_duplicate_delivery(self):
        await self.subscribe()
        packet = {"op": 0, "t": "MESSAGE_CREATE", "s": 2, "d": self.message()}
        await self.ws.send_json(packet)
        await asyncio.wait_for(self.ingested.wait(), 5)
        await self.actor.pump()
        self.gateway_ready.clear()
        await self.ws.send_json({"op": 7, "d": None})
        await asyncio.wait_for(self.gateway_ready.wait(), 5)
        self.assertEqual(len(self.resumes), 1)
        self.assertEqual(self.resumes[0]["session_id"], "synthetic-session")
        self.ingested.clear()
        await self.ws.send_json(packet)
        await asyncio.wait_for(self.ingested.wait(), 5)
        await self.actor.pump()
        self.assertEqual(len(self.events), 1)

    async def test_signature_algorithm_and_wrong_key_are_rejected(self):
        other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        claims = jwt.decode(self.token(), options={"verify_signature": False})
        forged = jwt.encode(claims, other, algorithm="RS256", headers={"kid": "synthetic-key"})
        self.assertEqual((await self.rpc("events/list", token=forged))[0], 401)
        forged = jwt.encode(claims, "synthetic-hmac-test-value-only-12345", algorithm="HS256", headers={"kid": "synthetic-key"})
        self.assertEqual((await self.rpc("events/list", token=forged))[0], 401)

    async def test_missing_metadata_and_base64_name(self):
        headers = {"Host": "bridge.example.test", "Authorization": "Bearer " + self.token(),
                   "Accept": "application/json, text/event-stream", "MCP-Protocol-Version": VERSION,
                   "Mcp-Method": "events/list"}
        async with self.client.post(self.endpoint + "/mcp", headers=headers,
            json={"jsonrpc": "2.0", "id": 1, "method": "events/list", "params": {}}) as r:
            self.assertEqual((r.status, (await r.json())["error"]["code"]), (400, -32602))
        encoded = "=?base64?" + base64.b64encode(b"discord_reply").decode() + "?="
        status, body = await self.rpc("tools/call", {"name": "discord_reply", "arguments": {}}, headers={"Mcp-Name": encoded})
        self.assertEqual(body["error"]["code"], -32602)

    async def test_host_origin_and_body_limits(self):
        for h in [{"Host": "attacker.test"}, {"Origin": "https://attacker.test"}]:
            async with self.client.post(self.endpoint + "/mcp", headers={"Host": "bridge.example.test", **h}, json={}) as r:
                self.assertEqual(r.status, 403)
        headers = {"Host": "bridge.example.test", "Authorization": "Bearer " + self.token(),
                   "Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
        async with self.client.post(self.endpoint + "/mcp", headers=headers, data=b"x" * 262145) as r:
            self.assertEqual(r.status, 413)


class TransportUnitTests(unittest.TestCase):
    def test_tls_connect_uses_pinned_ip_original_sni_without_dns(self):
        raw, tls = Mock(), Mock()
        tls.wrap_socket.return_value = Mock()
        with patch("bridge.network.socket.socket", return_value=raw), \
             patch("bridge.network.ssl.create_default_context", return_value=tls), \
             patch("bridge.network.socket.getaddrinfo", side_effect=AssertionError("DNS during pinned connect")):
            connection = PinnedHTTPSConnection("callback.example.test", "8.8.8.8", 10)
            connection.connect()
        raw.connect.assert_called_once_with(("8.8.8.8", 443))
        tls.wrap_socket.assert_called_once_with(raw, server_hostname="callback.example.test")

    def test_redirects_are_not_followed(self):
        connection = Mock()
        connection.getresponse.return_value.status = 302
        factory = Mock(return_value=connection)
        hook = HTTPSWebhook(["callback.example.test"], factory)
        self.assertEqual(hook.post("https://callback.example.test/x", ["8.8.8.8"], b"{}", {})[0], 302)
        self.assertEqual(factory.call_count, 1)
        self.assertEqual(connection.request.call_count, 1)
