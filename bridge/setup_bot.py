"""Discord onboarding commands only: no MCP listener, DM forwarding or event delivery."""
import argparse
import asyncio
import json
import os
from pathlib import Path
from urllib.parse import urlsplit
from .commands import OwnerCommands
from .config import read_secret
from .discord_adapter import DiscordBot
from .scope import Scope


def load_config(path):
    file = Path(path)
    if file.is_symlink() or file.stat().st_size > 16384:
        raise ValueError("Invalid private setup configuration")
    if os.name != "nt" and file.stat().st_mode & 0o077:
        raise ValueError("Setup configuration must be private")
    data = json.loads(file.read_text())
    required = {"owner_discord_id", "bot_discord_id", "resource", "discord_bot_token_file"}
    optional = {"discord_mode", "discord_guild_id", "discord_channel_id"}
    if not isinstance(data, dict) or not required <= set(data) or set(data) - required - optional:
        raise ValueError("Unexpected setup configuration")
    Scope(data.get("discord_mode", "dm"), data.get("discord_guild_id"), data.get("discord_channel_id"))
    for name in ("owner_discord_id", "bot_discord_id"):
        value = data[name]
        if not isinstance(value, str) or not value.isascii() or not value.isdigit() or not 17 <= len(value) <= 20:
            raise ValueError("Numeric Discord ID required")
    if data["owner_discord_id"] == data["bot_discord_id"]:
        raise ValueError("Owner and bot must differ")
    url = urlsplit(data["resource"])
    if (url.scheme != "https" or not url.hostname or url.username or url.password or url.query
            or url.fragment or url.port not in (443, None) or url.path != "/mcp"):
        raise ValueError("Canonical HTTPS MCP resource required")
    if not Path(data["discord_bot_token_file"]).is_absolute():
        raise ValueError("Absolute token file path required")
    return data


class SetupControl:
    onboarding = True

    async def status(self):
        return {"enabled": False, "subscriptions": 0, "pending": 0}

    async def disconnect(self):
        # Already disconnected: this process has no state or event transport.
        return None


async def ignore_message(*args, **kwargs):
    return False


async def run(config, register_commands=False):
    bot = DiscordBot(config["owner_discord_id"], config["bot_discord_id"], ignore_message,
                     receive_messages=False, scope=Scope(config.get("discord_mode", "dm"),
                         config.get("discord_guild_id"), config.get("discord_channel_id")))
    commands = OwnerCommands(bot, SetupControl(), config["resource"])
    async with bot:
        await bot.login(read_secret(config["discord_bot_token_file"]))
        if not bot.user or str(bot.user.id) != config["bot_discord_id"] or not bot.user.bot:
            raise ValueError("Configured bot identity mismatch")
        print("discord.login_verified", flush=True)
        if register_commands:
            registered = await commands.tree.sync()
            print(f"discord.commands_registered count={len(registered)}", flush=True)
        print("discord.gateway_connecting", flush=True)
        await bot.connect(reconnect=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--enable-network", action="store_true")
    parser.add_argument("--register-commands", action="store_true")
    args = parser.parse_args()
    if not args.enable_network:
        parser.error("Explicit --enable-network approval required")
    try:
        asyncio.run(run(load_config(args.config), args.register_commands))
    except KeyboardInterrupt:
        pass
    except Exception:
        parser.exit(1, "Onboarding stopped: verify private setup and connectivity.\n")


if __name__ == "__main__":
    main()
