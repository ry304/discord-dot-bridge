"""Official Discord bot API through the maintained discord.py SDK (not a selfbot)."""
import asyncio
import concurrent.futures
import discord
from .core import iso
from .scope import Scope


class DiscordBot(discord.Client):
    def __init__(self, owner_id, bot_id, submit_message, *, receive_messages=True, scope=None):
        self.scope = scope or Scope()
        intents = discord.Intents.none()
        intents.dm_messages = receive_messages and self.scope.mode == "dm"
        # GUILDS lets the SDK resolve guild message objects; no members/content intent.
        intents.guilds = self.scope.mode == "guild_mentions"
        intents.guild_messages = receive_messages and self.scope.mode == "guild_mentions"
        super().__init__(intents=intents, max_messages=None,
                         allowed_mentions=discord.AllowedMentions.none(),
                         max_ratelimit_timeout=10.0)
        self.owner_id, self.bot_id = str(owner_id), str(bot_id)
        self.submit_message = submit_message
        self.failed_messages = 0
        self.receive_messages = receive_messages

    def accepts_channel(self, channel):
        if self.scope.mode == "dm":
            return isinstance(channel, discord.DMChannel)
        return (isinstance(channel, discord.TextChannel) and channel.type == discord.ChannelType.text
                and self.scope.accepts(0, channel.id, channel.guild.id))

    async def verified_channel(self, channel_id):
        if self.scope.mode == "guild_mentions" and str(channel_id) != self.scope.channel_id:
            raise OSError("Destination outside configured scope")
        channel = await self.fetch_channel(int(channel_id))
        if not self.accepts_channel(channel):
            raise OSError("Destination outside configured scope")
        if self.scope.mode == "dm" and (not channel.recipient or str(channel.recipient.id) != self.owner_id):
            raise OSError("Destination is not owner DM")
        return channel

    async def on_ready(self):
        if not self.user or str(self.user.id) != self.bot_id or not self.user.bot:
            await self.close()
            raise RuntimeError("Configured bot identity mismatch")
        print("discord.gateway_ready identity_verified=true", flush=True)

    async def on_message(self, message):
        if not self.receive_messages:
            return
        if (not self.user or str(self.user.id) != self.bot_id
                or not self.accepts_channel(message.channel)
                or str(message.author.id) != self.owner_id or message.author.bot
                or message.author.system
                or not self.scope.accepts(message.channel.type.value, message.channel.id,
                                          str(message.guild.id) if message.guild else None)):
            return
        mentions = [{"id": str(user.id)} for user in getattr(message, "mentions", [])]
        if self.scope.mode == "guild_mentions" and not self.scope.mentions_bot(message.content, mentions, self.bot_id):
            return
        try:
            channel = await self.verified_channel(message.channel.id)
        except (discord.DiscordException, OSError):
            self.failed_messages += 1
            return
        d = {"id": str(message.id), "channel_id": str(message.channel.id),
             "author": {"id": str(message.author.id), "bot": message.author.bot,
                        "system": message.author.system},
             "content": message.content, "timestamp": iso(message.created_at.timestamp()),
             "type": message.type.value, "webhook_id": message.webhook_id}
        if self.scope.mode == "guild_mentions":
            d.update(guild_id=self.scope.guild_id, mentions=mentions)
        try:
            await self.submit_message({"op": 0, "t": "MESSAGE_CREATE", "d": d},
                                      channel_type=channel.type.value, recipient_id=self.owner_id)
        except Exception:
            # No raw message, token, callback URL or request data in logs.
            self.failed_messages += 1

    async def send_owner_reply(self, channel_id, owner_id, payload):
        if str(owner_id) != self.owner_id or not self.user or str(self.user.id) != self.bot_id:
            raise OSError("Bot identity unavailable")
        channel = await self.verified_channel(channel_id)
        ref = discord.MessageReference(message_id=int(payload["message_reference"]["message_id"]),
                                       channel_id=channel.id, fail_if_not_exists=True)
        # discord.py 2.7.1 sets enforce_nonce=True whenever nonce is supplied.
        return await channel.send(payload["content"], nonce=payload["nonce"], reference=ref,
                                  allowed_mentions=discord.AllowedMentions.none(), mention_author=False)


class DiscordSender:
    """Called only from the serialized core worker, never from its event loop."""
    def __init__(self, bot, loop):
        self.bot, self.loop = bot, loop

    def send_dm(self, channel, owner, payload):
        future = asyncio.run_coroutine_threadsafe(self.bot.send_owner_reply(channel, owner, payload), self.loop)
        try:
            future.result(timeout=15)
        except (concurrent.futures.TimeoutError, discord.DiscordException, OSError):
            future.cancel()
            raise OSError("Discord delivery failed or is uncertain") from None
