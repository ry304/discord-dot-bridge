import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
import discord
from bridge.auth import OAuthVerifier, AuthError
from bridge.commands import OwnerCommands
from bridge.core import Bridge
from bridge.discord_adapter import DiscordBot
from bridge.http_server import SerialCore, INTERNAL
from bridge.synthetic import OWNER, BOT, Clock, FakeWebhook, FakeDiscord, subscription, dispatch


class CommandTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.enabled = self.root / "enabled"
        self.enabled.write_text("enabled")
        self.verifier = OAuthVerifier(issuer="https://issuer.example.test", resource="https://bridge.example.test/mcp",
                                     subject="synthetic-owner", jwks_file=self.root / "unused.json", enabled_file=self.enabled)
        def factory():
            core = Bridge(self.root / "state.sqlite3", owner_id=OWNER, bot_id=BOT, bearer=INTERNAL,
                          callback_hosts=["callback.example.test"], webhook=FakeWebhook(), discord=FakeDiscord(), clock=Clock())
            core.subscribe(subscription())
            core.ingest(dispatch(), channel_type=1, recipient_id=OWNER)
            return core
        self.actor = SerialCore(factory, self.verifier)
        self.bot = DiscordBot(OWNER, BOT, AsyncMock())
        self.bot._connection.user = SimpleNamespace(id=int(BOT), bot=True)
        self.commands = OwnerCommands(self.bot, self.actor, self.verifier.resource)

    async def asyncTearDown(self):
        await self.actor.close()
        await self.bot.close()
        self.temp.cleanup()

    def interaction(self, owner=OWNER, guild=None, dm=True):
        return SimpleNamespace(user=SimpleNamespace(id=int(owner), bot=False), guild_id=guild,
            channel=Mock(spec=discord.DMChannel) if dm else Mock(spec=discord.GroupChannel),
            response=SimpleNamespace(send_message=AsyncMock(), defer=AsyncMock()),
            followup=SimpleNamespace(send=AsyncMock()))

    async def test_registration_metadata_is_user_install_bot_dm_only(self):
        payloads = [c.to_dict(self.commands.tree) for c in self.commands.tree.get_commands()]
        self.assertEqual({p["name"] for p in payloads}, {"setup", "status", "disconnect"})
        for payload in payloads:
            self.assertEqual(payload["contexts"], [1])
            self.assertEqual(payload["integration_types"], [1])
            self.assertFalse(payload.get("options"))

    async def test_owner_and_channel_checks_run_before_control(self):
        for interaction in (self.interaction(BOT), self.interaction(guild=1), self.interaction(dm=False)):
            await self.commands.handle(interaction, "disconnect")
            interaction.response.send_message.assert_awaited_once()
            self.assertTrue(interaction.response.send_message.call_args.kwargs["ephemeral"])
            interaction.followup.send.assert_not_awaited()
        self.assertTrue(self.verifier.enabled())
        self.assertEqual((await self.actor.status())["subscriptions"], 1)

    async def test_status_private_and_rate_limited(self):
        interaction = self.interaction()
        await self.commands.handle(interaction, "status")
        interaction.response.defer.assert_awaited_once_with(ephemeral=True, thinking=True)
        call = interaction.followup.send.call_args
        self.assertTrue(call.kwargs["ephemeral"])
        self.assertIn("Active subscriptions: 1", call.args[0])
        self.assertNotIn(OWNER, call.args[0])
        self.assertNotIn("callback", call.args[0])
        second = self.interaction()
        await self.commands.handle(second, "disconnect")
        second.response.send_message.assert_awaited_once()
        self.assertTrue(self.verifier.enabled())

    async def test_disconnect_revokes_and_cancels_persistently(self):
        interaction = self.interaction()
        await self.commands.handle(interaction, "disconnect")
        self.assertFalse(self.verifier.enabled())
        self.assertEqual(await self.actor.status(), {"enabled": False, "subscriptions": 0, "pending": 0})
        self.assertEqual(self.enabled.read_text().strip(), "disabled")
        with self.assertRaises(AuthError):
            self.verifier.verify("Bearer previously-valid-token")
        self.assertIn("Bridge disabled", interaction.followup.send.call_args.args[0])

    async def test_setup_only_guides_browser_flow_without_grant(self):
        interaction = self.interaction()
        before = await self.actor.status()
        await self.commands.handle(interaction, "setup")
        self.assertEqual(await self.actor.status(), before)
        content = interaction.followup.send.call_args.args[0]
        self.assertIn(self.verifier.resource, content)
        self.assertIn("existing dot", content)
        self.assertNotIn(OWNER, content)

    async def test_failed_disconnect_does_not_claim_success(self):
        self.commands.control = SimpleNamespace(disconnect=AsyncMock(side_effect=OSError("private diagnostic")))
        interaction = self.interaction()
        await self.commands.handle(interaction, "disconnect")
        content = interaction.followup.send.call_args.args[0]
        self.assertIn("could not be confirmed", content)
        self.assertNotIn("private diagnostic", content)
