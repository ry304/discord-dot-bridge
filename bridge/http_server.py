"""MCP 2026-07-28 JSON-response Streamable HTTP binding, single owner."""
import asyncio
import base64
import concurrent.futures
import json
from aiohttp import web
from .auth import AuthError, SCOPE
from .core import VERSION, MAX_BODY

META = "io.modelcontextprotocol/"
INTERNAL = "IN-PROCESS-ONLY-NOT-A-NETWORK-CREDENTIAL"
STATUS_TOOL = {"name": "discord_bridge_status", "description": "Read authenticated bridge readiness and bounded queue counts without Discord or callback network access.",
    "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    "securitySchemes": [{"type": "oauth2", "scopes": ["discord:bridge"]}],
    "annotations": {"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False}}


class SerialCore:
    def __init__(self, factory, verifier):
        self.pool = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="bridge-state")
        self.bridge = self.pool.submit(factory).result()
        self.verifier = verifier
        self.discord_ready = lambda: False
        self.slots = asyncio.Semaphore(32)

    async def submit(self, operation):
        if self.slots.locked():
            raise web.HTTPServiceUnavailable(text="Bridge queue full")
        async with self.slots:
            future = asyncio.get_running_loop().run_in_executor(self.pool, operation)
            try:
                return await asyncio.shield(future)
            except asyncio.CancelledError:
                # Retain the queue slot until a non-cancellable external effect
                # finishes; client disconnects cannot create an unbounded queue.
                await future
                raise

    async def rpc(self, request, authorization):
        def run():
            claims = self.verifier.verify(authorization)
            self.bridge.enabled = self.verifier.enabled()
            self.bridge.auth_until = claims["exp"]
            if request.get("method") == "tools/call" and request.get("params", {}).get("name") == "discord_bridge_status":
                if request["params"].get("arguments", {}) != {}:
                    return {"jsonrpc": "2.0", "id": request["id"], "error": {"code": -32602, "message": "No arguments accepted"}}
                ready = bool(self.discord_ready())
                value = {"mode": "live", "discord_connected": ready,
                         "subscriptions_enabled": self.bridge.enabled, "replies_enabled": self.bridge.enabled and ready,
                         "active_subscriptions": self.bridge.db.execute("SELECT count(*) FROM subscriptions WHERE expires>?", (self.bridge.clock(),)).fetchone()[0],
                         "pending_events": self.bridge.db.execute("SELECT count(*) FROM deliveries WHERE status='pending'").fetchone()[0]}
                return {"jsonrpc": "2.0", "id": request["id"], "result": {"content": [{"type": "text", "text": json.dumps(value)}], "isError": False}}
            response = self.bridge.rpc(request, "Bearer " + INTERNAL)
            if request.get("method") == "tools/list" and "result" in response:
                response["result"]["tools"].append(STATUS_TOOL)
            return response
        return await self.submit(run)

    async def ingest(self, dispatch, **metadata):
        def run():
            self.bridge.enabled = self.verifier.enabled()
            return self.bridge.ingest(dispatch, **metadata)
        return await self.submit(run)

    async def pump(self):
        def run():
            self.bridge.enabled = self.verifier.enabled()
            return self.bridge.pump()
        return await self.submit(run)

    async def close(self):
        await self.submit(self.bridge.close)
        self.pool.shutdown(wait=True)

    async def status(self):
        def run():
            db = self.bridge.db
            return {"enabled": self.verifier.enabled(),
                    "subscriptions": db.execute("SELECT count(*) FROM subscriptions WHERE expires>?", (self.bridge.clock(),)).fetchone()[0],
                    "pending": db.execute("SELECT count(*) FROM deliveries WHERE status='pending'").fetchone()[0]}
        return await self.submit(run)

    async def disconnect(self):
        # Disable authorization immediately, before waiting for earlier serialized work.
        self.verifier.disable()
        def run():
            self.bridge.enabled = False
            self.bridge.verified.clear()
            with self.bridge.db:
                self.bridge.db.execute("DELETE FROM deliveries")
                self.bridge.db.execute("DELETE FROM subscriptions")
        await self.submit(run)


def error(rid, code, message, status=400, data=None):
    body = {"jsonrpc": "2.0", "error": {"code": code, "message": message}}
    if type(rid) in (str, int):
        body["id"] = rid
    if data is not None:
        body["error"]["data"] = data
    return web.json_response(body, status=status)


def decoded(value):
    if value is None:
        return None
    if value.startswith("=?base64?") and value.endswith("?="):
        return base64.b64decode(value[9:-2], validate=True).decode("utf-8")
    if any(ord(c) < 32 or ord(c) > 126 for c in value):
        raise ValueError
    return value


def make_app(actor, verifier, *, allowed_hosts, allowed_origins=()):
    hosts, origins = frozenset(allowed_hosts), frozenset(allowed_origins)
    challenge = 'Bearer resource_metadata="' + verifier.resource.rsplit("/mcp", 1)[0] + '/.well-known/oauth-protected-resource", scope="' + SCOPE + '"'

    @web.middleware
    async def guard(request, handler):
        if request.host not in hosts:
            raise web.HTTPForbidden(text="Host is not allowed")
        if "Origin" in request.headers and request.headers["Origin"] not in origins:
            raise web.HTTPForbidden(text="Origin is not allowed")
        try:
            response = await handler(request)
        except AuthError:
            response = web.json_response({"error": "invalid_token"}, status=401,
                                         headers={"WWW-Authenticate": challenge})
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    app = web.Application(client_max_size=MAX_BODY, middlewares=[guard])

    async def metadata(request):
        return web.json_response(verifier.metadata())

    async def mcp(request):
        if request.method != "POST":
            return web.Response(status=405, headers={"Allow": "POST"})
        # Authenticate before parsing or producing side effects. Verification is
        # repeated in the worker to recheck revocation at execution time.
        await actor.submit(lambda: verifier.verify(request.headers.get("Authorization")))
        if request.content_type != "application/json":
            return error(None, -32600, "Expected application/json", 415)
        accept = request.headers.get("Accept", "")
        if "application/json" not in accept or "text/event-stream" not in accept:
            return error(None, -32600, "Accept must include JSON and event-stream", 406)
        try:
            raw = await asyncio.wait_for(request.read(), timeout=10)
            def reject_constant(value):
                raise ValueError
            body = json.loads(raw, parse_constant=reject_constant)
        except (ValueError, UnicodeDecodeError):
            return error(None, -32700, "Invalid JSON")
        except asyncio.TimeoutError:
            return error(None, -32600, "Request timeout", 408)
        if (not isinstance(body, dict) or body.get("jsonrpc") != "2.0"
                or type(body.get("id")) not in (str, int) or not isinstance(body.get("method"), str)):
            return error(None, -32600, "Expected a single JSON-RPC request")
        rid, method = body["id"], body["method"]
        params = body.get("params", {})
        if not isinstance(params, dict):
            return error(rid, -32602, "Invalid params")
        meta = params.get("_meta", {})
        if (not isinstance(meta, dict) or not isinstance(meta.get(META + "protocolVersion"), str)
                or not isinstance(meta.get(META + "clientCapabilities"), dict)):
            return error(rid, -32602, "Required MCP 2.0 request metadata missing")
        version = meta[META + "protocolVersion"]
        mirrors = {"MCP-Protocol-Version": version, "Mcp-Method": method}
        if method in ("tools/call", "prompts/get", "resources/read"):
            mirrors["Mcp-Name"] = params.get("uri" if method == "resources/read" else "name")
        try:
            if any(len(request.headers.getall(k, [])) != 1 or decoded(request.headers.get(k)) != v
                   for k, v in mirrors.items()):
                return error(rid, -32020, "MCP header mismatch")
        except (ValueError, UnicodeDecodeError):
            return error(rid, -32020, "Malformed MCP header")
        if version != VERSION:
            return error(rid, -32022, "Unsupported protocol version", data={"supported": [VERSION], "requested": version})
        try:
            response = await actor.rpc(body, request.headers.get("Authorization"))
        except AuthError:
            raise
        except Exception:
            return error(rid, -32603, "Internal bridge error", 500)
        if "result" in response:
            response["result"]["resultType"] = "complete"
            if method in ("server/discover", "tools/list"):
                response["result"].update(ttlMs=0, cacheScope="private")
            response["result"]["_meta"] = {META + "serverInfo": {"name": "discord-dot-bridge", "version": "0.2.0"}}
            return web.json_response(response)
        code = response["error"]["code"]
        return web.json_response(response, status=404 if code == -32601 else 400)

    app.router.add_get("/.well-known/oauth-protected-resource", metadata)
    app.router.add_get("/.well-known/oauth-protected-resource/mcp", metadata)
    app.router.add_route("*", "/mcp", mcp)
    return app
