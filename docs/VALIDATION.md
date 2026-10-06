# Validation evidence

Local Windows/Python 3.12.10 checks on 2026-10-06:

**Passed: 31 core/config/scope tests, 27 local adapter/command/discovery tests, and the synthetic demo.**

- Core/security/config tests exercise authentication, owner/DM filtering, persistent
  subscriptions, expiry/rotation, signatures, callback policy, dedup/replay, bounded
  retries, reply uncertainty, schema validation and configuration without side effects.
- Local adapter tests run an actual HTTP MCP server and mock WebSocket Gateway,
  mock Discord REST service and callback receiver. They use real discord.py, PyJWT,
  Standard Webhooks and the production transport/actor adapters.
- End-to-end local path: OAuth-authenticated discovery -> signed callback challenge
  -> SDK Gateway MESSAGE_CREATE -> durable event -> verified callback -> OAuth reply
  call -> SDK Discord REST message. Repeating the reply sends only one message.
- Additional local checks cover Gateway resume/dedup, JWT claims/signatures/algorithm,
  persistent disable state, modern metadata/header errors, Host/Origin and body limits,
  base64 tool-name headers, TLS destination/SNI contract and redirect rejection.
- Command checks cover user-install/DM-only registration metadata, owner/channel
  rejection, private status, rate limiting, durable disconnect and honest failure
  reporting. Metadata-only setup rejects all MCP POSTs even with bearer headers.
- Guild mention checks reject other guilds/channels/users, DMs, threads, bot echoes
  and missing mentions. They check scope-bound database reuse, event names, fixed
  reply destinations, fresh SDK channel resolution, nonprivileged intents and
  ephemeral guild command responses. Guild adapter checks use typed SDK mocks;
  actual Discord guild delivery/installation is still unverified.
- Authenticated catalog bootstrap checks verify real synthetic JWTs, reject wrong
  owner/audience/issuer/scope/expiry, enforce immediate disable, and refuse all
  subscriptions/replies even for the authenticated owner. No state files or
  delivery transport are created by that mode.

Reproduce with `python -m tests`, `python -m integration`, `python -m bridge demo`.
The first suite forbids sockets/DNS. The integration runner allows only loopback.
All identities and content are synthetic; test RSA keys are ephemeral in memory.

Limitations: mock callback HTTP substitutes for external TLS in integration tests;
the real TLS connection has a socket/SNI unit test, not a live certificate test.
These tests do not contact a real Discord bot, OAuth provider, ChatGPT account/dot or callback.
Live platform compatibility remains unverified. Docker staging was built and
tested on Linux; a metadata-only container returned 401 for MCP POSTs and bound
only to loopback, with non-root/read-only/capability/resource limits. This does
not establish OAuth, Discord or ChatGPT connectivity. The inactive CI template includes image build and
network-disabled tests; it has not run. Installing it requires GitHub workflow
permission, which the publishing credential did not have.
