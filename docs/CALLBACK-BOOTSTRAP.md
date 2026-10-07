# Review the platform callback before live activation

ChatGPT supplies its callback URL and signing secret in `events/subscribe`; the
official guide does not publish a fixed production hostname. Do not guess a host,
copy its example URL, broaden to wildcard domains, or treat an arbitrary bearer
holder's URL as trusted. The bridge still requires the exact verified owner.

An optional `bridge.callback_probe` process extends authenticated discovery for
ten minutes after startup. For the sole configured event and exact owner filter,
it validates HTTPS syntax and signing-secret format, writes only the lower-case
DNS hostname to a single new mode-0600 file, and ALWAYS returns an error. There is
no subscription or signing-secret storage, DNS request, verification call, event
delivery, Discord connection or reply. Full URL paths, queries and secrets are
never logged or saved. Existing hostname files are never overwritten. Wrong
owner/event, invalid tokens or malformed destinations cannot populate the file.
The authenticated `discord_bridge_status` read-only action reports only setup
booleans, never identities, destinations, messages or secrets. Refresh the plugin
catalog and call it successfully before attempting platform event setup.
Use `--status-only` while waiting for the platform catalog: capture stays disabled
regardless of elapsed time. The first authenticated catalog response emits only
`mcp.status_catalog status_included=true`; it contains no request or identity data.

Run with `python -m bridge.callback_probe --config /private/discovery.json
--scope-config /private/setup.guild.json --capture-dir /probe`. Mount only the
specific config/public-key/owner files read-only, plus a dedicated empty private
capture directory writable by the process. Do not mount the bot token. Preserve
the existing diagnostic implementation when building the probe overlay.

After the operator stages and activates this limited process, request ONE test
subscription from the same existing dot using `discord.channel.mentioned` and
the configured owner ID. Approve any platform task/connection action in that dot
as required. Expect failure: do not claim an active automation or silently retry.
The operator reviews only `callback.hostname`, verifies it belongs to the platform
and matches this user-initiated attempt, then explicitly approves that exact host.
The file is a candidate destination, not an automatic allowlist or proof of safety.

`scripts/prepare_live.py --root /PRIVATE/DEPLOYMENT --approved-callback-host HOST`
requires the reviewed host to match the captured file. It copies existing private
owner/guild/channel and OAuth bindings locally into mode-0600 live config and
creates a DISABLED enable file. It does not read a bot token or start a service.
It refuses to overwrite existing files. Review and activate separately; preserve
old state. Use only one Discord runtime. Refresh the connected plugin after live
activation, then request a fresh same-dot subscription and verify its signed
challenge before an owner mention/reply test. DNS/IP/TLS checks still apply on
every outgoing request, even after hostname approval.

Source: <https://developers.openai.com/plugins/build/mcp-events>

## Catalog refresh diagnosis

`server/discover` advertises the tools capability; individual definitions belong
in `tools/list`, not the OAuth resource metadata. Both discovery and tool-list
responses include MCP 2 cache hints `ttlMs: 0` and `cacheScope: "private"`.
HTTP `Cache-Control: no-store` alone does not replace these protocol fields.
See <https://modelcontextprotocol.io/specification/2026-07-28/server/utilities/caching>.

OpenAI's documented refresh procedure ends with testing in a new conversation:
<https://developers.openai.com/plugins/deploy/connect-chatgpt#refresh-metadata>.
If a refreshed catalog is confirmed at the server but an existing conversation
still exposes old tools, use a fresh conversation only to diagnose tool visibility
and read status. Do not create a replacement assistant or move the event subscription
away from the intended existing dot. A successful diagnostic in another conversation
does not itself establish that the intended dot's active tool context has updated.
