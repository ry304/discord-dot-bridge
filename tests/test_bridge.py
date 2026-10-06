import base64
import hashlib
import hmac
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bridge.core import (Bridge, Fault, MAX_BODY, VERSION, iso, public_addresses,
                         signed_request, signing_key, validate_url)
from bridge.synthetic import (OWNER, BOT, CHANNEL, MESSAGE, BEARER, SECRET, URL,
                              Clock, FakeWebhook, FakeDiscord, dispatch, subscription)


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "state.sqlite3"
        self.clock, self.hook, self.discord = Clock(), FakeWebhook(), FakeDiscord()
        self.open()

    def open(self):
        self.bridge = Bridge(self.path, owner_id=OWNER, bot_id=BOT, bearer=BEARER,
                             callback_hosts=["callback.example.test"], webhook=self.hook,
                             discord=self.discord, clock=self.clock)

    def tearDown(self):
        self.bridge.close()
        self.temp.cleanup()

    def rpc(self, method, params=None, auth="Bearer " + BEARER):
        return self.bridge.rpc({"jsonrpc": "2.0", "id": 1, "method": method,
                                "params": params or {}}, auth)

    def subscribe(self):
        result = self.rpc("events/subscribe", subscription())
        self.assertIn("result", result)
        return result["result"]

    def ingest(self, event=None, **kwargs):
        return self.bridge.ingest(event or dispatch(), channel_type=kwargs.get("channel_type", 1),
                                  recipient_id=kwargs.get("recipient_id", OWNER))

    def delivered(self):
        self.subscribe()
        self.assertTrue(self.ingest())
        self.bridge.pump()

    def reply(self, text="Synthetic reply", **extra):
        return self.rpc("tools/call", {"name": "discord_reply", "arguments": {
            "message_id": MESSAGE, "text": text, **extra}})

    def test_auth_applies_to_every_method_and_revocation(self):
        for method in ["server/discover", "events/list", "events/subscribe", "events/unsubscribe",
                       "tools/list", "tools/call"]:
            self.assertEqual(self.rpc(method, auth="Bearer wrong")["error"]["code"], -32001)
        self.subscribe()
        self.ingest()
        self.bridge.enabled = False
        self.assertEqual(self.bridge.pump(), 0)
        self.assertFalse(self.ingest())
        self.assertIn("error", self.rpc("server/discover"))

    def test_discovery(self):
        self.assertEqual(self.rpc("server/discover")["result"]["supportedVersions"], [VERSION])
        self.assertEqual(len(self.rpc("events/list")["result"]["events"]), 1)
        self.assertEqual(self.rpc("tools/list")["result"]["tools"][0]["name"], "discord_reply")

    def test_subscription_idempotency_rotation_restart_expiry(self):
        sid = self.subscribe()["id"]
        self.assertEqual(self.subscribe()["id"], sid)
        params = subscription()
        params["delivery"]["secret"] = "whsec_" + base64.b64encode(b"B" * 32).decode()
        self.assertEqual(self.rpc("events/subscribe", params)["result"]["id"], sid)
        self.bridge.close()
        self.open()
        self.ingest()
        self.bridge.pump()
        self.assertEqual(len(self.hook.calls[-1][3]["webhook-signature"].split()), 2)
        self.clock.now += 3601
        self.assertFalse(self.ingest(dispatch("555")))

    def test_wrong_owner_cursor_ttl_secret_and_second_callback(self):
        for mutate in [lambda p: p.update(arguments={"owner_id": "999"}),
                       lambda p: p.update(cursor="history"), lambda p: p.update(ttlMs=0),
                       lambda p: p.update(ttlMs=True),
                       lambda p: p["delivery"].update(secret="bad")]:
            params = subscription()
            mutate(params)
            self.assertIn("error", self.rpc("events/subscribe", params))
        self.subscribe()
        params = subscription()
        params["delivery"]["url"] = URL + "-other-dot"
        self.assertIn("error", self.rpc("events/subscribe", params))

    def test_callback_verification_failure_not_stored(self):
        self.hook.challenge_ok = False
        result = self.rpc("events/subscribe", subscription())
        self.assertEqual(result["error"]["data"]["reason"], "challenge_failed")
        self.assertEqual(self.bridge.db.execute("SELECT count(*) FROM subscriptions").fetchone()[0], 0)
        self.hook.challenge_ok = True
        self.hook.status = 302
        self.assertIn("error", self.rpc("events/subscribe", subscription()))

    def test_callback_timeout(self):
        with patch.object(self.hook, "post", side_effect=TimeoutError):
            self.assertEqual(self.rpc("events/subscribe", subscription())["error"]["data"]["reason"], "timeout")

    def test_verification_cache_is_bounded_and_key_specific(self):
        self.subscribe()
        self.subscribe()
        self.assertEqual(len(self.hook.calls), 1)
        self.clock.now += 61
        self.subscribe()
        self.assertEqual(len(self.hook.calls), 2)
        params = subscription()
        params["delivery"]["secret"] = "whsec_" + base64.b64encode(b"B" * 24).decode()
        self.rpc("events/subscribe", params)
        self.assertEqual(len(self.hook.calls), 3)

    def test_expired_subscription_stops_queued_event(self):
        params = subscription()
        params["ttlMs"] = 1000
        self.assertIn("result", self.rpc("events/subscribe", params))
        self.ingest()
        self.clock.now += 2
        self.assertEqual(self.bridge.pump(), 0)
        self.assertEqual(len(self.hook.calls), 1)

    def test_owner_burst_limit(self):
        self.subscribe()
        for n in range(30):
            self.assertTrue(self.ingest(dispatch(str(1000 + n))))
        with self.assertRaises(Fault):
            self.ingest(dispatch("2000"))

    def test_callback_ssrf_and_dns_rebinding(self):
        for url in ["http://callback.example.test/x", "https://evil.test/x", "https://u:p@callback.example.test/x",
                    "https://callback.example.test:444/x", URL + "#fragment", "https://127.0.0.1/x"]:
            with self.assertRaises(Fault):
                validate_url(url, self.bridge.hosts)
        for addresses in [[], ["not-an-IP"], ["127.0.0.1"], ["10.0.0.1"], ["169.254.169.254"], ["::1"],
                          ["224.0.0.1"], ["::ffff:8.8.8.8"], ["8.8.8.8", "192.168.1.1"]]:
            with self.assertRaises(Fault):
                public_addresses(addresses)
        self.subscribe()
        self.ingest()
        calls = len(self.hook.calls)
        self.hook.addresses = ["127.0.0.1"]
        self.bridge.pump()
        self.assertEqual(len(self.hook.calls), calls)

    def test_owner_dm_scope_and_feedback_loops(self):
        self.subscribe()
        for mutate in [lambda d: d.update(guild_id="999"), lambda d: d.update(webhook_id="999"),
                       lambda d: d["author"].update(bot=True), lambda d: d["author"].update(id=BOT),
                       lambda d: d["author"].update(id="999"), lambda d: d.update(type=7),
                       lambda d: d.update(content=""), lambda d: d.update(content="x" * 2001)]:
            event = dispatch()
            mutate(event["d"])
            self.assertFalse(self.ingest(event))
        self.assertFalse(self.ingest(channel_type=3))
        self.assertFalse(self.ingest(recipient_id="999"))
        self.assertTrue(self.ingest())

    def test_replay_timestamp_and_persistent_dedup(self):
        self.subscribe()
        for offset in [-301, 31]:
            event = dispatch()
            event["d"]["timestamp"] = iso(self.clock() + offset)
            self.assertFalse(self.ingest(event))
        self.assertTrue(self.ingest())
        self.bridge.close()
        self.open()
        self.assertFalse(self.ingest())
        self.bridge.pump()
        self.assertEqual(self.bridge.pump(), 0)

    def test_retries_stable_id_fresh_signature_bounded(self):
        self.subscribe()
        self.ingest()
        self.hook.status = 503
        for _ in range(7):
            self.bridge.pump()
            self.clock.now += 61
        calls = self.hook.calls[1:]
        self.assertEqual(len(calls), 5)
        self.assertEqual(len({c[3]["webhook-id"] for c in calls}), 1)
        self.assertEqual(len({c[3]["webhook-signature"] for c in calls}), 5)

    def test_terminal_http_errors(self):
        self.subscribe()
        self.ingest()
        self.hook.status = 413
        self.bridge.pump()
        self.clock.now += 61
        self.assertEqual(self.bridge.pump(), 0)

    def test_gone_deactivates_subscription(self):
        self.subscribe()
        self.ingest()
        self.hook.status = 410
        self.bridge.pump()
        self.assertEqual(self.bridge.db.execute("SELECT count(*) FROM subscriptions").fetchone()[0], 0)

    def test_reply_destination_idempotency_and_mentions(self):
        self.delivered()
        self.assertIn("error", self.reply(channel_id="999"))
        self.assertIn("result", self.reply())
        self.assertIn("result", self.reply())
        self.assertIn("error", self.reply("Changed reply"))
        self.assertEqual(len(self.discord.sent), 1)
        self.assertEqual(self.discord.sent[0]["allowed_mentions"]["parse"], [])
        self.assertTrue(self.discord.sent[0]["enforce_nonce"])

    def test_ambiguous_reply_never_automatically_resends_even_after_restart(self):
        self.delivered()
        self.discord.timeout = True
        self.assertTrue(self.reply()["result"]["isError"])
        self.bridge.close()
        self.open()
        self.assertTrue(self.reply()["result"]["isError"])
        self.assertEqual(len(self.discord.sent), 1)

    def test_reply_requires_delivery_and_expires(self):
        self.subscribe()
        self.ingest()
        self.assertIn("error", self.reply())
        self.bridge.pump()
        self.clock.now += 601
        self.assertIn("error", self.reply())

    def test_unsubscribe_idempotent_cancels_pending_and_reply(self):
        self.delivered()
        for _ in range(2):
            self.assertEqual(self.rpc("events/unsubscribe", subscription())["result"], {})
        self.assertEqual(self.bridge.pump(), 0)
        self.assertIn("error", self.reply())

    def test_capacity_fails_closed(self):
        self.subscribe()
        self.bridge.capacity = 1
        self.ingest()
        with self.assertRaises(Fault):
            self.ingest(dispatch("555"))

    def test_database_cannot_be_rebound(self):
        with self.assertRaises(ValueError):
            Bridge(self.path, owner_id="999", bot_id=BOT, bearer=BEARER,
                   callback_hosts=[], webhook=self.hook, discord=self.discord)

    def test_malformed_rpc_and_unknown_method(self):
        for request in [None, [], {}, {"jsonrpc": "2.0", "id": {}, "method": "events/list"}]:
            self.assertEqual(self.bridge.rpc(request, "Bearer " + BEARER)["error"]["code"], -32600)
        self.assertEqual(self.rpc("unknown")["error"]["code"], -32601)


class SignatureTests(unittest.TestCase):
    def test_standard_webhooks_signature_exact_bytes(self):
        raw, headers = signed_request({"text": "café"}, "evt_1", "sub_1", SECRET, 12345)
        expected = base64.b64encode(hmac.new(b"A" * 24, b"evt_1.12345." + raw, hashlib.sha256).digest()).decode()
        self.assertEqual(headers["webhook-signature"], "v1," + expected)
        altered = base64.b64encode(hmac.new(b"A" * 24, b"evt_1.12345." + raw + b" ", hashlib.sha256).digest()).decode()
        self.assertNotEqual(expected, altered)

    def test_size_and_secret_bounds(self):
        for secret in ["", "whsec_!!!!", "whsec_" + base64.b64encode(b"x" * 23).decode(),
                       "whsec_" + base64.b64encode(b"x" * 65).decode()]:
            with self.assertRaises(Fault):
                signing_key(secret)
        with self.assertRaises(Fault):
            signed_request({"x": "x" * MAX_BODY}, "evt", "sub", SECRET, 1)


if __name__ == "__main__":
    # Assert the entire suite remains offline, including future test additions.
    with patch("socket.socket", side_effect=AssertionError("Network forbidden in proof of concept")):
        unittest.main()
