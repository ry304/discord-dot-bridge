# Validation evidence

Local Windows/Python 3.12.10 checks on 2026-10-06:

**Passed: 26 core/config tests, 9 local adapter tests, and the synthetic demo.**

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

Reproduce with `python -m tests`, `python -m integration`, `python -m bridge demo`.
The first suite forbids sockets/DNS. The integration runner allows only loopback.
All identities and content are synthetic; test RSA keys are ephemeral in memory.

Limitations: mock callback HTTP substitutes for external TLS in integration tests;
the real TLS connection has a socket/SNI unit test, not a live certificate test.
No real Discord bot, OAuth provider, ChatGPT account/dot or callback was contacted.
Live platform compatibility and setup permissions remain unverified. Local Docker
Compose validation passed, but local image execution was unavailable because the
Docker daemon was not running. The inactive CI template includes image build and
network-disabled tests; it has not run. Installing it requires GitHub workflow
permission, which the publishing credential did not have.
