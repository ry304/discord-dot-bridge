"""Live wiring. Not invoked by imports, tests, demo, or configuration validation."""
import asyncio
import contextlib
import os
from pathlib import Path
from urllib.parse import urlsplit
from aiohttp import web
from .auth import OAuthVerifier
from .config import read_secret
from .core import Bridge
from .discord_adapter import DiscordBot, DiscordSender
from .http_server import INTERNAL, SerialCore, make_app
from .network import HTTPSWebhook
from .commands import OwnerCommands


async def serve(config, *, register_commands=False):
    token = read_secret(config.discord_bot_token_file)
    verifier = OAuthVerifier(issuer=config.oauth_issuer, resource=config.resource,
                             subject=config.oauth_subject, jwks_file=config.jwks_file,
                             enabled_file=config.enabled_file)
    if not verifier.enabled():
        raise ValueError("Bridge is disabled; protected enable file required")
    state = Path(config.state_path)
    state.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name != "nt":
        os.umask(0o077)
        if state.parent.stat().st_mode & 0o077:
            raise ValueError("State directory must be private to its owner")
    actor = None

    async def ingest(dispatch, **metadata):
        return await actor.ingest(dispatch, **metadata)

    bot = DiscordBot(config.owner_discord_id, config.bot_discord_id, ingest, scope=config.scope)
    loop = asyncio.get_running_loop()
    sender = DiscordSender(bot, loop)

    def factory():
        core = Bridge(state, owner_id=config.owner_discord_id, bot_id=config.bot_discord_id,
                      bearer=INTERNAL, callback_hosts=config.callback_hosts,
                      webhook=HTTPSWebhook(config.callback_hosts), discord=sender, scope=config.scope)
        core.bind_principal(config.oauth_issuer + "|" + config.oauth_subject)
        return core

    actor = SerialCore(factory, verifier)
    commands = OwnerCommands(bot, actor, config.resource)
    app = make_app(actor, verifier, allowed_hosts=[urlsplit(config.resource).netloc,
                   f"127.0.0.1:{config.listen_port}"], allowed_origins=config.allowed_origins or ())
    runner = web.AppRunner(app, access_log=None, shutdown_timeout=20)
    pump_task = None
    gateway_task = None

    async def pump():
        while True:
            await actor.pump()
            await asyncio.sleep(1)

    try:
        async with bot:
            await bot.login(token)
            if not bot.user or str(bot.user.id) != config.bot_discord_id or not bot.user.bot:
                raise ValueError("Token does not belong to configured bot")
            if register_commands:
                # This dedicated application's three global commands are replaced only
                # when the operator explicitly requests registration.
                await commands.tree.sync()
            await runner.setup()
            await web.TCPSite(runner, config.listen_host, config.listen_port).start()
            pump_task = asyncio.create_task(pump())
            gateway_task = asyncio.create_task(bot.connect(reconnect=True))
            done, _ = await asyncio.wait([pump_task, gateway_task], return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
    finally:
        await runner.cleanup()
        if pump_task:
            pump_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await pump_task
        await bot.close()
        if gateway_task:
            gateway_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await gateway_task
        await actor.close()
