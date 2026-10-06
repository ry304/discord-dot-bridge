# Auth0 operator checklist

This is a manual setup path for one owner, using a tenant domain and a pre-registered
OAuth client. Public discovery alone does not prove client or API configuration.
Do not put a client secret, access/refresh token, bot token or real deployment IDs
in this repository or a chat. Enter client credentials directly into the trusted
ChatGPT connection settings. The bridge needs public signing keys, not a client secret.

1. In Auth0, create a custom API with identifier exactly equal to your MCP resource,
   for example `https://bridge.example.test/mcp`. Use RS256 and an access-token
   lifetime of at most 3600 seconds. Add permission `discord:bridge`. Configure
   the RFC 9068 token profile when available. Enable offline access only if using
   refresh tokens.
2. Under tenant Advanced settings, enable Resource Parameter Compatibility Profile
   and Include Issuer in Authorization Responses. Confirm current plan availability
   for these settings; a trial account is not proof of long-term free availability.
   Do not upgrade or add a paid custom domain without explicit approval.
3. Register the ChatGPT client as a Regular Web Application following Auth0's manual
   third-party MCP client guide. Enable authorization code with PKCE S256; select
   `client_secret_post` for this manual confidential-client path. Add refresh-token
   grant only when required. Limit user-delegated API access to this client and scope;
   do not enable all third-party applications. Configure the intended user connection.
   Grant checkboxes are under Applications > Applications > the application >
   Settings > Show Advanced Settings (bottom of page) > Grant Types. They may
   already be enabled. Refresh-token issuance also requires `offline_access` in
   the authorization request, in addition to the API's Allow Offline Access setting.
4. Fetch public OIDC discovery over HTTPS and verify issuer, authorization/token
   endpoints, S256 support and RS256 JWKS. Keep the exact issuer spelling including
   trailing slash in bridge configuration and protected-resource metadata. Maintain
   the pinned public JWKS file as the provider rotates keys; stale keys fail closed.
5. Expose the authenticated endpoint through the approved HTTPS route. A metadata-only
   staging server can advertise discovery while denying every MCP POST; it cannot
   complete functional connection testing. Verify HTTPS and 401 behavior first.
   Before asking the user to create a connection that needs authenticated discovery,
   switch to the owner-bound catalog-only process described below. Do not assume
   ChatGPT will save a draft or display a callback before authenticating.
6. The user creates the MCP connection in ChatGPT using the resource URL and manual
   OAuth client settings. Copy the exact redirect URI from that connection's
   management page into Auth0 Allowed Callback URLs before login/consent. Do not
   invent a callback ID or use wildcard callbacks. With valid RFC 9207 issuer
   identification ChatGPT normally uses its stable redirect URI, but the displayed
   connection URI is authoritative. If the UI requires successful authentication
   before showing its management page, inspect its actual OAuth settings/redirect
   rather than bypassing validation or guessing a callback.
7. The owner authenticates and consents in the browser. Configure only that verified
   Auth0 subject in the bridge's private file. A client ID is not a user subject.
   Before live activation verify an access token is for the exact MCP resource,
   signed by the configured issuer, contains `discord:bridge`, has the expected
   owner subject and a bounded expiry. Do this via a secure operator handoff;
   never paste the token into chat or logs.
8. Verify missing/wrong bearer, wrong audience, subject and scope are denied; complete
   an actual existing-dot event subscription and one private Discord round trip.
   Retain the distinction between provider discovery, OAuth success and dot success.

Sources checked 2026-10-06:
- <https://auth0.com/ai/docs/mcp/guides/resource-param-compatibility-profile>
- <https://auth0.com/ai/docs/mcp/guides/registering-your-mcp-client-application/manual-client-registration>
- <https://auth0.com/ai/docs/mcp/get-started/authorization-for-your-mcp-server>
- <https://developers.openai.com/plugins/build/auth>

The hosted provider receives login identity and authentication telemetry. Discord
messages and dot context are not needed for identity-provider configuration.

## Resume a blocked dashboard setup

If Grant Types is not visible, first inspect a screenshot of the application type
and bottom of its Settings page, with secrets concealed. Do not keep repeating
settings lists, guess a different UI path, or enable machine-to-machine credentials
as a substitute for owner login. Leave the metadata-only endpoint closed and the
command-only Discord process unchanged until the account settings are resolved.

- <https://auth0.com/docs/get-started/applications/update-grant-types>
- <https://auth0.com/docs/secure/tokens/refresh-tokens/get-refresh-tokens>

## Authenticated catalog bootstrap without Discord forwarding

`python -m bridge.discovery_server --config /private/discovery.json` serves only
OAuth-verified `server/discover`, `tools/list` and `events/list`. It uses the same
signature, issuer, resource audience, exact owner subject, scope and lifetime
checks as the live service. It refuses `events/subscribe`, `events/unsubscribe`,
`tools/call`, legacy `initialize` and all other operations. It has no bot client,
token mount, database, callback transport or delivery worker. Its catalog clearly
states that actions are disabled. The Discord command-only process can stay up.

Example discovery configuration (all paths are deployment-private):

```json
{
  "resource": "https://bridge.example.test/mcp",
  "oauth_issuer": "https://issuer.example.test/",
  "oauth_subject_file": "/private/owner.subject",
  "jwks_file": "/private/public-jwks.json",
  "enabled_file": "/private/discovery.enabled",
  "discord_mode": "guild_mentions"
}
```

Configuration and subject files require mode 0600, and the enable file must contain
`enabled`. Missing owner identity or a disabled flag prevents startup. No identity
is automatically learned from the first login: that would allow an unintended user
to become the owner.

In Auth0, the operator selects the intended application user under User Management
> Users, verifies the login connection/account and privately copies its full
`user_id`. This is not the application Client ID or the tenant dashboard-admin ID.
An Auth0 dashboard account does not establish an application-user profile. If no
matching user exists, resolve the intended application login/account first; do not
create a user, password, grant or wildcard subject silently.

The owner can run `python3 scripts/set_owner_subject.py /private/owner.subject` in
an interactive terminal to store the value without echoing it or putting it in
shell history. The helper refuses to overwrite an existing identity file. The
agent can check existence/permissions without reading the value. The server
consumes that protected file locally and never logs it.

After this mode is active, the user performs ChatGPT registration and OAuth login.
Use the exact displayed callback or actual client redirect, never a guessed ID.
Confirm the nonsecret `mcp.discovery_authenticated owner_verified=true` milestone
and successful tool discovery. This proves only an accepted access token/catalog,
not refresh, Discord forwarding or dot subscription. Live activation is a separate
operator step after consent and callback scope review; refresh the catalog then.

- <https://auth0.com/docs/manage-users/user-accounts/user-profiles>
