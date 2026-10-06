"""Owner-authenticated MCP catalog only. No bot, storage, subscriptions or delivery."""
import argparse
import asyncio
import json
import os
from pathlib import Path
from urllib.parse import urlsplit
from aiohttp import web
from .auth import OAuthVerifier
from .core import VERSION, EVENT_DEFINITION, REPLY_TOOL
from .http_server import make_app


def private_text(path, limit=16384):
    file = Path(path)
    if not file.is_absolute() or file.is_symlink() or file.stat().st_size > limit:
        raise ValueError("Invalid private configuration file")
    if os.name != "nt" and file.stat().st_mode & 0o077:
        raise ValueError("Configuration file must be private")
    return file.read_text(encoding="utf-8")


def load_config(path):
    data = json.loads(private_text(path))
    required = {"resource", "oauth_issuer", "oauth_subject_file", "jwks_file", "enabled_file", "discord_mode"}
    if not isinstance(data, dict) or set(data) != required:
        raise ValueError("Unexpected discovery configuration")
    for key in ("resource", "oauth_issuer"):
        url = urlsplit(data[key])
        if (url.scheme != "https" or not url.hostname or url.username or url.password
                or url.query or url.fragment or url.port not in (None, 443)):
            raise ValueError("Canonical HTTPS URLs required")
    if urlsplit(data["resource"]).path != "/mcp" or data["discord_mode"] not in ("dm", "guild_mentions"):
        raise ValueError("Invalid resource or mode")
    for key in ("oauth_subject_file", "jwks_file", "enabled_file"):
        if not isinstance(data[key], str) or not Path(data[key]).is_absolute():
            raise ValueError("Absolute private file path required")
    return data


class DiscoveryActor:
    def __init__(self, verifier, mode):
        self.verifier, self.mode = verifier, mode
        self.slots = asyncio.Semaphore(32)
        self.confirmed = False

    async def submit(self, operation):
        if self.slots.locked():
            raise web.HTTPServiceUnavailable(text="Discovery queue full")
        async with self.slots:
            return operation()  # Bounded local public-key/file checks, no network.

    async def rpc(self, request, authorization):
        self.verifier.verify(authorization)
        rid, method = request["id"], request["method"]
        if method == "server/discover":
            result = {"supportedVersions": [VERSION], "capabilities": {"tools": {}, "events": {}}}
        elif method == "tools/list":
            tool = dict(REPLY_TOOL)
            tool["description"] += " Deployment is in discovery-only mode; replies are currently disabled."
            result = {"tools": [tool]}
        elif method == "events/list":
            event = dict(EVENT_DEFINITION)
            if self.mode == "guild_mentions":
                event.update(name="discord.channel.mentioned", description="An owner bot mention in the configured private guild channel.")
            event["description"] += " Discovery-only mode; subscriptions and event delivery are disabled."
            result = {"events": [event]}
        else:
            return {"jsonrpc": "2.0", "id": rid, "error": {"code": -32601,
                "message": "Discovery only: this operation is disabled"}}
        if not self.confirmed:
            print("mcp.discovery_authenticated owner_verified=true", flush=True)
            self.confirmed = True
        return {"jsonrpc": "2.0", "id": rid, "result": result}


def discovery_app(config):
    subject = private_text(config["oauth_subject_file"], 1024).strip()
    if not subject or len(subject) > 256 or any(c.isspace() for c in subject) or subject.startswith("REPLACE"):
        raise ValueError("Verified owner subject required")
    verifier = OAuthVerifier(issuer=config["oauth_issuer"], resource=config["resource"], subject=subject,
        jwks_file=config["jwks_file"], enabled_file=config["enabled_file"])
    if not verifier.enabled():
        raise ValueError("Discovery is disabled")
    return make_app(DiscoveryActor(verifier, config["discord_mode"]), verifier,
        allowed_hosts=[urlsplit(config["resource"]).netloc, "127.0.0.1:8765"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    args = parser.parse_args()
    try:
        web.run_app(discovery_app(load_config(args.config)), host="127.0.0.1", port=8765,
                    access_log=None, print=None)
    except Exception:
        parser.exit(1, "Discovery stopped: verify private owner binding and configuration.\n")


if __name__ == "__main__":
    main()
