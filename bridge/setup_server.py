"""Metadata-only deployment staging. All MCP requests are rejected, even with a token."""
import argparse
from urllib.parse import urlsplit
from aiohttp import web
from .auth import AuthError, SCOPE
from .http_server import make_app


class DisabledVerifier:
    def __init__(self, resource, issuer):
        self.resource, self.issuer = resource, issuer

    def metadata(self):
        return {"resource": self.resource, "authorization_servers": [self.issuer],
                "scopes_supported": [SCOPE], "bearer_methods_supported": ["header"]}

    def verify(self, authorization):
        raise AuthError("Deployment setup only")


class DisabledActor:
    async def submit(self, operation):
        return operation()

    async def rpc(self, request, authorization):
        raise AuthError("Deployment setup only")


def setup_app(resource, issuer, port=8765):
    for value in (resource, issuer):
        url = urlsplit(value)
        if (url.scheme != "https" or not url.hostname or url.username or url.password
                or url.query or url.fragment or url.port not in (None, 443)):
            raise ValueError("Canonical HTTPS URLs required")
    if urlsplit(resource).path != "/mcp" or not 1024 <= port <= 65535:
        raise ValueError("Resource /mcp and unprivileged port required")
    return make_app(DisabledActor(), DisabledVerifier(resource, issuer),
                    allowed_hosts=[urlsplit(resource).netloc, f"127.0.0.1:{port}"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resource", required=True)
    parser.add_argument("--issuer", required=True)
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    web.run_app(setup_app(args.resource, args.issuer, args.port),
                host="127.0.0.1", port=args.port, access_log=None, print=None)


if __name__ == "__main__":
    main()
