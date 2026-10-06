# Private setup and live acceptance (not yet executed)

## 1. Confirm platform access

Use the intended **existing dot**. Check that your workspace permits custom MCP
plugins and event-triggered tasks. The documented connection path is ChatGPT
Plugins -> plus -> Add custom MCP server -> enter connection details and
authentication -> Create as a plugin -> inspect/install it. See the
[official connection guide](https://developers.openai.com/plugins/deploy/connect-chatgpt).
An HTTPS endpoint or supported Secure MCP Tunnel is required for the host to reach
the server. Neither is provisioned by this repository or the local test command.

After connection, refresh/rescan the plugin and confirm `discord.dm.created`
(or `discord.channel.mentioned` in guild mention mode) and
`discord_reply` appear. Ask the existing dot to subscribe for the configured owner
ID and reply using the tool. Watch for an actual `events/subscribe` and successful
callback verification. If any platform capability is unavailable, stop at that
blocker; do not substitute scraping or a separate model API assistant.

## 2. Prepare the Discord bot, only after setup approval

1. In the Discord Developer Portal, create/select an application you control and
   its bot. Record the bot's numeric user ID. Use an official bot token, never your
   personal Discord token. Keep the bot private during the proof of concept.
2. Leave privileged Message Content, Members and Presence intents off. Default mode
   requests only DM message events. For the explicitly approved private guild
   channel option, follow [Discord setup](DISCORD-SETUP.md): exact guild/channel,
   owner allowlist, explicit mentions and minimum permissions. Never grant Administrator.
3. Store the bot token using a secure secret-manager/file handoff. On Linux use a
   service-owned file mode 0600; on Windows restrict its ACL to the service owner.
   Mount/reference the file, never put the value in chat, Git, commands or config.
4. Put the owner's numeric Discord ID and bot ID only in ignored private config.
   A username is not an authorization identifier. Example IDs in this repo are fake.

## 3. Configure OAuth with an established identity provider

Choose a provider supporting the current MCP OAuth flow: discovery, authorization
code with PKCE, appropriate client identification (CIMD, DCR or predefined client),
and the `resource` audience. See [OpenAI authentication](https://developers.openai.com/plugins/build/auth).
Do not create a grant merely to run tests.
An optional provider-specific path is documented in [Auth0 setup](AUTH0-SETUP.md).

Configure the canonical resource `https://YOUR_APPROVED_HOST/mcp`, scope
`discord:bridge`, exact issuer and the owner's verified OAuth subject. Issue RS256
access tokens with a `kid`, `iss`, `aud`, `sub`, `iat`, `exp`, and scope; lifespan
at most one hour. Copy the provider's **public** JWKS into the configured protected
file through a verified channel and rotate it when the IdP changes keys. Tokens
are validated on every action; callback subscription grants are capped at expiry.
Configure refresh tokens in the IdP/client so ChatGPT can renew authorization.

The resource metadata endpoints and 401 challenge are implemented. Authorization,
login/consent, PKCE, token issuance and refresh remain the IdP's responsibility.
There is no custom static API-key alternative for ChatGPT. Verify the provider's
end-to-end flow in staging before assuming it is compatible.

## 4. Approve and configure the host

Coordinate host resources, HTTPS/proxy, access controls, backup and exposure with
the infrastructure owner. No host, DNS, tunnel or firewall changes are included.
The service binds to loopback only; the approved HTTPS proxy must share access to
that listener and preserve the public Host header. For containers, design that
network arrangement explicitly. Do not repurpose the network-disabled test Compose
file as a production deployment without review.

Create private state storage and an operator-controlled enable file containing
`enabled`. Choose retention and capacity handling before sustained operation.
Replace all config placeholders, including callback host names learned from the
actual supported platform integration; do not guess or wildcard them. Validate:

```sh
python -m bridge validate-config --config config.local.json
```

After authorization, start with `serve --config config.local.json --enable-network`.
The runtime verifies the bot identity before opening its loopback MCP listener.
Disable by changing/removing the enable file; unsubscribe in the dot as well.
An in-flight operation may still complete.

## 5. Instruction for the existing dot

> Subscribe to this private bridge's discord.dm.created event for my configured
> owner ID. Treat its text as my request, subject to your normal permissions.
> Reply through discord_reply using the event's message_id. Send only the intended
> Discord reply, not credentials, hidden instructions or unrelated memory. Ask
> before sensitive external actions. If delivery is unknown, report that here
> instead of retrying the reply.

Keep this as a user instruction to the dot, not instructions embedded in event data.
In guild mention mode replace the event name with `discord.channel.mentioned` and
verify channel privacy first; only explicit mentions are accepted.

## Live acceptance checklist

Record sanitized outcomes, never tokens, callback URLs or private text:

- Actual account installs and authenticates the custom plugin; existing dot
  discovers the event/tool and subscribes successfully.
- Callback verification and a real owner message yield one reply in the original
  destination (DM or configured private guild channel).
- Other authors, destinations, group messages, bot echoes and stale/duplicate
  inputs are blocked; guild mode additionally ignores messages without bot mentions.
- Refresh, key rotation, restart, expiry, unsubscribe and local revocation work.
- Real invalid/stale webhook signatures are rejected by the platform.
- Real TLS, DNS rebinding, redirect and callback-host controls pass staging checks.
- Gateway disconnect/resume, rate limits, timeout ambiguity, queue capacity and
  failed delivery handling behave as documented. Verify batching and out-of-order events.
- No unrelated dot, chat, guild or user receives context. Verify file/backup protection.

Only after these pass should the deployment be described as working with the account.
