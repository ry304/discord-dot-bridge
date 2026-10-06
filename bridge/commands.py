"""Owner-only Discord setup commands. No credentials or account grants in Discord."""
import time
import discord
from discord import app_commands


class OwnerCommands:
    def __init__(self, bot, control, resource, clock=time.monotonic):
        self.bot, self.control, self.resource, self.clock = bot, control, resource, clock
        self.last_request = float("-inf")
        self.tree = app_commands.CommandTree(bot,
            allowed_contexts=app_commands.AppCommandContext(guild=False, dm_channel=True, private_channel=False),
            allowed_installs=app_commands.AppInstallationType(guild=False, user=True))

        @self.tree.command(name="setup", description="Show the private bridge setup steps; never enter credentials here")
        async def setup(interaction: discord.Interaction):
            await self.handle(interaction, "setup")

        @self.tree.command(name="status", description="Show bridge and subscription status without exposing private data")
        async def status(interaction: discord.Interaction):
            await self.handle(interaction, "status")

        @self.tree.command(name="disconnect", description="Disable this bridge and cancel its local event subscriptions")
        async def disconnect(interaction: discord.Interaction):
            await self.handle(interaction, "disconnect")

    async def handle(self, interaction, action):
        if (str(interaction.user.id) != self.bot.owner_id or interaction.user.bot
                or interaction.guild_id is not None
                or not isinstance(interaction.channel, discord.DMChannel)
                or not self.bot.user or str(self.bot.user.id) != self.bot.bot_id):
            await interaction.response.send_message("This command is available only to the configured owner in the app DM.", ephemeral=True)
            return
        now = self.clock()
        if now - self.last_request < 2:
            await interaction.response.send_message("Please wait two seconds before another command.", ephemeral=True)
            return
        self.last_request = now
        # Acknowledge before any queued database operation. All results stay private.
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            if action == "setup":
                content = ("This is a private, single-owner bridge.\n"
                    "1. The operator must finish OAuth and secure bot setup first. Never paste tokens or passwords here.\n"
                    "2. In ChatGPT Plugins, add the MCP connection using this server URL:\n"
                    f"{self.resource}\n"
                    "3. Complete login and consent in the browser. In your existing dot, request a subscription to discord.dm.created and replies through discord_reply.\n"
                    "4. Use /status, then send one test DM. Setup is complete only after a real dot reply.\n"
                    "After /disconnect, operator re-enablement and a new dot subscription are required.")
            elif action == "status":
                status = await self.control.status()
                content = (f"Bridge authorization: {'enabled' if status['enabled'] else 'disabled'}\n"
                    f"Active subscriptions: {status['subscriptions']}\n"
                    f"Pending events: {status['pending']}\n"
                    "These are local checks; they do not prove that your dot can receive or reply. No private messages or credentials are shown.")
            elif action == "disconnect":
                await self.control.disconnect()
                content = ("Bridge disabled; local subscriptions and queued deliveries cancelled. "
                    "An operation already in progress may have completed. Remove the subscription/connection in ChatGPT and revoke its OAuth grant there if desired. "
                    "Reconnection requires operator re-enablement; /setup cannot grant access.")
            else:
                content = "Unknown command."
        except Exception:
            content = "The operation could not be confirmed. Contact the operator; no credentials or diagnostic details are shown here."
        await interaction.followup.send(content, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())
