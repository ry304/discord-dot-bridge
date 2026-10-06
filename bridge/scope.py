"""One explicitly configured Discord destination; guild mode is opt-in."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Scope:
    mode: str = "dm"
    guild_id: str | None = None
    channel_id: str | None = None

    def __post_init__(self):
        if self.mode == "dm":
            if self.guild_id is not None or self.channel_id is not None:
                raise ValueError("DM mode cannot include guild or channel IDs")
        elif self.mode == "guild_mentions":
            for value in (self.guild_id, self.channel_id):
                if not isinstance(value, str) or not value.isascii() or not value.isdigit() or not 17 <= len(value) <= 20:
                    raise ValueError("Guild mention mode requires exact guild and text channel IDs")
        else:
            raise ValueError("Unsupported Discord mode")

    @property
    def event(self):
        return "discord.channel.mentioned" if self.mode == "guild_mentions" else "discord.dm.created"

    @property
    def binding(self):
        return f"{self.mode}:{self.guild_id or ''}:{self.channel_id or ''}"

    def accepts(self, channel_type, channel_id, guild_id):
        if self.mode == "dm":
            return channel_type == 1 and guild_id is None
        return channel_type == 0 and str(channel_id) == self.channel_id and str(guild_id) == self.guild_id

    def mentions_bot(self, content, mentions, bot_id):
        return (isinstance(content, str) and isinstance(mentions, list)
                and any(isinstance(m, dict) and m.get("id") == bot_id for m in mentions)
                and any(tag in content for tag in (f"<@{bot_id}>", f"<@!{bot_id}>")))
