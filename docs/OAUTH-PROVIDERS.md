# OAuth provider choices (reviewed 2026-10-06)

The bridge is an OAuth resource server, not an authorization server. Issuer,
resource, public JWKS and exact owner subject are configuration. No provider SDK,
tenant, credential or vendor endpoint is hardwired. Keep strict audience checks.

Required acceptance: authorization code with PKCE S256; exact client callback;
resource-bound RS256 JWT access tokens; scopes; refresh without broader resource
or scope; discovery; expiry; issuer and owner checks; ID tokens not accepted as API
access tokens. Test wrong resources on authorization, exchange and refresh and
test mixed resource/audience inputs. Provider documentation is not a live test.

## Authentik

The inspected 2026.8.3 installation defaults audience to client ID and does not
implement the required resource parameter in its authorization-code flow. A static
audience override alone does not validate resource binding, and scope mappings
can also alter ID token claims. Do not use an untested mapping or weaken verifier
checks. Existing unrelated Authentik applications must remain separate.

## Optional hosted provider: Auth0

Official Auth for MCP documentation supports a Resource Parameter Compatibility
Profile for authorization and refresh flows, plus issuer identification responses.
Enable both. Use a dedicated resource API with identifier exactly matching the
bridge resource, RS256, `discord:bridge` scope and <=1 hour token lifetime. A
predefined third-party web OAuth client avoids open dynamic registration. Register
the exact ChatGPT callback, require PKCE, enable refresh and use the supported
token-endpoint authentication method. Only the bridge owner's identity is allowed.

Auth0 prefers audience over resource when both are supplied: explicitly test that
a mismatched combination cannot access this bridge. Test after the free trial,
not just while trial features are available. Current pricing advertises Free at
$0, up to 25,000 monthly active users and Auth for MCP included. Custom domains
require credit-card verification; the tenant domain avoids that dependency.
Private-key JWT client authentication is Enterprise-only per CIMD documentation;
do not assume free CIMD compatibility with ChatGPT's preferred private-key method.
Manual predefined client registration is the proposed initial path.

This introduces an external identity processor: login identifiers, authentication
events and network metadata go to Auth0. Discord messages/dot context need not be
sent to the IdP. User approval and acceptance of the applicable signup terms are
required before any account or grant. Pricing is not a guarantee of entitlement,
an SLA or suitability under all service terms; verify the actual tenant features.

## Optional self-hosted provider: Logto OSS

Logto documents third-party MCP access, resource-bound JWTs, manual third-party
clients and self-hosted tenants. It is a credible provider-independent alternative
for an open-source deployment guide. It adds an identity service/database, updates,
backup and administration. Confirm the selected OSS version's signing algorithm,
discovery, code/refresh resource handling, PKCE and exact ChatGPT compatibility in
an isolated test before deploying. No Logto instance has been provisioned here.

Sources:
- <https://developers.openai.com/plugins/build/auth>
- <https://auth0.com/ai/docs/mcp/guides/resource-param-compatibility-profile>
- <https://auth0.com/ai/docs/mcp/guides/registering-your-mcp-client-application/manual-client-registration>
- <https://auth0.com/ai/docs/mcp/guides/registering-your-mcp-client-application/manual-cimd-registration>
- <https://auth0.com/pricing>
- <https://docs.logto.io/use-cases/ai/mcp-server-enable-third-party-ai-agent-access>
- <https://docs.logto.io/introduction/set-up-logto-oss>
