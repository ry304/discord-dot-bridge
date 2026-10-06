import copy
import json
import tempfile
import unittest
from pathlib import Path
from bridge.core import Bridge, Fault
from bridge.scope import Scope
from bridge.synthetic import OWNER, BOT, CHANNEL, BEARER, Clock, FakeDiscord, FakeWebhook, dispatch, subscription

GUILD = "555555555555555555"


class ScopeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / "state.sqlite3"
        self.hook, self.sender = FakeWebhook(), FakeDiscord()
        self.scope = Scope("guild_mentions", GUILD, CHANNEL)
        self.core = self.make(self.scope)
        sub = subscription()
        sub["name"] = self.scope.event
        self.core.subscribe(sub)

    def make(self, scope):
        return Bridge(self.db, owner_id=OWNER, bot_id=BOT, bearer=BEARER,
                      callback_hosts=["callback.example.test"], webhook=self.hook,
                      discord=self.sender, clock=Clock(), scope=scope)

    def tearDown(self):
        self.core.close()
        self.temp.cleanup()

    def message(self):
        event = dispatch()
        event["d"].update(guild_id=GUILD, content=f"<@{BOT}> synthetic request", mentions=[{"id": BOT}])
        return event

    def test_scope_requires_complete_exact_configuration(self):
        for args in [("guild_mentions",), ("dm", GUILD, CHANNEL), ("all",), ("guild_mentions", GUILD, "bad")]:
            with self.assertRaises(ValueError):
                Scope(*args)

    def test_channel_event_and_fixed_reply(self):
        event = self.message()
        self.assertTrue(self.core.ingest(event, channel_type=0, recipient_id=OWNER))
        self.core.pump()
        emitted = json.loads(self.hook.calls[-1][2])
        self.assertEqual(emitted["name"], "discord.channel.mentioned")
        self.assertNotIn("guild_id", emitted["data"])
        self.assertNotIn("channel_id", emitted["data"])
        self.assertEqual(self.core.reply({"message_id": event["d"]["id"], "text": "Synthetic reply"}), {"status": "sent"})
        self.assertEqual(len(self.sender.sent), 1)

    def test_reject_other_destinations_users_and_unmentioned_messages(self):
        mutations = [{"guild_id": OWNER}, {"channel_id": OWNER}, {"guild_id": None},
                     {"mentions": []}, {"content": "unmentioned"}, {"author": {"id": BOT}},
                     {"author": {"id": OWNER, "bot": True}}, {"webhook_id": BOT}]
        for mutation in mutations:
            event = self.message()
            event["d"].update(mutation)
            self.assertFalse(self.core.ingest(event, channel_type=0, recipient_id=OWNER))
        for kind in (1, 3, 11, 12):
            self.assertFalse(self.core.ingest(self.message(), channel_type=kind, recipient_id=OWNER))
        self.assertEqual(self.core.pump(), 0)
        self.assertEqual(len(self.hook.calls), 1)  # verification only

    def test_destination_changes_cannot_reuse_state(self):
        self.core.close()
        for scope in (Scope(), Scope("guild_mentions", GUILD, OWNER), Scope("guild_mentions", OWNER, CHANNEL)):
            with self.assertRaises(ValueError):
                self.make(scope)
        self.core = self.make(self.scope)

    def test_wrong_event_subscription_and_cross_channel_reply_rejected(self):
        with self.assertRaises(Fault):
            self.core.subscribe(subscription())
        event = self.message()
        self.core.ingest(event, channel_type=0, recipient_id=OWNER)
        self.core.pump()
        with self.core.db:
            self.core.db.execute("UPDATE messages SET channel=?", (OWNER,))
        with self.assertRaises(Fault):
            self.core.reply({"message_id": event["d"]["id"], "text": "Synthetic reply"})
        self.assertFalse(self.sender.sent)
