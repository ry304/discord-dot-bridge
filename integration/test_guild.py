import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
import discord
from bridge.commands import OwnerCommands
from bridge.discord_adapter import DiscordBot
from bridge.scope import Scope
from bridge.setup_bot import SetupControl
from bridge.synthetic import OWNER, BOT, CHANNEL, MESSAGE

GUILD = "555555555555555555"


class GuildTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.submit = AsyncMock()
        self.bot = DiscordBot(OWNER, BOT, self.submit, scope=Scope("guild_mentions", GUILD, CHANNEL))
        self.bot._connection.user = SimpleNamespace(id=int(BOT), bot=True)
        self.channel = self.text_channel()
        self.bot.fetch_channel = AsyncMock(return_value=self.channel)

    async def asyncTearDown(self):
        await self.bot.close()

    def text_channel(self, guild=GUILD, channel=CHANNEL):
        value = Mock(spec=discord.TextChannel)
        value.id = int(channel)
        value.guild = SimpleNamespace(id=int(guild))
        value.type = discord.ChannelType.text
        value.send = AsyncMock()
        return value

    def message(self):
        return SimpleNamespace(id=int(MESSAGE), channel=self.channel, guild=self.channel.guild,
            author=SimpleNamespace(id=int(OWNER), bot=False, system=False),
            mentions=[SimpleNamespace(id=int(BOT))], content=f"<@{BOT}> synthetic request",
            created_at=datetime.now(timezone.utc), type=discord.MessageType.default, webhook_id=None)

    async def test_intents_and_owner_mention_ingestion(self):
        self.assertEqual(self.bot.intents.value, (1 << 0) | (1 << 9))
        self.assertFalse(self.bot.intents.message_content)
        await self.bot.on_message(self.message())
        self.submit.assert_awaited_once()
        self.assertEqual(self.submit.call_args.kwargs, {"channel_type": 0, "recipient_id": OWNER})
        self.assertEqual(self.submit.call_args.args[0]["d"]["guild_id"], GUILD)

    async def test_wrong_channel_guild_author_and_missing_mentions_rejected(self):
        for channel in (self.text_channel(channel=OWNER), self.text_channel(guild=OWNER), Mock(spec=discord.DMChannel), Mock(spec=discord.Thread)):
            message = self.message()
            message.channel = channel
            await self.bot.on_message(message)
        message = self.message()
        message.author.id = int(BOT)
        await self.bot.on_message(message)
        message = self.message()
        message.mentions = []
        await self.bot.on_message(message)
        self.submit.assert_not_awaited()
        self.bot.fetch_channel.assert_not_awaited()

    async def test_fresh_resolution_and_reply_destination(self):
        self.bot.fetch_channel.return_value = self.text_channel(guild=OWNER)
        await self.bot.on_message(self.message())
        self.submit.assert_not_awaited()
        payload = {"content": "test", "nonce": MESSAGE, "message_reference": {"message_id": MESSAGE}}
        with self.assertRaises(OSError):
            await self.bot.send_owner_reply(CHANNEL, OWNER, payload)
        with self.assertRaises(OSError):
            await self.bot.send_owner_reply(OWNER, OWNER, payload)
        self.bot.fetch_channel.return_value = self.channel
        await self.bot.send_owner_reply(CHANNEL, OWNER, payload)
        self.channel.send.assert_awaited_once()
        self.assertFalse(self.channel.send.call_args.kwargs["mention_author"])

    async def test_guild_commands_exact_scope_ephemeral(self):
        commands = OwnerCommands(self.bot, SetupControl(), "https://bridge.example.test/mcp")
        for cmd in commands.tree.get_commands():
            metadata = cmd.to_dict(commands.tree)
            self.assertEqual(metadata["contexts"], [0])
            self.assertEqual(metadata["integration_types"], [0])
        def interaction(channel, owner=OWNER, guild=GUILD):
            return SimpleNamespace(user=SimpleNamespace(id=int(owner), bot=False), guild_id=int(guild),
                channel=channel, response=SimpleNamespace(send_message=AsyncMock(), defer=AsyncMock()),
                followup=SimpleNamespace(send=AsyncMock()))
        for item in (interaction(self.text_channel(channel=OWNER)), interaction(self.text_channel(guild=OWNER)),
                     interaction(self.channel, owner=BOT), interaction(self.channel, guild=OWNER)):
            await commands.handle(item, "status")
            item.response.defer.assert_not_awaited()
            item.response.send_message.assert_awaited_once()
        accepted = interaction(self.channel)
        await commands.handle(accepted, "status")
        accepted.response.defer.assert_awaited_once_with(ephemeral=True, thinking=True)
        self.assertTrue(accepted.followup.send.call_args.kwargs["ephemeral"])
