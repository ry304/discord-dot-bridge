# Metadata-only deployment staging

Before Discord credentials or OAuth consent, run the separate setup entry point:

```sh
python -m bridge.setup_server --resource https://bridge.example.test/mcp --issuer https://id.example.test/application/o/bridge/
```

It binds only to `127.0.0.1:8765`, serves protected-resource metadata, and rejects
every MCP POST with HTTP 401, including requests carrying bearer tokens. It does
not load credentials, create bridge state, instantiate a Discord client, or send
events. No plugin connection or subscription can succeed in this mode. A health
check verifies metadata availability only, not bridge functionality.

On Linux Docker, a host-network container can share the host cloudflared
loopback listener. Use a non-root UID, read-only filesystem, all capabilities
dropped, no-new-privileges, bounded memory/PIDs/CPU and log rotation. No Docker
socket, host directories or credentials are needed in setup mode. Host networking
shares the host network namespace; the application still binds strictly to loopback.

Publish only `/mcp` and the two protected-resource metadata paths through the
approved HTTPS proxy. Preserve Host, do not enable edge caching, and preserve
existing tunnel routes. Prepare the OAuth issuer before advertising its metadata.
Rollback by stopping only this Compose project and removing only its new route.

Switch to the live runtime only after secure bot-token handoff, verified owner and
bot IDs, OAuth claims/JWKS configuration, exact callback hosts, private state and
explicit user consent. See LIVE-PLAN.md. Never report setup mode as a live bridge.
