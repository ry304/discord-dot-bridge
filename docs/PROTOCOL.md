# Compatibility baseline

Reviewed 2026-10-06. This is a version-specific implementation, not a claim of
universal MCP compatibility or platform certification.

Primary sources:

- [OpenAI MCP Events](https://developers.openai.com/plugins/build/mcp-events).
- [MCP 2026-07-28](https://modelcontextprotocol.io/specification/2026-07-28),
  [HTTP binding](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/streamable-http),
  [base metadata](https://modelcontextprotocol.io/specification/2026-07-28/basic),
  [tools](https://modelcontextprotocol.io/specification/2026-07-28/server/tools).
- [Events draft baseline](https://github.com/modelcontextprotocol/experimental-ext-triggers-events/blob/6682596d65eec778fe0b8b1f43b4e89d2fe2c546/docs/design-sketch-proposal.md).
- [OAuth integration](https://developers.openai.com/plugins/build/auth).
- [Discord Gateway](https://docs.discord.com/developers/events/gateway) and
  [message API](https://docs.discord.com/developers/resources/message#create-message).

## Implemented profile

The HTTP adapter accepts one JSON-RPC request per POST, validates Origin/Host,
required version/client-capability metadata and mirrored version/method/name
headers, and returns JSON with `resultType: complete`. It implements discovery,
tool list/call and event list/subscribe/unsubscribe. Header mismatches, unsupported
versions and unknown methods have distinct protocol errors/statuses. Base64 name
headers are decoded before comparison. GET/DELETE sessions and legacy initialization
are not supported. Optional SSE, resource, prompt and client-interaction capabilities
are not advertised. The adapter itself implements this narrow binding; it does not
pretend an older MCP SDK supplies the new metadata or draft Events support.

ChatGPT's documented event profile uses webhook delivery and verification. The
bridge follows that profile rather than the draft's additional polling, streaming,
gap or terminated controls. Event data stays inside `data`; event IDs survive retry;
the platform supplies the subscription signing key. The official Standard Webhooks
Python library signs the exact serialized bytes and verifies deliveries in tests.
Callback verification uses a signed `verification` control body and constant-time
challenge comparison. The single principal is issuer plus subject, persistently
bound to the database and incorporated into deterministic subscription identity.

The draft contains optional features and SDK pseudocode, not a deployed ChatGPT
SDK contract. Its example result omissions are normalized to MCP 2.0 complete
results by the HTTP adapter. The OpenAI guide takes precedence for supported event
delivery modes. The events extension error `-32015` is retained as documented.

## Libraries and limits

`discord.py` is a maintained community SDK implementing the official bot API, not
an official Discord SDK. Its pinned version implements Gateway handshake,
heartbeat, resume/reconnect and REST rate handling. The integration tests drive
its real parser and REST client through local mock endpoints. Nonce enforcement
is checked against the pinned SDK's outgoing payload.

OAuth is a real resource-server implementation using PyJWT and cryptography.
An external IdP must provide authorization-code plus PKCE, compatible client
registration/discovery, refresh behavior and audience/resource-bound RS256 access
tokens. The project does not implement an authorization server or pretend a
static API key works in ChatGPT. Operator-managed JWKS and the local disable file
are explicit parts of this initial authentication profile.

The network unit tests verify pinned destination/SNI and no redirect follow. Local
integration substitutes loopback HTTP for external TLS; certificate-chain behavior
still needs an authorized staging test. A successful local test does not establish
the account's plugin access, callback acceptance, model behavior or live conformance.
