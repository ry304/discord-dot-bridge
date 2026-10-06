import unittest
from aiohttp.test_utils import TestClient, TestServer
from bridge.setup_server import setup_app


class SetupServerTests(unittest.IsolatedAsyncioTestCase):
    async def test_metadata_and_unconditional_denial(self):
        app = setup_app("https://bridge.example.test/mcp", "https://id.example.test/application/o/bridge/")
        async with TestClient(TestServer(app, host="127.0.0.1")) as client:
            headers = {"Host": "bridge.example.test"}
            response = await client.get("/.well-known/oauth-protected-resource", headers=headers)
            self.assertEqual(response.status, 200)
            self.assertEqual((await response.json())["resource"], "https://bridge.example.test/mcp")
            for authorization in (None, "Bearer token-not-accepted-in-setup"):
                request_headers = dict(headers)
                if authorization:
                    request_headers["Authorization"] = authorization
                for method in ("server/discover", "events/subscribe", "tools/call"):
                    response = await client.post("/mcp", headers=request_headers,
                                                 json={"jsonrpc": "2.0", "id": 1, "method": method})
                    self.assertEqual(response.status, 401)
                    self.assertIn("resource_metadata=", response.headers["WWW-Authenticate"])
            response = await client.get("/.well-known/oauth-protected-resource", headers={"Host": "untrusted.test"})
            self.assertEqual(response.status, 403)
            response = await client.get("/.well-known/oauth-protected-resource", headers={**headers, "Origin": "https://untrusted.test"})
            self.assertEqual(response.status, 403)
