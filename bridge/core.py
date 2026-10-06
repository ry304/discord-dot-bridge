"""Protocol core. All I/O is injected; this module never opens a network socket.

Single-process/single-thread prototype. SQLite commits precede external effects.
Network adapters run outside the serialized SQLite worker.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import json
import secrets
import sqlite3
import time
from datetime import datetime, timezone
from urllib.parse import urlsplit
from standardwebhooks import Webhook
from .scope import Scope

EVENT = "discord.dm.created"
VERSION = "2026-07-28"
DIRECT_MESSAGES_INTENT = 1 << 12
MAX_BODY = 262144


class Fault(Exception):
    def __init__(self, code, message, reason=None):
        super().__init__(message)
        self.code, self.reason = code, reason


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def iso(ts):
    return datetime.fromtimestamp(ts, timezone.utc).isoformat().replace("+00:00", "Z")


def signing_key(secret):
    try:
        if not isinstance(secret, str) or not secret.startswith("whsec_"):
            raise ValueError
        key = base64.b64decode(secret[6:], validate=True)
        if not 24 <= len(key) <= 64:
            raise ValueError
        return key
    except (ValueError, TypeError):
        raise Fault(-32602, "Invalid signing secret") from None


def signed_request(body, event_id, subscription_id, secret, now, old_secret=None):
    raw = canonical(body).encode("utf-8")
    if len(raw) > MAX_BODY:
        raise Fault(-32602, "Payload too large")
    stamp = str(int(now))
    signatures = []
    for key in [secret] + ([old_secret] if old_secret else []):
        signing_key(key)
        signatures.append(Webhook(key).sign(event_id, datetime.fromtimestamp(now, timezone.utc), raw.decode("utf-8")))
    return raw, {"Content-Type": "application/json", "webhook-id": event_id,
                 "webhook-timestamp": stamp, "webhook-signature": " ".join(signatures),
                 "X-MCP-Subscription-Id": subscription_id}


def validate_url(url, allowed_hosts):
    try:
        u = urlsplit(url)
        if (u.scheme != "https" or not u.hostname or u.username or u.password
                or u.fragment or u.port not in (None, 443)
                or u.hostname not in allowed_hosts):
            raise ValueError
        return u.hostname
    except (ValueError, TypeError):
        raise Fault(-32602, "Callback URL is not allowed") from None


def public_addresses(addresses):
    """Transport must resolve each attempt and connect only to one returned IP.

    TLS SNI and certificate verification must still use the original hostname.
    Never resolve again during connect, follow redirects, or honor proxy env vars.
    """
    if not addresses:
        raise Fault(-32015, "Callback unavailable", "destination_blocked")
    for address in addresses:
        try:
            ip = ipaddress.ip_address(address)
        except ValueError:
            raise Fault(-32015, "Callback unavailable", "destination_blocked") from None
        if not ip.is_global or ip.is_multicast or getattr(ip, "ipv4_mapped", None):
            raise Fault(-32015, "Callback unavailable", "destination_blocked")
    return tuple(addresses)


def object_schema(properties, required=None):
    return {"type": "object", "properties": properties,
            "required": required if required is not None else list(properties),
            "additionalProperties": False}


STRING = {"type": "string"}
EVENT_DEFINITION = {
    "name": EVENT, "description": "A text DM from the configured owner to the bot.",
    "delivery": ["webhook"], "inputSchema": object_schema({"owner_id": STRING}),
    "payloadSchema": object_schema({k: STRING for k in
                                    ("message_id", "owner_id", "text")}),
}
REPLY_TOOL = {
    "name": "discord_reply", "description": "Reply once to an accepted owner message. "
    "The destination is fixed by the original message; supply only the intended reply.",
    "inputSchema": object_schema({"message_id": STRING, "text": STRING}),
    "annotations": {"readOnlyHint": False, "destructiveHint": False,
                    "idempotentHint": True, "openWorldHint": True},
    "securitySchemes": [{"type": "oauth2", "scopes": ["discord:bridge"]}],
}


class Bridge:
    def __init__(self, database, *, owner_id, bot_id, bearer, callback_hosts,
                 webhook, discord, clock=time.time, capacity=1000, scope=None):
        self.scope = scope or Scope()
        self.event = self.scope.event
        if not all(isinstance(x, str) and x.isascii() and x.isdigit()
                   for x in (owner_id, bot_id)) or owner_id == bot_id:
            raise ValueError("Distinct owner and bot IDs required")
        if not isinstance(bearer, str) or len(bearer) < 32:
            raise ValueError("A bearer of at least 32 characters is required")
        self.owner, self.bot, self.bearer = owner_id, bot_id, bearer
        self.hosts = frozenset(callback_hosts)
        self.webhook, self.discord, self.clock = webhook, discord, clock
        self.capacity, self.enabled = capacity, True
        self.principal = owner_id
        self.auth_until = float("inf")
        self.verified = {}  # Bounded to the sole active callback; refreshed on key change.
        self.db = sqlite3.connect(database)
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
        PRAGMA journal_mode=WAL;
        PRAGMA synchronous=FULL;
        CREATE TABLE IF NOT EXISTS binding(owner TEXT, bot TEXT);
        CREATE TABLE IF NOT EXISTS subscriptions(
          id TEXT PRIMARY KEY, url TEXT, secret TEXT, old_secret TEXT,
          rotate_until REAL, expires REAL);
        CREATE TABLE IF NOT EXISTS messages(
          id TEXT PRIMARY KEY, channel TEXT, event TEXT, received REAL,
          reply_hash TEXT, reply_status TEXT);
        CREATE TABLE IF NOT EXISTS deliveries(
          sub TEXT, message TEXT, status TEXT, attempts INTEGER, due REAL,
          PRIMARY KEY(sub,message));
        ''')
        binding = self.db.execute("SELECT * FROM binding").fetchone()
        if binding and (binding["owner"], binding["bot"]) != (owner_id, bot_id):
            self.db.close()
            raise ValueError("Database belongs to another owner or bot")
        if not binding:
            with self.db:
                self.db.execute("INSERT INTO binding VALUES (?,?)", (owner_id, bot_id))
        self.db.execute("CREATE TABLE IF NOT EXISTS scope_binding(value TEXT)")
        row = self.db.execute("SELECT value FROM scope_binding").fetchone()
        legacy_data = self.db.execute("SELECT count(*) FROM messages").fetchone()[0] or self.db.execute("SELECT count(*) FROM subscriptions").fetchone()[0]
        if (row and row[0] != self.scope.binding) or (not row and legacy_data and self.scope.mode != "dm"):
            self.db.close()
            raise ValueError("Destination changed; preserve old state and use a new database")
        if not row:
            with self.db:
                self.db.execute("INSERT INTO scope_binding VALUES (?)", (self.scope.binding,))

    def close(self):
        self.db.close()

    def bind_principal(self, principal):
        self.db.execute("CREATE TABLE IF NOT EXISTS principal_binding(value TEXT)")
        row = self.db.execute("SELECT value FROM principal_binding").fetchone()
        if row and row[0] != principal:
            raise ValueError("Database belongs to another OAuth principal")
        if not row:
            with self.db:
                self.db.execute("INSERT INTO principal_binding VALUES (?)", (principal,))
        self.principal = principal

    def authorize(self, authorization):
        expected = ("Bearer " + self.bearer).encode()
        if not self.enabled or not isinstance(authorization, str) or not hmac.compare_digest(
                authorization.encode(), expected):
            raise Fault(-32001, "Unauthorized")

    def identity(self, params, needs_secret=False):
        if not isinstance(params, dict) or params.get("name") != self.event:
            raise Fault(-32602, "Unknown event")
        if params.get("arguments") != {"owner_id": self.owner}:
            raise Fault(-32602, "Owner filter required")
        d = params.get("delivery")
        if not isinstance(d, dict) or d.get("mode") != "webhook":
            raise Fault(-32602, "Webhook delivery required")
        validate_url(d.get("url"), self.hosts)
        if needs_secret:
            signing_key(d.get("secret"))
        identity = [self.principal, d["url"], self.event, params["arguments"]]
        return "sub_" + hashlib.sha256(canonical(identity).encode()).hexdigest()[:32]

    def post(self, url, body, event_id, sid, key, old=None):
        host = validate_url(url, self.hosts)
        # The injected transport receives a pinned destination set, not a license
        # to re-resolve. The shipped fake has no networking implementation.
        addresses = public_addresses(self.webhook.resolve(host))
        raw, headers = signed_request(body, event_id, sid, key, self.clock(), old)
        return self.webhook.post(url, addresses, raw, headers, timeout=10, redirects=False)

    def subscribe(self, params):
        sid = self.identity(params, True)
        if params.get("cursor") is not None:
            raise Fault(-32602, "This event does not support replay")
        ttl = params.get("ttlMs", 3600000)
        if ttl is None:
            ttl = 3600000
        if type(ttl) is not int or ttl <= 0:
            raise Fault(-32602, "ttlMs must be a positive integer or null")
        ttl = max(1000, min(ttl, 86400000))
        old = self.db.execute("SELECT * FROM subscriptions WHERE id=?", (sid,)).fetchone()
        # One callback for one dot; prevents accidentally broadcasting owner DMs.
        if not old and self.db.execute("SELECT count(*) FROM subscriptions").fetchone()[0]:
            raise Fault(-32602, "Unsubscribe the existing dot before changing callback")
        d = params["delivery"]
        challenge = secrets.token_urlsafe(24)
        start = self.clock()
        cache_key = (self.principal, d["url"], hashlib.sha256(d["secret"].encode()).hexdigest())
        try:
            if self.verified.get(cache_key, 0) <= start:
                status, response = self.post(d["url"], {"type": "verification", "challenge": challenge},
                                            "msg_verification_" + secrets.token_hex(12), sid, d["secret"])
                echoed = response.get("challenge") if isinstance(response, dict) else None
                if not (200 <= status < 300 and isinstance(echoed, str)
                        and hmac.compare_digest(echoed.encode(), challenge.encode())
                        and self.clock() - start <= 10):
                    raise Fault(-32015, "Callback verification failed", "challenge_failed")
                self.verified = {cache_key: self.clock() + 60}
        except TimeoutError:
            raise Fault(-32015, "Callback verification failed", "timeout") from None
        except OSError:
            raise Fault(-32015, "Callback verification failed", "connection_failed") from None
        expires = min(self.clock() + ttl / 1000, self.auth_until)
        if expires <= self.clock():
            raise Fault(-32012, "Authorization expired")
        previous = old["secret"] if old and old["secret"] != d["secret"] else None
        rotate_until = self.clock() + 300 if previous else 0
        if old and not previous and old["rotate_until"] > self.clock():
            previous, rotate_until = old["old_secret"], old["rotate_until"]
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO subscriptions VALUES (?,?,?,?,?,?)",
                            (sid, d["url"], d["secret"], previous, rotate_until, expires))
        return {"id": sid, "refreshBefore": iso(expires), "cursor": None, "truncated": False}

    def unsubscribe(self, params):
        sid = self.identity(params)
        self.verified.clear()
        with self.db:
            self.db.execute("DELETE FROM subscriptions WHERE id=?", (sid,))
            self.db.execute("DELETE FROM deliveries WHERE sub=?", (sid,))
        return {}

    def ingest(self, dispatch, *, channel_type, recipient_id):
        """Accept a MESSAGE_CREATE plus trusted channel metadata from bot SDK.

        Caller must resolve the actual configured channel. Do not take
        channel_type or recipient_id from user text or unauthenticated HTTP input.
        """
        if not self.enabled or recipient_id != self.owner:
            return False
        if not isinstance(dispatch, dict) or dispatch.get("t") != "MESSAGE_CREATE" or dispatch.get("op") != 0:
            return False
        d = dispatch.get("d", {})
        if not isinstance(d, dict) or not isinstance(d.get("author"), dict):
            return False
        if not self.scope.accepts(channel_type, d.get("channel_id"), d.get("guild_id")):
            return False
        if self.scope.mode == "guild_mentions" and not self.scope.mentions_bot(d.get("content"), d.get("mentions"), self.bot):
            return False
        a = d["author"]
        if (d.get("webhook_id") or a.get("bot") or a.get("system")
                or a.get("id") != self.owner or d.get("type", 0) != 0):
            return False
        if not all(isinstance(d.get(k), str) and 1 <= len(d[k]) <= 20 and d[k].isascii() and d[k].isdigit()
                   for k in ("id", "channel_id")):
            return False
        text = d.get("content")
        if not isinstance(text, str) or not text.strip() or len(text) > 2000:
            return False
        try:
            happened = datetime.fromisoformat(d["timestamp"].replace("Z", "+00:00"))
            if happened.tzinfo is None or not -30 <= self.clock() - happened.timestamp() <= 300:
                return False
        except (KeyError, ValueError, TypeError, AttributeError):
            return False
        if self.db.execute("SELECT 1 FROM messages WHERE id=?", (d["id"],)).fetchone():
            return False
        subs = self.db.execute("SELECT * FROM subscriptions WHERE expires>?", (self.clock(),)).fetchall()
        if not subs:
            return False
        if self.db.execute("SELECT count(*) FROM messages").fetchone()[0] >= self.capacity:
            raise Fault(-32000, "Prototype storage capacity reached")
        if self.db.execute("SELECT count(*) FROM messages WHERE received>?", (self.clock() - 60,)).fetchone()[0] >= 30:
            raise Fault(-32000, "Owner rate limit reached")
        event = {"eventId": "discord_" + d["id"], "name": self.event, "timestamp": iso(happened.timestamp()),
                 "data": {"message_id": d["id"], "owner_id": self.owner, "text": text}, "cursor": None}
        with self.db:
            self.db.execute("INSERT INTO messages VALUES (?,?,?,?,NULL,NULL)",
                            (d["id"], d["channel_id"], canonical(event), self.clock()))
            for sub in subs:
                self.db.execute("INSERT INTO deliveries VALUES (?,?, 'pending',0,?)",
                                (sub["id"], d["id"], self.clock()))
        return True

    def pump(self):
        """One bounded work pass. No sleeps; caller schedules next pass."""
        if not self.enabled:
            return 0
        rows = self.db.execute('''SELECT d.*,s.url,s.secret,s.old_secret,s.rotate_until,m.event,m.received
            FROM deliveries d JOIN subscriptions s ON s.id=d.sub
            JOIN messages m ON m.id=d.message WHERE d.status='pending' AND d.due<=?
            AND s.expires>? ORDER BY d.due LIMIT 30''', (self.clock(), self.clock())).fetchall()
        for row in rows:
            if self.clock() - row["received"] > 600 or row["attempts"] >= 5:
                with self.db:
                    self.db.execute("UPDATE deliveries SET status='failed' WHERE sub=? AND message=?",
                                    (row["sub"], row["message"]))
                continue
            attempt = row["attempts"] + 1
            with self.db:
                self.db.execute("UPDATE deliveries SET attempts=?,due=? WHERE sub=? AND message=?",
                                (attempt, self.clock() + min(2 ** attempt, 60), row["sub"], row["message"]))
            event = json.loads(row["event"])
            try:
                status, _ = self.post(row["url"], event, event["eventId"], row["sub"], row["secret"],
                                      row["old_secret"] if row["rotate_until"] > self.clock() else None)
            except (TimeoutError, OSError, Fault):
                status = 503
            result = "sent" if 200 <= status < 300 else (
                "pending" if (status in (408, 429) or status >= 500) and attempt < 5 else "failed")
            with self.db:
                self.db.execute("UPDATE deliveries SET status=? WHERE sub=? AND message=?",
                                (result, row["sub"], row["message"]))
                if status == 410:
                    self.db.execute("DELETE FROM subscriptions WHERE id=?", (row["sub"],))
        return len(rows)

    def reply(self, args):
        if not isinstance(args, dict) or set(args) != {"message_id", "text"}:
            raise Fault(-32602, "message_id and text required; destination cannot be changed")
        mid, text = args["message_id"], args["text"]
        if not isinstance(mid, str) or not isinstance(text, str) or not text.strip() or len(text) > 2000:
            raise Fault(-32602, "Reply must contain 1..2000 characters")
        row = self.db.execute("SELECT * FROM messages WHERE id=?", (mid,)).fetchone()
        if not row or self.clock() - row["received"] > 600:
            raise Fault(-32602, "Unknown or expired message")
        if self.scope.mode == "guild_mentions" and row["channel"] != self.scope.channel_id:
            raise Fault(-32602, "Message destination is outside configured scope")
        if not self.db.execute('''SELECT 1 FROM deliveries d JOIN subscriptions s ON s.id=d.sub
            WHERE d.message=? AND d.status='sent' AND s.expires>?''', (mid, self.clock())).fetchone():
            raise Fault(-32602, "Message has no active delivered subscription")
        digest = hashlib.sha256(text.encode()).hexdigest()
        if row["reply_hash"]:
            if row["reply_hash"] != digest:
                raise Fault(-32602, "A different reply is already reserved")
            return {"status": row["reply_status"]}
        # Reserve before send: a timeout/crash remains unknown and must NEVER
        # auto-resend. Discord nonce uniqueness is time-limited, not exactly-once.
        with self.db:
            self.db.execute("UPDATE messages SET reply_hash=?,reply_status='unknown' WHERE id=?", (digest, mid))
        payload = {"content": text, "allowed_mentions": {"parse": [], "replied_user": False},
                   "nonce": mid, "enforce_nonce": True,
                   "message_reference": {"message_id": mid, "fail_if_not_exists": True}}
        try:
            self.discord.send_dm(row["channel"], self.owner, payload)
        except (TimeoutError, OSError):
            return {"status": "unknown"}
        with self.db:
            self.db.execute("UPDATE messages SET reply_status='sent' WHERE id=?", (mid,))
        return {"status": "sent"}

    def rpc(self, request, authorization):
        rid = request.get("id") if isinstance(request, dict) else None
        try:
            self.authorize(authorization)
            if (not isinstance(request, dict) or request.get("jsonrpc") != "2.0"
                    or type(rid) not in (int, str) or not isinstance(request.get("method"), str)):
                raise Fault(-32600, "Invalid request")
            if len(canonical(request).encode()) > MAX_BODY:
                raise Fault(-32600, "Request too large")
            method, params = request["method"], request.get("params", {})
            if not isinstance(params, dict):
                raise Fault(-32602, "Parameters must be an object")
            if method == "server/discover":
                result = {"resultType": "complete", "supportedVersions": [VERSION],
                          "capabilities": {"tools": {}, "events": {}}}
            elif method == "events/list":
                definition = dict(EVENT_DEFINITION, name=self.event)
                if self.scope.mode == "guild_mentions":
                    definition["description"] = "An explicit bot mention by the configured owner in the sole allowed guild text channel."
                result = {"events": [definition]}
            elif method == "events/subscribe":
                result = self.subscribe(params)
            elif method == "events/unsubscribe":
                result = self.unsubscribe(params)
            elif method == "tools/list":
                result = {"tools": [REPLY_TOOL]}
            elif method == "tools/call" and params.get("name") == "discord_reply":
                value = self.reply(params.get("arguments"))
                result = {"content": [{"type": "text", "text": canonical(value)}],
                          "isError": value["status"] != "sent"}
            else:
                raise Fault(-32601, "Method not found")
            return {"jsonrpc": "2.0", "id": rid, "result": result}
        except Fault as exc:
            error = {"code": exc.code, "message": str(exc)}
            if exc.reason:
                error["data"] = {"reason": exc.reason}
            return {"jsonrpc": "2.0", "id": rid, "error": error}
