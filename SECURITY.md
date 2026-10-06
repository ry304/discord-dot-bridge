# Security and privacy

Experimental single-owner software. Live platform integration and production
deployment remain unverified. Do not expose the loopback listener directly.

The trusted boundaries are the owner Discord account, registered bot, configured
OAuth issuer/subject, validated callback receiver, host filesystem and bridge process.
A stolen owner account or OAuth token can defeat the allowlist. Incoming text is
untrusted; the dot must retain its ordinary action permissions and confirmation rules.

The MCP HTTP boundary validates OAuth before any dispatch; its internal bearer is
an in-process marker, not an external authentication mechanism. JWT verification
requires RS256 and exact issuer, audience, subject and scope. Public keys come from
an operator-managed JWKS file; token-supplied key URLs are never fetched. Tokens
must expire within one hour of issuance. Subscriptions cannot outlive the granting
token. Revocation through the protected enable file is checked on every request,
ingest and outbox pass. An in-flight request cannot be recalled. Upstream IdP
revocation is not introspected: use short token lifetimes or disable the bridge.

Callback URLs require explicit hosts and public addresses. The transport connects
directly to a validated IP and verifies TLS against the original hostname. It does
not follow redirects, consult proxy environment variables or forward OAuth tokens.
DNS lookup latency is still bounded by the OS resolver, not a separate watchdog.
Connection/body timeouts and response-size limits apply after resolution.

One callback avoids broadcasting owner messages across dots. The reply tool cannot
choose an arbitrary destination; it rechecks channel membership through Discord.
Mentions are disabled. Persistent reservation suppresses duplicate tool calls. A
crash/timeout may sacrifice delivery to prevent double sends; never blindly reset
an `unknown` reply. SDK rate limiting does not imply a guarantee of delivery.

SQLite holds accepted text, routing IDs and callback signing keys in plaintext.
Use a private directory, restricted service identity, encrypted host storage and
protected backups for live use. Windows requires equivalent explicit ACLs. There
is no automatic purge; storage stops at 1000 records. Define retention and an
operator-reviewed archival/purge procedure before sustained use. Do not run multiple
workers or share this database between owners. File protection and backup recovery
must be validated on the actual host.

The dot's explicit reply is copied to Discord. There is no broad context-export
tool, but code cannot guarantee the model never includes private information.
Configure the dot to send only the intended reply and retain normal permission checks.

Tests use synthetic identities and ephemeral signing keys, with external egress
blocked. Never put credentials, real conversations, database files or callback
URLs in public issues. Report sensitive findings privately through GitHub's private
reporting feature if enabled; otherwise request a private contact without disclosing
the exploit or private data publicly.
