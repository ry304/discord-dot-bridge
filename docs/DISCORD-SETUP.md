# Installable Discord app: private first release

Implemented commands: `/setup`, `/status`, `/disconnect`. These commands accept
no arguments or credentials. By default they are global commands restricted to
User Install and the bot's one-to-one DM. Optional guild mode is described below.
The configured owner and destination are checked again at execution. Responses are
ephemeral and mentions are disabled. Setup provides instructions only; no browser
account linking or ChatGPT grant is silently created.

## Operator prerequisites

1. Create a dedicated application at <https://discord.com/developers/applications>.
   Record the application ID and bot user ID. Keep all privileged intents off.
2. In Installation, enable User Install with `applications.commands`, using the
   Discord-provided install link. No server installation or guild permissions
   are required for these commands. Discord's tutorial says Add to my apps lets
   the user open a DM with the app. Never request Administrator or member access.
   Leave Interactions Endpoint URL empty: this runtime receives interactions over
   the official Gateway, not an independently configured HTTP interaction endpoint.
3. Complete the bot token handoff outside chat into a private service-readable
   file, mode 0600 on Linux, directory 0700. Do not use a personal Discord token.
   A self-hosting operator needs their own application/token; users of a future
   hosted service would not need to supply individual bot tokens.
4. Complete OAuth provider configuration and the MCP endpoint. Follow LIVE-PLAN.md;
   browser login, consent and existing-dot event subscription remain necessary.
5. Start live service with `--enable-network --register-commands` once to register
   this dedicated application's three commands. This replaces that application's
   global command set; do not use an unrelated/shared application. Subsequent
   starts can omit `--register-commands` unless the commands changed.

User installation is not proof of free-form Gateway message delivery. The present
message adapter still accepts only ordinary owner DMs. Verify one actual DM and
dot reply before claiming success. If the platform does not deliver ordinary DMs
for a user-only installation, evaluate a separate `/ask` interaction adapter or
an explicitly approved private test-server bot install. Neither fallback is
silently enabled. `/ask` is not implemented in this release.

## Disconnect behavior

For command onboarding before OAuth is ready, `python -m bridge.setup_bot
--config /private/setup.json --enable-network --register-commands` runs commands
only. The private JSON contains `owner_discord_id`, `bot_discord_id`, `resource`
and `discord_bot_token_file` (absolute path); no OAuth placeholders are needed.
This mode requests zero message intents (guild mode adds only Guilds for SDK
channel resolution) and ignores all ordinary messages. It
cannot forward DMs, subscribe, deliver events, or open an MCP listener. Run only
one bot runtime at a time; stop onboarding before activating the live runtime.

In onboarding mode `/disconnect` is an idempotent acknowledgement that the bridge
is already disconnected. No grant exists to revoke in that process.

`/disconnect` writes a durable disabled flag before cancelling local subscriptions
and delivery records through the serialized core. It retains replay/reply records
to prevent duplicate sends. An already running operation may finish. It does not
revoke the IdP grant or delete the ChatGPT-side connection; the user does that in
the respective UI. Re-enablement requires an operator and a new subscription.
The live runtime refuses to restart while disabled; after such a restart commands
are offline until the operator re-enables it. The enable file must be writable by
the service, in its private state directory.

## Optional private guild text channel

Set these additional fields in private setup/live configuration:

```json
{
  "discord_mode": "guild_mentions",
  "discord_guild_id": "555555555555555555",
  "discord_channel_id": "333333333333333333"
}
```

These are synthetic IDs; replace them privately. Both exact IDs are mandatory.
Only one mode is active: guild mode rejects DMs, threads, other channels and other
guilds. The configured owner remains the only accepted author. Send an explicit
`@bot` mention with each request; plain messages are ignored. No Message Content,
Members or Presence privileged intents are needed. Accepting every plain guild
message would need a separately reviewed mode and privileged Message Content.

Before activation, enable Guild Install for the dedicated application, with
`bot` and `applications.commands`. The user must authorize installation into the
intended server. Permissions: View Channel, Send Messages and Read Message History
(68608 combined). History permission is required by Discord for reply references;
this bridge does not crawl history. Never grant Administrator. Deny View Channel
to everyone and unrelated roles; allow only owner and bot in the chosen channel.
Server administrators can still access private channels. Replies are ordinary
channel messages visible to everyone with access; setup/status/disconnect remain
ephemeral. Verify actual permissions before using existing-dot context there.

After approved configuration/install, the operator re-registers commands using
`--register-commands`. In this mode commands declare Guild Install/Guild context
and still enforce exact owner, guild and channel at runtime. Global registration
may expose command names in other installed guilds, but execution is rejected.
Do not run both onboarding and live bots simultaneously.

Use a fresh state database when changing destination/mode; the old database is
preserved and cannot be rebound. Subscribe the existing dot to
`discord.channel.mentioned` in guild mode (`discord.dm.created` in DM mode).
The reply tool remains `discord_reply`, with destination fixed by the accepted
message. No command or model argument can choose another destination.

Onboarding emits only these positive startup milestones: `discord.login_verified`,
`discord.commands_registered count=3`, and `discord.gateway_ready identity_verified=true`.
No tokens, account IDs, names or message contents are logged. A running container
alone is not proof of readiness. A real command response and dot round trip remain
required acceptance checks.

## Product direction

Recommended first release: one self-hosted bridge and one owner, with a guided
Discord setup flow and provider-independent OAuth configuration. A central
multi-user hosted bot is a separate product: it needs per-owner identity binding,
storage and callback isolation, quotas, abuse handling, retention controls and
operating support. This release must not be used as that service.

Sources:
- <https://docs.discord.com/developers/tutorials/developing-a-user-installable-app>
- <https://docs.discord.com/developers/interactions/application-commands>
- <https://docs.discord.com/developers/events/gateway>
- <https://docs.discord.com/developers/resources/message>
- <https://developers.openai.com/plugins/build/mcp-events>
