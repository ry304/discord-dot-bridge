"""Opt-in, one-host subscription probe. No subscription, DNS, callback or bot I/O."""
import argparse
import inspect
import ipaddress
import json
import os
import re
import time
from pathlib import Path
from urllib.parse import urlsplit
from aiohttp import web
from . import discovery_server
from .auth import OAuthVerifier
from .core import signing_key
from .discovery_server import DiscoveryActor, private_text, load_config
from .http_server import make_app

STATUS_TOOL = {"name": "discord_bridge_status", "description": "Read the authenticated bridge setup state without Discord or callback network access.",
    "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    "securitySchemes": [{"type": "oauth2", "scopes": ["discord:bridge"]}],
    "annotations": {"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False}}


def hostname_only(url):
    if not isinstance(url, str) or len(url) > 4096:
        raise ValueError("Invalid callback")
    parsed = urlsplit(url)
    host = parsed.hostname
    if (parsed.scheme != "https" or parsed.username or parsed.password or parsed.fragment
            or parsed.port not in (None, 443) or not host or len(host) > 253
            or not re.fullmatch(r"[a-z0-9]+(?:[a-z0-9.-]*[a-z0-9])?", host)
            or "." not in host or any(not label or len(label) > 63 or label.startswith("-")
                                    or label.endswith("-") for label in host.split("."))):
        raise ValueError("Invalid callback")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return host
    raise ValueError("IP callback forbidden")


class ProbeActor(DiscoveryActor):
    def __init__(self, verifier, mode, owner, target, capture_enabled=True):
        super().__init__(verifier, mode)
        self.owner, self.target = owner, Path(target)
        self.capture_enabled = capture_enabled
        self.deadline = time.monotonic() + 600 if capture_enabled else 0
        self.catalog_reported = False

    async def rpc(self, request, authorization):
        if request.get("method") == "tools/list":
            response = await super().rpc(request, authorization)
            response["result"]["tools"].append(STATUS_TOOL)
            if not self.catalog_reported:
                print("mcp.status_catalog status_included=true", flush=True)
                self.catalog_reported = True
            return response
        if request.get("method") == "tools/call" and request.get("params", {}).get("name") == "discord_bridge_status":
            self.verifier.verify(authorization)
            if request["params"].get("arguments", {}) != {}:
                return {"jsonrpc": "2.0", "id": request["id"], "error": {"code": -32602, "message": "No arguments accepted"}}
            status = {"mode": "callback_setup_probe" if self.capture_enabled else "discovery_status", "probe_window_open": self.capture_enabled and time.monotonic() <= self.deadline,
                      "hostname_recorded": self.target.is_file(), "subscriptions_enabled": False,
                      "discord_connected": False, "replies_enabled": False}
            return {"jsonrpc": "2.0", "id": request["id"], "result": {
                "content": [{"type": "text", "text": json.dumps(status)}], "isError": False}}
        if request.get("method") != "events/subscribe":
            return await super().rpc(request, authorization)
        self.verifier.verify(authorization)
        params = request.get("params", {})
        expected = "discord.channel.mentioned" if self.mode == "guild_mentions" else "discord.dm.created"
        try:
            if not self.capture_enabled or time.monotonic() > self.deadline:
                raise ValueError
            if params.get("name") != expected or params.get("arguments") != {"owner_id": self.owner} or params.get("cursor") is not None:
                raise ValueError
            delivery = params["delivery"]
            if delivery.get("mode") != "webhook":
                raise ValueError
            signing_key(delivery.get("secret"))  # Validate only; never persist it.
            host = hostname_only(delivery.get("url"))
            # A single immutable file; repeated or different requests cannot overwrite.
            fd = os.open(self.target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w", encoding="ascii") as file:
                file.write(host + "\n")
                file.flush()
                os.fsync(file.fileno())
            print("mcp.callback_probe hostname_recorded=true subscription_created=false", flush=True)
        except Exception:
            pass  # Never print exception/request/URL/secret; refusal is invariant.
        return {"jsonrpc": "2.0", "id": request["id"], "error": {"code": -32000,
            "message": "Setup probe only: no subscription created; operator review required"}}


def probe_app(config, scope_path, directory, capture_enabled=True):
    subject = private_text(config["oauth_subject_file"], 1024).strip()
    if not subject or len(subject) > 256 or any(c.isspace() for c in subject) or subject.startswith("REPLACE"):
        raise ValueError("Owner binding required")
    scope = json.loads(private_text(scope_path))
    owner = scope["owner_discord_id"]
    if not isinstance(owner, str) or not re.fullmatch(r"[0-9]{17,20}", owner):
        raise ValueError("Owner filter required")
    if scope.get("discord_mode", "dm") != config["discord_mode"]:
        raise ValueError("Mode mismatch")
    root = Path(directory)
    if not root.is_absolute() or root.is_symlink() or not root.is_dir() or root.stat().st_mode & 0o077:
        raise ValueError("Private probe directory required")
    verifier = OAuthVerifier(issuer=config["oauth_issuer"], resource=config["resource"], subject=subject,
        jwks_file=config["jwks_file"], enabled_file=config["enabled_file"])
    if not verifier.enabled():
        raise ValueError("Discovery disabled")
    options = {}
    # Preserve deployed fixed-code diagnostics when available; no request logging.
    if "diagnostic" in inspect.signature(make_app).parameters:
        options["diagnostic"] = discovery_server.DiscoveryDiagnostics()
    return make_app(ProbeActor(verifier, config["discord_mode"], owner, root / "callback.hostname", capture_enabled), verifier,
        allowed_hosts=[urlsplit(config["resource"]).netloc, "127.0.0.1:8765"], **options)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--scope-config", required=True)
    parser.add_argument("--capture-dir", required=True)
    parser.add_argument("--status-only", action="store_true", help="Expose status and catalog only; never capture a callback hostname")
    args = parser.parse_args()
    try:
        web.run_app(probe_app(load_config(args.config), args.scope_config, args.capture_dir, not args.status_only),
            host="127.0.0.1", port=8765, access_log=None, print=None)
    except Exception:
        parser.exit(1, "Callback probe stopped; inspect private configuration.\n")


if __name__ == "__main__":
    main()
