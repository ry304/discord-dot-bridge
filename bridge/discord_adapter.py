"""Official Discord bot API through the maintained discord.py SDK (not a selfbot)."""
import asyncio
import concurrent.futures
import discord
from .core import iso


class DiscordBot(discord.Client):
    def __init__(self, owner_id, bot_id, submit_message):
        intents = discord.Intents.none()
        intents.dm_messages = True
        super().__init__(intents=intents, max_messages=None,
                         allowed_mentions=discord.AllowedMentions.none(),
                         max_ratelimit_timeout=10.0)
        self.owner_id, self.bot_id = str(owner_id), str(bot_id)
        self.submit_message = submit_message
        self.failed_messages = 0

    async def on_ready(self):
        if not self.user or str(self.user.id) != self.bot_id or not self.user.bot:
            await self.close()
            raise RuntimeError("Configured bot identity mismatch")

    async def on_message(self, message):
        if (not self.user or str(self.user.id) != self.bot_id
                or not isinstance(message.channel, discord.DMChannel)
                or str(message.author.id) != self.owner_id or message.author.bot
                or message.author.system
                or message.guild is not None):
            return
        try:
            channel = await self.fetch_channel(message.channel.id)
        except discord.DiscordException:
            self.failed_messages += 1
            return
        if not isinstance(channel, discord.DMChannel) or not channel.recipient or str(channel.recipient.id) != self.owner_id:
            return
        d = {"id": str(message.id), "channel_id": str(message.channel.id),
             "author": {"id": str(message.author.id), "bot": message.author.bot,
                        "system": message.author.system},
             "content": message.content, "timestamp": iso(message.created_at.timestamp()),
             "type": message.type.value, "webhook_id": message.webhook_id}
        try:
            await self.submit_message({"op": 0, "t": "MESSAGE_CREATE", "d": d},
                                      channel_type=1, recipient_id=self.owner_id)
        except Exception:
            # No raw message, token, callback URL or request data in logs.
            self.failed_messages += 1

    async def send_owner_reply(self, channel_id, owner_id, payload):
        if str(owner_id) != self.owner_id or not self.user or str(self.user.id) != self.bot_id:
            raise OSError("Bot identity unavailable")
        channel = await self.fetch_channel(int(channel_id))
        if not isinstance(channel, discord.DMChannel) or not channel.recipient or str(channel.recipient.id) != self.owner_id:
            raise OSError("Reply destination is not the owner DM")
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
