# Installable Discord app: private first release

Implemented commands: `/setup`, `/status`, `/disconnect`. These commands accept
no arguments or credentials. They are global commands restricted to User Install
and the bot's one-to-one DM. The configured owner is checked again at execution;
guilds, other DMs, group DMs, bots and non-owners are rejected. Responses are
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
This mode requests zero message intents and ignores all ordinary messages. It
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

## Product direction

Recommended first release: one self-hosted bridge and one owner, with a guided
Discord setup flow and provider-independent OAuth configuration. A central
multi-user hosted bot is a separate product: it needs per-owner identity binding,
storage and callback isolation, quotas, abuse handling, retention controls and
operating support. This release must not be used as that service.

Sources:
- <https://docs.discord.com/developers/tutorials/developing-a-user-installable-app>
- <https://docs.discord.com/developers/interactions/application-commands>
- <https://developers.openai.com/plugins/build/mcp-events>
